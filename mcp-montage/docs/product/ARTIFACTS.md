# Контракты человеческих артефактов

JSON обслуживает машину; Markdown обслуживает редактора. Gate не требует чтения JSON.

## `03_phase1/film-continuity.json` / `04_phase2/film-continuity.json`

Машинная проверка: KEEP всех сегментов как будущий master. `verdict: BLOCKED` при высокоуверенном KEEP-дубле между сегментами. Approve Gate 1 / prepare Gate 2 / Phase 3 concat требуют `PASS`. См. `FILM_CONTINUITY.md`.

## `03_phase1/review.md`

Обязательные разделы: readiness и blocking warnings; список сегментов; спорные cuts; B-roll/motion concepts; sync и grade; точные файлы для чтения; инструкция approval/reject.

## `03_phase1/segments/NN/transcript.md`

Это редактируемый источник истины:

```markdown
<!-- segment: 01; source: 01-camera.mov; revision: 3 -->

Текст, который остается.

<cut reason="false-start">Неудачный первый дубль.</cut>

<visual type="library-broll" asset="broll-0042">
Показать на фразе «локальная библиотека».
</visual>

<visual type="motion" brief="pipeline-three-phases">
Три фазы и два human gates; без декоративного текста.
</visual>
```

Parser сохраняет stable sentence/word ids отдельно от форматирования, чтобы правка текста не создавала случайные таймкоды.

## `04_phase2/review.md`

Для каждого сегмента показывает review MP4, verification verdict, expected/actual transcript diff, созданные visuals, открытые `[fix]` и статус полного просмотра человеком.

## `04_phase2/segments/NN/render-contract.json`

Машинный контракт композитора для Gate 2: `motion_mode`, sanitized on-screen motion texts, caption font/alignment. Без PASS в `qc.json → visual_render_policy` сегмент не проходит Phase 2 (см. `GATE2_VISUAL_POLICY.md`).

## `04_phase2/segments/NN/fixes.md`

```markdown
- [fix blocking] 00:18.2–00:20.0 — повторена фраза «в этом видео».
- [fix visual] 00:31.0 — PiP закрывает Export; убрать PiP до 00:36.5.
- [rule candidate] На PiP-сегментах проверять центр головы по 3+ кадрам.
```

`blocking` запрещает Gate 2 approval. `rule candidate` после подтверждения добавляется в style/QC rules и получает regression fixture.

## Approval record

Approval содержит project id, gate id, UTC timestamp, reviewer, hashes утвержденных артефактов, принятые исключения и версию style profile. Изменение утвержденного артефакта автоматически отменяет approval gate.
