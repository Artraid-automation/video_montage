# REEL_v001 End-to-End Implementation Plan

> **For agentic workers:** Execute this plan inline in one session after a single observer OK. Do not stop for micro-approvals. On failures: diagnose → fix/fallback → log in `lab/experiments/` + `lab/runs/` → continue. Stop only if Resolve/bridge dead or destructive action needs human.

**Goal:** Собрать готовый вертикальный рилс `reel_v001.mp4` из наших исходников в стиле референса MeVGaMG28nc (gold serif captions + hook title + optional list), экспорт в `06_exports/v001/`.

**Architecture:** Research уже сделан (style pack). Дальше: probe → ingest в Resolve Free через MCP CursorBridge → sync/audio → whisper transcript → editorial cut ~40–55s → 9:16 reframing → titles/captions по пресетам → лёгкий grade → render → запись atoms/run.

**Tech Stack:** DaVinci Resolve Free 21 + CursorBridge MCP · ffmpeg/ffprobe · faster-whisper (local) · lab presets `ref-MeVGaMG28nc` / `dankoe-gold-serif`

## Glossary (что значили прошлые слова)

| Термин | Смысл |
|--------|--------|
| **Ingest** | Импорт медиа в Media Pool Resolve + базовая раскладка на timeline |
| **Rough cut** | Черновая склейка смысла: вырезать воду, оставить хук→тело→punch, без полировки |
| **Fine cut / polish** | Стиль, субтитры, title/list, grade, мелкий ритм |
| **Export** | Рендер финального файла |

## Global Constraints

- Resolve **Free** (нет Studio Neural Engine subtitles; использовать `transcribe_file` / `transcribe_timeline`)
- CursorBridge должен быть running (`get_resolve_status.connected == true`)
- Style source of truth: `lab/presets/styles/ref-MeVGaMG28nc.md`, captions: `lab/presets/subtitles/dankoe-gold-serif.md`
- Target: **1080×1920**, ~**40–55s** (реф 51.3s), не полный сырец ~327s
- Source A-roll сейчас **1280×720 landscape** → обязательный center/face crop+zoom в 9:16
- Отдельный `03_audio/*.m4a` (~337s) чуть длиннее видео (~327s) — prefer отдельный audio если качество лучше; sync по старту, при рассинхроне >120ms → fallback на embedded AAC
- Техрешения агент принимает сам; наблюдатель оккает **только этот план целиком**, потом смотрит экспорт
- Кириллические пути: все MCP `file_paths` передавать как абсолютные Windows paths, найденные через `pathlib` (не копипаст из кракозябр консоли)
- После каждого нового приёма — atom в `lab/atoms/`; прогон — `lab/runs/0003-...`
- Не удалять media/project без явного стопа наблюдателя

## Known assets (locked)

```
FOOTAGE = <project>/01_footage/video_2026-07-16_18-04-55.mp4
  codec h264, 1280x720, ~327.2s, embedded aac
AUDIO   = <project>/03_audio/*.m4a
  aac stereo 48kHz, ~336.8s
EXPORT  = <project>/06_exports/v001/reel_v001.mp4
TIMELINE= REEL_v001
PROJECT bin work in Resolve (create/open project name: reel_dankoe_v001 if none)
```

Project FS root (UTF-8): under workspace `рилс/` / `прокты/` (exact folder via rglob on footage filename).

## File map (lab outputs this run)

| Path | Role |
|------|------|
| `lab/plans/2026-07-16-reel-v001-end-to-end.md` | this plan |
| `lab/runs/0003-YYYYMMDD-reel-v001-build.md` | execution log |
| `lab/source-map/current.md` | update paths/probe |
| `lab/05` equivalent notes in project `05_project/transcripts/v001.json` | whisper segments |
| `lab/05_project` via reel folder `05_project/edit/v001-cutlist.json` | keep/cut ranges |
| `lab/atoms/010-bridge-status.md` … as proven | atoms |
| `lab/presets/styles/ref-MeVGaMG28nc.md` | already exists |
| `lab/presets/subtitles/dankoe-gold-serif.md` | already exists |
| `<reel>/06_exports/v001/reel_v001.mp4` | deliverable |
| `<reel>/06_exports/v001/reel_v001_review.jpg` | optional poster frame |

---

### Task 0: Session gate + source-map refresh

**Files:**
- Modify: `lab/source-map/current.md`
- Create: `lab/runs/0003-2026-07-16-reel-v001-build.md` (start as pending)

**Produces:** confirmed bridge + absolute paths + media probe table in source-map

- [ ] **Step 1:** `get_resolve_status` → must be `{connected: true}`. If not: start CursorBridge instruction once in run log and retry; if still down — STOP (human).
- [ ] **Step 2:** Resolve absolute paths via Python `Path.rglob('video_2026-07-16_18-04-55.mp4')` and sibling `03_audio/*.m4a`.
- [ ] **Step 3:** ffprobe both; write width/height/duration/fps/audio into `source-map/current.md`.
- [ ] **Step 4:** `get_project_info`. If no usable project: `create_project` name `reel_dankoe_v001` (or load existing if already there).
- [ ] **Step 5:** Open Edit page if tool exists / note current page.

**Done when:** bridge OK, project open, source-map has absolute paths.

---

### Task 1: Deps for local transcription

**Files:**
- Modify: MCP venv at `E:\davinci-resolve-mcp\venv` (or active MCP python)
- Create: `lab/atoms/020-transcribe-file.md` (after first success)

**Produces:** `faster-whisper` importable by MCP server python

- [ ] **Step 1:** In MCP venv: `pip install faster-whisper soundfile` (and torch CPU if pulled as dep).
- [ ] **Step 2:** Smoke: `python -c "from faster_whisper import WhisperModel; print('ok')"`.
- [ ] **Step 3:** If MCP server was started before install — note in run log that Cursor may need MCP restart; try tool anyway.

**Done when:** whisper import works. On fail: retry with `model_size=base` later; document experiment.

---

### Task 2: Ingest media into Resolve

**Files:**
- Create atom: `lab/atoms/030-import-media.md` after success

**MCP:** `import_media`, `get_media_pool`, `create_folder` if available

- [ ] **Step 1:** Ensure media pool folder `v001_ingest` (create if tool allows; else root).
- [ ] **Step 2:** `import_media(file_paths=[FOOTAGE, AUDIO])`.
- [ ] **Step 3:** `get_media_pool` / structure — confirm both clips present by name.
- [ ] **Step 4:** Log clip names/ids in run file.

**Done when:** both assets visible in pool. Fallback: import footage only if audio path fails unicode; then use embedded audio.

---

### Task 3: Create timeline + place A-roll

**MCP:** `create_timeline`, `switch_timeline`, `append_to_timeline` / `insert_to_timeline`, `get_timeline_info`, `set_timeline_setting`, `set_clip_properties`

**Decisions locked:**
- Timeline name: `REEL_v001`
- Timeline format target: 1080×1920, 25fps (source ~25fps) if settings API allows; else project default + scale in clip
- Place full A-roll on V1 first (will cut later)

- [ ] **Step 1:** `create_timeline(name="REEL_v001")` + `switch_timeline`.
- [ ] **Step 2:** Set timeline resolution to 1080×1920 if `set_timeline_setting` supports it; else document and compensate with Zoom/Crop.
- [ ] **Step 3:** Append footage to timeline V1.
- [ ] **Step 4:** If separate audio used: put on A1, mute embedded if dual; else keep embedded.
- [ ] **Step 5:** `get_timeline_clips` + `get_timeline_info` — verify duration ≈327s.

**Done when:** REEL_v001 plays with picture+sound.

---

### Task 4: Transcribe (before cut)

**Why before cut:** cut decisions from words, not vibes.

**MCP:** `transcribe_file` on AUDIO (prefer) or FOOTAGE  
**Params locked:** `model_size="small"`, `language="ru"` if speech is Russian else `""` auto. First try auto; if garbage → force `ru` or `en` based on sample.

**Files:**
- Write: `<reel>/05_project/transcripts/v001_whisper.json` (segments with start/end/text)
- Write: `<reel>/05_project/transcripts/v001_whisper.txt` (readable)
- Atom: `lab/atoms/020-transcribe-file.md`

- [ ] **Step 1:** Call `transcribe_file`.
- [ ] **Step 2:** Persist JSON+TXT to `05_project/transcripts/`.
- [ ] **Step 3:** Summarize in run log: duration covered, language, first/last 3 segments.
- [ ] **Step 4:** If tool missing deps — install (Task 1) and retry; if still fail — ffmpeg extract wav 16k mono → retry; last resort offline note + STOP for human audio check.

**Done when:** segment list on disk with timestamps.

---

### Task 5: Editorial plan (cutlist) — rough cut design

**No Resolve writes yet — pure file.**

**Files:**
- Create: `<reel>/05_project/edit/v001-cutlist.json`
- Create: `<reel>/05_project/edit/v001-narrative.md`

**Locked editorial targets:**
- Final length **40–55s**
- Structure mirrored from ref:
  1. Hook title 2–4s (Mode A)
  2. Optional framework list 6–10s (Mode B) **only if** transcript naturally has 3–5 pillars; else skip list (do not invent fake Dan Koe list)
  3. Body captions Mode C for remaining time
- Cut rule: remove long pauses (>0.7s), repeats, prep talk, “эээ”, false starts; keep strongest claim sentences
- Prefer earliest strong hook line for open

**cutlist.json schema:**

```json
{
  "target_duration_s": 48,
  "fps": 25,
  "keeps": [
    {"start_s": 12.4, "end_s": 18.1, "role": "hook_vo", "note": "..."}
  ],
  "title": {"text": ["Line1", "Line2"], "hold_s": 3.0},
  "list": null,
  "caption_style": "dankoe-gold-serif"
}
```

- [ ] **Step 1:** Read transcript; mark keep ranges totaling ~45–50s.
- [ ] **Step 2:** Write narrative.md (hook / body / close in 5–8 bullets).
- [ ] **Step 3:** Write cutlist.json.
- [ ] **Step 4:** Self-check: sum(keeps) within 40–55s; each keep has role.

**Done when:** cutlist on disk. This is the rough-cut plan.

---

### Task 6: Apply rough cut on timeline

**MCP:** timeline markers + delete/ripple OR rebuild timeline from keeps  
**Preferred strategy (locked):** rebuild clean timeline `REEL_v001` (or `REEL_v001_cut`): for each keep range, append subclip / insert with in-out if API supports; else full clip + `delete_timeline_clips` / trim via available tools; if trim API weak — use markers + ffmpeg pre-cut masters then re-ingest.

**Fallback ladder:**
1. Native Resolve trim/delete via MCP
2. ffmpeg extract keep segments → concat → reimport as `v001_rough.mp4` → new timeline
3. Log experiment `lab/experiments/YYYYMMDD-roughcut-fallback-ffmpeg.md`

- [ ] **Step 1:** Try MCP-native cut from cutlist.
- [ ] **Step 2:** Verify `get_timeline_info` duration in 40–55s (±3s).
- [ ] **Step 3:** If out of band — adjust cutlist once and re-apply.
- [ ] **Step 4:** Atom `lab/atoms/040-rough-cut.md` with winning method.

**Done when:** timeline duration in target band with continuous audio.

---

### Task 7: Reframe to 9:16

**MCP:** `set_clip_properties` Zoom/Pan/Tilt/Crop/Scaling  
**Locked approach:** Scaling Fill or Zoom ~1.5–1.8 on 1280×720 into 1080×1920; Pan/Tilt to keep face centered (use thumbnail/`get_clip_thumbnail` if available to sanity-check).

- [ ] **Step 1:** Ensure timeline is 1080×1920 (or export will letterbox — fix settings).
- [ ] **Step 2:** For each V1 clip: set Zoom/Pan so headroom ~safe for Shorts UI.
- [ ] **Step 3:** Grab thumbnails at 10%/50%/90% — visual check (Read images).
- [ ] **Step 4:** Atom `lab/atoms/050-reframe-9x16.md`.

**Done when:** no horizontal bars; face not cropped at chin/forehead badly.

---

### Task 8: Hook title (Mode A)

**MCP:** `insert_title` Text+ on V2, set text/color if tools allow; else Text+ + manual property tools  
**Content:** from cutlist.title (derived from strongest hook line / project theme «как добиться всего…») — **Title Case**, gold `#EAC225` → RGB 0.918, 0.761, 0.145  
**Hold:** first 2.5–3.5s of timeline

- [ ] **Step 1:** Insert Text+ at start spanning hold_s.
- [ ] **Step 2:** Apply font serif if selectable; color/size/align center mid-chest.
- [ ] **Step 3:** If API cannot set styled text: create plain Text+ + write exact manual fallback steps in atom; still leave placeholder text correct.
- [ ] **Step 4:** Atom `lab/atoms/060-hook-title.md`.

**Done when:** title present on V2 over open.

---

### Task 9: Optional list (Mode B)

- [ ] **Step 1:** If `cutlist.list` is null → skip; note in run log.
- [ ] **Step 2:** Else: darken/blur underlay (duplicate V1 segment or opacity) + stacked Text+ lines; active/dim approximate if animation API missing (static all-white list acceptable for v001).
- [ ] **Step 3:** Atom `lab/atoms/070-framework-list.md` or experiment `skip-list`.

**Done when:** either list on timeline or explicit skip logged.

---

### Task 10: Captions (Mode C)

**MCP:** after transcript aligned to cut timeline — either:
- regenerate captions for cut media via `transcribe_timeline`, or
- remap original segments through cutlist offsets

**Then place phrases:**
- Prefer subtitle track / Text+ per phrase (whichever MCP supports stably)
- Style: `dankoe-gold-serif` — `#E1C445` → RGB 0.882, 0.769, 0.271; lowercase; ≤6 words; Y≈0.52

**Fallback ladder:**
1. Native subtitle clips via MCP
2. Batch Text+ titles per phrase
3. Generate `.srt` into `05_project/transcripts/v001.srt` + import if tool exists; else deliver SRT + burn-in via ffmpeg for export-only captions

- [ ] **Step 1:** Build phrase list JSON `v001_captions.json` (start/end/text).
- [ ] **Step 2:** Apply to timeline with best available method.
- [ ] **Step 3:** Spot-check 5 random phrases vs audio.
- [ ] **Step 4:** Atom `lab/atoms/080-captions-gold-serif.md`.

**Done when:** captions cover ≥90% spoken words on final cut.

---

### Task 11: Light polish

**Scope v001 (locked minimal):**
- Cool shadows / slight contrast if color API easy; else skip grade (captions+crop carry style)
- No Fusion fireworks
- Markers only if useful for human

- [ ] **Step 1:** Attempt mild color match to ref intent; 10 min max effort.
- [ ] **Step 2:** Audio levels: VO clear, no clip; music none unless already in source.
- [ ] **Step 3:** Playhead scrub checklist: hook / body / end.

**Done when:** no obvious technical defects (black frames, silence holes, huge letterboxing).

---

### Task 12: Export deliverable

**MCP:** render settings + add job + start render · or `quick_export`  
**Locked output:**
- Path: `<reel>/06_exports/v001/reel_v001.mp4`
- 1080×1920, H.264, AAC
- Filename exactly `reel_v001.mp4`

- [ ] **Step 1:** Create `06_exports/v001/` folder on disk.
- [ ] **Step 2:** Configure render + queue + start.
- [ ] **Step 3:** Poll `get_render_job_status` until complete (timeout 30 min).
- [ ] **Step 4:** ffprobe export — assert 1080x1920 and duration 40–55s.
- [ ] **Step 5:** Extract 3 review frames to `06_exports/v001/review/`.

**Fallback:** if Resolve render API fails → ffmpeg export from a bounced timeline file / or Media Out workaround documented; last resort: render timeline section via ffmpeg from cut master + overlay SRT (`subtitles=` filter) to still ship mp4.

**Done when:** `reel_v001.mp4` exists and probes clean.

---

### Task 13: Close the loop in lab

- [ ] **Step 1:** Finish `lab/runs/0003-...` with Result ok/fail/mixed + learnings.
- [ ] **Step 2:** Update `lab/pipelines/reel-from-footage-v0.md` → mark which atoms became proven; bump to v0.1 notes.
- [ ] **Step 3:** Update `lab/source-map/current.md` export path.
- [ ] **Step 4:** One-paragraph observer summary: where file is, duration, what matched ref, what is still weak.

**Done when:** lab reflects reality of the build.

---

## Execution policy (after observer OK)

1. Run Tasks 0→13 in order in **this chat**, inline.
2. No asking “делать Task N?” — only report blockers that need a human hand (Resolve closed, disk full, bridge dead).
3. Every failure → fallback ladder in that task → `lab/experiments/` note → continue.
4. Do not start Task 12 export until Task 10 captions attempted (even if captions fallback to SRT burn-in).
5. Taste pass is observer’s after export; agent does not wait mid-build for taste.

## Definition of Done (ship)

- [x] Plan written
- [ ] `reel_v001.mp4` at exports path
- [ ] Duration 40–55s, 1080×1920
- [ ] Gold-serif captions visible
- [ ] Hook title present (or documented API blocker + ffmpeg title burn-in)
- [ ] Run 0003 + atoms updated

## Observer OK gate

Наблюдатель отвечает одним словом **«ок»** / **«делай»** — после этого агент выполняет план целиком.
