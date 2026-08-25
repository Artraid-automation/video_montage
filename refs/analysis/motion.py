#!/usr/bin/env python3
"""Свод: реальные склейки, реальные зумы внутри плана, тайминг субтитров."""
import json, pathlib, numpy as np

def pctl(v,p):
    if len(v)==0: return None
    return round(float(np.percentile(v,p)),3)

for i in (1,2,3,4):
    rows = json.loads(pathlib.Path(f'analysis/ref{i}-probe3.json').read_text(encoding='utf-8'))
    t  = np.array([r['t'] for r in rows])
    fd = np.array([r.get('framediff', 0.0) for r in rows])
    dur = float(t[-1])

    # склейка = резкий скачок картинки; порог от собственного шума ролика
    thr = max(12.0, float(np.percentile(fd, 97)))
    cuts = [float(t[k]) for k in range(1, len(rows)) if fd[k] > thr]
    # схлопываем соседние пробы одной склейки
    merged = []
    for c in cuts:
        if not merged or c - merged[-1] > 0.25: merged.append(c)
    shots = np.diff([0.0] + merged + [dur])

    # зум внутри плана: перемножаем масштаб между склейками
    zoom_runs, cur, start = [], 1.0, 0.0
    cut_set = set(round(c,3) for c in merged)
    for k, r in enumerate(rows):
        if round(float(t[k]),3) in cut_set:
            if t[k]-start > 0.4: zoom_runs.append((start, float(t[k]), cur))
            cur, start = 1.0, float(t[k])
        s = r.get('scale')
        if s and r.get('inliers', 0) >= 12 and 0.9 < s < 1.1:
            cur *= s
    if dur - start > 0.4: zoom_runs.append((start, dur, cur))
    zoomed = [z for z in zoom_runs if abs(z[2]-1) > 0.012]
    speeds = [abs(z[2]-1)*100/(z[1]-z[0]) for z in zoomed]
    ins  = [z for z in zoomed if z[2] > 1]

    # субтитры: смена слова = провал IoU
    ious = [(r['t'], r.get('text_iou',1.0), r.get('text_area',0)) for r in rows]
    changes = [tt for tt,io,ar in ious if io < 0.35 and ar > 0]
    words = []
    for c in changes:
        if not words or c - words[-1] > 0.12: words.append(c)
    holds = np.diff(words) if len(words) > 2 else np.array([])

    print(f"\n===== ref{i} ({dur:.0f} с) =====")
    print(f"СКЛЕЙКИ: {len(merged)} шт = 1 каждые {dur/max(1,len(merged)):.2f} с (порог смены картинки {thr:.0f})")
    print(f"  длина плана: p10={pctl(shots,10)}с p25={pctl(shots,25)}с медиана={pctl(shots,50)}с p75={pctl(shots,75)}с p90={pctl(shots,90)}с max={pctl(shots,100)}с")
    print(f"  планов короче 1 с: {int((shots<1).sum())} из {len(shots)} ({100*int((shots<1).sum())//len(shots)}%)")
    print(f"ЗУМЫ: планов с движением кадра {len(zoomed)} из {len(zoom_runs)} ({100*len(zoomed)//max(1,len(zoom_runs))}%), из них наездов {len(ins)}, отъездов {len(zoomed)-len(ins)}")
    if zoomed:
        amps = [abs(z[2]-1)*100 for z in zoomed]
        print(f"  величина за план, %: p25={pctl(amps,25)} медиана={pctl(amps,50)} p75={pctl(amps,75)} p90={pctl(amps,90)}")
        print(f"  скорость, %/с: p25={pctl(speeds,25)} медиана={pctl(speeds,50)} p75={pctl(speeds,75)}")
    print(f"СУБТИТРЫ: смен текста {len(words)} = {len(words)/dur*60:.0f} в минуту")
    if len(holds):
        print(f"  слово держится: p25={pctl(holds,25)}с медиана={pctl(holds,50)}с p75={pctl(holds,75)}с")
