# Tanya reel pilot v2 — middle master cut

**Date:** 2026-07-21  
**Project:** `projects/tanya-reel-pilot`

## Symptom

Author asked to remove ~33s from the **1.0× master** between «…нужны ли тебе эти дополнительные траты» (~0:54) and «Короче говоря, они уходят…» (~1:27).

## Wrong assumption

That the cut is a single contiguous span inside one camera file or one segment.

## Root cause

The unwanted bridge spans **two Gate 1 segments** in the glued film:

| Segment | Removed KEEP | Content |
|---------|--------------|---------|
| `02` | `2.10` / `u0010` | «Зачастую вот эта вот разница между 60 и 54 тысячами…» + MOTION `2c` |
| `03` | `3.14` / `u0014` | «По моим наблюдениям деньги уходят…» + MOTION `3b` |

## Fix

Gate 2 revision `r000117`–`r000121`:

- `04_phase2/segments/02/fixes.md` — `cut entry=u0010`, `remove-visual entry=u0010`
- `04_phase2/segments/03/fixes.md` — `cut entry=u0014`, `remove-visual entry=u0014`
- Rebuilt seg `02`/`03`, re-finalized master.

**Evidence:** master duration `113.7s → 84.6s` (−29.1s); join at `~0:57.6` (`05_final/qc.json`, seg02 `rendered-transcript.json` ends `средств.` @ 25.64s + seg01 31.97s).

## Guardrail

- Author “cut between phrase A and B on the **master**” → map both phrases to segment KEEP blocks + cross-segment glue check before editing.
- Pipeline: `visual_probes` end frame uses `duration - 0.2` (not `−0.08`) — FFmpeg 8.x rejects `-ss` within ~100ms of EOF (`pipeline/factory/qc.py`).
- v1 archive preserved as `projects/_archive/tanya-reel-pilot-v1/` before v2 archive write.
