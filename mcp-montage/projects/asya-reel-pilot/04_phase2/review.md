# Gate 2 — проверка смонтированных сегментов

Каждый сегмент необходимо посмотреть полностью.

## Цельный фильм

- Continuity verdict: **PASS**
- Blocking KEEP duplicates: 0
- Artifact: [`film-continuity.json`](film-continuity.json)

## Segment 01

- Video: [`segments/01/review.mp4`](segments/01/review.mp4)
- Transcript verification: **PASS**; WER=0.1
- Technical/visual QC: **PASS**
- Visual render policy: **PASS**
- Visual audit (key+random+MOTION): **PASS**
- Cache hit: `false`
- Fixes: [`segments/01/fixes.md`](segments/01/fixes.md)

### Key composition probes (обязательная сверка)

- `key-start` @ 0.0s — [`segments/01/probes/gate2-audit/key-start-0.000.jpg`](segments/01/probes/gate2-audit/key-start-0.000.jpg)
- `key-mid` @ 25.258s — [`segments/01/probes/gate2-audit/key-mid-25.258.jpg`](segments/01/probes/gate2-audit/key-mid-25.258.jpg)
- `key-end` @ 50.317s — [`segments/01/probes/gate2-audit/key-end-50.317.jpg`](segments/01/probes/gate2-audit/key-end-50.317.jpg)

### Random frame probes (обязательная сверка)

- `random-01` @ 23.647s — [`segments/01/probes/gate2-audit/random-01-23.647.jpg`](segments/01/probes/gate2-audit/random-01-23.647.jpg)
- `random-02` @ 36.279s — [`segments/01/probes/gate2-audit/random-02-36.279.jpg`](segments/01/probes/gate2-audit/random-02-36.279.jpg)
- `random-03` @ 39.641s — [`segments/01/probes/gate2-audit/random-03-39.641.jpg`](segments/01/probes/gate2-audit/random-03-39.641.jpg)
- `random-04` @ 25.917s — [`segments/01/probes/gate2-audit/random-04-25.917.jpg`](segments/01/probes/gate2-audit/random-04-25.917.jpg)
- `random-05` @ 12.93s — [`segments/01/probes/gate2-audit/random-05-12.930.jpg`](segments/01/probes/gate2-audit/random-05-12.930.jpg)

### Per-MOTION checks

- MOTION `1c` 19.92–23.42s → **PASS**; on_screen=''
  - start @ 20.04s — [`probes/gate2-audit/motion-1c-start-20.040.jpg`](segments/01/probes/gate2-audit/motion-1c-start-20.040.jpg)
  - mid @ 21.67s — [`probes/gate2-audit/motion-1c-mid-21.670.jpg`](segments/01/probes/gate2-audit/motion-1c-mid-21.670.jpg)
  - end @ 23.3s — [`probes/gate2-audit/motion-1c-end-23.300.jpg`](segments/01/probes/gate2-audit/motion-1c-end-23.300.jpg)
- MOTION `1d` 39.62–43.12s → **PASS**; on_screen=''
  - start @ 39.74s — [`probes/gate2-audit/motion-1d-start-39.740.jpg`](segments/01/probes/gate2-audit/motion-1d-start-39.740.jpg)
  - mid @ 41.37s — [`probes/gate2-audit/motion-1d-mid-41.370.jpg`](segments/01/probes/gate2-audit/motion-1d-mid-41.370.jpg)
  - end @ 43.0s — [`probes/gate2-audit/motion-1d-end-43.000.jpg`](segments/01/probes/gate2-audit/motion-1d-end-43.000.jpg)

## Правило gate

Добавить адресные `[fix ...]` в файл сегмента. Blocking fix запрещает approval.
Постмонтажный transcript и verification относятся к реальному render, а не к исходному plan.
Gate 2 QC includes **visual_render_policy** and mandatory **visual_audit** (seeded random screenshots + separate probe set for every MOTION).
