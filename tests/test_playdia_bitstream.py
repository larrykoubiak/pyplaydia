import unittest

from playdia_codec.bitstream import BitReader, BitstreamExhausted


class BitReaderTests(unittest.TestCase):
    def test_reads_msb_first_across_byte_boundaries(self):
        reader = BitReader(bytes.fromhex("a5 3c"))

        self.assertEqual(reader.read_bits(4), 0b1010)
        self.assertEqual(reader.position.byte_offset, 0)
        self.assertEqual(reader.position.bit_offset, 4)
        self.assertEqual(reader.read_bits(8), 0b01010011)
        self.assertEqual(reader.read_bits(4), 0b1100)
        self.assertTrue(reader.eof)

    def test_reads_lsb_first_across_byte_boundaries(self):
        reader = BitReader(bytes.fromhex("a5 3c"), bit_order="lsb")

        self.assertEqual(reader.read_bits(4), 0b0101)
        self.assertEqual(reader.position.byte_offset, 0)
        self.assertEqual(reader.position.bit_offset, 4)
        self.assertEqual(reader.read_bits(8), 0b11001010)
        self.assertEqual(reader.read_bits(4), 0b0011)
        self.assertTrue(reader.eof)

    def test_peek_does_not_advance_and_fork_is_independent(self):
        reader = BitReader(bytes.fromhex("80"))
        forked = reader.fork()

        self.assertEqual(reader.peek_bits(3), 0b100)
        self.assertEqual(reader.bit_offset, 0)
        self.assertEqual(forked.read_bits(2), 0b10)
        self.assertEqual(reader.bit_offset, 0)

    def test_seek_skip_align_and_exhaustion(self):
        reader = BitReader(bytes.fromhex("12 34"))

        reader.seek(3)
        self.assertEqual(reader.read_bits(5), 0b10010)
        reader.skip(3)
        self.assertEqual(reader.align_to_next_byte(), 5)
        self.assertEqual(reader.byte_offset, 2)
        with self.assertRaises(BitstreamExhausted):
            reader.read_bit()

    def test_signed_bits(self):
        reader = BitReader(bytes.fromhex("80 7f"))

        self.assertEqual(reader.read_signed_bits(8), -128)
        self.assertEqual(reader.read_signed_bits(8), 127)

    def test_find_bits(self):
        reader = BitReader(bytes.fromhex("12 34"))

        self.assertEqual(reader.find_bits(0b100100011, 9), 3)
        self.assertEqual(reader.bit_offset, 0)


if __name__ == "__main__":
    unittest.main()
