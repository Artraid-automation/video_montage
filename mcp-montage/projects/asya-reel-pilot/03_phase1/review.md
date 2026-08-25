# Gate 1 — монтажное решение

## Blocking warnings

- Нет.

## Легенда артефактов

- `transcript.md` — интерфейс монтажа в preview-safe виде: `[0:12.000 -> 0:13.500] KEEP/CUT`, рядом `[MOTION]` / `[BROLL]` / `[FOOTAGE]`. Это **не** субтитры.
- Captions в Phase 2 собираются из блоков `KEEP`. `CUT` вырезается. Visual-метки — план вставок на якоре фразы.
- `grade-samples/` — 3 JPG варианта цвета (neutral/warm/punchy); выбор в `grade-manifest.json` → `selected`.
- `editorial-analysis.json` — машинные кандидаты (паузы/повторы/тейки). Читать JSON не обязательно: предложения зеркалятся в `CUT`.
- `Editorial candidates requiring review` — сколько кандидатов система пометила; сверь KEEP/CUT и MOTION briefs.
- `film-continuity.json` — проверка, что KEEP всех сегментов можно склеить в **один** ролик без дублей.

## Сегменты

### 01

- Source: `01_raw/01_camera.mp4`
- Transcript: [`segments/01/transcript.md`](segments/01/transcript.md)
- Sync: **NOT_REQUIRED**
- Grade samples: `segments/01/grade-samples/`
- Editorial analysis: `segments/01/editorial-analysis.json`
- Editorial candidates requiring review: 2
- Visual plan: `segments/01/visual-plan.json`
- Visual proposals: 4
- B-roll matches / motion fallbacks: 0 / 0

## Цельный фильм (склейка сегментов)

Сегменты — **части одного ролика**, не независимые клипы. Phase 3 склеит KEEP в master.
- Continuity verdict: **PASS**
- Blocking KEEP duplicates: 0
- Uncertain matches (review only): 0
- Artifact: [`film-continuity.json`](film-continuity.json)

## Обязательная проверка

1. Прочитать каждый `transcript.md`; менять KEEP/CUT, текст и MOTION/BROLL briefs.
2. Предложенные `CUT` можно вернуть в `KEEP` и наоборот — Phase 2 режет только CUT.
3. Выбрать grade в `grade-manifest.json`.
4. Проверить sync report и visual placements.
5. Снять **FILM CONTINUITY BLOCKED** (CUT дублирующих KEEP между сегментами), иначе approval невозможен.
6. После правок выполнить refresh Gate 1; approval привязан к новым hashes.

Project-level analysis: `cross-segment-take-analysis.json`.
Cross-segment take candidates requiring review: 0
Кандидаты зеркалятся в transcript как предлагаемые CUT; финальное решение за автором на Gate 1.

Phase 2 не запускается без валидного approval.
