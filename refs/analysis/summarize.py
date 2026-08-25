#!/usr/bin/env python3
import json, pathlib, statistics as st

def pct(vals, p):
    if not vals: return None
    s = sorted(vals); k = (len(s)-1)*p/100
    lo, hi = int(k), min(int(k)+1, len(s)-1)
    return round(s[lo] + (s[hi]-s[lo])*(k-lo), 1)

for i in (1,2,3,4):
    rows = json.loads(pathlib.Path(f'analysis/ref{i}-probe.json').read_text(encoding='utf-8'))
    faces = [r['face'] for r in rows if 'face' in r]
    caps  = [r['cap']  for r in rows if 'cap'  in r]
    fh = [f['h_pct'] for f in faces]
    print(f"\n===== ref{i}  ({len(rows)} проб = {len(rows)*0.25:.0f} с) =====")
    print(f"лицо найдено: {len(faces)}/{len(rows)} ({100*len(faces)//len(rows)}%)")
    print(f"КРУПНОСТЬ (высота лица, % кадра): p10={pct(fh,10)} p25={pct(fh,25)} медиана={pct(fh,50)} p75={pct(fh,75)} p90={pct(fh,90)} max={pct(fh,100)}")
    print(f"  глаза по вертикали, % сверху: p25={pct([f['eye_y_pct'] for f in faces],25)} медиана={pct([f['eye_y_pct'] for f in faces],50)} p75={pct([f['eye_y_pct'] for f in faces],75)}")
    print(f"  центр лица по горизонтали, %: p25={pct([f['cx_pct'] for f in faces],25)} медиана={pct([f['cx_pct'] for f in faces],50)} p75={pct([f['cx_pct'] for f in faces],75)}")
    if caps:
        print(f"СУБТИТРЫ (в {100*len(caps)//len(rows)}% проб):")
        print(f"  низ блока, % сверху: p10={pct([c['bot_pct'] for c in caps],10)} медиана={pct([c['bot_pct'] for c in caps],50)} p90={pct([c['bot_pct'] for c in caps],90)}")
        print(f"  верх блока, % сверху: медиана={pct([c['top_pct'] for c in caps],50)}")
        print(f"  высота глифа, % кадра: p25={pct([c['glyph_pct'] for c in caps],25)} медиана={pct([c['glyph_pct'] for c in caps],50)} p75={pct([c['glyph_pct'] for c in caps],75)}")
        print(f"  ширина блока, % кадра: медиана={pct([c['w_pct'] for c in caps],50)} p90={pct([c['w_pct'] for c in caps],90)}")
        print(f"  центр блока по горизонтали, %: медиана={pct([c['cx_pct'] for c in caps],50)}")
        b = [c['bgr'] for c in caps]
        print(f"  средний цвет текста BGR: {round(st.mean(x[0] for x in b))},{round(st.mean(x[1] for x in b))},{round(st.mean(x[2] for x in b))}")
    print(f"ЦВЕТ: насыщенность={pct([r['sat'] for r in rows],50)} яркость={pct([r['val'] for r in rows],50)} контраст(σ)={pct([r['contrast'] for r in rows],50)}")
