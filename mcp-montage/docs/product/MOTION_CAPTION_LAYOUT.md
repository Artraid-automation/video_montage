# MOTION × captions — layout & semantics (research)

**Status:** draft for author review · 2026-07-20  
**Trigger:** Gate 2 author feedback — motion animates smoothly but meaning is unclear; stacking with chest captions feels wrong.

Related: `docs/product/GATE1_MOTION_OVERLAY.md`, `docs/product/FRAMING.md`, `presets/styles/dankoe-mevga-v1/library.json`, `lab/references/MeVGaMG28nc/analysis.md`.

---

## Author feedback (verbatim intent)

| Signal | Detail |
|--------|--------|
| Motion quality | Dynamic, smooth enough — not repulsive |
| Semantics | Too primitive — e.g. shrinking bar at open: viewers don't know what it means |
| Layout | Caption + motion in the same chest band is wrong |
| Hypothesis | Shrink captions ×2, move down slightly; put motion in the caption slot — **needs research** |
| Direction | Think about complexity ladder; v1 templates are placeholders, not product |

**Out of scope:** audio pipeline (author has not listened).

---

## What successful reference cases do (MeVGaMG28nc / Dan Koe)

From `lab/references/MeVGaMG28nc/analysis.md` and style library cards:

1. **Graphic modes, not stacks.** The short alternates **one dominant text layer per beat**:
   - `hook_title` (0–5s) — big gold title, no phrase captions
   - `framework_list` (~5–15s) — blur+darken A-roll + spotlight list, no phrase captions
   - `captions_body` (~15–45s) — phrase captions only, no extra motion plates

2. **Anti-situation is explicit.** `captions_body` card forbids simultaneous `hook_title` / `framework_list` on the same tact. Compositor spec: **suppress body captions** under title/list.

3. **Motion language = text timing**, not abstract widgets. Primary “motion” in the reference is **phrase pop-on captions** synced to speech — not shrinking bars or `! ? …` glyphs.

4. **When a beat needs a “card”**, the card **is** the readable text (title lines, list items, formula). Icon-only beats are rare; meaning rides on **words the audience can read in <1s**.

**Implication for us:** layering full-size gold captions **and** a motion plate in the same chest band fights the reference model. Better default: **mode swap** during MOTION window (motion carries meaning; captions demoted or off), not shrink-and-stack.

---

## Platform / readability research (short-form 9:16)

Industry guidance (TikTok/Reels/Shorts safe zones, 2026):

- Captions live in **lower-middle / chest band** (~48–58% frame height) to clear platform UI and keep face visible.
- **One focal text block** per moment — word-by-word or short phrase chunks outperform dense stacks.
- Talking-head: never cover eyes/mouth; minimize vertical eye travel between face and text.

**Implication:** If motion occupies the chest band, captions must **move or pause** — not compete at the same size in the same band.

---

## Why Tanya seg01 hook bar fails semantically

Brief (scene `1a`):

> Индикатор счёта ползёт к «0 ₽» / пустой кошелёк. Зачем: …

Pipeline today:

1. `classify_motion` → template `meter_drop` (keyword match).
2. `motion_on_screen_text()` treats the whole brief as **director copy** → strips everything → **empty label**.
3. `meter_drop` renders **anonymous gold progress bar** at ~76% height — same real estate as captions.
4. Captions keep burning phrase text underneath/over — **double stimulus, single meaning**.

Root cause is **policy + template**, not ffmpeg timing:

- Audience punch `0 ₽` / `на нуле` exists in brief but is **discarded** by director-copy filter.
- Template has no wallet, no number, no words — only a bar.

---

## Layout strategies (compare)

| Strategy | Pros | Cons | Reference fit |
|----------|------|------|----------------|
| **A. Mode swap** — suppress or freeze captions during MOTION; motion owns chest band | Clean read; matches hook_title / framework_list pattern | Viewer loses phrase text for 2–3.5s (speech still audible) | **High** |
| **B. Demote captions** — smaller (≈50%), lower (abdomen / safe lower-third), motion in chest band | Keeps some subtitle anchor; author hypothesis | Still two text layers; smaller text harder on mobile; fights “gold phrase” brand | Medium |
| **C. Motion as caption replacement** — motion plate shows **the phrase punch** (e.g. `0 ₽`) instead of ASR chunk | Single text focal point; semantic clarity | Needs per-beat copy from brief/what, not generic template | **High** for punch beats |
| **D. Full takeover** — blur+darken + motion card (like `framework_list`) | Very clear hierarchy | Heavier look; only for strong beats | Medium (list-like beats) |
| **E. Stack unchanged** (current) | Simple compositor | Clutter; bar meaningless; violates style anti-situations | **Low** |

**Recommendation (draft):** default **A + C** — on MOTION window, **pause body captions** and render motion in chest band with **audience-readable punch** extracted from `what` / quoted spans in brief. Use **B** only as fallback when author insists on continuous captions.

**Implemented (v11):** captions burn for the full KEEP clip; ASS events are punched out only for the MOTION window (`caption_suppress_windows`). Gaps before/after motion keep phrase captions.

---

## Semantics ladder (complexity)

| Level | Example (seg01 `1a`) | Audience reads in <1s? |
|-------|----------------------|-------------------------|
| **v0 (now)** | Shrinking gold bar, no label | No |
| **v1** | Bar + big `0 ₽` + optional `на нуле` | Yes |
| **v2** | Wallet icon + animated balance `12 400 → 0 ₽` | Yes |
| **v3** | Mini scene: account card UI metaphor, tick-down numerals | Yes (more production) |

Same ladder for `panic_sequence`: `! ? …` → labeled steps (`паника` → `ищу` → `тушу`) → simple icon trio with Russian labels.

**Rule:** no icon-only MOTION in production Gate 2 unless brief supplies **≤6 word audience label** or quoted punch.

---

## Product contract changes (proposed, not implemented)

1. **`motion_audience_punch`** — extract from `what` field or `«…»` in brief before director-copy strip; never empty for shipped MOTION.
2. **`caption_mode` per window** — `body` | `demoted` | `suppressed` (default `suppressed` when MOTION active).
3. **Compositor order** — motion chest band only when captions suppressed/demoted; QC fails if caption bbox overlaps motion text bbox.
4. **Style library** — new anti-situation on `captions_body`: same tact as MOTION with chest overlay.
5. **Gate 2 audit** — MOTION probes must show **readable punch text** (OCR or vision check), not only “gold pixels present”.

---

## Open questions for author

1. **Mode swap vs demote:** OK to hide phrase captions for 2–3.5s while motion plays (speech continues)?
2. **Punch source:** Prefer `what` from Gate 1 (`0 ₽ / пустой кошелёк`) burned as-is, or agent-shortened (`0 ₽`)?
3. **Complexity budget:** Target v1 labels only next, or invest in v2 numerals/icons per template?
4. **List-like motions:** Should some MOTION beats promote to `framework_list`-style blur takeover?

---

## Next step (when approved)

1. Author picks layout default (A/C recommended).
2. Implement punch extraction + caption_mode in render contract (no audio changes).
3. Upgrade `meter_drop` + `panic_sequence` to v1 labels on Tanya seg01 only as fixture.
4. Re-run Gate 2 + author watches **only** motion beats + audit JPGs.
