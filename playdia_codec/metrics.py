from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def bit_counts(data: bytes, *, msb_first: bool = True) -> tuple[int, int]:
    ones = 0
    for byte in data:
        ones += int(byte).bit_count()
    total = len(data) * 8
    return total - ones, ones


def bits_to_string(data: bytes, *, msb_first: bool = True) -> str:
    if msb_first:
        return "".join(f"{byte:08b}" for byte in data)
    return "".join(f"{byte:08b}"[::-1] for byte in data)


@dataclass(frozen=True)
class AlternatingRunStats:
    longest_bits: int
    bits_in_runs_ge_16: int
    bits_in_runs_ge_32: int
    bits_in_runs_ge_64: int


def alternating_run_stats(data: bytes, *, msb_first: bool = True) -> AlternatingRunStats:
    previous: int | None = None
    run = 0
    longest = 0
    ge16 = 0
    ge32 = 0
    ge64 = 0

    def finish(length: int) -> None:
        nonlocal longest, ge16, ge32, ge64
        longest = max(longest, length)
        if length >= 16:
            ge16 += length
        if length >= 32:
            ge32 += length
        if length >= 64:
            ge64 += length

    for byte in data:
        bit_range = range(7, -1, -1) if msb_first else range(8)
        for shift in bit_range:
            bit = (byte >> shift) & 1
            if previous is None:
                run = 1
            elif bit != previous:
                run += 1
            else:
                finish(run)
                run = 1
            previous = bit

    if run:
        finish(run)

    return AlternatingRunStats(longest, ge16, ge32, ge64)


def common_bit_suffix(bitstrings: list[str]) -> str:
    if not bitstrings:
        return ""
    max_len = min(len(s) for s in bitstrings)
    suffix_len = 0
    for offset in range(1, max_len + 1):
        bit = bitstrings[0][-offset]
        if all(s[-offset] == bit for s in bitstrings):
            suffix_len = offset
        else:
            break
    return bitstrings[0][len(bitstrings[0]) - suffix_len :] if suffix_len else ""


def trailing_zero_bits_after_suffix(bitstring: str, suffix: str) -> int | None:
    for zeros in range(8):
        needle = suffix + ("0" * zeros)
        if bitstring.endswith(needle):
            return zeros
    return None
