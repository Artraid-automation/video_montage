#!/usr/bin/env python3
"""Сводит измерения четырёх референсов в один численный профиль стиля.
Значения — медиана по роликам; в скобках диапазон между роликами."""
import json, pathlib, numpy as np

REFS = (1,2,3,4)
def load(n, tag): return json.loads(pathlib.Path(f'analysis/ref{n}-{tag}.json').read_text(encoding='utf-8'))
def med(v): return round(float(np.median(v)),2) if len(v) else None

per_ref = {}
for i in REFS:
    r2, r3 = load(i,'probe2'), load(i,'probe3')
    full = [r['face'] for r in r2 if 'face' in r and r['face']['cy_pct'] < 55]
    caps = [r['cap'] for r in r2 if 'cap' in r]
    gap  = [r['cap']['top_pct']-r['face']['chin_pct'] for r in r2
            if 'cap' in r and 'face' in r and r['face']['cy_pct']<55
            and r['cap']['top_pct']>r['face']['chin_pct']]
    t  = np.array([r['t'] for r in r3]); fd = np.array([r.get('framediff',0.) for r in r3])
    thr = max(12., float(np.percentile(fd,97)))
    cuts, m = [float(t[k]) for k in range(1,len(r3)) if fd[k]>thr], []
    for c in cuts:
        if not m or c-m[-1] > 0.25: m.append(c)
    shots = np.diff([0.]+m+[float(t[-1])])
    words = []
    for tt in [r['t'] for r in r3 if r.get('text_iou',1.) < 0.35 and r.get('text_area',0) > 0]:
        if not words or tt-words[-1] > 0.12: words.append(tt)
    # речь: паузы между словами и привязка склеек к стыкам слов
    wj = pathlib.Path(f'analysis/ref{i}-words.json')
    sp = {}
    if wj.exists():
        w = json.loads(wj.read_text(encoding='utf-8'))
        gaps = [round(w[k]['s']-w[k-1]['e'],3) for k in range(1,len(w))]
        gaps = [g for g in gaps if g >= 0]
        bounds = [(w[k-1]['e']+w[k]['s'])/2 for k in range(1,len(w))]
        d = [min(abs(c-b) for b in bounds) for c in m] if bounds and m else []
        sp = {"words_per_min_spoken": round(len(w)/float(t[-1])*60),
              "pause_p90_s": round(float(np.percentile(gaps,90)),3) if gaps else None,
              "pause_p99_s": round(float(np.percentile(gaps,99)),3) if gaps else None,
              "pauses_over_300ms": sum(1 for g in gaps if g > 0.3),
              "speech_share": round(sum(x['e']-x['s'] for x in w)/float(t[-1]),2),
              "cuts_on_word_boundary_share": round(sum(1 for x in d if x <= 0.12)/len(d),2) if d else None}
    # перебивки: верхняя вставка, удержавшаяся дольше 1.5 с
    rows2 = json.loads(pathlib.Path(f'analysis/ref{i}-probe2.json').read_text(encoding='utf-8'))
    tt = [r['t'] for r in rows2]; slv = [r['split'] for r in rows2]
    runs, cur = [], []
    for k, y in enumerate(slv):
        if y is not None and (not cur or abs(y-cur[-1][1]) <= 2.0): cur.append((tt[k], y))
        else:
            if len(cur) >= 2: runs.append(cur)
            cur = [(tt[k], y)] if y is not None else []
    if len(cur) >= 2: runs.append(cur)
    stable = [r for r in runs if r[-1][0]-r[0][0] >= 1.5]
    ins = {"insert_share_of_runtime": round(sum(r[-1][0]-r[0][0] for r in stable)/float(t[-1]),2),
           "insert_len_s": med([r[-1][0]-r[0][0] for r in stable]) if stable else None,
           "insert_border_pct": med([np.median([q[1] for q in r]) for r in stable]) if stable else None}

    per_ref[i] = {**sp, **ins,
        "eye_pct": med([f['eye_pct'] for f in full]),
        "face_cx_pct": med([f['cx_pct'] for f in full]),
        "face_h_pct": med([f['h_pct'] for f in full]),
        "chin_pct": med([f['chin_pct'] for f in full]),
        "shot_s": med(shots),
        "cut_every_s": round(float(t[-1])/max(1,len(m)),2),
        "short_shot_share": round(float((shots<1).mean()),2),
        "caption_glyph_pct": med([c['glyph_pct'] for c in caps]),
        "caption_bottom_pct": med([c['bot_pct'] for c in caps]),
        "caption_width_pct": med([c['w_pct'] for c in caps]),
        "caption_gap_below_chin_pct": med(gap),
        "caption_hold_s": med(np.diff(words)) if len(words)>2 else None,
        "words_per_min": round(len(words)/float(t[-1])*60),
        "single_line_share": round(sum(1 for c in caps if c['lines']==1)/max(1,len(caps)),2),
    }

keys = list(per_ref[REFS[0]].keys())
profile = {}
for k in keys:
    vals = [per_ref[i][k] for i in REFS if per_ref[i][k] is not None]
    profile[k] = {"value": round(float(np.median(vals)),2),
                  "range": [round(min(vals),2), round(max(vals),2)],
                  "n_refs": len(vals)}

out = {
    "version": "measured-v1",
    "measured_on": "2026-08-25",
    "source": {"clips": len(REFS), "resolution": "1080x1920", "fps": 60,
               "durations_s": [132, 84, 158, 220],
               "note": "четыре референса одного автора; значения — медиана по роликам"},
    "units": "проценты от высоты кадра, если не указано иное",
    "profile": profile,
    "per_ref": per_ref,
}
pathlib.Path('../style/measured-v1.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
for k,v in profile.items():
    print(f"{k:32} {v['value']:>8}   диапазон {v['range']}")
