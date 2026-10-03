# F2 control investigation

Working notes from 2026-10-03, based on the local Dragon Ball Z: Chikyuu-hen
and Sailor Moon S discs. These are observations and hypotheses, not a control
format specification. Counts describe physical disc order, not reconstructed
gameplay. The raw dumper does not apply any of these interpretations.

The working model is **video -> persistent still screen -> conditional next
scene**, with possible branching while the video is still playing.

## Evidence and conventions

- Dragon Ball: **31,774 F2 records** in `output/DRAGON/controls/f2.csv`.
- Sailor Moon: **23,501 F2 records** in `output/MOON/controls/f2.csv`.
- Each CSV has a neighboring `f2_sectors.bin` containing complete, unchanged
  2352-byte sectors. Every exported sector was checked against its source.
- CSV `b00` is the **F2 marker**; **`b01` is the first byte after F2**, the
  suspected flags byte. Column suffixes are hexadecimal payload offsets.
- `raw_dump_offset` locates the sector in the BIN; payload starts 24 bytes later.
  The 35-byte CSV prefix is a convenient view, not an assertion of record length.
- For the observations below, physical scenes are delimited by **non-audio XA
  EOR**. Pictures are counted from F1-to-F2 packets. Audio EOR does not end a
  scene, and trailing scenes without pictures are excluded from picture counts.

## First-byte flags

| Bit in `b01` | Observed association | Dragon Ball | Sailor Moon |
|---|---|---:|---:|
| 7 (`0x80`) | End of a single-picture scene | 179 scenes | 1,086 scenes |
| 6 (`0x40`) | End of a multiple-picture scene | 370 scenes | 625 scenes |

There were no exceptions in these two discs. These bits appeared only on the
scene's final F2, alongside XA EOR; neither disc set both together. This is a
correlation with scene type, not yet proof of a particular playback instruction.

The combinations suggest independent modifiers: `0x60 = 0x40 | 0x20` and
`0xA0 = 0x80 | 0x20`, so bit 5 occurs with both scene types. Other observed
combinations include `0x44` and `0x50`. Meanings of the lower bits, the following
byte (`b02`), and the remaining bytes are unresolved.

## Video followed by its final picture

In Dragon Ball, **132 of the 179** single-picture scenes immediately follow
videos. Comparing the exported PNG pixels, **121 of those 132** exactly match
the preceding video's final frame. Pixel equality was checked for Dragon Ball;
the corresponding Sailor Moon images were not compared.

Dragon Ball's still scenes occupy only **8-16 sectors**, about **0.11-0.21
seconds** in a linear 75-sector/s readout. This is not a measurement of their
intended display duration on the console.

**Hypothesis:** these records establish a persistent resting screen, through
holding the picture or looping. Keep "hold this picture" separate from "wait
for a button": the condition for leaving the screen could be input, a timer,
or another condition. Bit 7 might select the still-screen mode while another
field controls progression.

## Candidate address layout

The address arithmetic initially came from
[PlaydiaEmu's player, revision 6e75840](https://github.com/AloysHF/PlaydiaEmu/blob/6e75840/crates/playdiaemu-core/src/player.rs)
and was tested against positions on these discs. Its command and button
interpretations are not assumed here.

- Seven candidate four-byte groups begin at payload offsets
  `0x03, 0x07, 0x0B, 0x0F, 0x13, 0x17, 0x1B`, counting F2 as offset zero.
- The first three bytes are provisionally binary `M, S, U`, with:
  **`LBA = M * 4500 + S * 75 + U * 5 - 150`**.
- These are not BCD values or ordinary CD MSF fields. The fourth byte is unknown.
- Not every group is necessarily an address. For example, recurring
  `00 03 00` values yield LBA 75, outside the game stream; zero groups and other
  apparent parameters must remain uninterpreted.

This is a research aid, not a validated schema for every F2 record. The full
sector and raw byte positions remain the source of truth.

## Video-to-still pointers and onward navigation

Using the candidate encoding, the video's final F2 contains a destination in
the following still for **all 132 Dragon Ball and 338 Sailor Moon video-to-still
pairs**. All Dragon Ball matches land at the still's physical start. In Sailor
Moon, 335 land at the physical start; three skip a leading sector and land on
the still's first F1.

A clear Dragon Ball example:

| F2 record | Candidate destinations |
|---|---|
| Video ends at LBA **14139**, `b01=0x40` | **14140** in all seven positions: the still's first F1 |
| Still ends at LBA **14148**, `b01=0x80` | **14150** in six positions: the next scene's first F1; **14140** in the last position: itself |

The relevant three-byte values are `03 0A 08` for 14140 and `03 0A 0A` for
14150. The still repeats the video's final picture.

**Hypothesis:** the video directs playback to the still, and the still supplies
onward destinations or a self-reference that preserves its display. Which
entry corresponds to no input, a button, or another condition is unknown.

## Input during video and timed events

Some video-ending F2s already contain several onward destinations that the
following still preserves. This could keep the same navigation choices active
during an animation and on its resting screen.

**Hypothesis:** a button press during video selects an outcome; reaching EOR
without input takes a default destination. That destination could be a waiting
screen, another animation, or a failure outcome. This could support quick-time
events, timed choices, or animated menus. Timeout behavior has not been proven.

The lower bits might distinguish input acceptance during playback, waiting
afterward, or timeout/default handling. These are possibilities to investigate,
not decoded meanings.

## Next comparisons

1. Compare the full F2 bytes in **identical-picture video/still pairs**. The image
   stays constant while the control data changes.
2. Compare pairs whose candidate destinations stay the same but flags or other
   bytes differ, to separate display mode from progression conditions.
3. Investigate bit 5 across `0x60` and `0xA0`, and other lower-bit combinations,
   without assigning button or timeout meanings in advance.
4. Check candidate destinations against actual F1 starts, including leading
   sectors, self-references, backward links, and values outside the stream.
5. Keep **display mode**, **accepted input**, and **condition for advancing** as
   separate questions. Establish default/no-input behavior before assigning
   controller buttons to entries.

## Regenerate the evidence

From the repository root:

```sh
venv/bin/python main.py -c 'input/DRAGON/Dragon Ball Z - Shin Saiyajin Zetsumetsu Keikaku - Chikyuu-hen (Japan).cue' --controls -d output/DRAGON
venv/bin/python main.py -c 'input/MOON/Bishoujo Senshi Sailor Moon S - Quiz Taiketsu! Sailor Power Shuketsu!! (Japan).cue' --controls -d output/MOON
```

`--controls` scans every loaded track for F2-marked Mode 2 sectors, including
matches with audio flags and matches after EOF. It does not follow pointers,
filter commands, or impose scene boundaries. `-l` limits only media exports.
Disc images and generated dumps stay in the ignored `input/` and `output/`
directories. See the [project README](../../README.md#dump-f2-control-records)
for CSV and BIN details.
