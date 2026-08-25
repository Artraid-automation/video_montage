# Asya — drop opening MOTION + 2× body captions

**Date:** 2026-07-22  
**Project:** `projects/asya-reel-pilot`

## Symptom

Author at FINAL_REVIEW: remove the first MOTION at cold open; body subtitles too small — need ~2× size.

## Fix

- Removed MOTION `1a` from `transcript.md` + `visual-plan.json` (kept `hook_title` on u0006).
- `project.json` `render_profile.caption_font_ratio: 0.09` (2× default 0.045); hook auto `max(0.072, body×1.25)`.
- `CAPTION_MAX_FONT_RATIO` raised to 0.10 so policy accepts the override.
- Wider torso wrap envelope for large type (`face×2.2`, frame ≤42%).

## Guardrail

Per-project `caption_font_ratio` in `render_profile` — do not silently 2× the global MeVGa body target for all formats.
