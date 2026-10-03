# pyplaydia

Playdia disc extraction and a Python decoder for AK8000 video frames.
The decoder reconstructs native **248×216 RGB images**, using 4×4 DCT blocks
and 4:2:0 chroma. The recovered coefficient mapping and reconstruction rules
come from [PlaydiaEmu](https://github.com/AloysHF/PlaydiaEmu); see
[third-party credits](THIRD_PARTY_NOTICES.md).

## Install

Use Python 3.10 or newer:

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
```

For an optional Cython build, install a C compiler and Python development
headers, then run:

```sh
venv/bin/python -m pip install cython setuptools
venv/bin/cythonize -i -f -X annotation_typing=False playdia_codec/*.py
venv/bin/python -m unittest discover -s tests
```

Python automatically imports the compiled extensions alongside the source;
the usual export commands still apply. Rebuild after editing the Python
files, or remove the generated `playdia_codec/*.so` files to return to pure
Python on Linux.
Disabling [annotation typing](https://cython.readthedocs.io/en/latest/src/userguide/source_files_and_compilation.html#compiler-directives)
keeps the build from enforcing Python type hints at runtime.
Cython is an optional build tool, not a requirement for running the source.

## Project layout

- `main.py`: disc extraction CLI.
- `iso9660.py`, `filestream.py`, `sector.py`: disc and filesystem handling.
- `control_dump.py`: complete raw F2 sectors and a byte CSV for inspection.
- `playdia_codec/`: working video/audio decoders and lossless AVI export.
  `adpcm.py` supplies native-rate mono/stereo PCM for both WAV and AVI.
- `tests/`: synthetic regression tests.
- `doc/`: historical research material, retained for reference.

## Export lossless video

```sh
venv/bin/python main.py -c 'input/game.cue' -v -d output
```

`-v` writes `output/video/video_000.avi`, etc., one clip per physical scene
containing video. Scenes without pictures produce no AVI file.
Video frames use **lossless PNG (MPNG)**, preserving every decoded RGB pixel.
Audio uses uncompressed 16-bit PCM at its native sample rate. Python and
Pillow write the AVI directly; no FFmpeg installation is needed.

Frame timing follows picture positions on the disc using a 75 Hz clock;
empty AVI frames hold the previous picture between updates. Audio starts at
clip time zero, with the last picture held if audio extends past the scene.
This reconstructs physical scene timing; it does not follow interactive
branches or establish exact console playback timing.

Use `-l 1` to export only the first physical scene per disc file. Silent scenes
still count toward the limit and keep their scene number. `-l 0` means no
limit; negative limits are rejected. Always supply a CUE path with `-c` and
choose an output mode: `-v`, `-f`, `-a`, or `--controls` (these can be combined). Running
without an output mode displays help.

## Export WAV audio

```sh
venv/bin/python main.py -c 'input/game.cue' -a -d output
```

`-a` writes `output/audio/audio_000.wav`, etc., with the same scene numbering
as AVI export. Both use the same 4-bit XA decoder and select the first audio
channel encountered in each scene. WAV files contain uncompressed 16-bit PCM
at the native 18,900 or 37,800 Hz rate, preserving mono/stereo; the old
44.1 kHz resampling has been removed. Silent scenes produce no WAV file.

## Export PNGs directly from a disc

```sh
venv/bin/python main.py -c 'input/game.cue' -f -d output
```

`-f` decodes each completed picture in memory and writes
`output/frames/000/frame_0000.png`, etc. Use `-l 1` to export only the first
physical scene. No intermediate BIN files are written.

## Dump F2 control records

```sh
venv/bin/python main.py -c 'input/game.cue' --controls -d output
```

This scans every loaded CUE track for Mode 2 sectors whose first payload byte
is **F2**, in physical order. It includes zero-filled prefixes, unknown byte
values, sectors without preceding F1s, and matches carrying audio, EOR or EOF
flags. It continues past EOF and does not use ISO directory or scene boundaries.
`-l` applies only to media exports; `--controls` always dumps all matches.

Each disc produces one set of files directly in `output/controls/`:

- `f2.csv`: source track name, disc/track sector positions, raw file offsets,
  raw MSF and XA subheader bytes, and a 35-byte prefix for spreadsheet viewing.
  Columns `b00`–`b22` are byte offsets from the payload start: `b00` is F2,
  followed by the next 34 bytes. `prefix_hex` contains the same bytes together.
- `f2_sectors.bin`: **complete, unchanged 2352-byte sectors**, one per CSV row.
  This preserves all payload bytes beyond the CSV preview, both XA subheaders,
  and the sector trailer. `raw_dump_offset` locates each row's sector in the BIN;
  its payload begins 24 bytes later and spans `payload_size` bytes.
- `summary.json`: total sectors scanned and F2 counts per source track.

All indexes and offsets are zero-based. `sector_lba` counts sectors across the
loaded track files in CUE order. No command, pointer, button, wait flag or record
layout is inferred. The 35-byte CSV preview does not define the record length;
the complete sector is available in the BIN. An audio-flagged marker match is
retained for inspection, without asserting that it is a control command.

Use a separate `-d` folder for each disc. For the local Dragon Ball image:

```sh
venv/bin/python main.py -c 'input/DRAGON/Dragon Ball Z - Shin Saiyajin Zetsumetsu Keikaku - Chikyuu-hen (Japan).cue' --controls -d output/DRAGON
```

Open `output/DRAGON/controls/f2.csv`. The dump no longer creates separate
`.AJS`/`.GLB` output folders; an empty `.GLB` table from an older run is not the
disc's F2 dump. Control-only extraction does not parse the ISO filesystem or
decode pictures. When combined with media exports, the raw dump finishes first.

The [F2 investigation notes](doc/f2/README.md) record observed flag patterns,
video/still relationships, candidate addresses, and open playback hypotheses.

## Python API

To inspect a complete picture packet assembled from F1/F2 sector payloads:

```python
from playdia_codec import Picture

picture = Picture.from_bytes(packet) # Complete F1/F2 sector packet in memory
picture.save("output/frame.png")
image = picture.to_image()       # Pillow RGB image, 248×216
rgb = picture.decode_rgb()       # Packed RGB888 bytes
rows = picture.video_stream.rows # 27 rows, each with 186 coefficient blocks
```

`Picture.from_bytes(data)` accepts a complete F1/F2 sector packet in memory;
`Picture.from_bytes(data, assembled=True)` accepts an assembled picture.
Invalid input raises `DecodeError` with the assembled bit position, row
number (1–27, or 0 before the first row), and zero-based block index where
applicable.
The stored streams use `bitstring.ConstBitStream`: their bits are read-only,
while `.pos` remains available for inspection and seeking.
`picture.control_stream.stream` retains all 34 bytes after the F2 marker.
`flags` and `second_byte` expose the first two bytes, while
`candidate_addresses` exposes the seven provisional four-byte groups at F2
payload offsets `0x03, 0x07, ..., 0x1B`. Their `input` properties identify the
observed selectors, in order: B, A, Right, Left, Up, Down, and no input. Each
group exposes the observed MSF-like expansion as `msf == (M, S, U * 5)`; `lba`
then subtracts the usual 150-sector lead-in. Neither property checks whether
the group is a real destination. The unresolved fourth byte and the record's
four `trailing_bytes` remain intact. The `single_picture_scene_end` and
`multiple_picture_scene_end` booleans report the observed high-bit correlations,
not established playback commands. Each row's `first_luma_dc` property exposes
its first decoded luminance DC coefficient.

Disc readers support context managers, so track files close even if an
export fails:

```python
from iso9660 import ISOImage

with ISOImage("input/game.cue") as disc:
    for record in disc.Files:
        disc.ReadVideo(record, "output/video", limit=1)
```

For interactive use without `with`, call `disc.close()` when finished.

## Codec model and validation

The decoder consumes exactly 27 rows of 31 macroblocks, with four Y blocks,
one Cb block, and one Cr block per macroblock. It uses the recovered custom
run/level VLCs, signed ten-bit escapes, implicit full-block endings,
macroblock DC prediction, separate Y/C quantizers, and a fixed-point 4×4
inverse DCT. It validates the terminator and padding without scanning ahead
past malformed coefficients.

The supported header is picture type 1, quantizer shift 0, and nonzero
factor, matching PlaydiaEmu's native decoder. Pixel reconstruction follows
PlaydiaEmu's integer arithmetic, including color conversion and rounding.
Exact equivalence to the original console's pixels remains unverified.

Run the synthetic regression tests (no disc image or Rust required):

```sh
venv/bin/python -m unittest discover -s tests
```

The [research archive](doc/README.md) retains the original analysis
spreadsheets and patent reference. This README describes the implemented
decoder.
