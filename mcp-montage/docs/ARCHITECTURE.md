# Архитектура Local AI Video Factory v2

Каноническая спецификация находится в `docs/product/`. Этот документ — краткая карта runtime.

```text
CLI / application phase runner
        │ owns state transitions and gates
        ▼
versioned JobLedger ── fingerprint + worker version + output hashes
        │
        ├─ Phase 1 workers: ingest, ASR, editorial, cross-takes, sync, visuals, grade
        ├─ Phase 2 workers: compositor, rendered-media ASR, verification, QC
        └─ Phase 3 workers: master, package, archive, library ingestion

Artifacts → runtime contracts → hash-bound human approval → next phase
```

## Границы ответственности

- `pipeline/studio.py` — один пользовательский CLI и composition root.
- `pipeline/factory/state.py` — атомарный state ledger, CAS revision, gates и approvals.
- `pipeline/factory/jobs.py` — независимый resumable job ledger; завершённый job переиспользуется только при совпадении fingerprint/version и повторной проверке всех outputs.
- `pipeline/factory/phase*.py` — application orchestration; media workers не меняют product state.
- `pipeline/factory/contracts.py` и `artifacts.py` — versioned runtime parsing, media/hash/input bindings.
- `render.py`, `providers.py`, `verification.py`, `qc.py` — раздельные compose → ASR → compare → QC stages.
- `archive.py` и `cleanup.py` — verified copy/readback и recoverable allowlisted quarantine.

## Gates

1. `GATE1_REVIEW`: transcript, editorial/cross-take candidates, visual/B-roll proposals, sync и grade samples.
2. `GATE2_REVIEW`: каждый готовый segment MP4, повторная ASR, transcript verification, audio/frame/layout/technical QC и исполняемые fixes.
3. `FINAL_REVIEW`: master, chapters, publishing package, full QC и readback-verified archive.

Approval хранит SHA manifest и всех вложенных evidence. Stale или изменённый артефакт делает approval недействительным.

## Восстановление

Product ledger отвечает на вопрос «какая фаза разрешена». Job ledger отвечает «какие вычисления уже доказанно завершены». После сбоя `resume` не доверяет строке checkpoint: он сверяет worker version, input fingerprint, size и SHA каждого output и пропускает только валидные jobs.

## Legacy

Pre-v2 core/contracts сохранены в `lab/legacy/` только для истории. Они не импортируются runtime и не определяют структуру новых проектов.