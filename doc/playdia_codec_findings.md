# Playdia Codec Findings

This is the reduced working set: things that are either directly observed or useful enough to keep as labeled hypotheses.

## Solid Observations

### Packet Layout

Packets are made of `0x800`-byte sectors:

```text
F1 ... F1 F2
```

The first sector starts:

```text
0x00: F1
0x01: 00
0x02: 80
0x03: 04
0x04: frame/control value
0x05..0x14: 16-byte table/control sequence
0x15..0x24: second 16-byte table/control sequence
0x25: 00
0x26: 80
0x27: 24
0x28: h28
0x29: h29
0x2A: first likely entropy byte
```

The default payload start should be `0x2A`.

Evidence:

- Hardware patching `0x28` visibly corrupts the QIS logo.
- Hardware patching `0x29` had no obvious visible effect in the captured QIS tests.
- Hardware patching from `0x2A` onward usually corrupts visible picture data.

### Header Tables

The two 16-byte sequences at `0x05..0x14` and `0x15..0x24` are not just duplicated padding.

Hardware patch tests showed:

```text
0x05 0A -> 14: luma got brighter
0x05 0A -> 05: luma got darker
0x15 0A -> 14: chroma got stronger
0x15 0A -> 05: chroma got weaker
```

So the best current interpretation is:

```text
0x05..0x14: luma table/control values
0x15..0x24: chroma table/control values
```

### Embedded Section Headers

Some picture payloads contain byte-aligned embedded headers:

```text
00 80 <marker> <h28> <h29>
```

where `<h28>` and `<h29>` match the first-sector bytes at `0x28..0x29`.

Observed marker sequence:

```text
24 [44] [64] [84] [A4] [C4] [E4]
```

Examples:

```text
001/frame_0023.bin:
  00 80 24 07 0C at raw 0x0025
  00 80 64 07 0C at raw 0x00A6
  00 80 A4 07 0C at raw 0x0123

001/frame_0180.bin:
  00 80 24 07 56 at raw 0x0025
  00 80 84 07 56 at raw 0x00C8
  00 80 C4 07 56 at raw 0x013D
```

Current audit:

```text
output/frames/000: 100 packets, no embedded section headers
output/frames/001: 77 / 198 packets have embedded section headers
output/frames/002: 9 / 706 packets have embedded section headers
```

Decoder experiments should skip these embedded five-byte headers and probably reset some local state at them. Their exact semantic meaning is not known yet.

### Timing

F2 sectors contain binary MSF-looking absolute targets. With AJS start LBA `01:00:00`, the observed end markers line up with extracted audio:

```text
000/frame_0099: 01:10:00 -> 10.000s relative
001/frame_0197: 01:36:06 -> 36.080s relative
002/frame_0705: 03:10:08 -> 130.107s relative
```

Audio/frame checks:

```text
audio_000.wav: ~10.014s, 100 frames -> ~10 fps
audio_001.wav: ~26.420s, 198 frames -> ~7.5 fps for that segment
audio_002.wav: ~93.960s, 706 frames -> ~7.5 fps for that segment
```

So packet cadence is segment-dependent, not one global video FPS.

### Repeated Frames

The QIS/logo sequence stores repeated visible frames as repeated identical packet binaries. That argues against normal inter-frame video compression for these frames.

### AK8851 Datasheet

`doc/AK8851.PDF` was reviewed. It is an AKM `NTSC/PAL/SECAM Digital Video Decoder` datasheet dated `2005/07`.

This is probably not documentation for the Playdia disc video codec:

- It decodes analog composite/S-video input into digital Y/Cb/Cr.
- It outputs ITU-R BT.601 / BT.656 style video, not compressed picture packets.
- It has no DCT, Huffman, JPEG, MPEG, VLC, entropy, macroblock, or decompression engine.
- Its main control surface is I2C registers for analog input selection, AGC/ACC, Y/C separation, output timing, VBI slicing, and image adjustments.

The useful takeaway is only that nearby AKM video parts used conventional digital video output:

```text
8-bit BT.656-style output: Cb0 Y0 Cr0 Y1 ...
16-bit output: Y on D[7:0], Cb/Cr on EXTDAT[7:0]
Y/Cb/Cr output format: 4:2:2
black level: Y=16, Cb/Cr=128
active line example: 720 pixels
```

That may help if comparing final display/output paths, but it does not explain the compressed bytes on disc.

## Useful Hypotheses

### Image Grid

The best working image geometry is:

```text
active coded image: 256x192
visible macroblock grid: 32x24
macroblock size: 8x8 pixels
```

Reason: the hardware checkerboard corruption appears to fit a 32x24 visible grid when viewed against a 640x480 capture.

### Transform / Chroma

The current best compression model is still:

```text
4x4 transform blocks
4:2:0 chroma
```

For `256x192`, that gives:

```text
Y:  64x48 = 3072 blocks
Cb: 32x24 = 768 blocks
Cr: 32x24 = 768 blocks
total: 4608 4x4 blocks
```

This fits the 16-byte table size and the luma/chroma behavior, but it is not proven.

### Bit Budget Sanity Check

If `001/frame_0023.bin` is interpreted as `256x192`, `4x4`, `4:2:0`, then:

```text
payload from 0x2A: 4404 bytes = 35232 bits
4608 blocks -> ~7.65 bits/block
768 8x8 macroblocks -> ~45.9 bits/macroblock
```

That is plausible for a mostly black title card with text and many empty blocks.

## Things Not To Treat As Facts

- It is not proven JPEG-adjacent.
- `01` / `10` as an EOB or empty-block VLC is plausible but unproven.
- F2 is not currently evidence for video commands; it looks more like timing/end metadata.
- `h28:h29` are copied into section headers, but their meaning is not known.
- The embedded section markers are structural, but they are not proven to mean rows, components, or coefficient passes.

## Dead Ends To Avoid Repeating

- Naively mapping raw bits to black/white does not decode the image.
- Equal-slicing the payload into a `32x24` occupancy grid does not recover title-card text.
- Treating the whole payload as one continuous VLC stream ignores embedded section headers.
- The cloned Playdia emulator did not demonstrate a working video decoder; it produced block/color noise in local tests.

## Current Minimal Tooling

- `playdia_codec/packet.py`: packet parser, F2 timing helpers, payload extraction, embedded section-header detection.
- `scripts/audit_packets.py`: emits CSV audits for packet layout, timing fields, payload metrics, and section headers.
- `tests/test_playdia_packet.py`: regression tests for the facts above.

Example:

```bash
python3 scripts/audit_packets.py output/frames/000 output/frames/001 output/frames/002 --csv-dir output/packet_audit
python3 -m unittest tests/test_playdia_packet.py
```
