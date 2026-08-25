# Gate 1 — agent as producer

## Contract

Gate 1 quality comes from **judgment in the Cursor chat**, not from cadence scripts.

Workflow per segment:

1. Heuristics write a draft (`editorial-analysis.json`) — candidates only.
2. Pipeline writes `llm-editorial-request.json` (`provider: agent`).
3. **Agent** reads `prompts/gate1-editorial-cohesion.v2.md` + request, decides `splits` / KEEP / CUT, writes `llm-editorial-response.json`.
4. Pipeline writes `llm-visual-request.json` (только KEEP).
5. **Agent** читает `prompts/gate1-visual-producer.v1.md` + `GATE1_MOTION_OVERLAY.md` и предлагает **оверлеи** поверх KEEP: where / what / why / `duration_s` → `llm-visual-response.json`.
6. Human reviews `transcript.md` (с `КОНЕЦ СЕГМЕНТА` и `оверлей-начало`/`оверлей-конец`).

Forbidden as “Gate 1 quality”:

- KEEP-list stamp scripts
- fixture provider outside tests
- auto MOTION every N seconds / copy speech text into MOTION brief

## Visuals

Cadence `visual_planning.enabled` is **off**. Visuals are a **mandatory agent pass**: propose beats with `what` + `why`. Empty `proposals` only if речь самодостаточна (редко).

## Segments

Keep media segments as work units for the agent.

## Tanya note

Seg 03 “обрыв” was UX: mega-block started at 6:38 while media ends ~8:46. Transcript shows long-block ranges and `[…] КОНЕЦ СЕГМЕНТА`.
