# Subtitle preset — dankoe-gold-serif

Status: draft v1 · tied to `presets/styles/ref-MeVGaMG28nc.md`

## Visual

| Param | Value |
|-------|--------|
| Font | Classic serif (closest available in Resolve; prefer Garamond/Times Bold) |
| Size | start ~64–84 px at 1080 width; tune on first export |
| Color | `#E1C445` |
| Style | Regular/Bold; optional slight italic |
| Case | lowercase (post-process transcript) |
| Align | Center |
| Position | Center X; Y ≈ 50–55% from top |
| Stroke | black, ~2–4 px equivalent |
| Shadow | soft black, low opacity, small offset (if stroke alone weak) |
| Max words on screen | 6 |
| Max lines | 2 |

## Timing

- Source: word-level transcript (whisper) → merge to phrases on punctuation / pause >350ms / max 6 words
- In: hard cut (no long fade)
- Out: hard cut to next phrase
- Lead/lag: 0–80ms vs speech start (tune in run logs)

## MCP notes

- Free Resolve: Text+ insert works; Fusion styling may need manual pass once, then save as preset/template
- When atom `020-transcribe-timeline` lands, this preset is the default style target
- Hex → Resolve: convert to 0–1 RGB in tool calls (`#E1C445` → R 0.882, G 0.769, B 0.271)

## Acceptance check

- [ ] Readable on light shirt
- [ ] Not covered by Shorts UI (bottom right / bottom bar)
- [ ] Feels gold-serif, not yellow-sans TikTok default
