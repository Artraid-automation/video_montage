# Asya — captions/motion share one chest X

**Date:** 2026-07-22  
**Project:** `projects/asya-reel-pilot`

## Symptom

Author: body captions wander left/right; MOTION sits on a different horizontal axis — eye jumps.

## Wrong assumption

Frame-center (`width/2`) is fine for motion/hook while captions use face X; ASS `\an8` top-anchor is stable enough for phrase length changes.

## Root cause

- Longform speaker is left-third (`caption_pos_x≈792`); motion/hook were drawn at frame center (~960).
- ASS `\an8\pos` pins the **top** of the text — short vs wrapped phrases look like they drift.
- Motion pill used left-edge text draw inside a wide box → empty right side.

## Fix

- Captions: `\an5\pos` (middle-center) on framing chest point.
- Motion + hook_title: `center_x=caption_pos_x` from framing plan; pill text `anchor=mm`.
- Motion font/pad sized from **height** (not width) — on 1920×1080, `width//12` made a giant bar.
- Cache key includes `MOTION_WORKER_VERSION` (`motion-dynamic-v5-height-font`).

## Guardrail

On off-center 16:9 talking-head, **one layout axis**: captions, MOTION, hook_title all share framing `caption_pos_x`. Never size motion type from frame **width** alone on longform.