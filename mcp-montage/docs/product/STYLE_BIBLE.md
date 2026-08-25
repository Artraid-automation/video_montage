# Style Bible — авторский канон (после Tanya reel pilot)

**Status:** active  
**Provenance:** `tanya-reel-pilot` Gate 1 → Gate 2 → Final (`COMPLETED`, 2026-07-21)  
**Pack:** `dankoe-mevga-v1` + решения автора на реальном ролике  
**Rule (short):** `.cursor/rules/style-bible.mdc`

Это не «ещё один style pack из YouTube». Это **что автор реально принял** на первом боевом прогоне. Следующие проекты стартуют отсюда.

---

## Формат по умолчанию

| | Reels (короткий) | Long-form |
|--|------------------|-----------|
| Профиль | `presets/profiles/reels-9x16.json` | `presets/profiles/longform-16x9.json` |
| Кадр | 9:16 · 720×1280 (delivery TG 1080×1920) | 16:9 · 1920×1080 |
| Длина ориентир | ~30–120 с | минуты+ |
| Грейды на Final | `neutral` + `dankoe` + `warm` | то же трио |
| Primary grade (Tanya) | автор смотрел все три; delivery часто **warm**/dankoe — в проекте `default_grade` | то же, не форсить podcast |

Podcast / отдельные «короткие Shorts-профили кроме Reels» — **не делаем**.

---

## Речь и Gate 1

- KEEP/CUT — решение продюсера-агента, не эвристики вслепую.
- MOTION = **оверлей на непрерывный KEEP**, 2.0–3.5 с, старт у ключевого слова/цифры.
- Не оставлять «фальшивую цельность» с двумя хуками в одном KEEP.
- Human `transcript.md`: короткие маркеры, bold речь, без dump word-ids.
- Film continuity: сегменты — главы **одного** фильма; KEEP-дубли между сегментами → BLOCK.

## Визуал Gate 2

- Framing: face detect → scale+crop; captions **под лицом** (грудь), gold `#E1C445`, serif.
- Body captions ≠ TikTok white bar.
- MOTION: читаемый audience punch; во время окна MOTION captions punched; **в промежутках** captions остаются.
- Style recipes только из library, когда контент тянет (hook → title, 3+ steps → list).
- Encode delivery: **yuv420p** High; не High 4:4:4.
- Перед «визуал ок» — открыть audit JPG (в т.ч. caption-gap).

## Аудио и Final

- Loudness проверять **на склейке** (loudnorm I≈−14), не гонять сегменты повторно.
- Чистые `grades/master-*.mp4` = 1.0× скорость.
- TG: отдельный файл **document** 1080×1920; опционально `speed_factor: 1.15` только на нём.
- iPhone: не слать критичное только через `sendVideo` без проверки document.

## MOTION-смыслы с Тани (канон сюжета)

| Sense id | О чём | Откуда |
|----------|--------|--------|
| `pain-zero-balance` | Боль «на нуле» / пустой кошелёк | seg01 · 1a |
| `panic-cascade` | Паника: горит → искать/занять → тушить | seg01 · 1b |
| `rule-ten-percent` | Правило 10% (60к → 6к) | seg02/03 · 2a/3a |
| `friction-other-bank` | Трение перевода в «чужой» банк | seg02 · 2b |
| `year-stack` | 12 месяцев / стопка 6к | seg02 · 2c |
| `values-scales` | Весы: мечта/спокойствие vs хотелки | seg03 · 3b |
| `priority-shift-cta` | Сдвиг приоритетов + CTA «схема» | seg03 · 3c |

Полные карточки: `library/senses/catalog.json`.

---

## Как обновлять

1. После каждого принятого Final — дописать сюда 3–10 строк «что апрувнули / что запретили».
2. Повторяющееся → proposed rule → approve (`AGENTS.md`).
3. Новые MOTION/BROLL смыслы → карточка в `library/senses/`, не «векторная модель».

## Связанное

- Style pack index: `docs/product/STYLE_LIBRARY.md`
- Learning: `docs/product/LEARNING_LOOP.md`, `docs/learning/`
- Profiles: `presets/profiles/`
- Senses: `library/senses/README.md`
