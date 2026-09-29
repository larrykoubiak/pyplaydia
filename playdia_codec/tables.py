"""Recovered AK8000 run/level codes (sign bit follows each codeword).

Adapted from PlaydiaEmu, revision 6e75840, video/ak8000.rs.
Copyright (c) 2026, Aloys (AloysHF). BSD-3-Clause; see
../LICENSES/PlaydiaEmu-BSD-3-Clause.txt and ../THIRD_PARTY_NOTICES.md.
"""

# (codeword, zero run, magnitude). These are custom codes, not JPEG/MPEG tables.
COEFFICIENT_CODES = (
    ("0000000010000", 0, 25),
    ("0000000010001", 5, 4),
    ("0000000010010", 0, 24),
    ("0000000010011", 0, 23),
    ("0000000010100", 3, 8),
    ("0000000010101", 3, 7),
    ("0000000010110", 3, 6),
    ("0000000010111", 2, 8),
    ("0000000011000", 2, 7),
    ("0000000011001", 2, 6),
    ("0000000011010", 1, 9),
    ("0000000011011", 1, 8),
    ("0000000011100", 1, 7),
    ("0000000011101", 0, 22),
    ("0000000011110", 0, 21),
    ("0000000011111", 0, 20),
    ("000000010000", 9, 1),
    ("000000010001", 8, 1),
    ("000000010010", 7, 1),
    ("000000010011", 5, 3),
    ("000000010100", 5, 2),
    ("000000010101", 4, 5),
    ("000000010110", 4, 4),
    ("000000010111", 4, 3),
    ("000000011000", 3, 5),
    ("000000011001", 3, 4),
    ("000000011010", 2, 5),
    ("000000011011", 1, 6),
    ("000000011100", 0, 19),
    ("000000011101", 0, 18),
    ("000000011110", 0, 17),
    ("000000011111", 0, 16),
    ("0000001000", 3, 3),
    ("0000001001", 2, 4),
    ("0000001010", 2, 3),
    ("0000001011", 1, 5),
    ("0000001100", 0, 15),
    ("0000001101", 0, 14),
    ("0000001110", 0, 13),
    ("0000001111", 0, 12),
    ("00000100", 6, 1),
    ("00000101", 4, 2),
    ("00000110", 3, 2),
    ("00000111", 1, 4),
    ("0000100", 5, 1),
    ("0000101", 2, 2),
    ("0000110", 0, 8),
    ("0000111", 0, 7),
    ("000100", 4, 1),
    ("000101", 1, 2),
    ("000110", 0, 6),
    ("000111", 0, 5),
    ("00100100", 1, 3),
    ("00100101", 0, 11),
    ("00100110", 0, 10),
    ("00100111", 0, 9),
    ("00101", 3, 1),
    ("00110", 2, 1),
    ("00111", 0, 4),
    ("1000", 1, 1),
    ("1001", 0, 3),
    ("101", 0, 2),
    ("11", 0, 1),
)

# Longest codeword (13 bits), including its following sign bit.
LOOKUP_BITS = 14


def _build_lookup():
    # Resolve the sign here too, so each coefficient needs just one lookup.
    # (bits consumed, run, signed level); zero identifies EOB/escape.
    entries = [("01", 0, 0), ("001000", 0, 0)]
    for code, run, level in COEFFICIENT_CODES:
        entries.extend(((code + "0", run, level), (code + "1", run, -level)))
    table = [None] * (1 << LOOKUP_BITS)
    for code, run, level in entries:
        length = len(code)
        first = int(code, 2) << (LOOKUP_BITS - length)
        entry = (length, run, level)
        for index in range(first, first + (1 << (LOOKUP_BITS - length))):
            if table[index] is not None:
                raise ValueError("overlapping coefficient codes")
            table[index] = entry
    return tuple(table)


LOOKUP = _build_lookup()
ZIGZAG = (0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15)
