# Film continuity — один ролик из N сегментов

## Law

Пронумерованные сегменты (`01`, `02`, `03`, …) — **части одного цельного видео**, которое Phase 3 склеит в master.  
Нельзя считать сегмент «готовым в изоляции», если его KEEP дублирует KEEP другого сегмента.

## Что проверяем

- Только **KEEP** из editable `transcript.md` (и на Gate 2 — из `expected-transcript.json`).
- Высокое лексическое сходство KEEP↔KEEP **между разными сегментами** → `verdict: BLOCKED`.
- Неопределённые совпадения → `uncertain_matches` (review only, не блок).

## Артефакты

| Phase | Path |
|-------|------|
| Gate 1 | `03_phase1/film-continuity.json` |
| Gate 2 | `04_phase2/film-continuity.json` |

## Gates

- **Gate 1 prepare** — continuity артефакт обязателен (`PASS` или `BLOCKED`).
- **Gate 1 approve** — только `PASS`.
- **Gate 2 prepare / Phase 3 concat** — только `PASS`.

Код: `pipeline/factory/film_continuity.py`.  
Always-on rule: `.cursor/rules/film-continuity.mdc`.
