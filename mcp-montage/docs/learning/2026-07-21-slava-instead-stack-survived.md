### 2026-07-21 — Slava: «вместо» stack survived first CUT (ASR alignment lie)

- **Symptom:** Author: ~50–60s (TG) still has meaning retake. Agent self-check of render ASR at review ~63–68s: «Вместо того чтобы… / Вместо твердой постоянной работы / Вместо того чтобы добежать».
- **Wrong assumption:** Cutting source words `526.87–530.43` («вместо твердой…» per Gate1 word IDs) removes that phrase from the burn.
- **Root cause:** Source word timings on u0172 were wrong — «добежать» spanned 4.4s and the real stack after 530.43 still contained false start + «твердой постоянной работы» + final take. Expected KEEP text had only one «вместо» → opener check on **expected** passed; WER (~9%) still under 14% despite insertions; opener check did **not** run on **actual** re-ASR.
- **Fix:** CUT through **535.73**; KEEP final take only. Verification also fails on repeated openers in **rendered** tokens (`v16`).
- **Guardrail:** `test_repeated_opener_in_actual_fails_even_if_expected_clean`; agent must re-ASR the contested window before claiming fixed / before TG.
- **Evidence:** `_probe_tmp` re-ASR review60 + source526; prior incomplete cut in `docs/learning/2026-07-21-slava-silence-instead-retake.md`.
