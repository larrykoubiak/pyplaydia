import unittest

from playdia_codec.segments import (
    COUNTER_BITS,
    F1_MARKER,
    F2_CONTROL_SIZE,
    F2_MARKER,
    PREFERRED_TAG_BITS_TEXT,
    SECTOR_SIZE,
    SYNC_BITS_TEXT,
    TAG_BITS,
    build_frame_stream,
    dump_frame_bytes,
    parse_segments,
)


def bytes_from_bits(bits: str) -> bytes:
    padding = (-len(bits)) % 8
    padded = bits + ("0" * padding)
    return int(padded, 2).to_bytes(len(padded) // 8, "big")


def header_bits(counter: int, tag_bits: str = "00100") -> str:
    return f"{SYNC_BITS_TEXT}{counter:0{COUNTER_BITS}b}{tag_bits}"


class SegmentTests(unittest.TestCase):
    def test_parse_segments_splits_on_sync_prefix(self):
        data = bytes.fromhex("00 80 04 0f 00 80 24 00")

        segments = parse_segments(data)

        self.assertEqual([segment.counter for segment in segments], [0, 1])
        self.assertEqual([segment.tag_bits for segment in segments], ["00100", "00100"])
        self.assertEqual(segments[0].payload_bits, "00001111")
        self.assertEqual(segments[1].payload_bit_length, 8)

    def test_tag_bits_are_not_required_to_be_fixed(self):
        data = bytes.fromhex("00 80 e0 00")

        segments = parse_segments(data, start_bit=0)

        self.assertEqual(len(segments), 0)

        segments = parse_segments(data, start_bit=0, filter_counter=False)
        self.assertEqual(segments[0].counter, 7)
        self.assertEqual(segments[0].tag_bits, "00000")

    def test_counter_filter_continues_after_missing_counter(self):
        data = bytes_from_bits(
            header_bits(0)
            + "111"
            + header_bits(2)
            + "000"
        )

        segments = parse_segments(data)

        self.assertEqual([segment.counter for segment in segments], [0, 2])
        self.assertEqual(segments[1].missing_counters_before, (1,))

    def test_frame_stream_skips_padding_until_next_sector(self):
        raw = bytearray([0x11] * (SECTOR_SIZE * 2))
        raw[0] = F1_MARKER
        raw[1:5] = bytes.fromhex("00 80 04 0f")
        raw[5:7] = b"\xff\xff"
        raw[SECTOR_SIZE] = F1_MARKER
        raw[SECTOR_SIZE + 1 : SECTOR_SIZE + 5] = bytes.fromhex("00 80 24 00")

        stream = build_frame_stream(bytes(raw))

        self.assertEqual(stream.data[:8], bytes.fromhex("00 80 04 0f 00 80 24 00"))
        self.assertEqual(stream.source_offsets[:8], (1, 2, 3, 4, SECTOR_SIZE + 1, SECTOR_SIZE + 2, SECTOR_SIZE + 3, SECTOR_SIZE + 4))
        self.assertEqual(stream.sectors[0].padding_start, 5)

    def test_dump_frame_bytes_logs_f2_control(self):
        raw = bytearray([0xFF] * (SECTOR_SIZE * 2))
        raw[0] = F1_MARKER
        raw[1:5] = bytes.fromhex("00 80 04 0f")
        raw[5:7] = b"\xff\xff"
        f2_base = SECTOR_SIZE
        raw[f2_base] = F2_MARKER
        raw[f2_base + 1] = 0x40
        raw[f2_base + 3 : f2_base + 6] = bytes([1, 10, 0])
        raw[f2_base + F2_CONTROL_SIZE : f2_base + F2_CONTROL_SIZE + 4] = bytes.fromhex("00 80 24 00")
        raw[f2_base + F2_CONTROL_SIZE + 4 : f2_base + F2_CONTROL_SIZE + 6] = b"\xff\xff"

        result = dump_frame_bytes(bytes(raw), include_bits=False)

        self.assertEqual(result["sync_bits"], SYNC_BITS_TEXT)
        self.assertEqual(result["counter_bits"], COUNTER_BITS)
        self.assertEqual(result["tag_bits"], TAG_BITS)
        self.assertEqual(result["preferred_tag_bits"], PREFERRED_TAG_BITS_TEXT)
        self.assertEqual(result["sectors"][0]["raw_offset"], "0x0")
        self.assertEqual(result["sectors"][0]["padding_start"], "0x5")
        self.assertEqual(result["sectors"][1]["raw_offset"], "0x800")
        self.assertEqual(result["f2"][0]["type"], 0x40)
        self.assertEqual(result["f2"][0]["raw_offset"], "0x800")
        self.assertEqual(result["f2"][0]["msf_targets"][0]["offset"], "0x3")
        self.assertEqual(result["f2"][0]["msf_targets"][0]["minute"], 1)
        self.assertEqual(result["f2"][0]["msf_targets"][0]["second"], 10)
        self.assertEqual([segment["counter"] for segment in result["segments"]], [0, 1])
        self.assertEqual([segment["tag_bits"] for segment in result["segments"]], ["00100", "00100"])
        self.assertEqual(result["segments"][0]["stream_bit_offset"], "0x0")
        self.assertEqual(result["segments"][0]["raw_byte_offset"], "0x1")
        self.assertEqual(result["segments"][1]["raw_byte_offset"], "0x823")

    def test_row_zero_payload_is_byte_aligned_frame_header_data(self):
        raw = bytearray([0xFF] * SECTOR_SIZE)
        raw[0] = F1_MARKER
        raw[1:0x25] = bytes.fromhex(
            "00 80 04 19"
            " 0a 14 0e 0d 12 25 16 1c 0f 18 0f 12 12 1f 11 14"
            " 0a 14 0e 0d 12 25 16 1c 0f 18 0f 12 12 1f 11 14"
        )
        raw[0x25:0x29] = bytes.fromhex("00 80 24 00")
        raw[0x29:0x2B] = b"\xff\xff"

        result = dump_frame_bytes(bytes(raw), include_bits=True)

        row0 = result["segments"][0]
        self.assertEqual(row0["counter"], 0)
        self.assertEqual(row0["tag_bits"], "00100")
        self.assertEqual(row0["payload_bit_length"], 264)
        self.assertEqual(row0["payload_bits"], "".join(f"{byte:08b}" for byte in raw[0x04:0x25]))


if __name__ == "__main__":
    unittest.main()
