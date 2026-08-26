#!/usr/bin/env python3
"""Опознание гарнитуры по образцам с ПРОЧИТАННЫМ текстом (не по транскрипту)."""
import pathlib, json, cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

SAMPLES = [(20.8,"частично"), (22.1,"хранились"), (23.4,"Воронежской"),
           (29.9,"предыдущие"), (31.2,"Татарстане"), (33.8,"прежнему")]
FONTS = sorted(pathlib.Path('fonts').glob('*.ttf'))

def mask(frame):
    h,w=frame.shape[:2]
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    m=((hsv[:,:,2]>225)&(hsv[:,:,1]<55)).astype(np.uint8)
    band=np.zeros_like(m); band[int(h*0.40):int(h*0.72),:]=1
    m=m*band
    n,lab,st,_=cv2.connectedComponentsWithStats(m,8)
    keep=[i for i in range(1,n) if st[i][4]>200 and 0.015*h<st[i][3]<0.08*h]
    if len(keep)<3: return None
    med=np.median([st[i][1] for i in keep])
    keep=[i for i in keep if abs(st[i][1]-med)<0.02*h]
    if len(keep)<4: return None
    out=np.zeros(m.shape,bool)
    for i in keep: out[lab==i]=True
    ys,xs=np.where(out)
    return out[ys.min():ys.max()+1, xs.min():xs.max()+1]

cap=cv2.VideoCapture('src/ref4.mp4'); fps=cap.get(cv2.CAP_PROP_FPS)
total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
want={int(round(t*fps)):txt for t,txt in SAMPLES}
refs=[]; idx=-1
while True:
    idx+=1
    if idx>=total: break
    if idx not in want:
        if not cap.grab(): break
        continue
    ok,fr=cap.read()
    if not ok: break
    m=mask(fr)
    if m is not None: refs.append((want[idx], m))
cap.release()
print("образцов с известным текстом:", [(t, m.shape) for t,m in refs])

def render(fp, text, px, wght):
    f=ImageFont.truetype(str(fp), px)
    try: f.set_variation_by_axes([wght])
    except Exception: pass
    img=Image.new('L',(px*(len(text)+3), px*3),0)
    ImageDraw.Draw(img).text((px,px), text, font=f, fill=255)
    a=np.array(img)>128
    ys,xs=np.where(a)
    return a[ys.min():ys.max()+1, xs.min():xs.max()+1]

def score(ref, cand):
    H=140
    def norm(m):
        h,w=m.shape
        return cv2.resize(m.astype(np.uint8)*255,(max(1,int(w*H/h)),H),interpolation=cv2.INTER_AREA)>127
    a,b=norm(ref),norm(cand)
    W=max(a.shape[1],b.shape[1])
    a=np.pad(a,((0,0),(0,W-a.shape[1]))); b=np.pad(b,((0,0),(0,W-b.shape[1])))
    best=0.0
    for dx in range(-8,9,2):
        bb=np.roll(b,dx,axis=1)
        iou=(a&bb).sum()/max(1,(a|bb).sum())
        best=max(best,iou)
    ar=ref.shape[1]/ref.shape[0]; ac=cand.shape[1]/cand.shape[0]
    return best, abs(ar-ac)/ar, abs(ref.mean()-cand.mean())/ref.mean()

rows=[]
for fp in FONTS:
    for wght in (900,800,700):
        try: per=[score(r, render(fp,t,110,wght)) for t,r in refs]
        except Exception: continue
        if not per: continue
        rows.append((fp.stem, wght,
                     float(np.mean([p[0] for p in per])),
                     float(np.mean([p[1] for p in per])),
                     float(np.mean([p[2] for p in per]))))
rows.sort(key=lambda r: -r[2])
print(f"\n{'шрифт':13} {'вес':>5} {'совпадение формы':>17} {'ошибка ширины':>14} {'ошибка веса':>12}")
seen=set()
for name,w,iou,ae,ie in rows:
    if name in seen: continue
    seen.add(name)
    print(f"{name:13} {w:>5} {iou:>17.3f} {ae:>14.3f} {ie:>12.3f}")
pathlib.Path('analysis/font-match.json').write_text(json.dumps(
    [{"font":n,"weight":w,"shape_iou":round(i,4),"width_err":round(a,3),"ink_err":round(k,3)}
     for n,w,i,a,k in rows], ensure_ascii=False, indent=2), encoding='utf-8')
