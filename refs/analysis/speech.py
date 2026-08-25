#!/usr/bin/env python3
"""Проверка гипотезы: склейки стоят там, где вырезаны паузы и вдохи."""
import json, pathlib, numpy as np
def p(v,q): return round(float(np.percentile(v,q)),3) if len(v) else None
print(f"{'':6} {'слов':>5} {'слов/мин':>9} {'пауза p50':>10} {'p90':>7} {'p99':>7} {'>0.3с':>7} {'>0.5с':>7} {'речь%':>7}")
allgaps={}
for i in (1,2,3,4):
    w = json.loads(pathlib.Path(f'analysis/ref{i}-words.json').read_text(encoding='utf-8'))
    r3 = json.loads(pathlib.Path(f'analysis/ref{i}-probe3.json').read_text(encoding='utf-8'))
    dur = r3[-1]['t']
    gaps = [round(w[k]['s']-w[k-1]['e'],3) for k in range(1,len(w))]
    gaps = [g for g in gaps if g >= 0]
    speech = sum(x['e']-x['s'] for x in w)
    allgaps[i]=(w,gaps)
    print(f"ref{i:<3} {len(w):>5} {len(w)/dur*60:>9.0f} {p(gaps,50):>10} {p(gaps,90):>7} {p(gaps,99):>7} "
          f"{sum(1 for g in gaps if g>0.3):>7} {sum(1 for g in gaps if g>0.5):>7} {100*speech/dur:>6.0f}%")
print("\nСклейки против стыков слов:")
for i in (1,2,3,4):
    w, gaps = allgaps[i]
    r3 = json.loads(pathlib.Path(f'analysis/ref{i}-probe3.json').read_text(encoding='utf-8'))
    t = np.array([r['t'] for r in r3]); fd = np.array([r.get('framediff',0.) for r in r3])
    thr = max(12., float(np.percentile(fd,97)))
    cuts, m = [float(t[k]) for k in range(1,len(r3)) if fd[k]>thr], []
    for c in cuts:
        if not m or c-m[-1] > 0.25: m.append(c)
    bounds = [(w[k-1]['e']+w[k]['s'])/2 for k in range(1,len(w))]
    # ближайший стык слов к каждой склейке
    d = [min(abs(c-b) for b in bounds) for c in m] if bounds else []
    inside = sum(1 for x in d if x <= 0.12)
    mid    = sum(1 for x in d if x <= 0.25)
    print(f"ref{i}: склеек {len(m)} | на стыке слов (±0.12 с) {inside} ({100*inside//len(m)}%) | ±0.25 с {mid} ({100*mid//len(m)}%) | медиана удаления {p(d,50)} с")
