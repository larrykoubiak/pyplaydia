"""4×4 inverse DCT and 4:2:0 reconstruction matching PlaydiaEmu.

Copyright (c) 2026, Aloys (AloysHF). Adapted under BSD-3-Clause;
see ../LICENSES/PlaydiaEmu-BSD-3-Clause.txt and ../THIRD_PARTY_NOTICES.md.
"""

WIDTH = 248
HEIGHT = 216

def _inverse_dct_1d(a, b, c, d):
    """Four-point cosine transform, with the basis scaled by 2**14."""
    even0 = (a + c) * 8192
    even1 = (a - c) * 8192
    odd0 = b * 10703 + d * 4433
    odd1 = b * 4433 - d * 10703
    return even0 + odd0, even1 + odd1, even1 - odd1, even0 - odd0


def inverse_dct(coefficients, quant, factor):
    """Dequantize 16 coefficients in raster order and return 4×4 samples."""
    scaled = [c * q * factor for c, q in zip(coefficients, quant)]
    if not any(scaled[1:]):
        # Exact DC-only equivalent of the two fixed-point transform passes.
        return [(scaled[0] + 128) >> 8] * 16
    intermediate = [_inverse_dct_1d(*scaled[offset:offset + 4]) for offset in range(0, 16, 4)]
    result = [0] * 16
    for x, column in enumerate(zip(*intermediate)):
        for y, value in enumerate(_inverse_dct_1d(*column)):
            # Two transform passes and factor/64 require division by 2**34.
            # Round only here to preserve the original integer result.
            result[y * 4 + x] = (value + (1 << 33)) >> 34
    return result


def reconstruct_rgb(rows, header):
    """Convert decoded, DC-predicted blocks to packed RGB888 bytes."""
    planes = [[0] * (WIDTH * HEIGHT), [0] * (WIDTH * HEIGHT // 4), [0] * (WIDTH * HEIGHT // 4)]
    for row in rows:
        for index, coefficients in enumerate(row.blocks):
            macroblock, block = divmod(index, 6)
            component = 0 if block < 4 else block - 3
            quant = header.quant_y if component == 0 else header.quant_c
            pixels = inverse_dct(coefficients, quant, header.factor)
            stride = WIDTH if component == 0 else WIDTH // 2
            x = macroblock * 8 + (block % 2) * 4 if component == 0 else macroblock * 4
            y = (row.lmbn - 1) * 8 + (block // 2) * 4 if component == 0 else (row.lmbn - 1) * 4
            plane = planes[component]
            for py in range(4):
                offset = (y + py) * stride + x
                plane[offset:offset + 4] = pixels[py * 4:py * 4 + 4]

    rgb = bytearray(WIDTH * HEIGHT * 3)
    luma_plane, cb_plane, cr_plane = planes
    # Every chroma sample serves four luma pixels in 4:2:0. Compute its
    # contribution once, with the original rounding, then reuse it.
    red = [(91881 * cr) >> 16 for cr in cr_plane]
    green = [(22554 * cb + 46802 * cr) >> 16 for cb, cr in zip(cb_plane, cr_plane)]
    blue = [(116130 * cb) >> 16 for cb in cb_plane]
    for y in range(HEIGHT):
        row = y * WIDTH
        chroma_row = (y // 2) * (WIDTH // 2)
        for x in range(WIDTH):
            luma = luma_plane[row + x] + 128
            chroma_index = chroma_row + x // 2
            r = luma + red[chroma_index]
            g = luma - green[chroma_index]
            b = luma + blue[chroma_index]
            offset = (row + x) * 3
            rgb[offset] = 0 if r < 0 else 255 if r > 255 else r
            rgb[offset + 1] = 0 if g < 0 else 255 if g > 255 else g
            rgb[offset + 2] = 0 if b < 0 else 255 if b > 255 else b
    return bytes(rgb)
