# Run 0002 — 2026-07-16 — reference stylepack

Mode: research
Result: ok

## Цель

Разобрать MeVGaMG28nc и зафиксировать style pack + subtitle preset без монтажа в Resolve.

## Референс / пресет

- `references/MeVGaMG28nc/source/MeVGaMG28nc.mp4`
- → `presets/styles/ref-MeVGaMG28nc.md`
- → `presets/subtitles/dankoe-gold-serif.md`

## Исходники

Не трогали. Source-map без изменений.

## План

1. Кадры + color sample
2. Analysis
3. Style + subtitle presets
4. Обновить checklist референса

## Факт

Сделано. Ключевые токены: caption `#E1C445`, title `#EAC225`, list spotlight white/dim, serif, lowercase captions, chest band.

## Ошибки

Первый color-sample зацепил кожу — исправлено фильтрами под yellow/gold.

## Learn

- Референс = 3 режима графики (title / list / captions), не один стиль субтитров
- Для билда следующим нужен atom транскрипции + Text+ style apply
