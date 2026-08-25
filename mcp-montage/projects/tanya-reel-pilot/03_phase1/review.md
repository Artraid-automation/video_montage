# Gate 1 — монтажное решение

## Blocking warnings

- Нет.

## Легенда артефактов

- `transcript.md` — интерфейс монтажа в preview-safe виде: `[0:12.000 -> 0:13.500] KEEP/CUT`, рядом `[MOTION]` / `[BROLL]` / `[FOOTAGE]`. Это **не** субтитры.
- Captions в Phase 2 собираются из блоков `KEEP`. `CUT` вырезается. Visual-метки — план вставок на якоре фразы.
- `grade-samples/` — 3 JPG варианта цвета (neutral/warm/punchy); выбор в `grade-manifest.json` → `selected`.
- `editorial-analysis.json` — машинные кандидаты (паузы/повторы/тейки). Читать JSON не обязательно: предложения зеркалятся в `CUT`.
- `Editorial candidates requiring review` — сколько кандидатов система пометила; сверь KEEP/CUT и MOTION briefs.

## Сегменты

### 01

- Source: `01_raw/01_camera.mp4`
- Transcript: [`segments/01/transcript.md`](segments/01/transcript.md)
- Sync: **NOT_REQUIRED**
- Grade samples: `segments/01/grade-samples/`
- Editorial analysis: `segments/01/editorial-analysis.json`
- Editorial candidates requiring review: 1
- Visual plan: `segments/01/visual-plan.json`
- Visual proposals: 2
- B-roll matches / motion fallbacks: 0 / 0

### 02

- Source: `01_raw/02_camera.mp4`
- Transcript: [`segments/02/transcript.md`](segments/02/transcript.md)
- Sync: **NOT_REQUIRED**
- Grade samples: `segments/02/grade-samples/`
- Editorial analysis: `segments/02/editorial-analysis.json`
- Editorial candidates requiring review: 0
- Visual plan: `segments/02/visual-plan.json`
- Visual proposals: 3
- B-roll matches / motion fallbacks: 0 / 0

### 03

- Source: `01_raw/03_camera.mp4`
- Transcript: [`segments/03/transcript.md`](segments/03/transcript.md)
- Sync: **NOT_REQUIRED**
- Grade samples: `segments/03/grade-samples/`
- Editorial analysis: `segments/03/editorial-analysis.json`
- Editorial candidates requiring review: 6
- Visual plan: `segments/03/visual-plan.json`
- Visual proposals: 3
- B-roll matches / motion fallbacks: 0 / 0

## Обязательная проверка

1. Прочитать каждый `transcript.md`; менять KEEP/CUT, текст и MOTION/BROLL briefs.
2. Предложенные `CUT` можно вернуть в `KEEP` и наоборот — Phase 2 режет только CUT.
3. Выбрать grade в `grade-manifest.json`.
4. Проверить sync report и visual placements.
5. После правок выполнить refresh Gate 1; approval привязан к новым hashes.

Project-level analysis: `cross-segment-take-analysis.json`.
Cross-segment take candidates requiring review: 1
Кандидаты зеркалятся в transcript как предлагаемые CUT; финальное решение за автором на Gate 1.

Phase 2 не запускается без валидного approval.
