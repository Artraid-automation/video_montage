# 2026-07-21 — Slava: meaning dupes + missing MeVGa framework_list

## Symptom
Author raised Gate 2 from 2/5 → 3/5 (framing OK) but blocked on:
1. Speech meaning repeats: «балуются → бросают → петля → бросают» then again «опускаем руки / бросаем».
2. Opening list is plain body captions — not Dan Koe blur+progressive 1/2/3/4 transition.

## Wrong assumption
1. KEEP u0169 (50s coalesced) was one clean beat; style_scenes in `style-scenes.json` / `llm-visual.json` would reach the renderer.
2. `framework_list` compositor already matched MeVGa (blur underlay + progressive spotlight).

## Root cause
1. **Editorial:** coalesced KEEP `1.169` kept the restatement after «в любом деле» («живут в этой петле… бросают и бросают…»). Ending KEEP `1.202` («Все, мы бросаем») echoed the same quit beat.
2. **Visual wiring:** `visual-plan.json` had `scenes: []` / `NO_VISUALS_PROPOSED` and **no `style_scenes`**, so render never applied `hook_title` / `framework_list`. `refresh_gate1` also wiped `style_scenes` when rebuilding the plan.
3. **Compositor gap:** `render_framework_list_card` drew a static dark plate (`active_index=0` only); A-roll blur was commented «optional later».

## Fix
1. Split `1.169` → KEEP `1.169p1` through «в любом деле,»; CUT `1.169p2` petlya restatement. CUT `1.202`.
2. Write `style_scenes` into `visual-plan.json` (hook on `u0016`; list on `u0017` active 0→1 + `u0018` active 2→3). Preserve `style_scenes` in `refresh_gate1`.
3. Progressive transparent list plate + `gblur`+darken on A-roll under `framework_list` (`ffmpeg-overlay-v13-list-blur`).

## Guardrail
- After Gate 1 visual proposals: assert `visual-plan.json` contains `style_scenes` when `llm-visual.json` / `style-scenes.json` does (`validate_visual_plan_style_wiring` in Gate 1 validate).
- `refresh_gate1` must not drop `style_scenes` (`reconcile_style_scenes` + sidecar reload).
- Gate 2 `evaluate_render_contract`: `style_recipes_expected` ⊆ `style_recipes_applied` — FAIL if `framework_list` / `hook_title` proposed but not burned.
- Regression: `tests/test_style_guard.py`.
- Before claiming editorial OK: re-ASR rendered master and grep for restated quit loops (`петле`, `бросают и бросают`, `Всё, мы бросаем`).
- Gate 2 probes at hook (~0.5s) and list (~3–10s) must show title / blur+numbered list, not body captions alone.

## Evidence
- Before text: …«живут в этой петле… бросают и бросают…» + «Всё, мы бросаем»
- After text: petlya / «Всё, мы бросаем» absent; duration ~105.7s (was ~123.6s)
- `render-contract.json`: `style_recipes_applied: [framework_list, hook_title]`, `cache_hit: false`
- Frames: `lab/references/MeVGaMG28nc/frames/slava_v3_hook_*.jpg`, `slava_v3_list*.jpg`
