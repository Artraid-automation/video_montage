# Asya longform — preserve 16:9 composition

**Date:** 2026-07-22  
**Project:** `projects/asya-reel-pilot`

## Symptom

Author: new project is **widescreen**, not vertical; frame must respect picture composition (speaker left, brand right).

## Wrong assumption

Reels framing (face-center crop into 9:16) applies the same way to longform.

## Root cause

Source `01_camera.mp4` is already **1280×720 16:9**. Speaker sits on the **left third**; **X10** plate is intentional negative space on the right. Face-centering would destroy that layout when spare crop room exists.

## Fix

- Profile: `longform-16x9` → delivery **1920×1080** (no 9:16).
- Framing: when scaled size fills output (`spare_x/y ≤ 2`), `composition_mode=preserve-source` — scale only, no face-center crop.
- Captions: `caption_pos_x` follows face center (chest under speaker), not dead frame center.

## Guardrail

- `pipeline/factory/framing.py`: preserve-source branch + under-face caption X.
- Project `framing.notes` / `02_inputs/style.md`: do not crop out X10 for “face in center”.
