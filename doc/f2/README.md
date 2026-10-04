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
  control/mode byte investigated below. Column suffixes are hexadecimal payload
  offsets.
- `raw_dump_offset` locates the sector in the BIN; payload starts 24 bytes later.
  The 35-byte CSV prefix is a convenient view, not an assertion of record length.
- For the observations below, physical scenes are delimited by **non-audio XA
  EOR**. Pictures are counted from F1-to-F2 packets. Audio EOR does not end a
  scene, and trailing scenes without pictures are excluded from picture counts.

## First byte (`b01`)

| Bit in `b01` | Observed association | Dragon Ball | Sailor Moon |
|---|---|---:|---:|
| 7 (`0x80`) | End of a single-picture scene | 179 scenes | 1,086 scenes |
| 6 (`0x40`) | End of a multiple-picture scene | 370 scenes | 625 scenes |

There were no exceptions in these two discs. These bits appeared only on the
scene's final F2, alongside XA EOR; neither disc set both together. This is a
correlation with scene type, not yet proof of a particular playback instruction.

The six values seen when considering only scene-final records are therefore
combinations of an ending bit and a lower-bit mode. The complete set across all
picture records contains five additional, non-ending forms:

| `b01` | Lower mode | Dragon Ball | Sailor Moon | Observed position |
|---:|---:|---:|---:|---|
| `00` | `00` | 29,182 | 18,592 | Non-final picture |
| `04` | `04` | 2,020 | 1,823 | Non-final picture |
| `10` | `10` | 16 | 12 | Non-final picture |
| `20` | `20` | 7 | 0 | Non-final picture |
| `24` | `24` | 0 | 1,363 | Non-final picture |
| `40` | `00` | 158 | 380 | Final, multiple pictures |
| `44` | `04` | 140 | 11 | Final, multiple pictures |
| `50` | `10` | 13 | 228 | Final, multiple pictures |
| `60` | `20` | 59 | 6 | Final, multiple pictures |
| `80` | `00` | 158 | 1,086 | Final, single picture |
| `A0` | `20` | 21 | 0 | Final, single picture |

The values have a clear bitwise structure: `0x44 = 0x40 | 0x04`,
`0x50 = 0x40 | 0x10`, `0x60 = 0x40 | 0x20`, `0xA0 = 0x80 | 0x20`, and
`0x24 = 0x20 | 0x04`. Bits 0, 1 and 3 were never set in either disc. This does
not yet establish that bits 2, 4 and 5 are independently interpreted flags;
`b01` might instead select related command modes whose values were designed to
compose this way.

The scene-ending forms have distinct route-table shapes. The descriptions here
refer only to that shape; words such as "transition" and "outcome" do not imply
that the console operation itself has been decoded.

- **`0x40`: one destination repeated seven times.** Every `0x40` record stores
  the same address triple for B, A, Right, Left, Up, Down and no input. For
  example, the Dragon Ball video ending at LBA 14139 puts LBA 14140 in all seven
  slots. By "automatic handoff" this document means only that the table offers
  no button-dependent alternative: all selectors lead to the following still.
- **`0x44`: different buttons can select different destinations.** At Dragon
  Ball LBA 45524, B, Right, Left and no input lead to 45525; A leads to 62790;
  Up leads to 45630; and Down leads to 45540. The corresponding pictures are
  menu-highlight states, so "button-specific navigation" means that the slot
  order explains the observed confirm and highlight movement.
- **`0x50`: several buttons deliberately share an outcome.** At the end of
  Sailor Moon scene 28, B and A both contain 18690, Right and Left both contain
  19890, and Up and Down both contain 21090. "Grouped" means that separate
  button slots store the same destination; it does not mean that the buttons
  must be pressed together. Other Sailor Moon `0x50` records divide the six
  slots into two groups of three, and Dragon Ball has several other partitions.
- **`0x60` and `0xA0`: routes also carry nonzero fourth bytes.** At Dragon Ball
  LBA 45449, five physical-button slots contain destination 44810 plus fourth
  byte `1E`, Down contains 44580 plus `14`, and no input contains 41940 plus
  `00`. "Parameterized" means only that choosing a slot apparently supplies
  both an address triple and an additional byte. Whether that byte is a timer,
  score, state value, or something else is unknown.
- **`0x80`: the ending record of a one-picture scene.** Unlike `0x40`, its route
  population is not fixed. Some button slots can be zero, some can point onward,
  and the no-input slot can point back to the same still. Calling these
  persistent still/control screens is a playback hypothesis supported by their
  self-references and very short physical extent, not a decoded `0x80` command.

The five non-ending forms are less settled:

- **`0x00`** is the overwhelmingly common base form inside ordinary videos.
  Its candidate slots vary, so "base" does not mean that it contains no control
  data.
- **`0x04`** occurs repeatedly inside interactive animations. In the Dragon
  Ball highlighted-menu sequences it already carries the A, Up and Down routes
  before the final `0x44`. In Sailor Moon scene 28, its Right and Left targets
  move forward and backward within the current animation. This supports an
  in-progress navigation role, but is not enough to name the operation.
- **`0x10`** is rare and looks more like setup data than a normal address table.
  A recurring form has invalid address-like triples followed by fourth bytes
  `01,01,02,02,03,03` for the six physical buttons; another uses
  `0A,0A,14,14,1E,1E`. These pairings resemble button-to-group or
  button-to-value assignments, but their use is unknown.
- **`0x20`** occurs only seven times in Dragon Ball, shortly before `0x60`
  endings, with route-specific fourth bytes. **`0x24`** occurs only in Sailor
  Moon interactive animations; it populates the Up, Down and no-input slots and
  alternates with `0x04` records that populate earlier button slots. Both forms
  appear to participate in the parameterized sequences, but neither has a safe
  operation name yet.

The lower six bits are not a literal six-button availability mask. Two Sailor
Moon static tutorial screens both use `b01=0x80`, `b02=0x02`, zero fourth bytes
and a zero trailer, but populate different physical-button route slots.
More generally, one `b01` value can accompany many different patterns of
populated slots. The strongest working model is therefore that availability is
implicit in the seven route groups: a zero address triple supplies no candidate
route, while a nonzero triple supplies button-specific data. Some nonzero
triples do not resolve to valid stream addresses, and a valid route may still
lead to the same destination as the default route, so this does not by itself
prove whether the console ignores or accepts a behaviorally inert button press.

## Second byte (`b02`)

`b02` correlates strongly with particular record modes, but is not exclusive to
still pictures and is not yet named:

- In Sailor Moon, all 1,086 bit-7 single-picture scenes have a nonzero `b02`:
  1,080 use `0x02`, five use `0x04`, and one uses `0x03`.
- Sailor Moon also has 958 `b01=0x24, b02=0x03` records spread across twelve
  multi-picture animations. Their decoded picture data changes. In scene 28,
  these alternate with `b01=0x04, b02=0x00` records at the same ten-sector
  picture cadence. Six animation records use `b01=0x10, b02=0x10`.
- Dragon Ball has 196 nonzero `b02` records. Only 132 are bit-7 scene endings;
  the others occur in multi-picture scenes. Observed values are `0x01`, `0x02`,
  `0x03`, `0x30`, `0x42`, `0xB0`, and `0xF0`.

The equal on-disc picture cadence rules out interpreting `b02` directly as the
number of sectors until the next picture. It could still be a logical display
hold, timer, mode argument, or another parameter used together with `b01`.
Those possibilities require playback evidence; the API therefore retains it
as the raw `second_byte`.

### Sailor Moon quiz timeout warning

The quiz screens provide direct evidence for a logical no-input timer even
though they do not reveal its duration:

- 1,047 one-picture answer screens form 349 sets of three highlighted answers.
- All 1,047 use `b01=0x80, b02=0x02`.
- Their no-input slots all point to LBA 149320, the start of scene 840. No other
  Sailor Moon selector or record form points there.

For the first question, pressing A on the correct highlighted answer routes to
the circle/result scene with fourth byte `01`; pressing A on either wrong answer
routes to the cross/result scene with fourth byte `00`. This is further evidence
that the fourth byte carries a result or state value rather than elapsed time.

During playback, scene 840's spoken prompt was identified as *hayaku* ("hurry
up"), so this is a timeout warning rather than the wrong-answer result. Its
ending `b01=0x40` record repeats `00 02 00` in all seven address positions. That
triple expands to LBA 0, not an ordinary scene target, and is a candidate special
return/resume value. A plausible flow is therefore answer screen -> no input ->
shared "hurry up" scene -> return to the interrupted answer screen. The exact
meaning of the zero target and behavior after repeated warnings still require
playback confirmation.

The wait cannot be the short physical extent of the answer still, so it must be
logical player behavior. `b02=0x02` is a plausible timed-wait mode or parameter
because it is invariant across all of these answer screens, but the data does
not show whether `02` specifies a duration, selects a preset, or merely
identifies the screen mode.

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

The disc data supports an MSF-like address with a five-sector final unit. At
Dragon Ball LBA 14139, for example, the physical sector header is `03:10:39`.
The F2 group `03 0A 08` expands to `03:10:40` because `0x0A` is binary 10 and
`8 * 5 = 40`; that is exactly the next F1 sector at LBA 14140. Subtracting the
standard 150-sector lead-in converts the expanded address to a zero-based LBA.

[PlaydiaEmu's player, revision 6e75840](https://github.com/AloysHF/PlaydiaEmu/blob/6e75840/crates/playdiaemu-core/src/player.rs)
was the initial lead for this arithmetic. It is used here because the sector
comparisons support it; PlaydiaEmu's command and button interpretations are not
assumed.

- Seven candidate four-byte groups begin at payload offsets
  `0x03, 0x07, 0x0B, 0x0F, 0x13, 0x17, 0x1B`, counting F2 as offset zero.
- The first three bytes are binary `M, S, U`, with:
  **`LBA = M * 4500 + S * 75 + U * 5 - 150`**.
- These are not BCD values. They differ from ordinary CD MSF because `U` counts
  five-sector units, and observed `S` values are not constrained below 60. The
  fourth byte is unknown.
- Not every group is necessarily an address. For example, recurring
  `00 03 00` values yield LBA 75, outside the game stream; zero groups and other
  apparent parameters must remain uninterpreted.

This is a research aid, not a validated schema for every F2 record. The full
sector and raw byte positions remain the source of truth.

### Fourth byte: per-route value

The fourth byte is not required to identify or enable a button: the route's
slot already identifies the selector, and confirmed working menu routes often
use `00`. It is also not an intrinsic property of the destination. Dragon Ball
contains many cases where the same button and destination occur with different
fourth bytes, and cases where several buttons share one destination but carry
different fourth bytes.

Two `b01=0x50` records at LBAs 158314 and 158654 are especially direct. All six
physical-button slots contain the same destination triple, `23 11 46`, while
their fourth bytes distinguish the selectors:

| Selector | B | A | Right | Left | Up | Down | No input |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fourth byte | `01` | `02` | `03` | `04` | `05` | `06` | `00` |

The common address lands inside the same following animation, so the fourth
byte is the only part of those six entries that preserves which button was
used.

Three Dragon Ball world-map records provide a second, stranger button-code
pattern that is stable across all three:

| Selector | B | A | Right | Left | Up | Down | No input |
|---|---:|---:|---:|---:|---:|---:|---:|
| Raw fourth byte | `6E` | `65` | `64` | `0B` | `0A` | `01` | `00` |
| Value in decimal | 110 | 101 | 100 | 11 | 10 | 1 | 0 |

Read as decimal numerals, those values spell the binary selector codes `110`,
`101`, `100`, `011`, `010`, `001`, and `000`. This is observationally an exact
mapping, however odd the representation; the reason for that representation is
unknown.

Other records use values such as `0A`, `14`, `1E` or route-dependent values
that are not fixed to one button. The safest current model is therefore a
**per-route value or argument**. It can preserve a button/result code when
several selectors share a destination, but it is not a universal button ID or
a simple availability bitmask. Its interpretation may depend on `b01` and
`b02`.

#### No growing fourth-byte timer observed

The non-EOR records were checked in physical picture order for a fourth byte
that grows as a video plays. Even after consecutive duplicates are collapsed,
neither disc contains an increasing run of three distinct fourth-byte values in
any route slot.

Dragon Ball's changes are isolated setup-like records, commonly
`01/02/03` followed by `0A/14/1E`, a long body of zeroes, and sometimes one
parameterized record near the end. Sailor Moon alternates fixed values such as
`9C/9F/9E` or `9C/AC/A7` with zero according to the `0x04`/`0x24` record type;
the nonzero values do not increase with elapsed pictures.

The only apparent three-step decreases occur in the opening six-picture setup
blocks of Dragon Ball scenes 429 and 548. Those blocks alternate `b01=0x10`
tables containing `0A/14/1E` and `01/02/03`, then switch to ordinary zero-valued
records for the rest of the scene. They are repeated configuration patterns,
not values that track the duration of those videos.

This rules out a simple fourth-byte elapsed-frame counter in these two discs.
It does not rule out time-sensitive choices. Because every picture has its own
F2 table, the currently active record already identifies the time window, and
its destination triples can change as playback advances. A button pressed later
can therefore take a different route without any counter being accumulated in
the fourth byte.

### Five-sector alignment

The five-sector unit is also visible in Dragon Ball's 179 bit-7 single-picture
scenes. Every picture begins at an LBA divisible by five. Its F1 sectors are
contiguous through the ending F2, with no intervening audio or F3 sectors.
After that EOR-bearing F2, zero-filled Form-2/RTS sectors align the next F1:

- 171 endings have one zero sector;
- 3 endings have two zero sectors;
- 5 endings already end on the boundary and need none.

In all 179 cases, the next nonzero sector is F1 at an LBA divisible by five.
This supports a five-sector scheduling or interleave unit. Accommodating the
normal audio/video layout is a plausible reason for it, but the padding alone
does not establish that each empty sector is specifically an audio slot.

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

The paired records support the video directing playback to the still, with the
still retaining onward button routes and a no-input self-reference. The route
order is established below; the exact command and timing behavior remains open.

## Input during video and timed events

### Observed controller route order

The seven groups correspond to the controller's six buttons followed by a
no-input route:

| Slot | Payload offset | Observed selector |
|---:|---:|---|
| 0 | `0x03` | B / cancel |
| 1 | `0x07` | A / confirm |
| 2 | `0x0B` | Right |
| 3 | `0x0F` | Left |
| 4 | `0x13` | Up |
| 5 | `0x17` | Down |
| 6 | `0x1B` | No input / default progression |

This order is supported independently by both discs. In Dragon Ball scenes
52–65, slots 4 and 5 move the highlight up and down through three choices,
while slot 1 activates the highlighted destination. Scenes 171, 173 and 175
add left/right movement. Scenes 544–547 provide a particularly direct check:
the purple, green, red and blue controller-button screens advance only through
slots 4, 2, 5 and 3 respectively, matching Up, Right, Down and Left.

Sailor Moon scenes 4–14 show the blue and green directional controls on screen;
their F2 records use slots 3 and 2 for left and right, and slot 1 confirms the
selection. Scene 16 separates buttons from default behavior: all six slots
0–5 route to the same destination while slot 6 is empty during playback. This
is direct evidence that slot 6 is not a seventh physical button. The B and A
labels for slots 0 and 1 follow from the remaining two controller buttons plus
their observed cancel/confirm behavior.

`NO_INPUT` describes the observed selector only. Depending on the record it
can continue playback, enter the following still, or self-reference that still;
it does not by itself establish a timer or timeout command.

### Pre-rendered Dragon Ball menu states

Dragon Ball scenes 52–65 show that the fourth route byte is not responsible
for darkening previously visited or unavailable choices in that menu. Every
fourth byte in every F2 record across those fourteen exported scenes is `00`.
The visual states are separate decoded pictures and separate route nodes:

- scenes 52–57 contain the normal three-choice menu with the top, middle and
  bottom choices selected in turn;
- scenes 58–61 contain the two remaining selections with the bottom choice
  darkened;
- scenes 62–65 contain the two remaining selections with the top choice
  darkened.

The address triples link the three normal states in a cycle. In each darkened
variant, Up and Down both move between only the two non-darkened states. Thus
the route graph itself carries this particular visited/disabled state by
selecting a different pre-rendered menu, without any changing fourth-byte
value. Whether the choice is specifically "visited" rather than unavailable
for another gameplay reason still requires gameplay context.

### Playback hypotheses

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
.venv/bin/python main.py -c 'input/DRAGON/Dragon Ball Z - Shin Saiyajin Zetsumetsu Keikaku - Chikyuu-hen (Japan).cue' --controls -d output/DRAGON
.venv/bin/python main.py -c 'input/MOON/Bishoujo Senshi Sailor Moon S - Quiz Taiketsu! Sailor Power Shuketsu!! (Japan).cue' --controls -d output/MOON
```

`--controls` scans every loaded track for F2-marked Mode 2 sectors, including
matches with audio flags and matches after EOF. It does not follow pointers,
filter commands, or impose scene boundaries. `-l` limits only media exports.
Disc images and generated dumps stay in the ignored `input/` and `output/`
directories. See the [project README](../../README.md#dump-f2-control-records)
for CSV and BIN details.
