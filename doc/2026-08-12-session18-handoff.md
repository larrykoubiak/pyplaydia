# AK8000 Decoder — Session 18 Handoff (Fable)

> **LATE-SESSION BREAKTHROUGH (see §0):** with full disc images + gameplay-recording
> ground truth, the bitstream structure was cracked: ROW-ADDRESSED units with
> explicit sync + 10-bit row counters. Sections below describe the earlier
> container work; §0 supersedes the "code unsolved" framing.

## 0. The bitstream structure (cracked via supervised analysis)

Row unit grammar (validated on 9 frames, 4 screens, 3 records, incl. white-bg):
```
00000000 1 CCCCCCCCCC 001 DDDDDDDDD [slot codes...]
  sync     10-bit row counter  row-DC field
```
- S-class (7-9 sector) frames: preamble unit + row counters 2..27 (26 rows,
  ~8 display lines each), 192 two-bit slots per row; empty slot = '10'
  (phase-flips to '01' after odd-length codes).
- The 14-bit end "terminator" = the same sync family (end-of-frame row marker).
- Base codeword candidate {10, 00, 111, 1100, 0110} (prefix-free) + variable
  escapes under prefixes 0100/0101/0111/1101; magnitude fields scale with fp
  (r=+0.993). Row syncs are the 8-zero escapes.
- No separate chroma section; color is per-slot or composite-domain.
- Ground truth: gameplay recordings audio-aligned to disc LBAs (75 sectors/s
  linear time) — `session18/align_recording.py`; ~11k frames mapped.
- Rosetta specimens: sample-soft record 9 (near-black promo text screens,
  5.2-6.6 KB streams), SM record 1388 (password screen region, 9 KB).
- Full evidence: `scratchpad/crack/geometry_report.md`, `fp_mining_report.md`,
  `disc_recon_report.md`.

### Decoder v2 state (scratchpad/crack2/, renders/session18-fable/supervised2/)
- True row header = 19 bits (`0^8 1` + 10-bit counter); 20-bit prefix-free
  absolute-DC token `0010000000`+v10, valid mid-row and optional at row start;
  DC = v10 × fp, linear through fp=46; black = −3055, DC ≈ 27.3×(Y−128);
  GT row geometry: y = 28 + (counter−2)·16 capture lines.
- SSIM vs ground truth: black-bg text screens 0.77–0.82 (v1: 0.056); white-bg
  logo 0.50–0.62; gray BANDAI 0.32–0.47; photo/menu stills 0.07–0.22.
- DEFINITIVE negatives: 93 Y/C block-pair interleave refuted; static
  QT-per-position refuted; per-block sparse-row codes carry ZERO luma
  (supervised measurement, n=104 ladder codes: slope ≈ 0).
- Round 3 RESOLVED the wall: the `1 0^a` family is a STATIC in-block value-code
  family `0^x 1 0^y` (adaptive reading refuted). Decoder v3
  (scratchpad/crack3/decoder_v3.py) exact-parses **99.3% of 1,794 battery rows**
  including 26/26 on the other disc lineage; SSIM battery 0.245→0.388
  (text screens 0.83, best 0.88), improvement on 68/69 frames.
- FUNDAMENTAL MEASUREMENT LIMIT: the in-block value codes (the glyph/detail
  layer) carry no signal measurable in the JPEG-capture ground truth in ANY
  domain — luma, chroma, and a 1,440-setting composite-synthesis grid, all with
  shuffled-null controls. Surviving interpretation: they encode ~fsc-band
  2-sample texture that the capture chain comb-filters out of both channels.
  ⇒ No further recording-based fitting is possible; the value table must come
  from hardware probes captured with full-bandwidth/raw composite.
- Disc 21 (research/adhoc/playdia_frame_tests/disc21): probe set crafted under
  the v3 grammar — opener-DC staircases at fp 7/16/32, single-code probes
  isolating every ladder/family/escape code on gray background, anchor-ambiguity
  and sync-slack probes, row-addressing probes, 0x27 sweep (risky probes last;
  fp=0 flat-gray marker frames).

**Date:** 2026-08-12
**Model:** Claude Fable 5 (first session; prior 17 sessions were Opus 4.6 and earlier)
**Focus:** Question foundational assumptions instead of extending the config grid.
**Verdict:** The bitstream **container** is now solved and several foundational
assumptions of sessions 1–17 are **disproven**. The entropy code itself remains
uncracked, but the search now stands on verified ground for the first time.

---

## 1. CRITICAL DISCOVERY: per-sector 0xF1 markers — all prior parsing was on corrupted streams

**Every 2048-byte sector inside a frame begins with a 1-byte 0xF1 marker.**
(Verified on QIS and all SM size classes; the byte after each marker is
high-entropy payload — there is no further per-sector header.)

Correct scan-stream assembly (now implemented in
`/data/blaydia/tmp/claude/session18/framework18.py::frame_scan_bits`):

```
sector 0:        payload = bytes [0x28 : 0x800]     (after the frame header)
sectors 1..k:    payload = bytes [off+1 : off+2048] (skip the 0xF1)
last sector:     starts 0xF2; header 0x23 bytes; payload [f2+0x23 : f2+0x800]
                 is the OVERFLOW TAIL of the video stream (used only when the
                 F1 payload is full). Trim trailing 0xFF from the concatenation.
```

Sessions 1–17 concatenated `0x28..0x2FFF` raw, injecting five 0xF1 bytes into the
bitstream (first at ~16% depth). **Every one of the ~10,900 configs ever tested
was evaluated on a desynced stream.** All conclusions built on those parses
(VLC swaps, size caps, hybrid signs, sub-frame boundaries at "~1/3") are void.

Corollary: the crafted frames burned for discs 18/19 overwrote the sector-start
bytes ⇒ real hardware saw invalid sector markers after sector 0 ⇒ the hardware
tests only ever exercised the **first 2008 bytes** of each crafted bitstream.
The "LEVEL-FIRST CONFIRMED / 2-bit run CONFIRMED" claims are void (the audit
had already downgraded them; this explains the photos mechanically).

## 1b. Physical disc layout (verified on the user's ROM during disc-20 prep)

Raw MODE2/2352 track; sector taxonomy by XA subheader + first user byte:

| Kind | Subheader | Form | First user byte | Notes |
|---|---|---|---|---|
| Video | `01 00 08 00` | 1 (2048) | 0xF1 | 7 per frame; frame header in first sector |
| Frame end | `01 00 08 00` | 1 (2048) | 0xF2 | 0x23-byte header + video overflow payload |
| Filler | `01 00 08 00` | 1 (2048) | 0xF3 | `F3 37 F9` + 0xFF fill; inserted on video underrun |
| Audio | `01 01 64 04` | 2 (2324) | (ADPCM) | **every LBA ≡ 13 (mod 16), rigid** |

Audio = mono 18.9 kHz 4-bit XA ADPCM: 4032 samples/sector = 213.3 ms, consumed at
exactly 75/16 sectors/s — the interleave ratio has zero slack, so the VIDEO side
absorbs timing via F3 fillers. Effective video rate ≈ (75 − 75/16 − fillers)/7 ≈
**10.04 fps** (corrects the old "75/7 ≈ 10.71 fps" estimate). Frames whose 7
video sectors straddle an audio LBA are split around it — any patch tooling must
walk real sectors (see `disc20/apply_disc20.py`); the linear-offset patching used
for discs 18/19 could never have worked for ~half the frames. First frame of
scene 000 starts at LBA 150 on this ROM.

## 2. Frame classes and geometry facts

- SM corpus contains FOUR frame classes: 7, 9, 14, 15 sectors (14336 / 18432 /
  28672 / 30720 bytes). 14454 of 23467 SM frames are 14-sector ("LARGE").
  Prior "cross-game validation" treated them all as 7-sector frames — garbage in.
- Unused capacity = whole sectors of pure 0xFF (marker byte + 0xFF fill).
- The F2 sector payload cap is 2013 bytes (0x23-byte header).
- QT (16 entries) is **identical across both games** — likely hardwired encoder
  table; QT[0] scaling confirmed on hardware (disc 7/8).
- Header bytes that vary per frame: **only 0x04 (FP) and 0x27**. Everything else
  including 0x25/0x26 is constant across 23k+ frames.

## 3. The end-of-stream terminator (new, universal)

Every frame's stream (1,426/1,426 tested across both games) ends with:

```
...content... 00000000100001 0{6,13} | 0xFF padding
```

i.e. a 14-bit epilogue `00000000100001` (frequently preceded by `01`, suggesting
a 16-bit read `0100000000100001` = 0x4021 — frame 45's file literally ends bytes
`40 21 00`), then zero-padding to byte boundary. Mid-stream occurrences of the
14-bit pattern exist (coincidental, irregular spacing — NOT slice markers; tested).
This gives an **exact end anchor for every frame**, full or not.

## 4. Verified container-level facts (all tested this session)

| Fact | Evidence |
|---|---|
| Bit order MSB-first | only MSB-first shows sharp run caps (maxZ=13, maxO=13) and 7/11 zero-run bumps; LSB/word-swapped variants smear them |
| Single contiguous stream (no byte/word interleave) | de-interleaving (mod 2/3/4) destroys run caps and bumps |
| Stream continuous across sectors | no terminator/padding at sector seams; terminator only at true end |
| F2 payload = video overflow | terminator found INSIDE F2 payload for full frames; F2 empty when video ends early |
| No fixed-width fields at stream start | first-16-bit "value" is bimodal (<2048 or >8191) = VLC fingerprint; fp-pair regression rejects fixed quantized field |
| No 3-way periodicity for static content | bit-level autocorrelation flat at all lags incl. n/3 |
| Zero-run stats (corrected stream) | hist caps at 12–13 with bumps at 7 and 11; one-runs smooth decay cap ~11–13; density 0.405 |
| Static-scene tails | one frame shows `01`×17 repeats before terminator ⇒ some 2-bit repeated unit exists (empty block / skip?) |
| 0x27 varies per frame (32..63), fluctuates frame-to-frame with instant reversions | not a resolution; hardware sensitivity (0→severe per-row COLOR banding w/ intact structure; 36→37 subtle color shift) fits a chroma quantizer/scale or per-row color parameter |

## 5. Metric calibration (why sessions 2–17 fooled themselves)

Null-model calibration (150+ deliberately-wrong parses: wrong offsets, wrong
frames, random configs): **|ref_corr| up to 0.42, p95 ≈ 0.40** for DC-chain
planes vs the reference photo. Prior sessions' SF01 was even worse (documented
0.98 on content-free parsers). ⇒ Any correlation below ~0.5 is noise. Nothing
found by this session's ~55,000 config-frame evaluations is significant either —
the difference is we now *know* it.

## 6. What the code is NOT (all tested on the corrected stream)

- Not: any repeating `[DC][AC items][EOB]` block structure under 12 universal
  code families × 12 × 12 (DC/level/run) × level-first/run-first × 4x4/8x8 caps —
  geometry-FREE test: parse until stream end, require block counts consistent
  across same-class frames. Best spread 14.8% (truth requires ~0%). 690
  survivors, none consistent. (`blockcount_search.py`)
- Not: fixed-width symbol streams / VQ-style (no 8/12/16-bit periodicity in
  short-lag bit autocorrelation; only weak lag-1/2 run correlation).
- Cross-shard validation (33 frames with exactly-known ends): every grid
  candidate plateaus near 50% stream consumption; the frame-45 "end-exact"
  screening hits were single-frame flukes. NO searched family consumes streams.

- Not: MPEG-1 DC-luma VLC family (any swap), size-VLC + fixed runs — under-consume.
- Not: pure Rice/EG/unary run-level or level-run families in interleaved MCU,
  row-planar, planar, CbCr-interleaved layouts at 4×4 or 8×8, at 192×144,
  320×240, 352×240, 256×192, with scan starts 0x28/0x29/0x2A/0x2C — 20 shard
  sweeps × ~2700 configs: no config both consumes streams exactly and
  correlates with the reference above null.
- Not: a "DC section first" layout (absolute or diff-chained; 8 grids × 12 codes
  × 4 scan orders — nothing above null).
- Not: fixed-width DC prologue fields.
- Bit-budget arithmetic: ~108k bits/frame at 192×144 4:2:0 = **~3:1 compression**
  — the code is LOW-compression; blocks must be coefficient-rich (~40 bits per
  4×4 block at single-image 192×144, ~14-15 bits/block at 320×240-class or
  3-subframe interpretations).

## 7. Hardware-photo forensics (new quantitative pipeline)

`scratchpad/photokit.py` + `photo_measurements.json`: rectification + per-band
phase-correlation displacement + garbage detection, validated on disc-15
controls (dx=0). Key reinterpretations:
- Displaced-logo photos (discs 18/19) show horizontal displacement with
  wraparound and NTSC hue rotation on displaced content — consistent with
  **line-phase slips** (real-time line-locked decode), not a framebuffer ring.
- Disc 18 checkerboard band: hardware consumed the crafted sector-0 payload
  (16,064 bits) producing ~33-35 rows of high-frequency garbage ⇒ rough
  parsing-rate datum (~460-490 bits/row on that pattern).
- fp_0.png (FP=0 hardware capture) is PERFECTLY uniform neutral gray ⇒ FP
  scales DC as well as AC (no fixed-DC path).

## 8. Recommended next steps (ranked by information value)

1. **Burn disc 20 with sector-marker-correct frames.** All prior crafted-frame
   hardware data is compromised. Rules: only modify payload bytes; keep 0xF1 at
   0x800/0x1000/...; keep the F2 sector; include (a) bit-shift probes (insert
   1-8 zeros early, observe corruption onset row => bits/row map), (b) truncated
   streams (terminator at chosen positions => does display stop at row R?),
   (c) the terminator moved earlier, (d) byte-value sweeps of the first 4 bytes.
2. **Code-inference via known plaintext prefix:** QIS f0's first rows are flat
   gray; SM 002 static frame ends with `01`×17 + terminator. Grow a prefix-code
   tree constrained by: stream ends exactly at terminator on EVERY frame (1,426
   test frames!), first codes encode near-flat content, ~3:1 total budget.
   This is a search over code TREES (not parameter grids) — likely needs a
   proper algorithmic approach (e.g., constrained grammar induction / DP over
   code-tree space scored by end-exactness across hundreds of frames).
3. **0x27 correlation once any partial decode exists** (chroma quantizer hypothesis).
4. **Examine the Playdia BIOS/driver code** (NecBiosDumper-Notes.md) for AK8000
   register-level command sequences — the driver may reveal frame-header field
   semantics (FP, 0x27) even though tables are on-chip.
5. Re-run any historically "promising" idea ONLY on the corrected assembly with
   the null-calibrated thresholds (≥0.5 |corr| + exact stream end on 30+ frames).

## 9. Infrastructure (all new this session)

- `/data/blaydia/tmp/claude/session18/framework18.py` — corrected assembly,
  geometry/code-family parser DSL, null-calibrated scoring
- `run_shard.py`, `gen_shards.py`, `shards/*.json`, `results/*.json` — 20-shard
  grid infrastructure (~55k config-frame evals)
- `check_hw_patterns.py` — disc 18/19 crafted-pattern compatibility checker
- `hand_search.py`, `dc_section_crack.py` — targeted structure searches (negative)
- `scratchpad/photokit.py`, `photo_measurements.json` — photo forensics pipeline
- `scratchpad/audit_fact_sheet.md` — full audit of sessions 1-17 evidence quality
- `scratchpad/null_calib.json` — significance thresholds
- Renders in `/data/blaydia/tmp/claude/renders/session18-fable/`
