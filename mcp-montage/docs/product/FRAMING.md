# Framing + face-aware captions (product instructions)

**Status:** implement now — auto framing from rules; captions placed from **recognized face**, not fixed ASS alignment.

## Problem

1. Talking-head A-roll has too much headroom (empty space above the head).
2. “Mid-chest” captions using fixed ASS alignment land **on the face** after crop/scale — coordinates ignore the person.
3. After reframe, every overlay must be re-checked on **real pixels**.

## Rules (framing)

| Metric | Target |
|--------|--------|
| Output | project `render_profile` (e.g. 720×1280) |
| Eyes | ≈ **22–26%** from top (follows from headroom + face fill) |
| Headroom | **6–14%** of frame height above face box top (target **10%**) |
| Face height | ≈ **24–30%** of frame height (head+shoulders, chest free for captions) |
| Horizontal | face center ≈ frame center |

Fail if face not detected on sample frames (fail-closed; no blind center crop — lab proven).

## Rules (captions)

- Style remains Dan Koe body: gold `#E1C445`, serif, short chunks.
- Vertical position = **below detected face box** (chest band), never fixed “middle of frame”.
- After burn-in, Gate 2 audit must detect face on probe JPGs and **FAIL if caption band overlaps face bbox**.

## Pipeline placement

1. Phase 2 before compose: sample A-roll → face detect → write `04_phase2/segments/NN/framing-plan.json`.
2. Render: apply `scale+crop` from plan on A-roll.
3. Caption ASS uses `\pos` from face on a framed still (or measured face after crop).
4. `visual_audit`: random + MOTION probes + **face/caption overlap** check.

## Out of scope v1

- Author picking among crop variants (auto-only per author decision 2026-07-20).
- Tracking face every frame (median of samples is enough for talking-head static camera).

## Lessons (learning loop)

Full symptom → cause → fix log: `docs/learning/2026-07-20-framing-face-captions.md`.  
Process: `docs/product/LEARNING_LOOP.md`.
