#!/usr/bin/env python3
"""Верхняя вставка: граница считается настоящей, только если держится на одной высоте
дольше 1.5 с. Разовый градиент — это фон, а не вставка."""
import json, pathlib, numpy as np
for i in (1,2,3,4):
    rows = json.loads(pathlib.Path(f'analysis/ref{i}-probe2.json').read_text(encoding='utf-8'))
    t = [r['t'] for r in rows]; sl = [r['split'] for r in rows]
    runs, cur = [], []
    for k, y in enumerate(sl):
        if y is not None and (not cur or abs(y - cur[-1][1]) <= 2.0):
            cur.append((t[k], y))
        else:
            if len(cur) >= 2: runs.append(cur)
            cur = [(t[k], y)] if y is not None else []
    if len(cur) >= 2: runs.append(cur)
    stable = [r for r in runs if r[-1][0]-r[0][0] >= 1.5]
    dur = t[-1]
    covered = sum(r[-1][0]-r[0][0] for r in stable)
    ys = [np.median([p[1] for p in r]) for r in stable]
    lens = [r[-1][0]-r[0][0] for r in stable]
    print(f"ref{i} ({dur:.0f} с): устойчивых вставок {len(stable)}, суммарно {covered:.0f} с = {100*covered/dur:.0f}% хронометража")
    if stable:
        print(f"   длина вставки: медиана {np.median(lens):.1f} с, диапазон {min(lens):.1f}–{max(lens):.1f} с")
        print(f"   граница по высоте кадра: медиана {np.median(ys):.0f}%, диапазон {min(ys):.0f}–{max(ys):.0f}%")
