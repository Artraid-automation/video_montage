# Learning loop — errors, nuances, reworks

**Status:** mandatory process (author 2026-07-20).  
**Rule:** `.cursor/rules/learning-loop.mdc`  
**Promotion of repeated corrections into product rules:** still via proposed → approved (`AGENTS.md`).

## Why

Fixes without causes repeat. The factory must accumulate **falsifiable lessons**: what looked right, why it was wrong, what evidence caught it, what guardrail prevents recurrence.

## When to write

| Trigger | Action |
|---------|--------|
| Author rejects a visual / editorial outcome | Log entry + rework plan |
| Gate QC / visual audit FAIL after a “PASS” claim | Log why the claim was false |
| Agent retries the same approach ≥2 times | Log wrong assumption before third try |
| OpenCV / ffmpeg / ASS / detector surprise | Log nuance (API version, filter semantics, false positives) |

## Entry template

```markdown
### YYYY-MM-DD — short title

- **Symptom:** what was seen (author words or artifact)
- **Wrong assumption:** what we believed
- **Root cause:** why that was false
- **Fix:** code / policy / docs change
- **Guardrail:** test name, audit check, fingerprint bump, rule
- **Evidence:** paths to JPG / JSON / QC reasons
```

## Index

| Date | Topic | File |
|------|-------|------|
| 2026-07-20 | Framing + face-aware captions (Tanya) | `docs/learning/2026-07-20-framing-face-captions.md` |
| 2026-07-20 | Dynamic MOTION templates + timed overlay | `docs/learning/2026-07-20-dynamic-motion.md` |
| 2026-07-20 | Master loudnorm + final grade trio | `docs/learning/2026-07-20-dynamic-motion.md` §10 |
| 2026-07-21 | Style Bible + profiles + agent senses (not NN embeddings) | `docs/product/STYLE_BIBLE.md` |
| 2026-07-21 | KEEP phrase echo + even-slice caption desync (Slava) | `docs/learning/2026-07-21-slava-caption-sync-echo.md` |
| 2026-07-21 | Lead-in silence + «вместо…вместо» retake (Slava) | `docs/learning/2026-07-21-slava-silence-instead-retake.md` |
| 2026-07-21 | «вместо» stack survived first CUT (ASR lie) | `docs/learning/2026-07-21-slava-instead-stack-survived.md` |

## Related canon

- `docs/product/FRAMING.md`
- `docs/product/GATE2_VISUAL_POLICY.md`
- Visual truth: Gate2 audit JPGs under `04_phase2/segments/NN/probes/gate2-audit/`
