# Gate 1 transcript UX contract

Author-facing `03_phase1/segments/NN/transcript.md` is the edit UI. It must stay readable in Markdown preview.

## Required human shape

```text
[0:07.120] KEEP id=2.3
**дербанить, отложи хотя бы десятую часть.**

[0:07.120] MOTION 2a (начало) @2.3
60 000 зарплата -> отложи 6 000 (10%) на счёт в другом банке

[0:11.120] MOTION 2a (конец)

[1:52.490] CUT (маркер пересъёма) id=2.24
**...сорванный дубль целиком...**
```

## Forbidden in human file

- `words=w000001,w000002,...` lists
- `[0:19.320 -> 0:21.440]` end-range display (start only on speech lines)
- Long ids like `visual-03-auto-u0001` or `u000001` when compact form exists
- Orphan one-word continuation blocks after a mid-phrase split
- `CUT` that deletes only the head of a clause and leaves the grammatical tail as `KEEP`
- MOTION without both `(начало)` and `(конец)` times

## CUT / KEEP engine

1. **Heuristic pre-pass** (`editorial.py` + `utterances.py`): pauses, retake markers, similar prefixes.
2. **Mandatory LLM cohesion pass** (`llm_editorial.py` + `prompts/gate1-editorial-cohesion.v2.md`): agent (Cursor chat) or openai writes `splits[]` + KEEP/CUT. See `docs/product/GATE1_AGENT_PRODUCER.md`. Fixture only in tests.

Heuristic alone is not Gate-1 quality. LLM result is written to `llm-editorial.json` and must exist before review. Human transcript shows coverage + `[timecode] КОНЕЦ СЕГМЕНТА`.

## Feedback loop note (Tanya 3.58)

Author rejected KEEP of a mega-block that still contained repeated hooks. System response:
- prompt v2 + agent producer judgment (not stamp scripts)
- validator rejects KEEP on multi-take text; explode is safety-net only
- Gate 1 must show progressive coverage through `media_end` and an explicit segment end line

## Visuals

Cadence auto-MOTION is **off**. After KEEP/CUT the agent proposes **overlays** on continuous speech (`GATE1_MOTION_OVERLAY.md`): `what` + `why` + `duration_s` ∈ [1.8, 4.5]. Markup uses `(оверлей-начало)` / `(оверлей-конец)` and `(поверх речи ~Ns)`.



Word IDs, exact end times, and raw ASR segmentation remain in `source-transcript.json`. Human short ids (`3.5`, `3a`) expand back to machine `u0005` on load.

## Provenance

Captured from author Gate 1 review (Tanya reel pilot, 2026-07-20). Agent rule: `.cursor/rules/gate1-transcript-ux.mdc`.
