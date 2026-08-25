# Longform 16:9 — caption size lock (author OK)

**Date:** 2026-07-22  
**Project:** `projects/asya-reel-pilot`

## Decision

Author: body captions at `caption_font_ratio: 0.15` (~162px on 1080p) look good on widescreen left-third talking-head. Lock this as the longform default.

## Wrong assumption (prior)

Vertical-reel MeVGa ratio `0.045` (or even `0.09`) reads tiny on 1920×1080 because the speaker only occupies the left third.

## Fix / lock

- Profile `presets/profiles/longform-16x9.json` → `render_profile.caption_font_ratio: 0.15`
- Project `asya-reel-pilot` already uses the same value
- Reels `9:16` keeps the smaller default (`0.045`) unless overridden

## Guardrail

Do not shrink longform body captions back toward the vertical-reel ratio without a new author pass on Gate2 probe JPGs.
