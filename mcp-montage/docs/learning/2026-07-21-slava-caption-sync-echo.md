### 2026-07-21 — Slava final: KEEP echo + caption timing desync

- **Symptom:** Author on Final Review: opening sounds like «ежедневная работа руками работа руками»; ~28s feels desynced — sigh/breath with captions as if speaking. Author correctly noted post-render ASR+sync fix loop did not catch this.
- **Wrong assumption:** (1) Gate2 `verify_transcript` WER PASS means speech is editorially clean. (2) Evenly slicing phrase captions across clip duration is “close enough” to speech.
- **Root cause:**
  1. KEEP `u0017` ended on «ежедневная работа,» and KEEP `u0018` restarted «руками, работа руками…» — the duplicate was **in the approved expected text**, so WER compared render ASR to a bad target and passed (`wer≈0.067`).
  2. `_write_caption_ass` timed phrases as `duration/n_chunks` (even slice). Long coalesced KEEP (~17s around u0156–u0159) drifts from real word times; breaths show leftover/next captions → perceived desync.
  3. `expected_render_transcript` also used even token spacing, so timing drift could not fail closed.
- **Fix:**
  - Editorial split: KEEP `u0018p1` «руками,»; CUT `u0018p2` «работа руками»; KEEP `u0018p3` «и упорство…».
  - Captions + expected timeline use source word timestamps (`ffmpeg-overlay-v14-word-captions`).
  - Verification rejects adjacent n-gram echoes and speech timing drift vs re-ASR.
- **Guardrail:** `tests/test_transcript_verify.py` (echo + drift); `tests/test_caption_gaps.py::test_ass_uses_word_timings_not_even_slices`; project `transcript_verification.reject_adjacent_echoes` + drift thresholds.
- **Evidence:** `04_phase2/segments/01/verification.json` (pre-fix PASS with echo in `expected_tokens`); `03_phase1/segments/01/transcript.md` splits; probe after rebuild.
