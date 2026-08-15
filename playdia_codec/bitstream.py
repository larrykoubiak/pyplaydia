from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BitOrder = Literal["msb", "lsb"]


class BitstreamExhausted(EOFError):
    pass


@dataclass(frozen=True)
class BitPosition:
    byte_offset: int
    bit_offset: int


class BitReader:
    """Generic bit reader over a bytes-like object."""

    def __init__(
        self,
        data: bytes | bytearray | memoryview,
        *,
        bit_offset: int = 0,
        bit_order: BitOrder = "msb",
    ):
        if bit_order not in ("msb", "lsb"):
            raise ValueError("bit_order must be 'msb' or 'lsb'")
        if bit_offset < 0 or bit_offset > len(data) * 8:
            raise ValueError("bit_offset is outside the bitstream")
        self._data = bytes(data)
        self._bit_offset = bit_offset
        self._bit_order: BitOrder = bit_order

    @property
    def bit_order(self) -> BitOrder:
        return self._bit_order

    @property
    def bit_offset(self) -> int:
        return self._bit_offset

    @property
    def byte_offset(self) -> int:
        return self._bit_offset // 8

    @property
    def bit_in_byte(self) -> int:
        return self._bit_offset % 8

    @property
    def position(self) -> BitPosition:
        return BitPosition(self.byte_offset, self.bit_in_byte)

    @property
    def bits_remaining(self) -> int:
        return len(self._data) * 8 - self._bit_offset

    @property
    def eof(self) -> bool:
        return self._bit_offset >= len(self._data) * 8

    def fork(self) -> "BitReader":
        return BitReader(self._data, bit_offset=self._bit_offset, bit_order=self._bit_order)

    def seek(self, bit_offset: int) -> None:
        if bit_offset < 0 or bit_offset > len(self._data) * 8:
            raise ValueError("bit_offset is outside the bitstream")
        self._bit_offset = bit_offset

    def skip(self, bit_count: int) -> None:
        self.seek(self._bit_offset + bit_count)

    def align_to_next_byte(self) -> int:
        skipped = (-self._bit_offset) % 8
        self._bit_offset += skipped
        return skipped

    def read_bit(self) -> int:
        if self.eof:
            raise BitstreamExhausted("cannot read past end of bitstream")
        byte = self._data[self.byte_offset]
        if self._bit_order == "msb":
            shift = 7 - self.bit_in_byte
        else:
            shift = self.bit_in_byte
        bit = (byte >> shift) & 1
        self._bit_offset += 1
        return bit

    def read_bits(self, bit_count: int) -> int:
        if bit_count < 0:
            raise ValueError("bit_count must be non-negative")
        if bit_count > self.bits_remaining:
            raise BitstreamExhausted("cannot read past end of bitstream")
        value = 0
        for index in range(bit_count):
            bit = self.read_bit()
            if self._bit_order == "msb":
                value = (value << 1) | bit
            else:
                value |= bit << index
        return value

    def peek_bits(self, bit_count: int) -> int:
        start = self._bit_offset
        try:
            return self.read_bits(bit_count)
        finally:
            self._bit_offset = start

    def read_signed_bits(self, bit_count: int) -> int:
        if bit_count <= 0:
            raise ValueError("bit_count must be positive")
        value = self.read_bits(bit_count)
        sign = 1 << (bit_count - 1)
        return value - (1 << bit_count) if value & sign else value

    def find_bits(self, pattern: int, bit_count: int, *, start: int | None = None) -> int | None:
        if bit_count <= 0:
            raise ValueError("bit_count must be positive")
        if pattern < 0 or pattern >= (1 << bit_count):
            raise ValueError("pattern does not fit in bit_count")
        start_offset = self._bit_offset if start is None else start
        end = len(self._data) * 8 - bit_count
        for offset in range(start_offset, end + 1):
            probe = BitReader(self._data, bit_offset=offset, bit_order=self._bit_order)
            if probe.read_bits(bit_count) == pattern:
                return offset
        return None
