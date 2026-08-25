# Design: conditional Dan Koe style pack (MeVGaMG28nc)

Status: **draft for author review** · 2026-07-20 (rev: searchable library catalog)  
Reference short: https://youtube.com/shorts/MeVGaMG28nc  
Lab seeds: `lab/presets/styles/ref-MeVGaMG28nc.md`, `lab/presets/subtitles/dankoe-gold-serif.md`, `lab/references/MeVGaMG28nc/analysis.md`  
Process reference (Brian architecture): `docs/product/REFERENCE_SYSTEM.md`

## Problem

Phase 2 currently burns generic white bottom captions and does not apply the reference look. Lab already extracted the Dan Koe look, but it is not a **searchable recipe library** wired into Gate 1 proposals or Gate 2 QC.

Author requirement:

1. **Extract and save** visual recipes from the reference (what happens on screen).
2. Attach **broad, searchable criteria**: tags + situations when each is appropriate.
3. Later **pull from the library by search/tags**, not by memorizing cryptic mode ids.
4. Apply a recipe **only when content matches** — never “one style for the whole video.”

## Goals

1. Product **style library** (versioned): each recipe is a catalog card, not just a render preset.
2. Cards are **searchable** (tags, situations, keywords, “what happens”).
3. Gate 1 agent/producer **retrieves** candidates from the library, then proposes which fit which KEEP.
4. Compositor renders the chosen recipe; Gate 2 QC checks the render contract.
5. Default path never invents title cards or blurred lists “for style.”

## Non-goals

- Pixel-perfect font licensing / custom OTF in v1.
- Copying Dan Koe’s script, mic prop, or exact lighting.
- Auto cadence (“every N seconds drop a title”).
- Resolve-only path for Gate 2 review MP4s.

---

## Library card schema (for search + reuse)

Each saved recipe is one card. Fields are the product contract for humans and agents.

| Field | Purpose |
|-------|---------|
| `id` | Stable machine id (`hook_title`, …) |
| `title` | Human name (RU/EN ok) |
| `source` | Where observed (`MeVGaMG28nc` @ timecode range) |
| `what_happens` | Plain description of the picture: layers, text, motion, A-roll treatment |
| `look` | Tokens: font class, color, size band, position, grade notes |
| `tags` | Short searchable labels (`#hook`, `#list`, `#captions`, `#blur`, …) |
| `situations` | **Broad** “when to use” bullets (speech/content patterns, not one narrow rule) |
| `anti_situations` | When **not** to use (prevent cargo-cult) |
| `min_content` | Soft gates (e.g. list needs ≥3 real points) — guidance, not the only criterion |
| `inputs` | What producer must supply (`title` text, `lines[]`, phrase captions from ASR, …) |
| `compositor` | How Phase 2 draws it (ffmpeg recipe key) |
| `search_text` | Free-text blob = title + what_happens + situations + tags (for ripgrep / agent retrieval) |

**Search UX (v1):** markdown/JSON catalog under `presets/styles/` + `docs/product/STYLE_LIBRARY.md` index; agent and human grep by tag or situation phrase. Later: optional tiny search helper — not required to ship cards.

---

## Seed catalog (from MeVGaMG28nc)

Criteria below are **intentionally wider** than “only if exact hook wording” / “only if numbered 1–4.” Agent matches on situation + tags; human trims at Gate 1.

### 1. `captions_body` — золотые фразовые субтитры

- **what_happens:** Поверх живого говорящего появляются короткие фразы (3–6 слов), золотой serif, по центру примерно на груди; смена фраз в такт речи; лицо не закрыто огромной стеной текста снизу.
- **tags:** `#captions` `#serif` `#gold` `#chest-band` `#phrase` `#default-speech` `#talking-head`
- **situations (широко):**
  - идёт обычная речь / объяснение / история;
  - нужна читаемость без TikTok-бара снизу;
  - вертикальный talking-head;
  - нет отдельной «карточки» (title/list), которая уже несёт текст.
- **anti_situations:** одновременно с полным framework_list / крупным hook_title на том же такте (двойной текст); пустые/служебные CUT.
- **min_content:** есть KEEP-речь.
- **inputs:** phrase chunks from transcript (word/pause merge).

### 2. `hook_title` — крупный заголовок-хук

- **what_happens:** Крупный золотой serif (часто italic), 3–5 коротких строк по центру поверх A-roll; держится пару секунд; это «обложка мысли», не бегущая строка.
- **tags:** `#hook` `#title` `#serif` `#gold` `#cold-open` `#promise` `#thesis` `#big-text`
- **situations (широко):**
  - человек формулирует **обещание / тему ролика** («как…», «вот почему…», «главное — …»);
  - сильный **тезис** или название системы, которое стоит увидеть целиком;
  - холодный старт / возврат после паузы, где нужна «обложка»;
  - фраза, которую в монтаже хочется **запомнить глазом**, а не только ухом;
  - не обязательно дословный clickbait — достаточно ясного hook/thesis beat.
- **anti_situations:** каждая вторая реплика; чисто связка («ну вот», «смотри»); длинный абзац без сжатия в title.
- **min_content:** 1 сжатый title (не весь монолог).
- **inputs:** `title` (edited short lines).

### 3. `framework_list` — блюр + нумерованный/пунктирный каркас

- **what_happens:** A-roll под текстом сильно затемнён и размыт; по центру список пунктов; активный пункт яркий, остальные тусклые (spotlight); ощущение «вот система из N шагов».
- **tags:** `#list` `#framework` `#steps` `#blur` `#darken` `#spotlight` `#enumerate` `#system` `#playbook`
- **situations (широко):**
  - в речи есть **несколько сопоставимых пунктов** (шаги, правила, ошибки, причины, принципы) — ориентир **3+**, но также «явный каркас», даже если спикер не сказал «во-первых»;
  - человек **перечисляет систему** / playbook / чеклист;
  - нужно на секунды **показать структуру**, пока голос идёт;
  - повторное напоминание уже названных столпов (reprise list).
- **anti_situations:** один тезис; два пункта без ощущения системы; список ради декора; пункты выдуманы агентом, их нет в речи.
- **min_content:** ≥3 real lines grounded in KEEP text (soft; human may approve 3 from a longer spoken set).
- **inputs:** `lines[]` (short labels), optional per-line timings for spotlight.

### 4. `grade_talking_head` — база картинки

- **what_happens:** Не отдельная «графика», а общий look: спокойная кожа, более холодные тени, cinematic talking-head; задаёт фон для всех текстовых рецептов.
- **tags:** `#grade` `#color` `#cinematic` `#talking-head` `#base-look`
- **situations:** любой talking-head сегмент этого style pack; выбор/подтверждение на Gate 1 как сейчас (samples).
- **anti_situations:** ломать кожу ради «золота субтитров»; давить в чёрное так, что текст не читается без обводки.

---

## Who decides + how they search

1. **Library is source of truth** — agent does not invent unnamed looks.
2. Agent **retrieves** cards by tags/situations vs KEEP text (e.g. speech looks like enumeration → pull `#list` / `#framework`).
3. Agent proposes `style_scene` with: `recipe` id, `anchor`, `what`, `why`, plus recipe inputs; **why must cite situation/tag match** (searchable audit).
4. Human edits/removes at Gate 1.
5. Criteria stay **broad on the card**; narrowness comes from human veto + anti_situations — not from one brittle regex.

## Data flow

```
MeVGa analysis / lab presets
        ↓ promote
STYLE LIBRARY cards (id, what_happens, tags, situations, look, …)
        ↓ retrieve by tag/situation
Gate 1 agent → style_scene proposals
        ↓ human approve
transcript / visual-plan
        ↓
Phase 2 compositor
        ↓
render-contract + Gate 2 visual_render_policy
```

## Compositor behavior (v1)

Unchanged intent from prior draft: chest gold captions; hook title overlay; list = blur+darken + spotlight lines; suppress body captions under title/list; MOTION remains overlay-on-speech.

## Gate 2 QC (blocking)

- Captions match library look for `captions_body` (gold, serif intent, chest band — not bottom giant sans).
- Declared `hook_title` / `framework_list` must appear in render-contract; missing → FAIL.
- No producer notes (`Зачем:`) on screen.

## Tanya pilot

- `style_version: dankoe-mevga-v1` points at this library.
- Recompose after compositor+QC; author watches Gate 2.

## Acceptance (falsifiable)

1. Library cards exist with **tags + situations + what_happens** for all four recipes; index is greppable.
2. Search by tag `#hook` or phrase «обещание темы» finds `hook_title`.
3. Fixture KEEP without list/hook → only `captions_body` (+ grade).
4. Fixture KEEP with clear multi-step system → agent contract can select `framework_list` citing a situation/tag.
5. Old bottom white captions → visual_render_policy FAIL.

## Out of scope follow-ups

- Licensed font file.
- Perfect Hyperframes list animation.
- Full-text embedding search (v1 = tags + markdown grep).
