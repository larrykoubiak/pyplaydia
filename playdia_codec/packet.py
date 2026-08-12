from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SECTOR_SIZE = 0x800
FIRST_PAYLOAD_OFFSET = 0x2A
EARLIEST_PAYLOAD_CANDIDATE_OFFSET = 0x28
F2_TAIL_OFFSET = 0x23
FIRST_MARKER = 0xF1
FINAL_MARKER = 0xF2
HEADER_MAGIC = b"\x00\x80\x04"
SECOND_PREFIX = b"\x00\x80"
SUBFRAME_HEADER_SIZE = 5
SUBFRAME_MARKER_VALUES = (0x24, 0x44, 0x64, 0x84, 0xA4, 0xC4, 0xE4)


class PacketLayoutError(ValueError):
    pass


@dataclass(frozen=True)
class PayloadExtraction:
    data: bytes
    source_offsets: tuple[int, ...]
    bytes_before_full_padding_strip: int
    trailing_ff_stripped: int
    f2_tail_bytes: int
    f2_tail_non_ff_bytes: int
    subframe_headers_stripped: int


@dataclass(frozen=True)
class SubframeHeader:
    raw_offset: int
    marker_value: int
    h28: int
    h29: int

    @property
    def end_offset(self) -> int:
        return self.raw_offset + SUBFRAME_HEADER_SIZE


@dataclass(frozen=True)
class PlaydiaPacket:
    path: Path
    raw: bytes

    @classmethod
    def from_file(cls, path: str | Path) -> "PlaydiaPacket":
        p = Path(path)
        return cls(p, p.read_bytes())

    @property
    def sector_count(self) -> int:
        return len(self.raw) // SECTOR_SIZE

    @property
    def sector_markers(self) -> tuple[int, ...]:
        return tuple(self.raw[i * SECTOR_SIZE] for i in range(self.sector_count))

    @property
    def header_value_04(self) -> int:
        self._require_first_header()
        return self.raw[0x04]

    @property
    def header_value_28(self) -> int:
        self._require_first_header()
        return self.raw[0x28]

    @property
    def secondary_value_27(self) -> int:
        self._require_first_header()
        return self.raw[0x27]

    @property
    def duplicated_header_sequence(self) -> bytes:
        self._require_first_header()
        return self.raw[0x05:0x15]

    def validate(self) -> None:
        if len(self.raw) % SECTOR_SIZE != 0:
            raise PacketLayoutError(f"{self.path}: size is not a multiple of 0x800")
        if self.sector_count < 2:
            raise PacketLayoutError(f"{self.path}: expected at least one F1 sector and one F2 sector")
        markers = self.sector_markers
        if markers[-1] != FINAL_MARKER:
            raise PacketLayoutError(f"{self.path}: final sector marker is 0x{markers[-1]:02x}, not F2")
        bad = [(i, marker) for i, marker in enumerate(markers[:-1]) if marker != FIRST_MARKER]
        if bad:
            idx, marker = bad[0]
            raise PacketLayoutError(f"{self.path}: sector {idx} marker is 0x{marker:02x}, not F1")
        self._require_first_header()

    def _require_first_header(self) -> None:
        if len(self.raw) < FIRST_PAYLOAD_OFFSET:
            raise PacketLayoutError(f"{self.path}: too short for first-sector header")
        if self.raw[0] != FIRST_MARKER:
            raise PacketLayoutError(f"{self.path}: first byte is not F1")
        if self.raw[0x01:0x04] != HEADER_MAGIC:
            raise PacketLayoutError(f"{self.path}: missing 00 80 04 header magic")
        if self.raw[0x05:0x15] != self.raw[0x15:0x25]:
            raise PacketLayoutError(f"{self.path}: duplicated 16-byte header sequence differs")
        if self.raw[0x25:0x27] != SECOND_PREFIX:
            raise PacketLayoutError(f"{self.path}: missing 00 80 secondary header prefix")

    def f2_prefix(self) -> bytes:
        base = (self.sector_count - 1) * SECTOR_SIZE
        return self.raw[base : base + F2_TAIL_OFFSET]

    def f2_type(self) -> int:
        prefix = self.f2_prefix()
        return prefix[1] if len(prefix) > 1 else 0

    def f2_msf_targets(self) -> tuple[tuple[int, int, int, int, int], ...]:
        """Return valid-looking CD MSF slots as (offset, minute, second, frame, lba)."""
        prefix = self.f2_prefix()
        targets: list[tuple[int, int, int, int, int]] = []
        for offset in range(3, min(len(prefix) - 3, 31), 4):
            minute = prefix[offset]
            second = prefix[offset + 1]
            frame = prefix[offset + 2]
            if second >= 75 or frame >= 75:
                continue
            lba = minute * 4500 + second * 75 + frame - 150
            if lba < 0:
                continue
            targets.append((offset, minute, second, frame, lba))
        return tuple(targets)

    def f2_tail_without_padding(self) -> bytes:
        base = (self.sector_count - 1) * SECTOR_SIZE
        tail = self.raw[base + F2_TAIL_OFFSET : base + SECTOR_SIZE]
        end = len(tail)
        while end > 0 and tail[end - 1] == 0xFF:
            end -= 1
        return tail[:end]

    def subframe_headers(self, *, include_primary: bool = True) -> tuple[SubframeHeader, ...]:
        """Return 00 80 <marker> h28 h29 chunk headers found in the raw packet."""
        self._require_first_header()
        h28 = self.raw[0x28]
        h29 = self.raw[0x29]
        headers: list[SubframeHeader] = []
        for offset in range(0, max(0, len(self.raw) - SUBFRAME_HEADER_SIZE + 1)):
            if not include_primary and offset == 0x25:
                continue
            if self.raw[offset : offset + 2] != SECOND_PREFIX:
                continue
            marker_value = self.raw[offset + 2]
            if marker_value not in SUBFRAME_MARKER_VALUES:
                continue
            if self.raw[offset + 3] != h28 or self.raw[offset + 4] != h29:
                continue
            headers.append(SubframeHeader(offset, marker_value, h28, h29))
        return tuple(headers)

    def extract_payload(
        self,
        *,
        first_payload_offset: int = FIRST_PAYLOAD_OFFSET,
        include_f2_tail: bool = True,
        strip_trailing_ff: bool = True,
        strip_subframe_headers: bool = False,
    ) -> PayloadExtraction:
        self.validate()
        if first_payload_offset < EARLIEST_PAYLOAD_CANDIDATE_OFFSET or first_payload_offset >= SECTOR_SIZE:
            raise ValueError(
                "first_payload_offset must be in "
                f"0x{EARLIEST_PAYLOAD_CANDIDATE_OFFSET:02x}..0x{SECTOR_SIZE - 1:03x}"
            )
        subframe_header_offsets: set[int] = set()
        if strip_subframe_headers:
            for header in self.subframe_headers(include_primary=False):
                subframe_header_offsets.update(range(header.raw_offset, header.end_offset))

        data = bytearray()
        offsets: list[int] = []

        def append_range(start: int, end: int) -> None:
            for raw_offset in range(start, end):
                if raw_offset in subframe_header_offsets:
                    continue
                data.append(self.raw[raw_offset])
                offsets.append(raw_offset)

        append_range(first_payload_offset, SECTOR_SIZE)
        for sector_index in range(1, self.sector_count - 1):
            base = sector_index * SECTOR_SIZE
            append_range(base + 1, base + SECTOR_SIZE)

        f2_tail = self.f2_tail_without_padding() if include_f2_tail else b""
        f2_tail_non_ff = sum(byte != 0xFF for byte in f2_tail)
        if f2_tail:
            base = (self.sector_count - 1) * SECTOR_SIZE + F2_TAIL_OFFSET
            append_range(base, base + len(f2_tail))

        before_strip = len(data)
        stripped = 0
        if strip_trailing_ff:
            while data and data[-1] == 0xFF:
                data.pop()
                offsets.pop()
                stripped += 1

        return PayloadExtraction(
            bytes(data),
            tuple(offsets),
            before_strip,
            stripped,
            len(f2_tail),
            f2_tail_non_ff,
            len(subframe_header_offsets),
        )
