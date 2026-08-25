# Asya — captions must track the torso, not a static median

**Date:** 2026-07-22  
**Project:** `projects/asya-reel-pilot`

## Symptom

Author: gold captions sit on the left chest / necklace; left edge sticks past the body into brick, right edge ends on the arm — looks shifted left, not symmetric on the torso.

## Wrong assumption

1. Face-box geometric center + fixed segment `caption_pos` is “chest center” for the whole cut.
2. Wide ASS wrap (28 chars) is fine as long as `\an8\pos` is centered.
3. `\an5` mid-anchor would fix vertical neck overlap (it put half the block *on* the necklace).
4. Hook title can reuse mid-clip face sample even when the title burns at t≈0.

## Root cause

- Longform `preserve-source` keeps one crop; speaker still walks L/R. Median framing caption X (~802) lags later faces (~880–950) → text sits on the old left chest while the body moved right.
- Phrase width (~400px) exceeded shoulder envelope (~face×1.75) → even a correct center looks left-heavy (bg overhang left, sleeve on the right).
- Hook/title used mid-clip face + small gap → first lines on necklace / wrong X at open.

## Fix

- Per-KEEP `caption_layout_at_timestamp` (body = mid clip; hook_title = near clip start).
- Torso X ratio 0.78 (sternum/buttons right of YuNet face-cx); wrap budget + 2-word beats + up to 3 lines when narrow.
- `\an8` below necklace (15% gap, chest band ≥62%); hook shares live chest X.
- Worker `ffmpeg-overlay-v19-chest-track`.

## Evidence (Gate2 probes, gold ink below necklace only)

- `caption-gap-01-8.040`: gold_cx≈903 vs buttons≈868, width≈175, clear≈224px under chin.
- `key-mid-25.258`: width≈243 (was ~430); clear≈228px; residual ~40px left of buttons on long KEEP = within-clip walk.
- QC / visual_audit: PASS.

## Guardrail

On preserve-source 16:9, never burn one segment-wide caption X. Refresh chest layout per KEEP (hook samples start). After visual fixes, measure gold bbox **excluding necklace HSV** vs vest buttons on Gate2 JPGs before claiming OK.
