"""Decode extracted Playdia picture packets to native 248×216 RGB images.

Recovered entropy and reconstruction rules adapted from PlaydiaEmu.
Copyright (c) 2026, Aloys (AloysHF). BSD-3-Clause; see
../LICENSES/PlaydiaEmu-BSD-3-Clause.txt and ../THIRD_PARTY_NOTICES.md.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import ClassVar

from bitstring import ConstBitStream, Bits, ReadError
from PIL import Image

from .tables import LOOKUP, LOOKUP_BITS, ZIGZAG
from .transform import HEIGHT, WIDTH, reconstruct_rgb


class StreamType(IntEnum):
    VIDEO = 0xF1
    CONTROL = 0xF2
    PADDING = 0xF3


class ControlInput(IntEnum):
    """Observed selector for the seven candidate routes in an F2 record."""

    B = 0
    A = 1
    RIGHT = 2
    LEFT = 3
    UP = 4
    DOWN = 5
    NO_INPUT = 6


SECTOR_SIZE = 0x800
F2_CONTROL_SIZE = 0x22
PICTURE_ROWS = 27
BLOCKS_PER_ROW = 31 * 6
ROW_TERMINATOR = Bits(uint=0x21, length=14)


class DecodeError(ValueError):
    """Invalid picture, with a position in the assembled (marker-free) stream."""

    def __init__(self, message, *, bit=0, row=0, block=0):
        self.bit = bit
        self.row = row
        self.block = block
        super().__init__(f"{message} (bit {bit}, row {row}, block {block})")


class _CoefficientReader:
    def __init__(self, stream: ConstBitStream):
        self.stream = stream
        self.row = 0
        self.block = 0

    def error(self, message):
        return DecodeError(message, bit=self.stream.pos, row=self.row, block=self.block)

    def read(self, fmt):
        try:
            return self.stream.read(fmt)
        except ReadError as exc:
            raise self.error("Truncated coefficient stream") from exc

    def coefficients(self):
        stream = self.stream
        coefficients = [0] * 16
        position = 0
        while position < 16:
            start = stream.pos
            available = min(LOOKUP_BITS, len(stream) - start)
            if not available:
                raise self.error("Truncated coefficient code")
            # Slice once for lookahead, then advance without rereading the
            # prefix. Only the cursor changes; the picture bits are immutable.
            prefix = stream[start:start + available].uint << (LOOKUP_BITS - available)
            entry = LOOKUP[prefix]
            if entry is None:
                raise self.error("Truncated coefficient code" if available < LOOKUP_BITS - 1 else "Invalid coefficient code")
            length, run, level = entry
            if length > available:
                # A complete code with a missing sign reports the sign's
                # position, just as a separate one-bit read would.
                if level and length == available + 1:
                    stream.pos = start + available
                raise self.error("Truncated coefficient stream")
            stream.pos = start + length
            if level == 0:
                if length == 2:  # 01: end of this block.
                    break
                # 001000: a general run/level escape, including DC differences.
                run = self.read("uint:4")
                level = self.read("int:10")
            position += run
            if position >= 16:
                raise self.error("Coefficient run exceeds the 4x4 block")
            coefficients[ZIGZAG[position]] = level
            position += 1
        # Filling coefficient 15 ends the block without consuming an EOB.
        return coefficients


@dataclass
class PictureHeader:
    PSC: ClassVar[Bits] = Bits(uint=0x400, length=19)
    ptype: int
    qbs: int
    factor: int
    quant_y: bytes
    quant_c: bytes
    pos: int

    @classmethod
    def read(cls, stream: ConstBitStream) -> "PictureHeader":
        pos = stream.pos
        try:
            if stream.read(19) != cls.PSC:
                raise DecodeError("Invalid picture start code", bit=pos)
            return cls(
                ptype=stream.read(3).uint,
                qbs=stream.read(2).uint,
                factor=stream.read(8).uint,
                quant_y=stream.read(128).bytes,
                quant_c=stream.read(128).bytes,
                pos=pos,
            )
        except ReadError as exc:
            raise DecodeError("Truncated picture header", bit=stream.pos) from exc


@dataclass
class LMB:
    """One complete macroblock row; data includes every coefficient symbol."""

    LMBSC: ClassVar[Bits] = Bits(uint=0x20, length=14)
    lmbn: int
    pos: int
    data: Bits = field(repr=False)
    blocks: list[tuple[int, ...]] = field(repr=False)

    @classmethod
    def read(cls, reader: _CoefficientReader, expected_row: int) -> "LMB":
        pos = reader.stream.pos
        reader.row, reader.block = expected_row, 0
        if reader.read("uint:19") != (0x20 << 5) | expected_row:
            raise reader.error(f"Expected macroblock row {expected_row}")
        data_start = reader.stream.pos
        predictors = [0, 0, 0]
        blocks = []
        for index in range(BLOCKS_PER_ROW):
            reader.block = index
            block = index % 6
            component = 0 if block < 4 else block - 3
            coefficients = reader.coefficients()
            coefficients[0] += predictors[component]
            # Y1 predicts Y2/Y3/Y4 and the next macroblock's Y1.
            # Cb and Cr accumulate independently. All three reset each row.
            if block == 0 or component != 0:
                predictors[component] = coefficients[0]
            blocks.append(tuple(coefficients))
        data = Bits(reader.stream[data_start:reader.stream.pos])
        return cls(expected_row, pos, data, blocks)

    @property
    def first_luma_dc(self):
        """First block's decoded luminance DC."""
        return self.blocks[0][0]

    @property
    def byte_offset(self):
        return self.pos // 8

    @property
    def bit_offset(self):
        return self.pos % 8


class VideoStream:
    def __init__(self):
        self.stream = ConstBitStream()
        self.header: PictureHeader | None = None
        self.rows: list[LMB] = []

    def parse_rows(self):
        self.header = None
        self.rows = []
        self.stream.pos = 0
        header = PictureHeader.read(self.stream)
        if header.ptype != 1 or header.qbs != 0 or header.factor == 0:
            raise DecodeError(
                f"Unsupported picture header: ptype={header.ptype}, qbs={header.qbs}, factor={header.factor}"
            )
        reader = _CoefficientReader(self.stream)
        rows = [LMB.read(reader, row) for row in range(1, PICTURE_ROWS + 1)]
        if reader.read("uint:14") != ROW_TERMINATOR.uint:
            raise reader.error("Invalid picture terminator")
        # Up to 15 zero bits, then byte-aligned FF fill. Never scan ahead to
        # hide a missing row, an invalid coefficient, or a false terminator.
        used_bits = len(self.stream.bytes.rstrip(b"\xff")) * 8
        padding = used_bits - self.stream.pos
        if not 0 <= padding <= 15 or (padding and reader.read(f"uint:{padding}") != 0):
            raise reader.error("Invalid picture padding")
        self.header, self.rows = header, rows

    def decode_rgb(self) -> bytes:
        if self.header is None:
            self.parse_rows()
        return reconstruct_rgb(self.rows, self.header)


@dataclass(frozen=True)
class CandidateAddress:
    """One provisional M/S/U address group from an F2 control record.

    ``payload_offset`` counts from the F2 marker at offset zero.  ``fourth``
    is retained beside the three address bytes, but is not interpreted.
    """

    slot: int
    payload_offset: int
    m: int
    s: int
    u: int
    fourth: int

    @property
    def raw(self) -> bytes:
        return bytes((self.m, self.s, self.u, self.fourth))

    @property
    def input(self) -> ControlInput:
        """Return the observed button/no-input condition for this route."""
        return ControlInput(self.slot)

    @property
    def frame(self) -> int:
        """Expand the five-sector unit stored in the third address byte."""
        return self.u * 5

    @property
    def msf(self) -> tuple[int, int, int]:
        """Return the observed binary M/S/five-sector-unit representation."""
        return self.m, self.s, self.frame

    @property
    def absolute_sector(self) -> int:
        """Expand the three address bytes to a sector count including lead-in."""
        return self.m * 4500 + self.s * 75 + self.frame

    @property
    def lba(self) -> int:
        """Return the candidate zero-based LBA without validating the target."""
        return self.absolute_sector - 150


class ControlStream:
    """The 34 bytes after an F2 marker, with tentative fields exposed.

    Only the layout and address arithmetic documented in ``doc/f2/README.md``
    are decoded.  Unresolved bytes remain available both as named raw fields
    and through ``stream``; no command, button, or navigation meaning is
    assigned here.
    """

    SIZE = F2_CONTROL_SIZE
    CANDIDATE_COUNT = 7
    CANDIDATE_START = 2  # Stream index; payload offset 3 includes the F2.
    CANDIDATE_SIZE = 4
    SINGLE_PICTURE_END_BIT = 0x80
    MULTIPLE_PICTURE_END_BIT = 0x40

    def __init__(self, data: bytes | bytearray | None = None):
        self.stream = ConstBitStream(bytes=b"" if data is None else bytes(data))
        self.flags: int | None = None
        self.second_byte: int | None = None
        self.candidate_addresses: tuple[CandidateAddress, ...] = ()
        self.trailing_bytes = b""
        if data is not None:
            self.parse()

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "ControlStream":
        """Parse exactly 34 marker-free bytes from an F2 sector."""
        return cls(data)

    def parse(self):
        """Parse tentative fields while preserving the stream and its cursor."""
        raw = self.stream.bytes
        if len(raw) != self.SIZE:
            raise ValueError(f"Expected exactly {self.SIZE} F2 control bytes, got {len(raw)}")

        self.flags = raw[0]
        self.second_byte = raw[1]
        addresses = []
        for slot in range(self.CANDIDATE_COUNT):
            start = self.CANDIDATE_START + slot * self.CANDIDATE_SIZE
            addresses.append(CandidateAddress(
                slot, start + 1, raw[start], raw[start + 1], raw[start + 2], raw[start + 3]
            ))
        self.candidate_addresses = tuple(addresses)
        trailer_start = self.CANDIDATE_START + self.CANDIDATE_COUNT * self.CANDIDATE_SIZE
        self.trailing_bytes = raw[trailer_start:]
        return self

    @property
    def single_picture_scene_end(self) -> bool:
        """Whether bit 7 has the observed single-picture-scene correlation."""
        return self.flags is not None and bool(self.flags & self.SINGLE_PICTURE_END_BIT)

    @property
    def multiple_picture_scene_end(self) -> bool:
        """Whether bit 6 has the observed multiple-picture-scene correlation."""
        return self.flags is not None and bool(self.flags & self.MULTIPLE_PICTURE_END_BIT)

    @property
    def unresolved_flag_bits(self) -> int | None:
        """Return the lower six bits, whose meanings remain unresolved."""
        if self.flags is None:
            return None
        return self.flags & ~(self.SINGLE_PICTURE_END_BIT | self.MULTIPLE_PICTURE_END_BIT)


class Picture:
    """An extracted F1…F2 frame, with validated coefficients and RGB export."""

    width = WIDTH
    height = HEIGHT

    def __init__(self, data, *, assembled=False):
        self.video_stream = VideoStream()
        self.control_stream = ControlStream()
        if assembled:
            self.video_stream.stream = ConstBitStream(bytes=data)
        else:
            self.read_sectors(data)
        self.video_stream.parse_rows()

    @classmethod
    def from_bytes(cls, data: bytes | bytearray, *, assembled=False) -> "Picture":
        """Read sectors, or marker-free picture bytes with assembled=True."""
        return cls(data, assembled=assembled)

    def read_sectors(self, data):
        if not data or len(data) % SECTOR_SIZE:
            raise DecodeError("Expected complete 2048-byte extracted sectors")
        if data[0] != StreamType.VIDEO:
            raise DecodeError("A picture must start with an F1 sector")
        video = bytearray()
        control = bytearray()
        ended = False
        for start in range(0, len(data), SECTOR_SIZE):
            sector = data[start:start + SECTOR_SIZE]
            if ended:
                raise DecodeError("Unexpected sector after F2; expected one picture")
            if sector[0] == StreamType.VIDEO:
                video.extend(sector[1:])
            elif sector[0] == StreamType.CONTROL:
                control.extend(sector[1:F2_CONTROL_SIZE + 1])
                video.extend(sector[F2_CONTROL_SIZE + 1:])
                ended = True
            elif sector[0] == StreamType.PADDING and sector[3:] == b"\xff" * (SECTOR_SIZE - 3):
                continue
            else:
                raise DecodeError(f"Invalid video sector at byte 0x{start:x}")
        if not ended:
            raise DecodeError("Missing F2 end sector")
        self.video_stream.stream = ConstBitStream(bytes=video)
        self.control_stream = ControlStream(control)

    def decode_rgb(self) -> bytes:
        """Return native 248×216 pixels in packed R, G, B byte order."""
        return self.video_stream.decode_rgb()

    def to_image(self) -> Image.Image:
        return Image.frombytes("RGB", (WIDTH, HEIGHT), self.decode_rgb())

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_image().save(path)

    def __repr__(self):
        return f"Picture({WIDTH}x{HEIGHT})"
