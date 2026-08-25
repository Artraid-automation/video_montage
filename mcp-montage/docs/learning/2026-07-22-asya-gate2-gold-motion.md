# Asya Gate2 — gold necklace FP + motion плитк false match

**Date:** 2026-07-22  
**Project:** `projects/asya-reel-pilot`

## Symptom

Gate 2 self-verify FAIL: (1) `hook title overlaps upper face` on `key-start` with no title on screen; (2) WER 0.17; (3) motion on-screen text `12 мес × 6 000` from unrelated Tanya template.

## Wrong assumption

Any dense-enough gold row cluster over the face bbox is a hook title. Brief word «плитках» means month-stack motion.

## Root cause

- Asya wears a **gold chain**; warm brick/skin also match the gold mask → sparse clusters in the eye band.
- Hook clearance used `start < min_title_top (0.48·H)` vs whole face box — false-positive jewelry before title even appears.
- `classify_motion` matched `"плитк"` → `stack_growth` (Tanya year tiles).
- Weak KEEP opener `u0003` missing from re-ASR relative to expected → WER/order fail.

## Fix

- `verify_hook_title_clear_of_face`: require gold **density** ≥10% of row width; overlap only if cluster starts **above eye line**.
- `classify_motion`: `stack_growth` only with month/year context, not bare «плитк».
- Editorial: CUT `u0003`; rebuild segment — verification WER=0.10 PASS, QC PASS.

## Guardrail

- Do not treat jewelry/brick gold as hook title without density + eye-line test.
- Motion template keywords must be content-specific (months/stack), not decorative words like «плитки» in a frame metaphor.
