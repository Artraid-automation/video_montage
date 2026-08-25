### 2026-07-21 — Slava: 5s lead-in silence + «вместо…вместо» retake

- **Symptom:** Author scored Gate2 audio **2/5**. TG ~29–31s: silence/sighs. Later: audible retake «вместо твердой постоянной работы, вместо того…» not cut.
- **Wrong assumption:** (1) `max_silence_s=6.0` is fine for Reels. (2) Phrase-echo detector only needs identical n-grams — different continuations after the same opener are OK.
- **Root cause:**
  1. KEEP `u0165p2` started at **484.95** while first word «большинство» is at **490.13** → **5.18s** dead air burned into the cut. In TG ×1.15 that lands near wall-clock **29–31s**. Gap was **4.8s** in re-ASR but below the 6s threshold → verification **PASS**.
  2. `u0169p1` kept both «вместо твердой постоянной работы» and «вместо того чтобы…» — a spoken false-start rephrase, not an identical bigram echo.
- **Fix:** Trim `u0165p2` in to **490.13**. Split `u0169p1`: CUT `526.87–530.43` («вместо твердой…»), KEEP the «вместо того чтобы…» take. Verification: `max_silence_s=1.2`, lead-in silence FAIL, repeated opener (`вместо`) FAIL.
- **Guardrail:** `tests/test_transcript_verify.py` (`test_repeated_opener_retake_fails`, `test_leading_silence_in_keep_fails`); worker `segment-compose-asr-verify-qc-v15`.
- **Evidence:** pre-fix rendered gap after «ставить.» @31.54 before «Большинство» @36.34; source words for u0169p1 `526.87–530.43`.
