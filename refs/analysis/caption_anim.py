#!/usr/bin/env python3
"""Анимация субтитра: что происходит с текстом в первые кадры после смены слова.
Шаг — один кадр (1/60 с), окно от -0.05 до +0.35 с вокруг смены."""
import sys, json, cv2, numpy as np, pathlib

W = 540
def text_mask(frame):
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v, s, hh = hsv[:,:,2], hsv[:,:,1], hsv[:,:,0]
    m = (((v>225)&(s<60)) | ((v>180)&(s>90)&(hh>15)&(hh<45))).astype(np.uint8)
    band = np.zeros_like(m); band[int(h*0.38):int(h*0.80), :] = 1
    return m*band

def measure(frame):
    tm = text_mask(cv2.resize(frame, (W, int(W*frame.shape[0]/frame.shape[1]))))
    if tm.sum() == 0: return None
    ys, xs = np.where(tm > 0)
    h, w = tm.shape
    return {"area": int(tm.sum()),
            "w": round(100*(xs.max()-xs.min()+1)/w, 2),
            "h": round(100*(ys.max()-ys.min()+1)/h, 2),
            "cy": round(100*(ys.min()+ys.max())/2/h, 2),
            "cx": round(100*(xs.min()+xs.max())/2/w, 2)}

def main(path, probe3, out, limit=40):
    rows = json.loads(pathlib.Path(probe3).read_text(encoding='utf-8'))
    ch = []
    for r in rows:
        if r.get('text_iou', 1.0) < 0.35 and r.get('text_area', 0) > 0:
            if not ch or r['t'] - ch[-1] > 0.5: ch.append(r['t'])
    ch = ch[:limit]
    cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # Один последовательный проход: seek по кадру на 60 fps уже однажды съел десять минут.
    windows = {}
    for c in ch:
        base = int(round(c*fps))
        for k in range(-3, 22):
            windows.setdefault(base+k, []).append((c, round(k/fps, 4)))
    buckets = {c: [] for c in ch}
    idx = -1
    while True:
        idx += 1
        if idx >= total: break
        if idx not in windows:
            if not cap.grab(): break
            continue
        ok, fr = cap.read()
        if not ok: break
        m = measure(fr)
        for c, dt in windows[idx]:
            buckets[c].append({"dt": dt, **(m or {"area": 0})})
    events = [{"t": c, "seq": sorted(v, key=lambda x: x["dt"])} for c, v in buckets.items() if v]
    cap.release()
    pathlib.Path(out).write_text(json.dumps(events, ensure_ascii=False), encoding='utf-8')
    print(f"{pathlib.Path(path).name}: разобрано {len(events)} появлений слова")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
