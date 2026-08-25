# Asya — brand captions + drop MOTION 1b

**Date:** 2026-07-22  
**Project:** `projects/asya-reel-pilot`

## Symptom

Author: subtitles show ASR mush «про женщины» / «экзесидвижение»; need org names «PRO Женщин» and «X10 Движение». Second MOTION graphic (1b) should go.

## Wrong assumption

Burning casefolded source word tokens is fine for body captions; org names can stay phonetic ASR.

## Fix

- `caption_display_text()`: casefold body, then restore brand spellings (incl. Latin `pro` after casefold of `PRO`).
- `caption_burn_words_for_entry()` merges `про`+`женщин*` into one burn token; wrap treats brands as atomic.
- Transcript KEEP text updated for review; MOTION `1b` removed from transcript + visual-plan.
- Expected/re-ASR still uses source word IDs (WER unchanged).

## Guardrail

Known brand mishears get a caption rewrite map — do not leave raw ASR org names on screen when the author names the brand. Never casefold brand tokens without a restore pass (`PRO` → `pro`).
