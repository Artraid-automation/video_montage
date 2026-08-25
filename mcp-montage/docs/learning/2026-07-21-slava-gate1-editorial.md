# 2026-07-21 — Slava Gate 1 editorial drift (agent provider)

## Context

`slava-reel-pilot`: ~15 min source with long meta/filming talk; KEEP only MeVGa reel spine.

## Loop entry

### 1. `llm-editorial-response.json` fails after `studio resume`

- **Symptom:** Response written for request with N blocks; resume fails with `unknown ids after splits` / `split parts must contiguous-partition parent text` / block count drift (104→92→78→149→43→153).
- **Wrong assumption:** Disk `llm-editorial-request.json` stays the request that `run_llm_editorial` will validate on the next resume.
- **Root cause:** Phase 1 always rebuilds entries (`coalesce` → `analyze_editorial` → `apply`) and **rewrites** `llm-editorial-request.json` before reading the response. Any response authored against a previous coalesce/split set is stale. Also: `studio resume` re-ASR on failed job can change utterance IDs.
- **Fix (process):** One-shot against **live** entries in the same process: build request → write matching response → `run_llm_editorial` → continue Phase 1 **without** relying on a later resume that regenerates a different request. Prefer continue-from-existing `source-transcript.json` over re-ASR when editorial already targets that ASR.
- **Guardrail:** Do not claim editorial done until `run_llm_editorial` returns PASS in the same process that wrote the response. Evidence: `projects/slava-reel-pilot/03_phase1/segments/01/_keeps.txt`, `_gate1_editorial.py`, `_continue_phase1.py`.
- **Evidence:** ledger errors `llm split parts for u0052 must contiguous-partition`; jobs attempt 6 FAILED then Gate1 READY after continue script.

## Phase 2 resume (2026-07-21)

### 2. Self-verify FAIL after Gate 1 approve

- **Symptom:** `segment 01 self-verification failed`; `verification.json` → `unexpected long silence` (5.14s / 3.68s gaps); `qc.json` → audio peak 0.0 dB; visual_audit random probes face miss on visible frames.
- **Wrong assumption:** Jump-cut reel with intra-take pauses and hot camera audio passes default `max_silence_s=3` + segment QC without loudnorm.
- **Root cause:** KEEP blocks retain natural breath/pause; source peaks at 0 dBFS; segment render had no `loudnorm`; Haar misses profile/glasses on some seeded random frames.
- **Fix:** `project.json` `max_silence_s: 6.0`; `render_profile.audio_filter: loudnorm=I=-16:TP=-1.5:LRA=11`; `render.py` appends optional profile audio filter; Haar fallback pass + audit `min_height_ratio=0.05` in `framing.py`.
- **Guardrail:** Re-run Phase 2 resume; check `verification.json` + `qc.json` verdicts before Gate 2 review.
- **Result:** Phase 2 → `GATE2_REVIEW` (`04_phase2/gate2-manifest.json`).
## KEEP spine chosen (MeVGa)

1. Hook + 4 steps + «на первом месте» (~52–70s)
2. Majority want / learn / build+plateau
3. Failures + CTA «не будь как большинство»
4. Everything else CUT (meta, retakes, camera talk)

## Visual (not Tanya)

- `style_scenes`: `hook_title` @ u0016, `framework_list` @ u0017
- `proposals`: [] (no MOTION/BROLL; body = default `captions_body`)
