# Gate 2 — проверка смонтированных сегментов

Каждый сегмент необходимо посмотреть полностью.

## Цельный фильм

- Continuity verdict: **PASS**
- Blocking KEEP duplicates: 0
- Artifact: [`film-continuity.json`](film-continuity.json)

## Segment 01

- Video: [`segments/01/review.mp4`](segments/01/review.mp4)
- Transcript verification: **PASS**; WER=0.009804
- Technical/visual QC: **PASS**
- Visual render policy: **PASS**
- Visual audit (random+MOTION): **PASS**
- Cache hit: `true`
- Fixes: [`segments/01/fixes.md`](segments/01/fixes.md)

### Random frame probes (обязательная сверка)

- `random-01` @ 13.782s — [`segments/01/probes/gate2-audit/random-01-13.782.jpg`](segments/01/probes/gate2-audit/random-01-13.782.jpg)
- `random-02` @ 28.676s — [`segments/01/probes/gate2-audit/random-02-28.676.jpg`](segments/01/probes/gate2-audit/random-02-28.676.jpg)
- `random-03` @ 18.944s — [`segments/01/probes/gate2-audit/random-03-18.944.jpg`](segments/01/probes/gate2-audit/random-03-18.944.jpg)

### Per-MOTION checks

- MOTION `1a` 0.0–3.2s → **PASS**; on_screen=''
  - start @ 0.12s — [`probes/gate2-audit/motion-1a-start-0.120.jpg`](segments/01/probes/gate2-audit/motion-1a-start-0.120.jpg)
  - mid @ 1.6s — [`probes/gate2-audit/motion-1a-mid-1.600.jpg`](segments/01/probes/gate2-audit/motion-1a-mid-1.600.jpg)
  - end @ 3.08s — [`probes/gate2-audit/motion-1a-end-3.080.jpg`](segments/01/probes/gate2-audit/motion-1a-end-3.080.jpg)
- MOTION `1b` 21.18–24.68s → **PASS**; on_screen=''
  - start @ 21.3s — [`probes/gate2-audit/motion-1b-start-21.300.jpg`](segments/01/probes/gate2-audit/motion-1b-start-21.300.jpg)
  - mid @ 22.93s — [`probes/gate2-audit/motion-1b-mid-22.930.jpg`](segments/01/probes/gate2-audit/motion-1b-mid-22.930.jpg)
  - end @ 24.56s — [`probes/gate2-audit/motion-1b-end-24.560.jpg`](segments/01/probes/gate2-audit/motion-1b-end-24.560.jpg)

## Segment 02

- Video: [`segments/02/review.mp4`](segments/02/review.mp4)
- Transcript verification: **PASS**; WER=0.025974
- Technical/visual QC: **PASS**
- Visual render policy: **PASS**
- Visual audit (random+MOTION): **PASS**
- Cache hit: `false`
- Fixes: [`segments/02/fixes.md`](segments/02/fixes.md)

### Random frame probes (обязательная сверка)

- `random-01` @ 5.321s — [`segments/02/probes/gate2-audit/random-01-5.321.jpg`](segments/02/probes/gate2-audit/random-01-5.321.jpg)
- `random-02` @ 15.145s — [`segments/02/probes/gate2-audit/random-02-15.145.jpg`](segments/02/probes/gate2-audit/random-02-15.145.jpg)
- `random-03` @ 23.796s — [`segments/02/probes/gate2-audit/random-03-23.796.jpg`](segments/02/probes/gate2-audit/random-03-23.796.jpg)

### Per-MOTION checks

- MOTION `2a` 8.26–11.06s → **PASS**; on_screen=''
  - start @ 8.38s — [`probes/gate2-audit/motion-2a-start-8.380.jpg`](segments/02/probes/gate2-audit/motion-2a-start-8.380.jpg)
  - mid @ 9.66s — [`probes/gate2-audit/motion-2a-mid-9.660.jpg`](segments/02/probes/gate2-audit/motion-2a-mid-9.660.jpg)
  - end @ 10.94s — [`probes/gate2-audit/motion-2a-end-10.940.jpg`](segments/02/probes/gate2-audit/motion-2a-end-10.940.jpg)
- MOTION `2b` 11.52–15.02s → **PASS**; on_screen=''
  - start @ 11.64s — [`probes/gate2-audit/motion-2b-start-11.640.jpg`](segments/02/probes/gate2-audit/motion-2b-start-11.640.jpg)
  - mid @ 13.27s — [`probes/gate2-audit/motion-2b-mid-13.270.jpg`](segments/02/probes/gate2-audit/motion-2b-mid-13.270.jpg)
  - end @ 14.9s — [`probes/gate2-audit/motion-2b-end-14.900.jpg`](segments/02/probes/gate2-audit/motion-2b-end-14.900.jpg)

## Segment 03

- Video: [`segments/03/review.mp4`](segments/03/review.mp4)
- Transcript verification: **PASS**; WER=0.090909
- Technical/visual QC: **PASS**
- Visual render policy: **PASS**
- Visual audit (random+MOTION): **PASS**
- Cache hit: `false`
- Fixes: [`segments/03/fixes.md`](segments/03/fixes.md)

### Random frame probes (обязательная сверка)

- `random-01` @ 8.073s — [`segments/03/probes/gate2-audit/random-01-8.073.jpg`](segments/03/probes/gate2-audit/random-01-8.073.jpg)
- `random-02` @ 19.246s — [`segments/03/probes/gate2-audit/random-02-19.246.jpg`](segments/03/probes/gate2-audit/random-02-19.246.jpg)
- `random-03` @ 26.314s — [`segments/03/probes/gate2-audit/random-03-26.314.jpg`](segments/03/probes/gate2-audit/random-03-26.314.jpg)

### Per-MOTION checks

- MOTION `3c` 0.8–4.3s → **PASS**; on_screen=''
  - start @ 0.92s — [`probes/gate2-audit/motion-3c-start-0.920.jpg`](segments/03/probes/gate2-audit/motion-3c-start-0.920.jpg)
  - mid @ 2.55s — [`probes/gate2-audit/motion-3c-mid-2.550.jpg`](segments/03/probes/gate2-audit/motion-3c-mid-2.550.jpg)
  - end @ 4.18s — [`probes/gate2-audit/motion-3c-end-4.180.jpg`](segments/03/probes/gate2-audit/motion-3c-end-4.180.jpg)

## Правило gate

Добавить адресные `[fix ...]` в файл сегмента. Blocking fix запрещает approval.
Постмонтажный transcript и verification относятся к реальному render, а не к исходному plan.
Gate 2 QC includes **visual_render_policy** and mandatory **visual_audit** (seeded random screenshots + separate probe set for every MOTION).
