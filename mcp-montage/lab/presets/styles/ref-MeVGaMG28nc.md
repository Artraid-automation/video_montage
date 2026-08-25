# Style pack — ref MeVGaMG28nc

Status: **v1 draft from frames** · 2026-07-16  
Source analysis: `references/MeVGaMG28nc/analysis.md`

## Identity (one sentence)

Moody talking-head Short: **gold classic serif type** over cool cinematic portrait, with optional **spotlight numbered list** chapter.

## Tokens

```
format: 1080x1920
fps_target: 24
safe_caption_y: 0.48..0.58   # normalized frame height center of text
caption_color: #E1C445
title_color: #EAC225
list_active: #FFFFFF
list_dim: #666666
list_dim_opacity: 0.30
stroke: black thin OR soft drop shadow
font_family_intent: classic serif (Times / Garamond class)
caption_case: lowercase
title_case: Title Case
```

## Modes

### Mode A — Hook title

- Italic bold serif, gold `#EAC225`
- 3–5 short lines, centered, mid chest
- No heavy stroke
- Hold ~2–4s over live A-roll

### Mode B — Framework list

- Duplicate A-roll under: blur + darken hard
- 3–6 numbered lines, serif, centered
- Animate spotlight: active white, others dim
- One idea per beat (~1–2s per line)

### Mode C — Talking captions (default body)

- Phrase chunks 3–6 words
- Gold `#E1C445`, serif, lowercase
- Thin black stroke / shadow
- Center X, Y ~ mid-chest
- Pop-on on phrase boundaries from transcript

## Grade intent (approximate)

- Keep skin natural
- Cool/blueish shadows, muted greens
- Protect highlight on face
- Do **not** crush to pure black on shirt if captions need contrast — rely on stroke

## Resolve mapping (v0)

| Style need | Resolve approach |
|------------|------------------|
| Captions | Text+ or subtitle track + Fusion title later |
| Title card | Text+ generator on V2 |
| List card | stacked Text+ or single Fusion comp (manual if API weak) |
| List BG | compound clip / blur+gain on underlay |
| Grade | Color page primary wheels; save still when happy → `presets/resolve/` |

Exact Fusion node graphs TBD in atoms after first successful build.

## Do / Don't

**Do:** short phrases, gold serif, chest band, one accent system (list OR punch-in, not both every second).  
**Don't:** emoji spam, thick white TikTok sans, rainbow word highlights, top-of-frame titles under notch/UI.
