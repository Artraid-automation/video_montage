# Asya — longform captions still too small at 0.09

**Date:** 2026-07-22  
**Project:** `projects/asya-reel-pilot`

## Symptom

Author: on widescreen, body captions still look tiny (even after “×2” to `caption_font_ratio=0.09` / ~97px).

## Wrong assumption

Doubling the vertical-reel MeVGa ratio (0.045→0.09) is enough on 1920×1080. On 16:9 the subject is only a left third — absolute px that feel big on 9:16 still read small against the wide canvas.

## Fix

- `caption_font_ratio: 0.15` (~162px on 1080p); `CAPTION_MAX_FONT_RATIO` → 0.18.
- Hook stays `max(0.072, body×1.25)` so it remains larger than body.

## Guardrail

For longform left-third talking-head, judge caption size on Gate2 probe JPGs against torso/face — not only vs the vertical-reel ratio. Prefer project `caption_font_ratio` ≥0.12 on 16:9 when author wants Reels-like presence.
