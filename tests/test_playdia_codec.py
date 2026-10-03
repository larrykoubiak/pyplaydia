"""Synthetic codec fixtures; no commercial disc data is needed for tests."""

import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from PIL import Image

from playdia_codec import ControlInput, ControlStream, DecodeError, Picture
from playdia_codec.transform import inverse_dct
from iso9660 import ISOImage
from sector import Submodes


def escape(run, level):
    return f"001000{run:04b}{level & 1023:010b}"


def picture_bytes(block=None, *, rows=27, factor=4, quant_y=None, quant_c=None):
    header = b"\x00\x80\x04" + bytes([factor])
    header += bytes(quant_y if quant_y is not None else [64] * 16)
    header += bytes(quant_c if quant_c is not None else [64] * 16)
    bits = []
    for row in range(rows):
        bits.append(f"{0x20:014b}{row + 1:05b}")
        bits.extend(block(row, index) if block else "01" for index in range(186))
    bits.append(f"{0x21:014b}")
    entropy = "".join(bits)
    entropy += "0" * (-len(entropy) % 8)
    return header + int(entropy, 2).to_bytes(len(entropy) // 8, "big")


def sectors(packet, *, padding=False):
    """Put a contiguous stream across F1 sectors and a nonempty F2 tail."""
    result = bytearray()
    while len(packet) > 2013 or not result:
        count = min(2047, len(packet))
        result += b"\xf1" + packet[:count] + b"\xff" * (2047 - count)
        packet = packet[count:]
        if padding:
            result += b"\xf3\x37\xf9" + b"\xff" * 2045
    result += b"\xf2" + b"\x40" + bytes(33) + packet + b"\xff" * (2013 - len(packet))
    return bytes(result)


class PictureTests(unittest.TestCase):
    def test_all_27_rows_can_start_without_a_dc_escape(self):
        picture = Picture.from_bytes(picture_bytes(), assembled=True)
        self.assertEqual([row.lmbn for row in picture.video_stream.rows], list(range(1, 28)))
        self.assertTrue(all(row.first_luma_dc == 0 for row in picture.video_stream.rows))
        self.assertEqual(picture.decode_rgb(), bytes([128]) * (248 * 216 * 3))
        # Reinspection replaces rows instead of appending another picture.
        picture.video_stream.parse_rows()
        self.assertEqual(len(picture.video_stream.rows), 27)

    def test_macroblock_prediction_and_row_reset(self):
        deltas = {0: 16, 1: 8, 2: -8, 6: 8}
        packet = picture_bytes(lambda row, block: (escape(0, deltas[block]) if row == 0 and block in deltas else "") + "01")
        image = Picture.from_bytes(packet, assembled=True).to_image()
        for x, y, value in [(0, 0, 144), (4, 0, 152), (0, 4, 136), (4, 4, 144), (8, 0, 152), (12, 0, 152), (0, 8, 128)]:
            self.assertEqual(image.getpixel((x, y)), (value,) * 3)

    def test_signed_escape_and_full_block_without_eob(self):
        full = escape(0, -64) + "110" * 15
        packet = picture_bytes(lambda row, block: full if block == 0 else "01")
        picture = Picture.from_bytes(packet, assembled=True)
        self.assertEqual(picture.video_stream.rows[0].blocks[0], (-64,) + (1,) * 15)
        image = picture.to_image()
        self.assertEqual(image.getpixel((8, 0)), (64, 64, 64))
        self.assertEqual(image.getpixel((247, 215)), (64, 64, 64))

    def test_escape_can_skip_dc_and_land_on_last_coefficient(self):
        packet = picture_bytes(lambda row, block: escape(15, -512) if block == 0 else "01")
        picture = Picture.from_bytes(packet, assembled=True)
        self.assertEqual(picture.video_stream.rows[0].blocks[0], (0,) * 15 + (-512,))

    def test_rare_code_and_zigzag(self):
        # run=5, level=+4, then run=9, level=+1 fills positions 5 and 15.
        packet = picture_bytes(lambda row, block: "00000000100010" + escape(9, 1) if block == 0 else "01")
        coefficients = Picture.from_bytes(packet, assembled=True).video_stream.rows[0].blocks[0]
        self.assertEqual(coefficients[2], 4)
        self.assertEqual(coefficients[15], 1)
        self.assertEqual(sum(coefficients), 5)

    def test_terminator_shaped_bits_inside_a_coefficient_are_not_a_boundary(self):
        # This 13-bit VLC plus its sign bit is also the 14-bit 0x21 terminator.
        packet = picture_bytes(lambda row, block: "00000000100001" + "01" if block == 0 else "01")
        picture = Picture.from_bytes(packet, assembled=True)
        self.assertEqual(picture.video_stream.rows[0].first_luma_dc, -25)
        self.assertEqual(picture.to_image().getpixel((0, 0)), (103, 103, 103))

    def test_separate_quantizers_and_chroma_predictors(self):
        def block(row, index):
            deltas = {0: 3, 4: 1, 5: 2}
            return (escape(0, deltas[index]) if row == 0 and index in deltas else "") + "01"

        cases = [
            ({}, (133, 130, 132)),
            ({"quant_y": [128] + [64] * 15}, (136, 133, 135)),
            ({"quant_c": [128] + [64] * 15}, (136, 128, 134)),
            ({"factor": 8}, (139, 131, 137)),
        ]
        for options, expected in cases:
            with self.subTest(options=options):
                image = Picture.from_bytes(picture_bytes(block, **options), assembled=True).to_image()
                self.assertEqual(image.getpixel((0, 0)), expected)
                self.assertEqual(image.getpixel((247, 7)), expected)
                self.assertEqual(image.getpixel((0, 8)), (128, 128, 128))

    def test_ac_uses_cosine_transform_and_chroma_covers_two_by_two_pixels(self):
        # A horizontal AC coefficient in the first Cb block; all luma is neutral.
        packet = picture_bytes(lambda row, block: escape(1, 16) + "01" if row == 0 and block == 4 else "01")
        image = Picture.from_bytes(packet, assembled=True).to_image()
        for x in range(8):
            cb = round(64 * math.cos((2 * (x // 2) + 1) * math.pi / 8) / (2 * math.sqrt(2)))
            expected_blue = 128 + math.floor(cb * 116130 / 65536)
            self.assertEqual(image.getpixel((x, 0))[2], expected_blue)
            self.assertEqual(image.getpixel((x, 0)), image.getpixel((x, 1)))
        self.assertEqual(image.getpixel((8, 0)), (128, 128, 128))

    def test_mixed_ac_and_quantizers_preserve_integer_transform_rounding(self):
        coefficients = (63, -7, 12, -3, 5, 9, -11, 2, -4, 8, 1, -6, 10, -2, 7, -9)
        # Recorded from the original two-pass integer matrix transform.
        self.assertEqual(inverse_dct(coefficients, bytes(range(17, 33)), 9), [
            54, 64, 22, 38,
            25, 11, 64, 19,
            45, 34, 27, 104,
            31, 11, 4, 49,
        ])

    def test_rejects_coefficient_overflow_with_row_and_block_context(self):
        packet = picture_bytes(lambda row, block: escape(14, 1) + escape(1, 1) + "01" if block == 2 else "01")
        with self.assertRaises(DecodeError) as caught:
            Picture.from_bytes(packet, assembled=True)
        self.assertEqual((caught.exception.row, caught.exception.block), (1, 2))
        self.assertIn("exceeds", str(caught.exception))

    def test_truncated_escape_preserves_bit_row_and_block_context(self):
        packet = picture_bytes(lambda row, block: escape(0, -7) + "01" if row == 0 and block == 0 else "01")
        # Header + row marker + escape + run leave only three level bits.
        with self.assertRaises(DecodeError) as caught:
            Picture.from_bytes(packet[:40], assembled=True)
        self.assertEqual((caught.exception.bit, caught.exception.row, caught.exception.block), (317, 1, 0))
        self.assertIn("Truncated coefficient stream", str(caught.exception))

    def test_truncated_sign_preserves_bit_row_and_block_context(self):
        packet = picture_bytes(lambda row, block: "00101001" if row == 0 and block == 0 else "01")
        # A five-bit code ends at bit 312; its following sign bit is missing.
        with self.assertRaises(DecodeError) as caught:
            Picture.from_bytes(packet[:39], assembled=True)
        self.assertEqual((caught.exception.bit, caught.exception.row, caught.exception.block), (312, 1, 0))
        self.assertIn("Truncated coefficient stream", str(caught.exception))

    def test_byte_aligned_terminator_needs_no_padding_read(self):
        # One five-bit coefficient puts the final terminator on a byte boundary.
        packet = picture_bytes(lambda row, block: "1001001" if row == 0 and block == 0 else "01")
        picture = Picture.from_bytes(packet, assembled=True)
        self.assertEqual(picture.video_stream.stream.pos, len(packet) * 8)
        self.assertEqual(picture.to_image().getpixel((0, 0)), (131, 131, 131))

    def test_rejects_incomplete_rows_headers_codes_and_padding(self):
        valid = picture_bytes()
        bad_code = valid[:36] + b"\x00\x80\x20\x00\x00" + valid[41:]
        variants = [
            b"", valid[:35], valid[:400], valid[:-1], picture_bytes(rows=26),
            bytes([1]) + valid[1:], valid[:2] + b"\x05" + valid[3:],
            picture_bytes(factor=0), valid + b"\x00\x00", valid[:-1] + bytes([valid[-1] | 1]),
            valid[:36] + bytes([valid[36] ^ 1]) + valid[37:], bad_code,
        ]
        for index, packet in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(DecodeError):
                Picture.from_bytes(packet, assembled=True)
        padded = Picture.from_bytes(valid + bytes(1) + b"\xff" * 30, assembled=True)
        self.assertEqual(padded.decode_rgb(), bytes([128]) * (248 * 216 * 3))

    def test_f1_f2_assembly_preserves_tails_and_skips_f3(self):
        # Enough coefficients to force a continuation F1 and meaningful F2 data.
        packet = picture_bytes(lambda row, block: escape(0, 1) + "01")
        picture = Picture.from_bytes(sectors(packet, padding=True))
        self.assertTrue(picture.video_stream.stream.bytes.startswith(packet))
        self.assertEqual(picture.control_stream.stream.bytes, b"\x40" + bytes(33))
        self.assertEqual(picture.control_stream.flags, 0x40)
        self.assertTrue(picture.control_stream.multiple_picture_scene_end)
        self.assertEqual(picture.video_stream.rows[26].blocks[-1][0], 31)

    def test_f2_control_fields_and_candidate_addresses(self):
        groups = [
            (3, 10, 8, 0x91),   # Candidate LBA 14140.
            (3, 10, 10, 0x92),  # Candidate LBA 14150.
            (0, 3, 0, 0x93),    # Candidate LBA 75.
            (0, 0, 0, 0x94),    # Arithmetic is exposed without validation.
            (1, 2, 3, 0x95),
            (4, 5, 6, 0x96),
            (7, 8, 9, 0x97),
        ]
        raw = bytes((0xA4, 0xF0)) + b"".join(bytes(group) for group in groups) + b"\xde\xad\xbe\xef"
        control = ControlStream.from_bytes(raw)

        self.assertEqual(control.stream.bytes, raw)
        self.assertEqual(control.stream.pos, 0)
        self.assertEqual(control.flags, 0xA4)
        self.assertEqual(control.second_byte, 0xF0)
        self.assertTrue(control.single_picture_scene_end)
        self.assertFalse(control.multiple_picture_scene_end)
        self.assertEqual(control.unresolved_flag_bits, 0x24)
        self.assertEqual([address.payload_offset for address in control.candidate_addresses], [3, 7, 11, 15, 19, 23, 27])
        self.assertEqual([address.input for address in control.candidate_addresses], [
            ControlInput.B, ControlInput.A, ControlInput.RIGHT, ControlInput.LEFT,
            ControlInput.UP, ControlInput.DOWN, ControlInput.NO_INPUT,
        ])
        self.assertEqual([address.lba for address in control.candidate_addresses[:4]], [14140, 14150, 75, -150])
        self.assertEqual(control.candidate_addresses[0].msf, (3, 10, 40))
        self.assertEqual(control.candidate_addresses[0].absolute_sector, 14290)
        self.assertEqual(control.candidate_addresses[0].raw, bytes(groups[0]))
        self.assertEqual(control.trailing_bytes, b"\xde\xad\xbe\xef")

    def test_f2_control_requires_the_complete_marker_free_record(self):
        for size in (0, 33, 35):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "exactly 34"):
                ControlStream.from_bytes(bytes(size))

        empty = ControlStream()
        self.assertIsNone(empty.flags)
        self.assertEqual(empty.candidate_addresses, ())

    def test_rejects_malformed_sector_packets(self):
        valid = sectors(picture_bytes())
        for packet in [b"", valid[:-1], valid[:2048], valid[2048:], valid + valid[:2048], b"\xf0" + valid[1:]]:
            with self.subTest(length=len(packet)), self.assertRaises(DecodeError):
                Picture.from_bytes(packet)
        bad_f3 = valid[:2048] + b"\xf3" + bytes(2047) + valid[2048:]
        with self.assertRaisesRegex(DecodeError, "Invalid video sector"):
            Picture.from_bytes(bad_f3)


class ExtractionTests(unittest.TestCase):
    def test_non_video_sectors_do_not_contaminate_the_next_frame(self):
        packet = sectors(picture_bytes())
        data = [
            bytes(2324),
            b"\xf2" + bytes(2047),  # A control-only F2 cannot start a picture.
            packet[:2048],
            b"\xf3\x37\xf9" + b"\xff" * 2045,
            bytes(2324),
            packet[2048:],
        ]
        track = [SimpleNamespace(Data=value, Submode=Submodes.Data) for value in data]
        track.append(SimpleNamespace(Submode=Submodes.EOF))
        stream = SimpleNamespace(Sectors=track, ReadSector=lambda index: track[index])
        disc = ISOImage.__new__(ISOImage)
        disc._ISOImage__imagestream = stream
        with tempfile.TemporaryDirectory() as directory:
            disc.ReadVideoFrames(SimpleNamespace(ExtentLocation=0), directory)
            frames = list(Path(directory).rglob("frame_*.png"))
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].relative_to(directory), Path("000/frame_0000.png"))
            self.assertEqual(list(Path(directory).rglob("*.bin")), [])
            with Image.open(frames[0]) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (248, 216))
                self.assertEqual(image.tobytes(), Picture.from_bytes(packet).decode_rgb())


if __name__ == "__main__":
    unittest.main()
