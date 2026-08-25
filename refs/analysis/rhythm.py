#!/usr/bin/env python3
"""Ритм и работа с крупностью: ступени (склейки со сменой масштаба) и плавные зумы."""
import json, pathlib, statistics as st

def pctl(v,p):
    if not v: return None
    s=sorted(v); k=(len(s)-1)*p/100; lo=int(k); hi=min(lo+1,len(s)-1)
    return round(s[lo]+(s[hi]-s[lo])*(k-lo),2)

for i in (1,2,3,4):
    rows = json.loads(pathlib.Path(f'analysis/ref{i}-probe2.json').read_text(encoding='utf-8'))
    ts = [r['t'] for r in rows]
    fh = [r['face']['h_pct'] if 'face' in r else None for r in rows]
    steps, zooms, cur = [], [], []
    for k in range(1, len(fh)):
        if fh[k] is None or fh[k-1] is None:
            continue
        rel = (fh[k]-fh[k-1])/fh[k-1]*100
        if abs(rel) > 8:                      # скачок за 0.2 с = склейка со сменой крупности
            steps.append((ts[k], round(rel,1)))
        elif 0.8 < abs(rel) <= 8:             # плавное движение
            zooms.append(rel)
    gaps = [round(steps[k][0]-steps[k-1][0],2) for k in range(1,len(steps))]
    caps = [r['cap'] for r in rows if 'cap' in r]
    colors = {}
    for c in caps: colors[c['color']] = colors.get(c['color'],0)+1
    lines = {}
    for c in caps: lines[c['lines']] = lines.get(c['lines'],0)+1
    dur = ts[-1]
    print(f"\n===== ref{i} ({dur:.0f} с) =====")
    print(f"смен крупности: {len(steps)} = 1 каждые {dur/max(1,len(steps)):.1f} с")
    if gaps:
        print(f"  интервал между сменами: p25={pctl(gaps,25)}с медиана={pctl(gaps,50)}с p75={pctl(gaps,75)}с")
    ups = [s[1] for s in steps if s[1]>0]; downs=[s[1] for s in steps if s[1]<0]
    print(f"  приближения {len(ups)} (медиана +{pctl(ups,50)}%), отъезды {len(downs)} (медиана {pctl(downs,50)}%)")
    print(f"  величина шага, % от текущей крупности: p25={pctl([abs(s[1]) for s in steps],25)} медиана={pctl([abs(s[1]) for s in steps],50)} p75={pctl([abs(s[1]) for s in steps],75)} p90={pctl([abs(s[1]) for s in steps],90)}")
    print(f"плавное движение внутри плана: {len(zooms)} проб из {len(rows)} ({100*len(zooms)//len(rows)}%), медиана {pctl([abs(z) for z in zooms],50)}%/0.2с")
    print(f"субтитры: строк в кадре {dict(sorted(lines.items()))}, цвет {colors}")
    print(f"  низ блока % сверху: p25={pctl([c['bot_pct'] for c in caps],25)} медиана={pctl([c['bot_pct'] for c in caps],50)} p75={pctl([c['bot_pct'] for c in caps],75)}")
    print(f"  высота глифа % кадра: медиана={pctl([c['glyph_pct'] for c in caps],50)} (px при 1920: {pctl([c['glyph_pct'] for c in caps],50)*19.2:.0f})")
    print(f"  ширина блока % кадра: медиана={pctl([c['w_pct'] for c in caps],50)} p90={pctl([c['w_pct'] for c in caps],90)}")
    faces=[r['face'] for r in rows if 'face' in r]
    print(f"крупность (высота лица % кадра): p25={pctl([f['h_pct'] for f in faces],25)} медиана={pctl([f['h_pct'] for f in faces],50)} p75={pctl([f['h_pct'] for f in faces],75)}")
    print(f"глаза % сверху: p25={pctl([f['eye_pct'] for f in faces],25)} медиана={pctl([f['eye_pct'] for f in faces],50)} p75={pctl([f['eye_pct'] for f in faces],75)}")
