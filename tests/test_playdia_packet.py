from pathlib import Path
import unittest

from playdia_codec.metrics import bits_to_string, trailing_zero_bits_after_suffix
from playdia_codec.packet import PlaydiaPacket


class PlaydiaPacketTests(unittest.TestCase):
    def test_qis_packet_layout_and_payload(self):
        pkt = PlaydiaPacket.from_file(Path("output/frames/000/frame_0000.bin"))
        pkt.validate()
        self.assertEqual(pkt.sector_count, 7)
        self.assertEqual(pkt.sector_markers, (0xF1, 0xF1, 0xF1, 0xF1, 0xF1, 0xF1, 0xF2))
        self.assertEqual(pkt.header_value_04, 0x0F)
        self.assertEqual(pkt.header_value_28, 0x00)
        payload = pkt.extract_payload()
        self.assertEqual(len(payload.data), 12319)
        self.assertEqual(payload.data[-4:], bytes.fromhex("82 01 08 00"))

    def test_title_packet_layout_f2_overflow_and_terminator(self):
        pkt = PlaydiaPacket.from_file(Path("output/frames/001/frame_0063.bin"))
        pkt.validate()
        self.assertEqual(pkt.sector_count, 9)
        self.assertEqual(pkt.f2_tail_without_padding()[:4], bytes.fromhex("41 cc 31 90"))
        payload = pkt.extract_payload()
        self.assertEqual(payload.f2_tail_non_ff_bytes, 1035)
        bits = bits_to_string(payload.data, msb_first=True)
        self.assertIsNotNone(trailing_zero_bits_after_suffix(bits, "00000000100001000000"))

    def test_f2_msf_end_markers(self):
        ajs_start_lba = 1 * 4500 - 150

        qis_end = PlaydiaPacket.from_file(Path("output/frames/000/frame_0099.bin"))
        self.assertEqual(qis_end.f2_type(), 0x40)
        self.assertEqual(qis_end.f2_msf_targets()[0], (3, 1, 10, 0, 5100))
        self.assertEqual((qis_end.f2_msf_targets()[0][4] - ajs_start_lba) / 75, 10.0)

        title_end = PlaydiaPacket.from_file(Path("output/frames/001/frame_0197.bin"))
        self.assertEqual(title_end.f2_type(), 0x40)
        self.assertEqual(title_end.f2_msf_targets()[0], (3, 1, 36, 6, 7056))
        self.assertAlmostEqual((title_end.f2_msf_targets()[0][4] - ajs_start_lba) / 75, 36.08)

        intro_end = PlaydiaPacket.from_file(Path("output/frames/002/frame_0705.bin"))
        self.assertEqual(intro_end.f2_type(), 0x40)
        self.assertEqual(intro_end.f2_msf_targets()[0], (3, 3, 10, 8, 14108))
        self.assertAlmostEqual((intro_end.f2_msf_targets()[0][4] - ajs_start_lba) / 75, 130.10666666666665)

    def test_payload_start_offset_override(self):
        pkt = PlaydiaPacket.from_file(Path("output/frames/001/frame_0023.bin"))
        payload_29 = pkt.extract_payload(first_payload_offset=0x29).data
        payload_2a = pkt.extract_payload().data

        self.assertEqual(payload_29[0], 0x0C)
        self.assertEqual(payload_2a[0], 0xAA)
        self.assertEqual(payload_29[1:], payload_2a)

    def test_embedded_subframe_headers_can_be_stripped(self):
        pkt = PlaydiaPacket.from_file(Path("output/frames/001/frame_0023.bin"))
        headers = pkt.subframe_headers()

        self.assertEqual(
            [(header.raw_offset, header.marker_value, header.h28, header.h29) for header in headers],
            [(0x25, 0x24, 0x07, 0x0C), (0xA6, 0x64, 0x07, 0x0C), (0x123, 0xA4, 0x07, 0x0C)],
        )

        original = pkt.extract_payload()
        stripped = pkt.extract_payload(strip_subframe_headers=True)

        self.assertEqual(stripped.subframe_headers_stripped, 10)
        self.assertEqual(len(stripped.data), len(original.data) - 10)
        self.assertNotIn(bytes.fromhex("00 80 64 07 0c"), stripped.data)
        self.assertNotIn(bytes.fromhex("00 80 a4 07 0c"), stripped.data)


if __name__ == "__main__":
    unittest.main()
