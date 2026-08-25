# Gate 2 — проверка смонтированных сегментов

Каждый сегмент необходимо посмотреть полностью.

## Цельный фильм

- Continuity verdict: **PASS**
- Blocking KEEP duplicates: 0
- Artifact: [`film-continuity.json`](film-continuity.json)

## Segment 01

- Video: [`segments/01/review.mp4`](segments/01/review.mp4)
- Transcript verification: **PASS**; WER=0.082353
- Technical/visual QC: **PASS**
- Visual render policy: **PASS**
- Visual audit (key+random+MOTION): **PASS**
- Cache hit: `false`
- Fixes: [`segments/01/fixes.md`](segments/01/fixes.md)

### Key composition probes (обязательная сверка)

- `key-start` @ 0.0s — [`segments/01/probes/gate2-audit/key-start-0.000.jpg`](segments/01/probes/gate2-audit/key-start-0.000.jpg)
- `key-mid` @ 45.483s — [`segments/01/probes/gate2-audit/key-mid-45.483.jpg`](segments/01/probes/gate2-audit/key-mid-45.483.jpg)
- `key-end` @ 90.767s — [`segments/01/probes/gate2-audit/key-end-90.767.jpg`](segments/01/probes/gate2-audit/key-end-90.767.jpg)

### Random frame probes (обязательная сверка)

- `random-01` @ 90.614s — [`segments/01/probes/gate2-audit/random-01-90.614.jpg`](segments/01/probes/gate2-audit/random-01-90.614.jpg)
- `random-02` @ 8.699s — [`segments/01/probes/gate2-audit/random-02-8.699.jpg`](segments/01/probes/gate2-audit/random-02-8.699.jpg)
- `random-03` @ 46.075s — [`segments/01/probes/gate2-audit/random-03-46.075.jpg`](segments/01/probes/gate2-audit/random-03-46.075.jpg)
- `random-04` @ 38.141s — [`segments/01/probes/gate2-audit/random-04-38.141.jpg`](segments/01/probes/gate2-audit/random-04-38.141.jpg)
- `random-05` @ 25.015s — [`segments/01/probes/gate2-audit/random-05-25.015.jpg`](segments/01/probes/gate2-audit/random-05-25.015.jpg)

## Правило gate

Добавить адресные `[fix ...]` в файл сегмента. Blocking fix запрещает approval.
Постмонтажный transcript и verification относятся к реальному render, а не к исходному plan.
Gate 2 QC includes **visual_render_policy** and mandatory **visual_audit** (seeded random screenshots + separate probe set for every MOTION).
