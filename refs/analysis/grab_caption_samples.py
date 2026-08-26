#!/usr/bin/env python3
"""Вырезает чистые маски строк субтитра и складывает в один лист с номерами."""
import cv2, numpy as np, pathlib, json
VIDEO='src/ref4.mp4'
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
    out=np.zeros_like(m)
    for i in keep: out[lab==i]=255
    ys,xs=np.where(out>0)
    return out[ys.min():ys.max()+1, xs.min():xs.max()+1]
cap=cv2.VideoCapture(VIDEO); fps=cap.get(cv2.CAP_PROP_FPS)
total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
picks=[]; idx=-1; last=-99
while True:
    idx+=1
    if idx>=total: break
    if idx % int(fps*1.3):
        if not cap.grab(): break
        continue
    ok,fr=cap.read()
    if not ok: break
    m=mask(fr)
    if m is not None and m.shape[1]>380 and m.shape[0]>28:
        picks.append((round(idx/fps,2), m))
        if len(picks)>=10: break
cap.release()
H=90; rows=[]
for i,(t,m) in enumerate(picks):
    r=cv2.resize(m,(int(m.shape[1]*H/m.shape[0]),H))
    lbl=np.zeros((H,120),np.uint8)
    cv2.putText(lbl,f"#{i}",(6,60),cv2.FONT_HERSHEY_SIMPLEX,1.4,255,3)
    rows.append(np.hstack([lbl,r]))
W=max(r.shape[1] for r in rows)
sheet=np.vstack([np.pad(r,((6,6),(0,W-r.shape[1]))) for r in rows])
cv2.imwrite('analysis/frames/caption-samples.png', 255-sheet)
pathlib.Path('analysis/caption-samples.json').write_text(json.dumps([t for t,_ in picks]))
for i,(t,m) in enumerate(picks): print(f"#{i} t={t} размер {m.shape[1]}x{m.shape[0]}")
