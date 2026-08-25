# Gate 2 visual audit — Tanya reel pilot

**Claim:** «Phase 2 / Gate 2 готов к авторскому просмотру: графика, оверлеи и субтитры корректны.»

**Verdict: NOT VERIFIED** (2026-07-20)

## What automated PASS actually checked

- WER / order ratio on re-ASR
- Resolution, fps±tolerance, duration, not-near-black probes, audio loudness, geometric layout boxes

It did **not** check: face visibility, caption size/legibility, motion as overlay vs replace, brief leakage onto screen.

## Fresh frame evidence (`audit/gate2-visual-review/`)

| Frame | Finding |
|-------|---------|
| `01_t001.jpg`, `01_t005.jpg` | Talking head **gone**. Full-frame motion card; producer brief (`Зачем:…`) burned into graphic; huge ASS caption overlaps it |
| `01_t012.jpg` | Face visible but **captions cover face** (full utterance, ~83px Arial on 1280h) |
| `01_t024.jpg` | Same: motion card + brief dump + caption stack; top line clipped |
| `02_t010.jpg` | 60→6 diagram ok-ish, but brief/why text under captions |
| `02_t018.jpg` | Motion is wall of brief text, not «два банка»; captions dominate |

## Root causes in code

1. `render.py`: `type==motion` **replaces** camera with motion card (`base = generated_motion`) — contradicts Gate 1 overlay laws.
2. `motion.py`: draws full `brief` (includes `Зачем:`) on card.
3. Captions: one ASS event for entire KEEP, `fontsize = height * 0.065`, Alignment 2 center — walls of text over face.

## Required before saying Gate 2 ready

- [ ] Motion composites **over** A-roll (opacity/PiP/lower-third), does not replace speaker
- [ ] On-screen motion uses `what` only (never `why` / agent notes)
- [ ] Captions: bottom safe zone, smaller type, no full-paragraph center stack over face
- [ ] Re-render 01–03 + human frame audit pass
