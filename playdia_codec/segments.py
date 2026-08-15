from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bitstream import BitOrder


SECTOR_SIZE = 0x800
F1_MARKER = 0xF1
F2_MARKER = 0xF2
F2_CONTROL_SIZE = 0x23
SYNC_VALUE = 0b00000000100000
SYNC_BITS = 14
COUNTER_BITS = 5
TAG_BITS = 6
PREFERRED_TAG_BITS_TEXT = "001000"
SEGMENT_PREFIX_BITS = SYNC_BITS + COUNTER_BITS + TAG_BITS
SYNC_BITS_TEXT = f"{SYNC_VALUE:0{SYNC_BITS}b}"


@dataclass(frozen=True)
class SectorLog:
    index: int
    raw_offset: int
    marker: int
    payload_start: int | None
    payload_end: int | None
    payload_bytes_used: int
    padding_start: int | None


@dataclass(frozen=True)
class F2Control:
    sector_index: int
    raw_offset: int
    control_bytes: bytes


@dataclass(frozen=True)
class FrameStream:
    data: bytes
    source_offsets: tuple[int, ...]
    sectors: tuple[SectorLog, ...]
    f2_controls: tuple[F2Control, ...]


@dataclass(frozen=True)
class Segment:
    index: int
    counter: int
    missing_counters_before: tuple[int, ...]
    tag_bits: str
    stream_bit_offset: int
    bit_in_byte: int
    raw_byte_offset: int
    payload_bits: str

    @property
    def payload_bit_length(self) -> int:
        return len(self.payload_bits)


def data_to_bit_text(data: bytes, *, bit_order: BitOrder = "msb") -> str:
    if bit_order == "msb":
        return "".join(f"{byte:08b}" for byte in data)
    return "".join("".join("1" if (byte >> bit) & 1 else "0" for bit in range(8)) for byte in data)


def pattern_to_bit_text(value: int, bit_count: int, *, bit_order: BitOrder = "msb") -> str:
    bits = f"{value:0{bit_count}b}"
    return bits if bit_order == "msb" else bits[::-1]


def bit_text_to_int(bits: str, *, bit_order: BitOrder = "msb") -> int:
    return int(bits if bit_order == "msb" else bits[::-1], 2)


def bitslice(data: bytes, start_bit: int, end_bit: int, *, bit_order: BitOrder = "msb") -> str:
    bits = data_to_bit_text(data, bit_order=bit_order)
    if start_bit < 0 or end_bit < start_bit or end_bit > len(bits):
        raise ValueError("invalid bit slice")
    return bits[start_bit:end_bit]


def hex_offset(value: int | None) -> str | None:
    return None if value is None else f"0x{value:X}"


def f2_msf_targets(control: bytes) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for offset in range(3, min(len(control) - 3, 31), 4):
        minute = control[offset]
        second = control[offset + 1]
        frame = control[offset + 2]
        if second >= 75 or frame >= 75:
            continue
        lba = minute * 4500 + second * 75 + frame - 150
        if lba < 0:
            continue
        targets.append({"offset": hex_offset(offset), "minute": minute, "second": second, "frame": frame, "lba": lba})
    return targets


def append_until_padding(
    raw: bytes,
    *,
    start: int,
    end: int,
    stream: bytearray,
    source_offsets: list[int],
) -> tuple[int, int | None]:
    offset = start
    while offset < end:
        if offset + 1 < end and raw[offset] == 0xFF and raw[offset + 1] == 0xFF:
            return offset - start, offset
        stream.append(raw[offset])
        source_offsets.append(offset)
        offset += 1
    return end - start, None


def build_frame_stream(raw: bytes, *, sector_size: int = SECTOR_SIZE) -> FrameStream:
    if sector_size <= 0:
        raise ValueError("sector_size must be positive")

    stream = bytearray()
    source_offsets: list[int] = []
    sectors: list[SectorLog] = []
    f2_controls: list[F2Control] = []

    sector_count = (len(raw) + sector_size - 1) // sector_size
    for sector_index in range(sector_count):
        base = sector_index * sector_size
        end = min(base + sector_size, len(raw))
        if base >= end:
            continue
        marker = raw[base]

        payload_start: int | None
        if marker == F1_MARKER:
            payload_start = base + 1
        elif marker == F2_MARKER:
            control_end = min(base + F2_CONTROL_SIZE, end)
            f2_controls.append(F2Control(sector_index, base, raw[base:control_end]))
            payload_start = control_end
        else:
            payload_start = base

        used, padding_start = append_until_padding(
            raw,
            start=payload_start,
            end=end,
            stream=stream,
            source_offsets=source_offsets,
        )
        sectors.append(
            SectorLog(
                index=sector_index,
                raw_offset=base,
                marker=marker,
                payload_start=payload_start,
                payload_end=end,
                payload_bytes_used=used,
                padding_start=padding_start,
            )
        )

    return FrameStream(bytes(stream), tuple(source_offsets), tuple(sectors), tuple(f2_controls))


def find_segment_starts(
    data: bytes,
    *,
    bit_order: BitOrder = "msb",
    start_bit: int = 0,
    filter_counter: bool = True,
) -> list[tuple[int, int, str]]:
    bits = data_to_bit_text(data, bit_order=bit_order)
    return find_segment_starts_in_bits(
        bits,
        bit_order=bit_order,
        start_bit=start_bit,
        filter_counter=filter_counter,
    )


def find_segment_starts_in_bits(
    bits: str,
    *,
    bit_order: BitOrder = "msb",
    start_bit: int = 0,
    filter_counter: bool = True,
) -> list[tuple[int, int, str]]:
    candidates: list[tuple[int, int, str]] = []
    search = start_bit
    sync_bits = pattern_to_bit_text(SYNC_VALUE, SYNC_BITS, bit_order=bit_order)
    while True:
        bit_offset = bits.find(sync_bits, search)
        if bit_offset < 0:
            break
        if bit_offset + SEGMENT_PREFIX_BITS <= len(bits):
            counter_start = bit_offset + SYNC_BITS
            tag_start = counter_start + COUNTER_BITS
            counter = bit_text_to_int(
                bits[counter_start:tag_start],
                bit_order=bit_order,
            )
            tag_bits = bits[tag_start : tag_start + TAG_BITS]
            candidates.append((bit_offset, counter, tag_bits))
            search = bit_offset + SEGMENT_PREFIX_BITS
            continue
        search = bit_offset + 1

    if not filter_counter:
        return candidates

    return filter_counter_candidates(candidates)


def filter_counter_candidates(candidates: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    starts: list[tuple[int, int, str]] = []
    expected_counter = 0
    index = 0

    while index < len(candidates) and expected_counter < (1 << COUNTER_BITS):
        matching: list[tuple[int, int, str]] = []
        first_later: tuple[int, int, str] | None = None
        first_preferred_later: tuple[int, int, str] | None = None
        for candidate in candidates[index:]:
            _, counter, tag_bits = candidate
            if counter < expected_counter:
                continue
            if counter == expected_counter:
                matching.append(candidate)
            else:
                if first_later is None:
                    first_later = candidate
                if first_preferred_later is None and tag_bits == PREFERRED_TAG_BITS_TEXT:
                    first_preferred_later = candidate

        if matching:
            selected = next(
                (candidate for candidate in matching if candidate[2] == PREFERRED_TAG_BITS_TEXT),
                matching[0],
            )
        elif starts and first_preferred_later is not None:
            selected = first_preferred_later
        elif starts and first_later is not None:
            selected = first_later
        else:
            break

        starts.append(selected)
        while index < len(candidates) and candidates[index][0] <= selected[0]:
            index += 1
        expected_counter = selected[1] + 1

    return starts


def missing_counters(previous_counter: int | None, counter: int) -> tuple[int, ...]:
    if previous_counter is None:
        return tuple(range(counter))
    if counter <= previous_counter + 1:
        return ()
    return tuple(range(previous_counter + 1, counter))


def parse_segments(
    data: bytes,
    *,
    bit_order: BitOrder = "msb",
    start_bit: int = 0,
    source_offsets: tuple[int, ...] | None = None,
    filter_counter: bool = True,
) -> list[Segment]:
    if source_offsets is None:
        source_offsets = tuple(range(len(data)))
    if len(source_offsets) != len(data):
        raise ValueError("source_offsets must have one entry per data byte")

    bits = data_to_bit_text(data, bit_order=bit_order)
    starts = find_segment_starts_in_bits(
        bits,
        bit_order=bit_order,
        start_bit=start_bit,
        filter_counter=filter_counter,
    )
    segments: list[Segment] = []
    stream_end = len(bits)
    previous_counter: int | None = None
    for index, (bit_offset, counter, tag_bits) in enumerate(starts):
        stream_byte_offset = bit_offset // 8
        bit_in_byte = bit_offset % 8
        raw_byte_offset = source_offsets[stream_byte_offset]
        payload_start = bit_offset + SEGMENT_PREFIX_BITS
        end = starts[index + 1][0] if index + 1 < len(starts) else stream_end
        segments.append(
            Segment(
                index=index,
                counter=counter,
                missing_counters_before=missing_counters(previous_counter, counter),
                tag_bits=tag_bits,
                stream_bit_offset=bit_offset,
                bit_in_byte=bit_in_byte,
                raw_byte_offset=raw_byte_offset,
                payload_bits=bits[payload_start:end],
            )
        )
        previous_counter = counter
    return segments


def segment_to_json(segment: Segment, *, include_bits: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "index": segment.index,
        "counter": segment.counter,
        "tag_bits": segment.tag_bits,
        "stream_bit_offset": hex_offset(segment.stream_bit_offset),
        "bit_in_byte": segment.bit_in_byte,
        "raw_byte_offset": hex_offset(segment.raw_byte_offset),
        "payload_bit_length": segment.payload_bit_length,
    }
    if segment.missing_counters_before:
        item["missing_counters_before"] = list(segment.missing_counters_before)
    if include_bits:
        item["payload_bits"] = segment.payload_bits
    return item


def sector_to_json(sector: SectorLog) -> dict[str, Any]:
    return {
        "index": sector.index,
        "raw_offset": hex_offset(sector.raw_offset),
        "marker": f"{sector.marker:02X}",
        "payload_start": hex_offset(sector.payload_start),
        "payload_end": hex_offset(sector.payload_end),
        "payload_bytes_used": sector.payload_bytes_used,
        "padding_start": hex_offset(sector.padding_start),
    }


def f2_to_json(control: F2Control) -> dict[str, Any]:
    return {
        "sector_index": control.sector_index,
        "raw_offset": hex_offset(control.raw_offset),
        "control_bytes": control.control_bytes.hex(" "),
        "type": control.control_bytes[1] if len(control.control_bytes) > 1 else None,
        "msf_targets": f2_msf_targets(control.control_bytes),
    }


def dump_frame_bytes(
    raw: bytes,
    *,
    bit_order: BitOrder = "msb",
    start_bit: int = 0,
    include_bits: bool = True,
    filter_counter: bool = True,
) -> dict[str, Any]:
    frame_stream = build_frame_stream(raw)
    segments = parse_segments(
        frame_stream.data,
        bit_order=bit_order,
        start_bit=start_bit,
        source_offsets=frame_stream.source_offsets,
        filter_counter=filter_counter,
    )
    return {
        "size_bytes": len(raw),
        "stream_size_bytes": len(frame_stream.data),
        "bit_order": bit_order,
        "sync_bits": SYNC_BITS_TEXT,
        "counter_bits": COUNTER_BITS,
        "tag_bits": TAG_BITS,
        "preferred_tag_bits": PREFERRED_TAG_BITS_TEXT,
        "counter_filter": filter_counter,
        "sector_count": len(frame_stream.sectors),
        "sectors": [sector_to_json(sector) for sector in frame_stream.sectors],
        "f2": [f2_to_json(control) for control in frame_stream.f2_controls],
        "segment_count": len(segments),
        "segments": [segment_to_json(segment, include_bits=include_bits) for segment in segments],
    }


def dump_file(
    path: str | Path,
    *,
    bit_order: BitOrder = "msb",
    start_bit: int = 0,
    include_bits: bool = True,
    filter_counter: bool = True,
) -> dict[str, Any]:
    resolved = Path(path)
    result = dump_frame_bytes(
        resolved.read_bytes(),
        bit_order=bit_order,
        start_bit=start_bit,
        include_bits=include_bits,
        filter_counter=filter_counter,
    )
    return {"path": str(resolved), **result}


def parse_int(value: str) -> int:
    return int(value, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dump sync-delimited bit segments as JSON.")
    parser.add_argument("frame", type=Path)
    parser.add_argument("--bit-order", choices=("msb", "lsb"), default="msb")
    parser.add_argument("--start-bit", type=parse_int, default=0)
    parser.add_argument("--raw-candidates", action="store_true", help="do not filter by expected counter sequence")
    parser.add_argument("--no-bits", action="store_true", help="omit payload_bits strings")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)

    result = dump_file(
        args.frame,
        bit_order=args.bit_order,
        start_bit=args.start_bit,
        include_bits=not args.no_bits,
        filter_counter=not args.raw_candidates,
    )
    print(json.dumps(result, indent=args.indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
