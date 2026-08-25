# 2026-07-20 — Dynamic MOTION (templates + timed overlay)

## Author signal (clarification)

- **Symptom:** «видео великолепны» — но это **не** полное принятие продукта.
- **Scope praised:** визуал Gate2 — кроп, субтитры на груди, общий вид (grade = neutral).
- **Out of scope for now:** звук не оценивался — в аудио не лезть.
- **Next:** научиться **динамическому MOTION**.

## Loop entries

### 1. MOTION declared but invisible on screen

- **Symptom:** `render-contract.json` had `motion_count > 0`, `motion_on_screen_texts: []`, nothing animated on review MP4.
- **Wrong assumption:** overlay mode + brief in transcript ⇒ viewer sees motion.
- **Root cause:** `motion_on_screen_text()` correctly strips director copy → empty label → compositor skipped plate (`if motion_on_screen:`).
- **Fix:** `classify_motion(brief)` maps director brief → **template** (`meter_drop`, `formula_split`, …) with optional audience label; always render animated plate.
- **Guardrail:** `tests/test_motion.py` template map; contract gets `motion_template`.
- **Evidence:** Tanya seg01–03 contracts before fix.

### 2. Static card for full KEEP clip (not overlay window)

- **Symptom:** Motion would have sat on entire speech block, not 2–3.5s beat.
- **Wrong assumption:** One KEEP clip ≡ one motion timing.
- **Root cause:** Compositor used `duration=entry.end-entry.start` and full-span overlay.
- **Fix:** `resolve_visual_start/end` → `motion_window_start_s/end_s` local to clip; ffmpeg `setpts` delay + `overlay enable='between(t,...)'`.
- **Guardrail:** `visual_audit` probes declared window; render contract stores window fields.
- **Evidence:** `pipeline/factory/render.py`, `visual_audit.py` comment updated.

### 3. Static PNG loop ≠ dynamic motion

- **Symptom:** Even when text showed, plate was frozen PNG looped.
- **Wrong assumption:** Overlay presence is enough for «motion».
- **Root cause:** `render_motion_card` = single frame + `-loop 1`.
- **Fix:** `render_motion_overlay` — per-frame PIL animation (fade/slide/progress) encoded to RGBA clip (`motion-dynamic-v1`).
- **Guardrail:** `tests/test_motion.py::test_render_produces_short_rgba_clip`.
- **Evidence:** `pipeline/factory/motion.py`.

## Templates v1 (from Tanya briefs)

| Template | Trigger keywords | Audience label |
|----------|------------------|----------------|
| `meter_drop` | ползёт, индикатор, нуле | (icon only) |
| `panic_sequence` | иконки, паник, горящ | (icon only) |
| `formula_split` | `60 000 → 6 000` | formula text |
| `bank_friction` | два банка, перевод, замок | `2 банка` |
| `stack_growth` | месяцев, плитки | `12 × 6к` |
| `scales_tilt` | весы, vs | `приоритеты` |
| `priority_shift` | сдвиг приоритетов, схема | `схема` |
| `kinetic_accent` | fallback | (line only) |

Canon: `docs/product/GATE1_MOTION_OVERLAY.md` (timing laws unchanged).

### 4. Motion animates but meaning unreadable (author Gate 2)

- **Symptom:** Shrinking gold bar at seg01 open — smooth, not ugly, but viewers don't know what it represents.
- **Wrong assumption:** Icon-only template + timed overlay = audience gets the brief's intent.
- **Root cause:** (1) `motion_on_screen_text()` strips director brief including quoted `«0 ₽»`; `meter_drop` renders bar with **no label**. (2) Full chest captions still burn during MOTION — two competing focal layers in same band.
- **Fix (proposed, not shipped):** Extract **audience punch** from `what` / quotes; upgrade templates to v1+ (words/numbers); **caption mode swap** during MOTION (suppress or demote), per reference graphic-mode pattern.
- **Guardrail:** `docs/product/MOTION_CAPTION_LAYOUT.md`; Gate 2 MOTION probes must show readable punch text.
- **Evidence:** `projects/tanya-reel-pilot/03_phase1/segments/01/visual-plan.json` scene `1a`; `pipeline/factory/motion.py::_frame_meter_drop`; `visual_policy.motion_on_screen_text`.

### 5. Caption × MOTION stacking (author hypothesis)

- **Symptom:** Layering motion over gold chest captions feels wrong.
- **Wrong assumption:** Shrink captions ×2 and stack motion above = reference-quality layout.
- **Root cause:** MeVGa/Dan Koe uses **one dominant graphic mode per beat** (title OR list OR captions), not simultaneous chest text + widget (`lab/references/MeVGaMG28nc/analysis.md`; `captions_body` anti_situations in style library).
- **Fix (proposed):** Default **suppress body captions** during MOTION window; motion owns chest band with readable punch. Optional fallback: demoted smaller captions lower — author decision pending.
- **Guardrail:** Style card anti-situation + render-contract `caption_mode`; overlap audit.
- **Evidence:** `docs/product/MOTION_CAPTION_LAYOUT.md` strategies A–E.

### 6. Motion v2: semantic templates + caption mode swap (implementation)

- **Symptom:** v1 templates were icon-only (bar, `! ? …`), not readable; captions competed in same band.
- **Wrong assumption:** Template shape alone carries meaning.
- **Root cause:** (1) `_extract_audience_punch()` didn't exist — quoted `«0 ₽»` was stripped by director-copy filter; labels were empty. (2) Templates drew abstract shapes without text. (3) Captions burned always, no motion-aware suppression.
- **Fix:** `motion-dynamic-v2`:
  - `_extract_audience_punch()` — extracts from `«…»` quotes, formula patterns, amounts;
  - `classify_motion()` — every template gets a non-empty `label`; `suppress_captions=True` by default;
  - Templates rewritten: `meter_drop` = wallet card + animated balance counter + progress bar; `panic_sequence` = 3 labeled step cards; `formula_split` = animated number split with card; `bank_friction` = labeled bank cards + friction lock; `stack_growth` = labeled month tiles + running total; `scales_tilt` = labeled pans; `priority_shift` = labeled item cards with directional arrows;
  - All templates add dark gradient scrim behind motion zone;
  - Renderer: `suppress_captions_for_motion` flag — when motion has `suppress_captions=True`, body captions off for that clip (mode swap);
  - Render fingerprint: `ffmpeg-overlay-v9-motion-v2`.
- **Guardrail:** 10 unit tests pass including punch extraction, label non-empty, suppress flag. Render tests need ffmpeg.
- **Evidence:** `pipeline/factory/motion.py` v2, `pipeline/factory/render.py` v9, `tests/test_motion.py`.

### 7. Seg02 preview stops ~7s (concat copy seam)

- **Symptom:** Author: second video plays until ~7s then stops. File on disk is ~40s; ffmpeg full decode OK.
- **Wrong assumption:** `-c copy` concat of per-clip H.264/AAC is fine for Gate 2 review players.
- **Root cause:** Independently encoded clips stream-copied via concat demuxer → irregular `avg_frame_rate`, GOP/timestamp seams. Cursor/preview players often halt near early seams (~clip-001+002 ≈ 8s). Media itself was complete.
- **Fix:** `concat_clips` re-encodes to CFR 30fps + AAC (`ffmpeg-overlay-v10-concat-reencode`).
- **Guardrail:** After concat, probe `avg_frame_rate` should be `30/1` (or profile fps); learning note here.
- **Evidence:** Tanya seg02 before: `avg_frame_rate=9300480/310067`; after rebuild: `30/1`, duration 40.4s.

### 8. Captions missing for whole KEEP when MOTION present (author Gate 2)

- **Symptom:** Seg02 shows only animations; no body captions in gaps between MOTION beats.
- **Wrong assumption:** Mode-swap = turn off captions for the entire KEEP clip that hosts a MOTION.
- **Root cause:** `suppress_captions_for_motion` disabled ASS burn for the full clip; MOTION is only a 2–3.5s window inside a longer KEEP (e.g. 14s).
- **Fix:** Always burn phrase captions; punch holes only for `motion_window_start_s..end_s` via `_subtract_suppress_windows` (`ffmpeg-overlay-v11-caption-gaps`).
- **Guardrail:** `tests/test_caption_gaps.py`; contract field `caption_suppress_windows`.
- **Evidence:** Author review of `04_phase2/segments/02/review.mp4`.

### 9. Agent shipped caption-gap fix without self-audit (process)

- **Symptom:** Author: «плохо что ты его сам не диагностировал — надо проверять.»
- **Wrong assumption:** Code fix + unit test is enough before human re-watch.
- **Root cause:** No Gate2 audit check for gold captions in MOTION gaps; agent did not open gap probe JPGs after rebuild.
- **Fix:** `gate2-visual-audit-v3` adds `caption_gap_checks` (gold_px in chest band outside motion windows). QC enables `require_caption_gaps` when captions + motions + `caption_pos_y`. Cursor rule: self-verify audit JPGs after visual fixes.
- **Guardrail:** `tests/test_gate2_visual_audit.py::test_missing_captions_in_gap_fails_when_required`; `.cursor/rules/gate2-visual-policy.mdc`.
- **Evidence:** This entry; audit probes `caption-gap-*.jpg` under `probes/gate2-audit/`.

### 10. Audio check belongs after master concat (author)

- **Symptom:** Author wants loudness/mix checked on the glued film, not re-checked per segment.
- **Wrong assumption:** Segment review audio ≈ final delivery audio.
- **Root cause:** Phase 3 previously concat'd without loudnorm / multi-grade delivery; no Final Review grade trio.
- **Fix:** Phase 3 `master-package-v4`: concat → `loudnorm I=-14` → three grade masters (`neutral`, `dankoe`, `warm`); primary = `default_grade`; `grade-review.md` + audio metrics on master.
- **Guardrail:** Final QC embeds `master_audio` + `grade_candidates`; listen only on `05_final/grades/`.
- **Evidence:** Tanya `05_final/grade-review.md`, `05_final/grades/master-*.mp4`.

### 11. Telegram black video + “unsupported format” (yuv444p)

- **Symptom:** TG plays audio over black frame ~5s then says format not supported.
- **Wrong assumption:** H.264 MP4 + AAC is enough for Telegram in-app player.
- **Root cause:** Motion `rgba` overlays / grade filters left masters as `pix_fmt=yuv444p` + `High 4:4:4 Predictive`. Telegram needs `yuv420p` + High (8-bit 4:2:0).
- **Fix:** Force `-pix_fmt yuv420p -profile:v high` on clip encode, concat, and `apply_grade` (`ffmpeg-overlay-v12-yuv420p`); re-encoded Tanya masters and re-sent.
- **Guardrail:** Probe deliverables for `yuv420p` before TG send; never ship High 4:4:4.
- **Evidence:** Before probe `High 4:4:4 Predictive,yuv444p`; after `High,yuv420p` on `05_final/grades/master-*.mp4`.

### 12. Telegram iPhone squash + delivery file

- **Symptom:** Desktop/Android OK; iPhone TG shows horizontally stretched face + letterboxing. File on disk is SAR 1:1 / 9:16.
- **Wrong assumption:** `sendVideo` preserves our encode for all clients.
- **Root cause:** TG server recompress for in-app video; iOS player mishandles some variants. Document upload does not recompress — 1080×1920 document played correctly.
- **Fix:** Phase 3 / `telegram-deliver` builds a **separate** `05_final/delivery/tg-*-1080x1920*.mp4` (`sendDocument` by default). Optional `telegram_delivery.speed_factor` (e.g. 1.15) applies **only** to that file; clean grade masters stay 1.0×.
- **Guardrail:** `tests/test_telegram_delivery.py`; project.json `telegram_delivery` block; never mutate `grades/master-*.mp4` for speed/TG size.
- **Evidence:** Author iPhone screenshot `photo_2026-07-20_18-28-16.jpg`; working document send of warm 720 and 1080.

### 13. “Embeddings” = agent sense cards, not a model

- **Symptom:** Author rejected technical embedding/API framing for P5 media semantics.
- **Wrong assumption:** Item “embeddings” means sentence-transformers or OpenAI vectors.
- **Root cause:** Need searchable **meanings** after a real film; the agent already sees the video/transcripts in chat and can write cards.
- **Fix:** `library/senses/catalog.json` from Tanya MOTION briefs; lexical `search_senses` + B-roll query expansion; Style Bible + `reels-9x16` / `longform-16x9` profiles only.
- **Guardrail:** `tests/test_profiles_and_senses.py`; Style Bible forbids external embedding providers for this layer.
- **Evidence:** Tanya visual-plan scenes 1a–3c; `docs/product/STYLE_BIBLE.md`.
