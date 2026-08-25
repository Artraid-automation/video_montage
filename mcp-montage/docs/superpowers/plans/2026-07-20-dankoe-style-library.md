# Dan Koe Style Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a searchable Dan Koe (MeVGaMG28nc) style recipe library and wire default body captions + grade + Gate 2 policy to it; agent can propose hook/list recipes when content warrants.

**Architecture:** Versioned JSON catalog under `presets/styles/dankoe-mevga-v1/` is the source of truth. `pipeline/factory/style_library.py` loads/searches cards. Captions/grade/compositor read look tokens from the pack. Gate 1 visual agent retrieves cards by tags/situations; Gate 2 `visual_render_policy` enforces chest gold serif captions and declared style recipes.

**Tech Stack:** Python 3.12, existing factory (render ASS, ffmpeg, unittest), markdown index for humans.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-20-dankoe-style-pack-design.md`
- Recipes are conditional — never auto title/list for style alone
- No `Зачем:` on screen
- MOTION remains overlay-on-speech
- Do not commit unless user asks
- TDD: failing test before production code per task
- PYTHONPATH for studio: repo `pipeline/`; for tests: repo root

## File map

| Path | Role |
|------|------|
| `presets/styles/dankoe-mevga-v1/library.json` | Machine catalog of recipe cards |
| `docs/product/STYLE_LIBRARY.md` | Human greppable index |
| `pipeline/factory/style_library.py` | Load, validate, search cards |
| `pipeline/factory/visual_policy.py` | Caption band/color/font policy from pack |
| `pipeline/factory/render.py` | ASS style from pack; future title/list layers |
| `pipeline/factory/grade.py` | Add `dankoe` grade filter |
| `pipeline/factory/llm_visual.py` | Include library digest in request; accept `style_scenes` |
| `prompts/gate1-visual-producer.v1.md` | Instruct retrieval by tags/situations |
| `tests/test_style_library.py` | Search + card schema |
| `tests/test_visual_policy.py` | Chest/gold policy (extend) |

---

### Task 1: Style library catalog + search API

**Files:**
- Create: `presets/styles/dankoe-mevga-v1/library.json`
- Create: `docs/product/STYLE_LIBRARY.md`
- Create: `pipeline/factory/style_library.py`
- Create: `tests/test_style_library.py`

**Interfaces:**
- Produces: `load_style_library(path|version) -> dict`, `search_recipes(library, query: str) -> list[dict]`, `get_recipe(library, recipe_id) -> dict`

- [ ] **Step 1: Write failing tests** in `tests/test_style_library.py` for load, tag search `#hook`, situation phrase search, missing id error
- [ ] **Step 2: Run** `python -m unittest tests.test_style_library -v` → FAIL
- [ ] **Step 3: Add `library.json`** with four cards from the spec (full fields)
- [ ] **Step 4: Implement `style_library.py`**
- [ ] **Step 5: Write `STYLE_LIBRARY.md` index** linking ids/tags
- [ ] **Step 6: Run tests → PASS**

---

### Task 2: Caption policy = chest gold serif (not bottom white)

**Files:**
- Modify: `pipeline/factory/visual_policy.py`
- Modify: `pipeline/factory/render.py` (`_write_caption_ass`)
- Modify: `tests/test_visual_policy.py`

**Interfaces:**
- Consumes: `get_recipe(... captions_body).look`
- Produces: ASS with serif font, PrimaryColour gold, Alignment=5 (center), MarginV for chest band; policy evaluates chest + gold

- [ ] **Step 1: Failing tests** — old bottom alignment FAIL; gold chest PASS; giant bottom FAIL
- [ ] **Step 2: Update visual_policy** constants/helpers for dankoe body captions
- [ ] **Step 3: Update render ASS writer** to use pack look (Times New Roman / Georgia, `#E1C445`, center, chest MarginV)
- [ ] **Step 4: Phrase-chunk captions** (max ~6 words per event) when word timings absent: split KEEP text
- [ ] **Step 5: Tests PASS**

---

### Task 3: Grade `dankoe` + Tanya style_version bind

**Files:**
- Modify: `pipeline/factory/grade.py` — add filter approximating cool shadows
- Modify: `projects/tanya-reel-pilot/project.json` — `style_version`, optional `default_grade: dankoe` only if author already chose; prefer document + sample, keep default_grade unless Gate1 selected
- Modify: `projects/tanya-reel-pilot/02_inputs/style.md` — point at library

- [ ] **Step 1: Add grade filter + unit check key exists**
- [ ] **Step 2: Point Tanya style.md + style_version at `dankoe-mevga-v1`**
- [ ] **Step 3: Ensure grade samples include dankoe** (GRADE_FILTERS iteration already does)

---

### Task 4: Agent retrieval + `style_scenes` in visual LLM contract

**Files:**
- Modify: `pipeline/factory/llm_visual.py`
- Modify: `prompts/gate1-visual-producer.v1.md`
- Modify: `tests/test_llm_visual.py` (or new)

**Interfaces:**
- Request includes `style_library_digest` (id, tags, situations summary)
- Response may include `style_scenes: [{id, recipe, anchor, what, why, title?, lines?}]`
- Validate recipe id ∈ library; why required; list lines ≥3 when recipe=framework_list

- [ ] **Step 1: Failing validation tests**
- [ ] **Step 2: Implement digest + validation**
- [ ] **Step 3: Update prompt** with library retrieval rules (plain language)
- [ ] **Step 4: Tests PASS**

---

### Task 5: Compositor hooks for `hook_title` and `framework_list` (v1)

**Files:**
- Create: `pipeline/factory/style_overlay.py` — render title PNG and list PNG sequences
- Modify: `pipeline/factory/render.py` — overlay when style_scene on entry
- Modify: `pipeline/factory/transcript.py` / visual plan load path as needed
- Modify: `pipeline/factory/visual_policy.py` — contract fields for style recipes used
- Test: `tests/test_style_overlay.py`

- [ ] **Step 1: Failing test** — title overlay PNG contains gold-ish pixels; list has N lines
- [ ] **Step 2: Implement overlay generators**
- [ ] **Step 3: Wire into `_render_entry` when style scene present; suppress body captions
- [ ] **Step 4: render-contract records `style_recipes_applied`**
- [ ] **Step 5: Tests PASS**

---

### Task 6: Product docs + cursor rule

**Files:**
- Create: `.cursor/rules/style-library.mdc`
- Modify: `docs/product/GATE2_VISUAL_POLICY.md` — chest/gold not bottom
- Modify: `docs/product/ARTIFACTS.md` — library pointer

- [ ] **Step 1: Write rule + update GATE2 policy docs**
- [ ] **Step 2: Done when docs match shipped behavior**

---

### Task 7: Smoke — synthetic phase2 caption look

**Files:**
- Extend: `tests/test_visual_policy.py` Phase2 test asserts contract caption_alignment center/chest and color metadata if present

- [ ] **Step 1: Assert render-contract caption fields match dankoe body**
- [ ] **Step 2: PASS**

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Searchable cards tags/situations/what_happens | 1 |
| Conditional use | 4–5 |
| captions_body look + QC | 2, 7 |
| hook_title / framework_list | 4, 5 |
| grade | 3 |
| Tanya bind | 3 |
| No cargo-cult auto | 4 prompt + anti_situations |

## Execution

User said «делай дальше» → **inline execution** in this session (executing-plans style), starting Task 1.
