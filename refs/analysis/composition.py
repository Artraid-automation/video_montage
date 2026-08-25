#!/usr/bin/env python3
"""Композиция только по кадрам БЕЗ верхней вставки (лицо в верхней половине)."""
import json, pathlib, numpy as np
def p(v,q): return round(float(np.percentile(v,q)),1) if len(v) else None
print(f"{'ролик':6} {'кадров':>7} {'глаза%':>18} {'центр X%':>18} {'высота лица%':>18} {'подбородок%':>12}")
for i in (1,2,3,4):
    rows=json.loads(pathlib.Path(f'analysis/ref{i}-probe2.json').read_text(encoding='utf-8'))
    f=[r['face'] for r in rows if 'face' in r and r['face']['cy_pct']<55]
    eye=[x['eye_pct'] for x in f]; cx=[x['cx_pct'] for x in f]
    hh=[x['h_pct'] for x in f]; ch=[x['chin_pct'] for x in f]
    print(f"ref{i:<3} {len(f):>7} {str(p(eye,25))+'/'+str(p(eye,50))+'/'+str(p(eye,75)):>18} "
          f"{str(p(cx,25))+'/'+str(p(cx,50))+'/'+str(p(cx,75)):>18} "
          f"{str(p(hh,25))+'/'+str(p(hh,50))+'/'+str(p(hh,75)):>18} {p(ch,50):>12}")
print("\n(значения: p25/медиана/p75; глаза и подбородок — % от верха кадра)")
# субтитры относительно подбородка
print("\nразрыв «подбородок → верх субтитра», % высоты кадра:")
for i in (1,2,3,4):
    rows=json.loads(pathlib.Path(f'analysis/ref{i}-probe2.json').read_text(encoding='utf-8'))
    g=[r['cap']['top_pct']-r['face']['chin_pct'] for r in rows
       if 'cap' in r and 'face' in r and r['face']['cy_pct']<55 and r['cap']['top_pct']>r['face']['chin_pct']]
    print(f"  ref{i}: n={len(g)} p25={p(g,25)} медиана={p(g,50)} p75={p(g,75)}")
