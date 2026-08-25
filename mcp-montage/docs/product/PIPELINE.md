# Исполняемый pipeline

## Структура проекта

```text
projects/<slug>/
├── project.json
├── 01_raw/                         # пронумерованные исходники
├── 02_inputs/                      # brief, style, B-roll, WAV
├── 03_phase1/
│   ├── manifest.json
│   ├── film-continuity.json        # KEEP across segments → one film
│   ├── review.md                   # Gate 1
│   └── segments/01/
│       ├── source-transcript.json
│       ├── transcript.md           # редактируемый source of truth
│       ├── sync-report.json
│       ├── grade-samples/
│       └── visual-plan.json
├── 04_phase2/
│   ├── film-continuity.json        # recheck from expected KEEP
│   ├── review.md                   # Gate 2
│   └── segments/01/
│       ├── review.mp4
│       ├── rendered-transcript.json
│       ├── rendered-transcript.md
│       ├── verification.json
│       ├── verification.md
│       └── fixes.md
├── 05_final/
│   ├── master.mp4
│   ├── qc.json
│   ├── chapters.txt
│   └── publishing-package/
└── 06_state/
    ├── project-state.json
    ├── approvals.jsonl
    ├── events.jsonl
    └── checkpoints/
```

Имена будут мигрированы из прежних `00_admin/04_work/05_review`; существующий pilot сохраняется как доказательство низкоуровневых возможностей.

## Фаза 1

1. Проверить нумерацию и состав feeds.
2. Выполнить `ffprobe`, создать manifest и hashes.
3. Связать camera/screen/WAV в логические сегменты.
4. Транскрибировать каждый сегмент с word timestamps.
5. Найти cuts, но представить их внутри читаемого transcript.
6. Подобрать library B-roll и создать briefs отсутствующих scenes.
7. Выполнить sync analysis и grade samples.
8. Валидировать полноту артефактов.
9. Построить `film-continuity.json` (KEEP↔KEEP между сегментами как будущий master).
10. Создать Gate 1 `review.md`; остановиться.

Gate 1 готов, если каждый raw вошел в manifest, у каждого сегмента есть transcript и cut plan, visual связан с фразой/time range, sync/grade имеют статус, warnings перечислены в начале review, а **склейка сегментов** не содержит blocking KEEP-дублей (`docs/product/FILM_CONTINUITY.md`). Approve Gate 1 требует `film-continuity.verdict == PASS`.

## Фаза 2

1. Проверить hash Gate 1 approval.
2. Построить очередь новых visuals.
3. Для каждого сегмента: sync → cuts → layout → B-roll/motion → captions → grade → render.
4. Извлечь аудио из render и транскрибировать заново.
5. Сравнить actual transcript с утвержденным kept transcript.
6. Сделать visual probes начала/середины/конца каждого PiP и generated scene.
7. Выполнить technical QC.
8. При детектируемой ошибке пересобрать с ограниченным retry budget.
9. Пересчитать `04_phase2/film-continuity.json` из expected KEEP; при BLOCKED — fail-closed.
10. Сформировать Gate 2 review; остановиться.

Минимальные проверки: нет пропавших/повторенных фраз и лишней тишины; sync в допуске; PiP не закрывает screen content; лицо в safe area; B-roll покрывает диапазон; motion читаем; codec/resolution/fps/audio соответствуют профилю; **между сегментами нет KEEP-дублей**.

## Ревизии

`fixes.md` содержит адресные замечания. Оркестратор вычисляет зависимости, инвалидирует только нужные outputs и пересобирает их. После этого retranscription и verification выполняются заново; старый verdict не наследуется.

## Фаза 3

1. Проверить Gate 2 approval и отсутствие blocking fixes.
2. Убедиться, что film continuity PASS (fail-closed перед concat).
3. Склеить последние verified версии сегментов.
4. Loudnorm на склейке; три clean grade masters (`neutral` / style / `warm`) — без ускорения.
5. Создать chapters / publishing package; архив; library ingest.
6. **Telegram delivery (отдельный файл):** `05_final/delivery/tg-*-1080x1920*.mp4` как **document**; опционально `telegram_delivery.speed_factor` (например 1.15) только на этом файле. Чистые грейды не трогаем. Credentials: `.env` `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ADMIN_CHAT_ID`. CLI: `telegram-deliver`.
7. Выдать Final Review; `accept-final` → COMPLETED.

Очистка — отдельная явная команда после принятия финала с dry-run manifest.
