import argparse
import math
import os
from collections import Counter
from pathlib import Path
import pandas as pd


def bytes_to_binary(byte_data):
    return ''.join(format(byte, '08b') for byte in byte_data)


def shannon_entropy(counter, total):
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counter.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def byte_stats(data, top_n=16):
    counter = Counter(data)
    total = len(data)
    entropy = shannon_entropy(counter, total)
    top = counter.most_common(top_n)
    return {
        "size_bytes": total,
        "entropy_bits_per_byte": entropy,
        "top_bytes": [(f"{b:02X}", c, round((c / total) * 100, 4)) for b, c in top],
    }


def bit_entropy(data):
    bit_counter = Counter()
    for b in data:
        bit_counter.update([(b >> i) & 1 for i in range(8)])
    total_bits = len(data) * 8
    entropy = shannon_entropy(bit_counter, total_bits)
    return {"entropy_bits": entropy, "bit_counts": dict(bit_counter)}


def top_bit_patterns(data, lengths=(4, 8, 12), limit_bits=200_000, top_n=16):
    bits = bytes_to_binary(data)
    if limit_bits and limit_bits < len(bits):
        bits = bits[:limit_bits]
    results = {}
    for ln in lengths:
        counter = Counter(bits[i:i+ln] for i in range(0, len(bits) - ln + 1))
        results[ln] = counter.most_common(top_n)
    return results


def scan_huffman_like_prefixes(data, max_len=12, limit_bits=200_000):
    """
    Collect counts of bit prefixes up to max_len. This helps spot canonical Huffman-ish trees:
    a steep drop-off or very common short codes can hint at control markers.
    """
    bits = bytes_to_binary(data)
    if limit_bits and limit_bits < len(bits):
        bits = bits[:limit_bits]
    prefix_counts = [Counter() for _ in range(max_len + 1)]
    for i in range(len(bits)):
        max_slice = min(max_len, len(bits) - i)
        for ln in range(1, max_slice + 1):
            prefix_counts[ln][bits[i:i+ln]] += 1
    summary = {}
    for ln in range(1, max_len + 1):
        total = sum(prefix_counts[ln].values())
        top = prefix_counts[ln].most_common(8)
        summary[ln] = {"total": total, "top": top}
    return summary


def bucket_stats(data, bucket_size, top_n=3):
    buckets = []
    for start in range(0, len(data), bucket_size):
        end = min(start + bucket_size, len(data))
        window = data[start:end]
        counter = Counter(window)
        ent = shannon_entropy(counter, len(window))
        top = counter.most_common(top_n)
        buckets.append({"start": start, "end": end - 1, "entropy": ent, "top": top})
    return buckets


def analyze_file(path, args):
    raw = Path(path).read_bytes()
    if args.ignore_ff:
        data = bytes(b for b in raw if b != 0xFF)
        removed = len(raw) - len(data)
        print(f"Analyzing {path} ({len(raw)} bytes, removed {removed} 0xFF padding bytes)")
    else:
        data = raw
        print(f"Analyzing {path} ({len(data)} bytes)")

    masks = [None] + args.xor_masks
    for mask in masks:
        if mask is None:
            view = data
            tag = "raw"
        else:
            view = bytes(b ^ mask for b in data)
            tag = f"xor_{mask:02X}"
        print(f"\n=== view: {tag} ===")
        bstats = byte_stats(view)
        print(f"Byte entropy: {bstats['entropy_bits_per_byte']:.4f} bits/byte")
        print("Top bytes (hex, count, %):")
        for entry in bstats["top_bytes"]:
            print("  ", entry)

        bitinfo = bit_entropy(view)
        zeros = bitinfo["bit_counts"].get(0, 0)
        ones = bitinfo["bit_counts"].get(1, 0)
        print(f"Bit entropy: {bitinfo['entropy_bits']:.4f} bits, zeros: {zeros}, ones: {ones}")

        patterns = top_bit_patterns(
            view,
            lengths=args.pattern_lengths,
            limit_bits=args.limit_bits,
            top_n=args.top_n,
        )
        for ln, top in patterns.items():
            print(f"Top {args.top_n} patterns of length {ln}:")
            for pat, count in top:
                print(f"  {pat} -> {count}")

        if args.scan_prefixes:
            prefixes = scan_huffman_like_prefixes(
                view,
                max_len=args.prefix_max_len,
                limit_bits=args.limit_bits,
            )
            print("Prefix histogram (top 8 per length):")
            for ln in range(1, args.prefix_max_len + 1):
                top = prefixes[ln]["top"]
                print(f"  len {ln}: {top}")

        if args.bucket_size > 0:
            print(f"Buckets (size {args.bucket_size} bytes):")
            buckets = bucket_stats(view, args.bucket_size, top_n=3)
            for b in buckets:
                rng = f"{b['start']:06X}-{b['end']:06X}"
                tops = " ".join([f"{bt:02X}:{cnt}" for bt, cnt in b["top"]])
                print(f"  {rng} entropy={b['entropy']:.4f} top=[{tops}]")


def main():
    parser = argparse.ArgumentParser(description="Bitstream analysis helpers")
    parser.add_argument("files", nargs="+", help="Input binary files to analyze")
    parser.add_argument("--pattern-lengths", nargs="+", type=int, default=[4, 8, 12],
                        help="Bit pattern lengths to histogram (default: 4 8 12)")
    parser.add_argument("--limit-bits", type=int, default=200_000,
                        help="Max bits to sample for pattern analysis (default: 200000)")
    parser.add_argument("--top-n", type=int, default=16, help="Top-N patterns to show")
    parser.add_argument("--scan-prefixes", action="store_true",
                        help="Scan prefix frequencies up to --prefix-max-len")
    parser.add_argument("--prefix-max-len", type=int, default=12,
                        help="Max prefix length for prefix scan (default: 12)")
    parser.add_argument("--ignore-ff", action="store_true",
                        help="Ignore bytes equal to 0xFF (common padding) in stats and pattern scans")
    parser.add_argument("--xor-masks", nargs="+", type=lambda x: int(x, 0), default=[],
                        help="Try additional views by XORing the stream with these byte masks (e.g., 0x55 0xAA)")
    parser.add_argument("--bucket-size", type=int, default=0,
                        help="If >0, compute per-bucket entropy/top bytes with this bucket size (bytes)")
    parser.add_argument("--export-excel", type=str, default=None,
                        help="If set, export collected stats for all files to an Excel workbook")
    args = parser.parse_args()

    if args.export_excel:
        collect_to_excel(args)
    else:
        for f in args.files:
            analyze_file(f, args)


def collect_to_excel(args):
    """
    Collect bit_analysis-style stats for provided files and export to Excel.

    Sheets:
      - entropy: file, view, size_bytes, byte_entropy, bit_entropy, zeros, ones
      - top_bytes: file, view, byte_hex, count, pct
      - patterns: file, view, length, pattern, count
      - prefixes (optional): file, view, length, prefix, count
      - buckets (optional): file, view, start, end, entropy, top_bytes (string)
    """
    xor_masks = args.xor_masks or []
    entropy_rows = []
    top_bytes_rows = []
    pattern_rows = []
    prefix_rows = []
    bucket_rows = []

    for f in args.files:
        path = Path(f)
        raw = path.read_bytes()
        data = bytes(b for b in raw if b != 0xFF) if args.ignore_ff else raw
        views = [("raw", data)]
        for m in xor_masks:
            views.append((f"xor_{m:02X}", bytes(b ^ m for b in data)))

        for view_name, view_data in views:
            bstats = byte_stats(view_data)
            bitinfo = bit_entropy(view_data)
            entropy_rows.append(
                {
                    "file": path.name,
                    "view": view_name,
                    "size_bytes": bstats["size_bytes"],
                    "byte_entropy": bstats["entropy_bits_per_byte"],
                    "bit_entropy": bitinfo["entropy_bits"],
                    "zeros": bitinfo["bit_counts"].get(0, 0),
                    "ones": bitinfo["bit_counts"].get(1, 0),
                }
            )
            for byte_hex, count, pct in bstats["top_bytes"]:
                top_bytes_rows.append(
                    {
                        "file": path.name,
                        "view": view_name,
                        "byte": byte_hex,
                        "count": count,
                        "pct": pct,
                    }
                )
            patterns = top_bit_patterns(
                view_data,
                lengths=args.pattern_lengths,
                limit_bits=args.limit_bits,
                top_n=args.top_n,
            )
            for ln, top_list in patterns.items():
                for pat, count in top_list:
                    pattern_rows.append(
                        {
                            "file": path.name,
                            "view": view_name,
                            "length": ln,
                            "pattern": pat,
                            "count": count,
                        }
                    )
            if args.scan_prefixes:
                prefixes = scan_huffman_like_prefixes(
                    view_data,
                    max_len=args.prefix_max_len,
                    limit_bits=args.limit_bits,
                )
                for ln in range(1, args.prefix_max_len + 1):
                    for prefix, count in prefixes[ln]["top"]:
                        prefix_rows.append(
                            {
                                "file": path.name,
                                "view": view_name,
                                "length": ln,
                                "prefix": prefix,
                                "count": count,
                            }
                        )
            if args.bucket_size > 0:
                buckets = bucket_stats(view_data, args.bucket_size, top_n=3)
                for b in buckets:
                    top_str = " ".join([f"{bt:02X}:{cnt}" for bt, cnt in b["top"]])
                    bucket_rows.append(
                        {
                            "file": path.name,
                            "view": view_name,
                            "start": b["start"],
                            "end": b["end"],
                            "entropy": b["entropy"],
                            "top": top_str,
                        }
                    )

    out = Path(args.export_excel)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out) as writer:
        pd.DataFrame(entropy_rows).to_excel(writer, sheet_name="entropy", index=False)
        pd.DataFrame(top_bytes_rows).to_excel(writer, sheet_name="top_bytes", index=False)
        pd.DataFrame(pattern_rows).to_excel(writer, sheet_name="patterns", index=False)
        if args.scan_prefixes and prefix_rows:
            pd.DataFrame(prefix_rows).to_excel(writer, sheet_name="prefixes", index=False)
        if args.bucket_size > 0 and bucket_rows:
            pd.DataFrame(bucket_rows).to_excel(writer, sheet_name="buckets", index=False)
    print(f"Wrote analysis for {len(args.files)} files to {out}")


if __name__ == "__main__":
    main()
