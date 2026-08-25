# Analysis — MeVGaMG28nc

Source: `source/MeVGaMG28nc.mp4`  
Duration: **51.3s** · Format: **1080×1920** · FPS: **24**  
Frames sampled: `frames/frame_001.jpg` … `frame_010.jpg` (every ~5s)  
Color samples: PIL on caption band (2026-07-16)

## 1. Narrative skeleton

| Beat | Approx | What happens |
|------|--------|----------------|
| Hook title | 0–5s | Full-screen title over talking head: *How To Achieve Anything You Want In Life* |
| Framework list | ~5–15s | Dark blurred BG + numbered 4-step list; active line bright, others dim |
| Body VO + captions | ~15–45s | Talking head, phrase-by-phrase yellow serif captions |
| Close | ~45–51s | Continues same caption language (no hard CTA card observed in samples) |

Core message pattern: **authority hook → numbered system → talking-head proof with caption hits**.

## 2. Edit rhythm

- Density: **medium-high** on captions (phrase chunks, not full sentences on screen)
- Camera: mostly **locked** medium close-up; energy from gestures + caption timing
- Pattern: `title card → list reveal → talking head + captions`
- Shot length: single A-roll camera; “cuts” are mostly **graphic mode changes**, not hard camera cuts
- Punch-ins: not dominant in sampled frames (no heavy digital zoom language)

## 3. Typography

### 3.1 Hook title (frame_001)

| Param | Value |
|-------|--------|
| Role | Hero title |
| Face | Bold **italic serif** (Times/Garamond family feel) |
| Case | Title Case |
| Color | **#EAC225** (sampled avg; peaks ~#F4C404) |
| Stroke | none / negligible |
| Align | center |
| Position | mid-frame over chest |
| Layout | 4 stacked lines, large |

### 3.2 Captions / VO sync (frames 003–010)

| Param | Value |
|-------|--------|
| Role | Phrase captions |
| Face | Classic **serif** (same family as title, upright or slight italic) |
| Case | **lowercase** preferred |
| Color | **#E1C445** (sampled avg captions) |
| Contrast aid | thin **black stroke** and/or soft drop shadow |
| Align | center |
| Position Y | **lower-middle** (~45–55% height), over chest — above platform UI |
| Chunking | short phrases (3–6 words), pop-on |

Examples from frames:  
`don't know what they want` · `for multiple years.` · `is very painful.` · `Most people don't build.` · `only to get that` · `But when that flatlines,` · `when they fail,` · `between their lower self`

### 3.3 Numbered list mode (frame_002)

| Param | Value |
|-------|--------|
| Face | Serif, centered stack |
| Active line | **#FFFFFF**, full opacity (+ soft glow/shadow) |
| Inactive lines | dark gray, **~20–35% opacity** |
| BG treatment | heavy darken + blur of A-roll under text |
| Behavior | spotlight: one line bright, previous dim |

List content in ref:

1. A clear vision  
2. Daily learning  
3. Daily building  
4. Persistence & iteration  

## 4. Color / grade

| Token | Approx | Notes |
|-------|--------|-------|
| Caption gold | `#E1C445` | primary text |
| Title gold | `#EAC225` | slightly hotter |
| Active list | `#FFFFFF` | |
| Dim list | `#666666` @ ~30% | |
| Key light | warm/neutral on face L | |
| Rim | cool **blue/purple** on R shoulder/ear | separation |
| BG | split light wall L / deep shadow R | minimalist |
| Grade | cool shadows, natural skin, muted midtones | cinematic talking-head |

## 5. Motion / effects

| Effect | Present? | Notes for MCP v0 |
|--------|----------|------------------|
| Phrase pop-on captions | yes | primary motion language |
| List spotlight | yes | can be multi-layer Text+ or Fusion later |
| Hard transitions / whip | no (sampled) | skip in v0 |
| Punch-in zoom | rare/absent | optional later |
| Stickers/emojis | no | ignore |
| BG blur+dark for list | yes | Resolve: blur + exposure or duplicate+blur track |

## 6. Audio

- Clear dry VO / podcast mic aesthetic (SM7B-style in frame — visual brand cue, not required to copy prop)
- Music bed likely low under VO (needs ear-pass; not measured yet)
- Caption hits sync to speech phrases, not beat grid

## 7. Reuse vs ignore

**Reuse (style system):**

- 9:16 talking-head framing  
- Gold serif captions, lowercase, chest band  
- Hook title card (italic gold serif)  
- Optional numbered-list “spotlight” chapter beat  
- Cool rim / moody grade language (approximate, not 1:1 light setup)

**Ignore:**

- Exact script / personal brand of creator  
- Mic/keyboard as mandatory props  
- Pixel-perfect font file (use closest system/Resolve serif until we pick a licensed face)

## 8. Implications for our footage

Our assets: A-roll mp4 + separate m4a.  
Pipeline should: ingest → 9:16 center → sync audio if needed → rough cut → whisper phrases → apply `presets/subtitles/dankoe-gold-serif.md` → optional title + list cards from style pack → export.
