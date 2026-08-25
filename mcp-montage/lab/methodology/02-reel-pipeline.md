# Pipeline: вертикальный рилс (черновик v0)

Опирается на структуру исходников:

```
рилс/<проект>/
  01_footage   A-roll
  02_screen    скрины
  03_audio     отдельный звук
  04_broll
  05_project
  06_exports
```

Текущий проект: см. `source-map/current.md`.

## Стадии

### S0 — Research (без Resolve)

- разобрать референс → `references/<id>/analysis.md`
- собрать style pack → `presets/styles/`
- обновить source-map

### S1 — Ingest

- импорт `01_footage` (+ `03_audio` если нужен sync)
- проверка ориентации / 9:16
- создание timeline `REEL_vN`

### S2 — Rough cut

- вырезать паузы/фальстарты (по маркерам или по транскрипту)
- выстроить смысловые блоки под хук → развитие → punchline/CTA
- целевая длина: ориентир Shorts ~15–45s (уточняется по референсу)

### S3 — Captions

- локальная транскрипция (faster-whisper; пакет ставится при первом captions-прогоне)
- таймкоды → субтитры на timeline
- стиль из `presets/subtitles/` (после разбора референса)

### S4 — Polish (то, что MCP тянет стабильно)

- цвет клипа / LUT если есть
- zoom/pan для акцентов (static props; keyframes — fallback руками)
- маркеры для ручных transitions

### S5 — Export

- 1080×1920, H.264/H.265, в `06_exports/vN/`
- лог в `runs/`

## Что сознательно НЕ автоматизируем в v0

- сложные Fusion-компы 1:1 с референсом
- идеальный match cut
- ручной taste-pass наблюдателя

Это наращивается через experiments → atoms → presets.
