# Playdia AK8000 — Comprehensive Analysis (State of Knowledge)

* **Date:** 2026-08-13
* **Analyst:** Claude Fable 5 (session 18)
* **Scope:** Everything known about the Bandai Playdia AK8000 video codec after 18
  sessions of software analysis + hardware test discs 7–24. This document
  supersedes the pre-session-18 understanding, most of which was invalidated.
* **Confidence key:** **[HW]** verified on real console output · **[DATA]**
  proven from disc bytes / recordings · **[FIT]** fit to ground-truth, not yet
  hardware-confirmed · **[HYP]** hypothesis · **[DEAD]** ruled out.

---

## 0. Executive summary

The AK8000 is a proprietary, undocumented video decoder in the Bandai Playdia
(1994). No prior decoder existed. As of this session:

* The **physical disc layout, frame container, and entropy-stream grammar are
  solved and verified** across two full commercial discs (Sample Soft, Sailor
  Moon Quiz) and both disc lineages.
* A working **intra decoder (v3) exact-parses 99.3% of all frame rows** and
  reconstructs correct backgrounds, luma DC levels, and content geometry
  (SSIM up to 0.88 vs the real console on text screens).
* **Two mechanisms remain open:** (1) the *value layer* — the per-block codes
  that carry glyph/texture detail encode near-subcarrier information the
  standard capture chain filters out; (2) **inter-frame prediction** (P-frames),
  which cover ~half of all frames and the intra decoder cannot reconstruct.
* Ground truth now comes from **audio-aligned gameplay recordings** (the disc's
  XA audio, untouched by patching, pins each video frame to a disc sector), plus
  a series of **crafted hardware test discs** (20–24).

The single most important correction this session: **the pre-session-18 model
(8×8 blocks, 3 sub-frames, MPEG-1 DC-VLC, "SF01" metric) was wrong**, because
every prior parse ran on a mis-assembled bitstream (per-sector marker bytes were
never stripped) and was scored by a degenerate metric that rewarded noise.

---

## 1. Physical disc layout **[HW/DATA]**

Raw **MODE2/2352** CD tracks. Track 1 is a bare ISO9660/CD-XA shell (PVD + path
tables + root dir, then zero-fill) — **there is no executable code on the disc**;
all decode logic lives in the console's uPD78214 mask ROM (undumped) and the
AK8000 silicon. Track 2 holds one giant A/V stream file.

Sector taxonomy (subheader at raw offset 16–20; user data at raw+24):

| Kind | Subheader (file,ch,submode,coding) | Form | First user byte | Role |
|---|---|---|---|---|
| Video | `01 00 08 00` | 1 (2048 B) | `0xF1` | frame data; frame-start sectors also carry `00 80 04` at user bytes 1–3 |
| Frame-end | `01 00 08 00` | 1 | `0xF2` | ends a frame: 0x23-byte control header + overflow payload |
| Filler | `01 00 08 00` | 1 | `0xF3` | encoder-underrun padding (`F3 37 F9` + `0xFF`) |
| Audio | `01 01 64 04` | 2 (2324 B) | ADPCM | XA-ADPCM, channel 1 |

* **Audio** is XA-ADPCM, **mono 18.9 kHz, 4-bit**, placed at a rigid cadence of
  **one sector every 16** (LBA ≡ 13 mod 16 on the observed ROM). One audio
  sector = 4032 samples = 213.3 ms; consumed at exactly 75/16 sectors/s, so the
  interleave has zero slack and the **video** side absorbs timing via `F3`
  fillers. Effective video rate ≈ **10 fps** (this corrects the old "75/7 ≈
  10.71 fps"). Sample Soft has a second audio channel used for an interactive
  dual track (not stereo). Extractor: `research/adhoc/xa_audio_extract.py`.
* Audio is **untouched by video patching**, which is what makes audio-based
  recording→LBA alignment possible.

---

## 2. Frame container **[DATA]**

A frame = a run of `0xF1` video sectors terminated by one `0xF2` sector, split
around any interleaved audio/`F3` sectors. **Frame size classes** (Sample Soft):
7, 8, 9, 13, 14, 15 sectors (14336 / 16384 / 18432 / … bytes). Sailor Moon:
7/9/14/15. Roughly half of the Sample Soft frames are 7-sector.

### 2.1 The crucial fix — per-sector `0xF1` markers

**Every 2048-byte sector begins with its own marker byte.** Sessions 1–17
concatenated raw sector data and thus injected five `0xF1` bytes into the middle
of every bitstream, desyncing all parsing. Correct assembly:

```
sector 0 (F1):     payload = user_bytes[0x28 : 0x800]   (after the frame header)
sectors 1..k (F1): payload = user_bytes[0x01 : 0x800]   (skip the F1 marker)
last sector  (F2): payload = user_bytes[0x23 : 0x800]   (after a 0x23-byte header)
```
Concatenate, then strip trailing `0xFF` padding. The F2 payload is the
**overflow tail** of the entropy stream, used only when the F1 payload is full.
Implemented in `tmp/claude/session18/framework18.py :: frame_scan_bits`.

### 2.2 Frame header (first-sector user bytes 0x00–0x27)

| Offset | Bytes | Meaning | Confidence |
|---|---|---|---|
| 0x00 | 1 | `0xF1` sector marker | [DATA] |
| 0x01–0x03 | 3 | `00 80 04` constant | [DATA] |
| **0x04** | 1 | **`fp` — quantizer / dequant scale** | [HW] |
| 0x05–0x14 | 16 | **Quantizer table (QT)** — 16 entries | [HW] |
| 0x15–0x24 | 16 | **exact copy of the QT** | [DATA] |
| 0x25–0x26 | 2 | `00 80` constant | [DATA] |
| **0x27** | 1 | **color-path parameter** (usually `0x24`=36) | [HW] |
| **0x28…** | — | **entropy stream begins here** (byte 0x28 is its first byte) | [DATA] |

Across 23k+ Sailor Moon frames, **only bytes 0x04 (fp) and 0x27 vary**; the QT
is identical on every frame of both games (a fixed encoder table, not per-frame
adaptive). Native QT (luma) = `0A 14 0E 0D 12 25 16 1C 0F 18 0F 12 12 1F 11 14`.

### 2.3 Frame type — byte 0x28 (= first entropy byte) **[DATA/HW]**

The opening byte of the entropy stream behaves as a **frame type**: `0x00` =
**I-frame** (intra, self-contained), `0x07` = **P-frame** (inter-predicted from
the previously displayed frame). Sample Soft splits ~50/50 (7345 type-0 / 7278
type-7); the remaining ~47% of frames carry other opening bytes (`0x01`, `0x06`,
`0x1d–1f`, `0x38–3f`, `0x60–7f`, …) that are *not* a simple I/P flag. GOP shape:
1751 records are pure-I (static holds/menus), 81 are pure-P (video, no I-frame at
all — they inherit a reference across the record boundary), the rest mixed; I-runs
median 1, P-runs median 4 (max 204).

### 2.4 End-of-frame terminator **[DATA]**

Every frame's entropy stream ends with the 14-bit string `00000000100001`
(commonly read as the 16-bit `01 00000000100001` = `0x4021`; frame 45 of the old
corpus literally ends bytes `40 21 00`), then zero-padding to a byte boundary,
then `0xFF` fill. This is the same "8 zeros + 1 + short field" family as the row
headers (§3) — i.e. the end-of-frame is itself a row-sync marker.

---

## 3. Entropy stream — the row grammar **[DATA/FIT]**

Decoder: `crack3/decoder_v3.py`. Validated on **99.3% of 1,794 test rows** across
both discs and lineages (exact parse to the terminator).

### 3.1 Row structure

The stream is **row-addressed**, not a fixed-width raster:

```
row unit = 00000000 1 CCCCCCCCCC 001 [186 blocks]
             sync    10-bit row#   row-DC field
```

* A 7/9-sector **S-class** frame has a **preamble unit** + row counters **2..27**
  (26 rows), i.e. rows are ~8 display lines tall (26×8 ≈ 208 of ~240 lines,
  centered). Row width = **186 two-bit block slots**.
* An **absolute-DC token** `0010000000` + `v10` (20 bits total, `v10` = 10-bit
  two's-complement) sets a row/block DC. **DC = v10 × fp** (linear through fp=46);
  black ≈ −3055, and the mapping is **DC ≈ 27.3 × (Y − 128)** [FIT]. This token
  may also appear mid-row to re-anchor DC.
* **Block framing:** each block is EOB-terminated with `01`; an empty block is a
  bare `01`. The dominant 2-bit unit in any stream is `10`/`01` (phase-flipping),
  = the empty/zero-block symbol.

### 3.2 Codebook (block interior)

Prefix-free small vocabulary + a static escape family:

* **Ladder codes** `1 0^(k-1) 1 s` for magnitudes k=1..6 (sign-last), with
  zero-run prefixes `00`/`000`.
* **Family codes** `0^x 1 0^y` (this is what earlier notes called the
  "specials"/`1 0^a`; it is **static, not adaptive** — the adaptive-Rice
  hypothesis was tested and refuted).
* **Gamma escapes** `0^z 1 <z bits> s`, z≈5..14, for large values.

Adding the escape family to the small vocabulary took content rows from 0 to
exact-186 parses with zero wrong-counts. The `fp`-sweep alignment (same content
at different fp) confirmed the value fields scale with fp (r = +0.99).

### 3.3 What v3 reconstructs — and the wall

v3 renders **DC only**: correct backgrounds, per-row luma level, and the row/column
position of content bands. It does **not** render glyph/texture detail, for a
*fundamental* reason established this session:

> The per-block value codes carry **no signal measurable in the recordings** — not
> in luma, not in chroma, not across a 1,440-setting composite-synthesis grid,
> all with shuffled-null controls. The surviving interpretation: they encode
> **near-subcarrier (fsc-band) texture** that the capture chain's comb filter
> removes from both the luma and chroma it outputs.

So no further *recording-based* fitting can recover the value layer — it needs a
raw/full-bandwidth composite capture or direct silicon probing. There is **no
separate chroma section**; color is per-block/composite-domain (consistent with
0x27 being a color-path parameter, hue-rotation on timing slips, and the
`0xFF`-input → fine-green-checkerboard hardware behavior).

---

## 4. Dequant & display path **[HW/DATA]**

* **fp (0x04)** scales all reconstructed coefficients including DC. `fp=0` →
  uniform neutral gray (all coefficients zero). Native per-scene fp variation is
  honored on screen; displayed contrast rises monotonically with fp. **[HW]**
* **QT (0x05–0x14)** — 16 per-position quantizer steps. QT[0] scales DC
  brightness (discs 7/8). The 16-entry table is the strongest hint the transform
  block is **16 samples** (a ~2px×8-line strip, or a 4×4), but this is **not yet
  hardware-confirmed** — disc 22's QT-zeroing was confounded by a P-frame base
  and disc 23's edits were inert (see §6). QT-basis isolation is the marquee
  open experiment.
* **0x27** — color-path parameter (`0x24`=36 default). Zeroing it (disc 15)
  causes per-row color banding with the block grid preserved → a color-space /
  burst-phase / chroma-quantizer role, not geometry. Its exact law is open (the
  capture chain is comb-blind to the chroma it controls).

### 4.1 Display / parameter-application model **[DATA, one HW test pending]**

Established from recordings + disc structure:

> The console **re-decodes to the display iff the incoming frame's entropy
> stream differs from the currently-displayed frame.** On a run of byte-identical
> streams it **holds** the previous decode and ignores subsequent headers. When
> it does decode, it applies **that frame's own** fp/QT/0x27 (per-frame, not
> scene-latched — partial-corr(GT contrast, fp | content) = +0.30).

This explains every hardware result: disc 23's header edits on a byte-identical
hold were inert (held); disc 22's stream transplants displayed (banding); disc
15's washout markers worked by breaking the hold. **Disc 24** is the minimal
hardware test that confirms this and unlocks the right probe-vehicle design.

---

## 5. Decoder status

| Layer | Status | Where |
|---|---|---|
| Disc/sector layout | **Solved** [HW] | framework18, xa_audio_extract |
| Frame container / assembly | **Solved** [DATA] | framework18.frame_scan_bits |
| Row grammar (headers, counters, DC token, EOB) | **Solved** [DATA] | crack3/decoder_v3.py |
| Block codebook (ladder/family/gamma) | **Solved** structurally [DATA] | crack/codebook_report.md |
| DC value law (fp, opener) | **Solved** [FIT], HW-pending | crack2/value_fit_report.md |
| Per-block value semantics (detail/texture) | **Open** — capture-invisible | crack3 (refutations) |
| Chroma / 0x27 law | **Open** | — |
| Inter-frame prediction (P-frames) | **Open** — new front | pframe/pframe_findings.json |

**Best renders:** black-background text screens SSIM 0.77–0.83 (up to 0.88); the
old-lineage QIS logo frame renders the correct gray field with the logo band in
the right rows. Backgrounds/levels/positions correct everywhere; glyphs blocky.

---

## 6. Hardware test discs (this session) **[HW]**

| Disc | Design | Result / lesson |
|---|---|---|
| 15–17 | Prior single-byte header edits | fp, QT[0], 0x27 roles established; secondary-payload = disc-layout control |
| 18–19 | Prior crafted bitstreams | **Void** — the crafts overwrote sector-0 F1 markers, so hardware only ever saw sector 0; "level-first / 2-bit run CONFIRMED" claims are not valid |
| 20 | Truncation / bit-insertion probes (real stream) | **Played.** First bits→rows map (25/50/75% of bits → 28.8/47.2/61.9% of rows); terminator is not a stop code; no frame persistence; line-locked real-time decode with quantized row slips |
| 21 | Synthetic all-empty probe frames | **Froze the console** — synthetic frames ~1476 B are below the ~5196 B hard floor. Rule: probe frames must be **real, full-length**, minimally edited |
| 22 | Header sweeps on a transplanted still | **Played but confounded** — the base was a **P-frame**; standalone it predicted onto gray markers → rainbow banding on every probe. Revealed inter-frame prediction |
| 23 | Header sweeps on record-0 I-frame hold | **Inert** — byte-identical hold → console held the first decode → zero pixel change. Revealed the display/param-latch model |
| 24 | 15-frame diagnostic (moving-run, establishing-frame, hold-break) | **Built & verified; awaiting capture.** Decides per-frame vs held application so the real sweep disc can be designed correctly |

Recordings live in `research/claude/ak8000/test-cases/results/0NN/`. The
ready-to-burn disc 24 is at `research/adhoc/discs/sample-soft-disc24/`; its design
is in `research/adhoc/playdia_frame_tests/disc24/README.md`.

---

## 7. What is ruled out **[DEAD]**

* 8×8 DCT blocks; 3 sub-frames per packet; MPEG-1 DC-VLC (any swap); DC-size
  caps — all artifacts of the mis-assembled bitstream + the degenerate "SF01"
  metric (which scored ≥0.98 on content-free parsers).
* 93 Y/C block-pair interleave; static QT-per-position as the whole story;
  per-block codes carrying luma; fixed-width escapes; adaptive-Rice in-block
  code; length-prefixed row records; fixed-width symbol / VQ schemes.
* The old QIS 000 corpus is a **different disc revision** than the Sample Soft
  dump (fp 13 vs 15); keep lineages separate.

---

## 8. Recommended next steps (priority order)

1. **Burn & capture disc 24** → confirm the display model; then build the real
   sweep disc on the correct vehicle (establishing frames of stills / runs across
   motion), sweeping fp, QT[0], the QT-basis, and 0x27.
2. **Raw-composite capture** of the value-layer probes — the only way to see the
   fsc-band detail the standard chain filters out. Without it, glyph-level decode
   is unreachable from recordings.
3. **Crack inter-frame prediction (P-frames).** ~half the disc. Use an I-frame
   followed by a known-delta P-frame (crafted, once disc 24 fixes the vehicle) to
   learn the residual/reference model. `pframe/pframe_findings.json` has the GOP
   structure and first observations.
4. **Dump the uPD78214 mask ROM** (see `NecBiosDumper-Notes.md`) — the only route
   to the exact dequant/color constants and the on-chip codebook if analysis
   plateaus.

---

## 9. Artifact index

* Decoder / framework: `tmp/claude/session18/framework18.py`,
  `…/scratchpad/crack3/decoder_v3.py`
* Reports: `…/scratchpad/audit_fact_sheet.md`, `disc_recon_report.md`,
  `fp_mining_report.md`, `crack/geometry_report.md`, `crack/codebook_report.md`,
  `crack2/value_fit_report.md`, `crack3/decoder_v3_report.md`,
  `pframe/pframe_findings.json`, `dispmodel/display_model_summary.json`
* Tools: `research/adhoc/xa_audio_extract.py`,
  `research/adhoc/playdia_frame_tests/disc{20,22,23,24}/`
* Ground truth: audio-aligned recordings + `gt_sample_soft/frame_map.json`
* Catalogs: `tmp/claude/session18/{sample_soft,sailor_moon}_catalog.npz`
* Session handoff: `research/claude/ak8000/planning/2026-08-12-session18-handoff.md`

*(Scratchpad paths under `/tmp/claude-1001/-data-blaydia/*/scratchpad/` are
session-local; copy anything worth keeping into the repo.)*
