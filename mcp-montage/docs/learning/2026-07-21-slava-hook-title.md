# 2026-07-21 — Slava: hook title over face (not MeVGa cold-open)

## Symptom
Before the 1–2–3–4 list, opening text sat dead-center over the face. Author: first phrase must differ from body captions (size/font/placement), like Dan Koe.

## Wrong assumption
`render_hook_title_card` with `y = 0.42*h - th/2` and `font = width//14` was “good enough” MeVGa.

## Root cause
1. Hook Y centered on mid-frame → gold lines over eyes/nose (Dan Koe reference: title starts **below** face, ~0.64–0.81h).
2. Hook font (~51px on 720) ≤ body captions (~58px on 1280) — inverted hierarchy.
3. No Gate 2 check that hook ≠ body or that `key-start` gold clears upper face.

## Fix
- Hook: italic Times, `#EAC225`, font_ratio **0.072**, place below `face_bottom` (chest), clamp top ≥ 0.48h.
- Contract fields: `hook_title_font_size`, `hook_title_y_center_ratio`.
- QC: `hook_title_policy` (font > body; Y not too high) + `verify_hook_title_clear_of_face` on `key-start`.

## Guardrail
- `tests/test_style_guard.py` (font/Y fails), `tests/test_style_overlay.py` (placement meta)
- Gate 2 FAIL if hook covers upper face on key-start when `hook_title` expected
- Pixel evidence: Dan Koe `dankoe_01_0.5s.jpg` title clusters mid ≥0.66h; Slava broken clusters mid ~0.49–0.60h inside face box

## Evidence
- `lab/references/MeVGaMG28nc/frames/dankoe_01_0.5s.jpg` vs `slava_v3_hook_0.5s.jpg`
- `docs/learning/2026-07-21-slava-list-and-dupes.md` (list wiring) + this file
