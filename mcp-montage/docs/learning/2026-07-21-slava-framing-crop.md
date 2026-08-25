# 2026-07-21 — Slava Gate 2: framing over-zoom crops head (author catch)

## Symptom
Rendered 9:16 video cuts left half of head and top of head — «нет профессионального кадра».

## Wrong assumption
`compute_framing_plan` zoom formula (`headroom_scale`) properly handles 720p landscape source → 9:16 crop.

## Root cause
Source: 1280×720, face ~200px tall (28% of 720). `headroom_scale` formula pushed zoom to 2.0× (above cover 1.778×) to place the crown at `HEADROOM_TARGET=0.10`. At 2× zoom, scaled image is 2570×1446, and the 720×1280 crop window can't contain both the centered face and the head edges.

Specifically:
- `headroom_scale = out_h * 0.9 / (src_h - crown_y) = 1280 * 0.9 / (720 - 146) = 2.007`
- This exceeds `cover = 1.778`, causing over-zoom
- The face is already big enough (28% of source height) — zooming past cover pushes head edges out of frame

In the MeVGa reference, the face fills ~25–30% of 9:16 height, centered horizontally with visible shoulders — our 2× zoom broke this.

## Fix
`framing.py`: when `source_face_ratio >= 0.18` (face already fills ≥18% of source), cap `max_face_scale = cover`. Only zoom past cover when the face is small and needs filling.

Result: scale drops to 1.778 (cover-only), face L=182 R=538 centered in 720px, headroom 25%, full head+shoulders visible.

## Guardrail
- `test_framing.py` passes (existing geometry tests)
- Re-render Phase 2; check gate2-audit probes for full head visibility
- Framing-plan samples should be checked: if ≥50% of samples have `face: null`, the detector is unreliable on that source and crop may be wrong
- Gate 2 now blocks on deterministic `key-start` / `key-mid` / `key-end` probes plus 5 seeded random probes
- Composition is now a hard check on probe JPGs: face must keep >=24 px from frame edges, stay within 12% of horizontal center, and keep headroom >=4%

## Evidence
- Before: `framing-plan.json` `scale: 2.008`, `crop_x: 1032`, face `predicted.face_height_ratio: 0.125` (wrong — Haar detection noise)
- After: `scale: 1.778`, face properly centered, `face_height_ratio: 0.278`
- Probe JPGs: `random-02-74.236.jpg` shows left-half-of-head cropped
- `docs/learning/2026-07-21-slava-framing-crop.md` (this file)

## Rule candidate
If face is ≥18% of source height, do not zoom past cover. This is a heuristic for "face already big enough" — prevents the headroom formula from over-zooming on low-res sources where the subject fills the frame.

## Follow-up proof (v1 — audit catches the problem)
After adding composition audit, the same Slava render stopped at Gate 2 with:
- `key[mid]: face horizontally off-center (offset_ratio=0.350 > 0.120)`
- `key[end]: face horizontally off-center (offset_ratio=0.134 > 0.120)`

This is the desired behavior: the system now blocks the shot before author review instead of asking the author to discover the miss manually.

## Follow-up proof (v2 — root cause found and fixed)

**Symptom:** After multiple numeric adjustments (tolerance ratios, anchor logic, median vs scored face), the head was STILL cropped on the left. The author explicitly asked: "go do research on how to frame a shot, use visual references like Dan Koe."

**Root cause:** Haar cascade (`haarcascade_frontalface_default.xml`) was returning **false positive face boxes** on the source footage. On sample-09 (66.74s), Haar strict returned `x=683, w=200` — a 200px box positioned far to the right of the actual face. The real face center was at `cx_ratio ~0.41-0.45` (Yunet), but Haar reported `cx_ratio=0.61`. This caused `crop_x=1032` instead of the correct `crop_x=666`, shifting the crop 366px to the right and cutting the head off the left edge.

All previous "fixes" (median vs anchor, tolerance ratios, max_face_scale cap) were treating **symptoms of a wrong detector**, not the root cause.

**Fix:** Replaced Haar cascade with OpenCV Yunet DNN face detector (`face_detection_yunet_2023mar.onnx`) as primary detector, with Haar as fallback. Yunet returns accurate face bounding boxes with confidence scores >0.87 on all test frames.

**Evidence:**
| Frame | Haar cx (strict) | Yunet cx | Correct? |
|-------|------------------|----------|----------|
| 52.52s | no detection | 0.45 | Yunet |
| 53.77s | 0.50 | 0.45 | Yunet (more stable) |
| 66.74s | **0.61** | 0.41 | Yunet (Haar was FALSE POSITIVE) |
| 67.72s | 0.54 | 0.38 | Yunet |
| 69.88s | no detection | 0.46 | Yunet |

Result: `crop_x` changed from 1032 to 666. Face centered at x=361 vs frame center 360.

**Lesson:** When composition looks wrong despite "correct" math, the input data (face detection) may be wrong. Do not trust Haar cascade for production framing — use a DNN-based detector (Yunet, MediaPipe, or similar). Numeric parameter tuning cannot fix garbage-in from a fundamentally unreliable detector.
