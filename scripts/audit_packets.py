#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from playdia_codec.metrics import (
    alternating_run_stats,
    bit_counts,
    bits_to_string,
    common_bit_suffix,
    sha256_hex,
    shannon_entropy,
    trailing_zero_bits_after_suffix,
)
from playdia_codec.packet import PlaydiaPacket


DEFAULT_TERMINATOR = "00000000100001000000"


def iter_packet_paths(folder: Path) -> list[Path]:
    return sorted(folder.glob("frame_*.bin"))


def packet_index(path: Path) -> int:
    stem = path.stem
    return int(stem.split("_")[-1])


def audit_folder(folder: Path, terminator: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    bitstrings_msb: list[str] = []
    bitstrings_lsb: list[str] = []
    duplicate_groups: dict[str, list[int]] = defaultdict(list)

    for path in iter_packet_paths(folder):
        pkt = PlaydiaPacket.from_file(path)
        payload = pkt.extract_payload()
        stripped_payload = pkt.extract_payload(strip_subframe_headers=True)
        data = payload.data
        f2_targets = pkt.f2_msf_targets()
        subframe_headers = pkt.subframe_headers()
        internal_subframe_headers = pkt.subframe_headers(include_primary=False)
        zeros, ones = bit_counts(data)
        alt = alternating_run_stats(data)
        bits_msb = bits_to_string(data, msb_first=True)
        bits_lsb = bits_to_string(data, msb_first=False)
        bitstrings_msb.append(bits_msb)
        bitstrings_lsb.append(bits_lsb)
        raw_hash = sha256_hex(pkt.raw)
        payload_hash = sha256_hex(data)
        duplicate_groups[raw_hash].append(packet_index(path))

        rows.append(
            {
                "frame_index": packet_index(path),
                "path": str(path),
                "packet_size": len(pkt.raw),
                "sector_count": pkt.sector_count,
                "sector_markers": " ".join(f"{m:02X}" for m in pkt.sector_markers),
                "h04": pkt.header_value_04,
                "h27": pkt.secondary_value_27,
                "h28": pkt.header_value_28,
                "f2_type": pkt.f2_type(),
                "f2_msf_targets": ";".join(
                    f"{offset}:{minute:02d}:{second:02d}:{frame:02d}:{lba}"
                    for offset, minute, second, frame, lba in f2_targets
                ),
                "payload_len": len(data),
                "payload_len_subframe_stripped": len(stripped_payload.data),
                "payload_len_before_padding_strip": payload.bytes_before_full_padding_strip,
                "trailing_ff_stripped": payload.trailing_ff_stripped,
                "f2_tail_bytes": payload.f2_tail_bytes,
                "f2_tail_non_ff_bytes": payload.f2_tail_non_ff_bytes,
                "subframe_header_bytes_stripped": stripped_payload.subframe_headers_stripped,
                "subframe_sequence": " ".join(f"{header.marker_value:02X}" for header in subframe_headers),
                "internal_subframe_sequence": " ".join(
                    f"{header.marker_value:02X}@{header.raw_offset:04X}" for header in internal_subframe_headers
                ),
                "byte_entropy": shannon_entropy(data),
                "zeros": zeros,
                "ones": ones,
                "zero_ratio": zeros / (zeros + ones) if zeros + ones else 0.0,
                "count_55": data.count(0x55),
                "count_aa": data.count(0xAA),
                "density_55_aa": (data.count(0x55) + data.count(0xAA)) / len(data) if data else 0.0,
                "longest_alt_bits": alt.longest_bits,
                "alt_bits_ge_16": alt.bits_in_runs_ge_16,
                "alt_bits_ge_32": alt.bits_in_runs_ge_32,
                "alt_bits_ge_64": alt.bits_in_runs_ge_64,
                "terminator_zero_align_msb": trailing_zero_bits_after_suffix(bits_msb, terminator),
                "terminator_zero_align_lsb": trailing_zero_bits_after_suffix(bits_lsb, terminator),
                "raw_sha256": raw_hash,
                "payload_sha256": payload_hash,
            }
        )

    summary: dict[str, object] = {
        "folder": str(folder),
        "packet_count": len(rows),
        "packet_sizes": dict(Counter(row["packet_size"] for row in rows)),
        "sector_counts": dict(Counter(row["sector_count"] for row in rows)),
        "h04_values": dict(Counter(row["h04"] for row in rows)),
        "h27_values": dict(Counter(row["h27"] for row in rows)),
        "h28_values": dict(Counter(row["h28"] for row in rows)),
        "internal_subframe_header_counts": dict(
            Counter(
                0 if not row["internal_subframe_sequence"] else len(str(row["internal_subframe_sequence"]).split())
                for row in rows
            )
        ),
        "subframe_sequences": dict(Counter(row["subframe_sequence"] for row in rows)),
        "internal_subframe_marker_values": dict(
            Counter(
                marker.split("@", 1)[0]
                for row in rows
                for marker in str(row["internal_subframe_sequence"]).split()
            )
        ),
        "common_suffix_msb": common_bit_suffix(bitstrings_msb),
        "common_suffix_lsb": common_bit_suffix(bitstrings_lsb),
        "terminator_msb_align_counts": dict(Counter(row["terminator_zero_align_msb"] for row in rows)),
        "terminator_lsb_align_counts": dict(Counter(row["terminator_zero_align_lsb"] for row in rows)),
        "duplicate_raw_groups": [idxs for idxs in duplicate_groups.values() if len(idxs) > 1],
    }
    return rows, summary


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def print_summary(summary: dict[str, object]) -> None:
    print(f"\n== {summary['folder']} ==")
    print(f"packets: {summary['packet_count']}")
    print(f"packet_sizes: {summary['packet_sizes']}")
    print(f"sector_counts: {summary['sector_counts']}")
    print(f"h04_values: {summary['h04_values']}")
    print(f"h27_values: {summary['h27_values']}")
    print(f"h28_values: {summary['h28_values']}")
    print(f"internal_subframe_header_counts: {summary['internal_subframe_header_counts']}")
    print(f"internal_subframe_marker_values: {summary['internal_subframe_marker_values']}")
    sequences = Counter(summary["subframe_sequences"])
    if sequences:
        print("top_subframe_sequences:")
        for sequence, count in sequences.most_common(8):
            print(f"  {count:3d} {sequence}")
    msb_suffix = str(summary["common_suffix_msb"])
    lsb_suffix = str(summary["common_suffix_lsb"])
    print(f"common_suffix_msb_len: {len(msb_suffix)} tail: {msb_suffix[-64:]}")
    print(f"common_suffix_lsb_len: {len(lsb_suffix)} tail: {lsb_suffix[-64:]}")
    print(f"terminator_msb_align_counts: {summary['terminator_msb_align_counts']}")
    print(f"terminator_lsb_align_counts: {summary['terminator_lsb_align_counts']}")
    groups = summary["duplicate_raw_groups"]
    if groups:
        print("duplicate raw packet groups:")
        for idxs in groups:
            print(f"  n={len(idxs)} first={idxs[0]} last={idxs[-1]} indices={idxs[:24]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Playdia F1/F2 packet folders.")
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--csv-dir", type=Path, default=None)
    parser.add_argument("--terminator", default=DEFAULT_TERMINATOR)
    args = parser.parse_args()

    for folder in args.folders:
        rows, summary = audit_folder(folder, args.terminator)
        print_summary(summary)
        if args.csv_dir is not None:
            write_csv(args.csv_dir / f"{folder.name}.csv", rows)


if __name__ == "__main__":
    main()
