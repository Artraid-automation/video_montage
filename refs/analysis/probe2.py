#!/usr/bin/env python3
"""Разбор v2: разделяет полный кадр и split-screen, чистит субтитры по обводке,
классифицирует цвет текста, пишет временной ряд крупности для поиска зумов."""
import sys, json, cv2, numpy as np, pathlib

STEP = 0.20
W = 540

def cascades():
    b = pathlib.Path(cv2.data.haarcascades)
    return (cv2.CascadeClassifier(str(b/"haarcascade_frontalface_default.xml")),
            cv2.CascadeClassifier(str(b/"haarcascade_profileface.xml")))

def face(gray, cs):
    best = None
    for c in cs:
        for (x,y,w,h) in c.detectMultiScale(gray, 1.15, 5, minSize=(40,40)):
            if best is None or w*h > best[2]*best[3]:
                best = (int(x),int(y),int(w),int(h))
        if best: break
    return best

def split_line(frame):
    """Горизонтальная граница вставки: строка с резким скачком содержания в 30–70% высоты."""
    h = frame.shape[0]
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    rows = g.mean(axis=1)
    lo, hi = int(h*0.30), int(h*0.70)
    d = np.abs(np.diff(rows))[lo:hi]
    if d.size == 0: return None
    k = int(np.argmax(d))
    if d[k] < 12: return None
    y = lo + k
    top, bot = g[:y], g[y:]
    # содержание половин должно реально различаться
    if abs(top.mean() - bot.mean()) < 10 and abs(top.std() - bot.std()) < 10:
        return None
    return round(100*y/h, 1)

def color_class(bgr):
    b,g,r = bgr
    if r > 180 and g > 170 and b > 160: return "белый"
    if r > 170 and g > 150 and b < 120: return "жёлтый"
    if g > 150 and r < 140 and b < 140: return "зелёный"
    return "иной"

def captions(frame):
    """Текст = яркий/жёлтый компонент, обведённый тёмным контуром."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v, s, hh = hsv[:,:,2], hsv[:,:,1], hsv[:,:,0]
    core = (((v>225)&(s<60)) | ((v>180)&(s>90)&(hh>15)&(hh<45)) | ((v>170)&(s>90)&(hh>45)&(hh<85))).astype(np.uint8)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(
        cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8)), 8)
    glyphs = []
    for i in range(1, n):
        x,y,cw,ch,area = stats[i]
        if area < 120 or ch < 0.012*h or ch > 0.09*h or cw > 0.5*w: continue
        pad = max(3, ch//6)
        y0,y1 = max(0,y-pad), min(h,y+ch+pad); x0,x1 = max(0,x-pad), min(w,x+cw+pad)
        ring = gray[y0:y1, x0:x1].copy()
        inner = ring[pad:-pad, pad:-pad] if ring.shape[0]>2*pad and ring.shape[1]>2*pad else None
        if inner is None: continue
        s_ring = float(np.median(np.concatenate([ring[0], ring[-1], ring[:,0], ring[:,-1]])))
        if s_ring > 90: continue                     # нет тёмной обводки — не субтитр
        m = (lab[y:y+ch, x:x+cw] == i)
        px = frame[y:y+ch, x:x+cw][m]
        glyphs.append({"x":int(x),"y":int(y),"w":int(cw),"h":int(ch),
                       "bgr":[float(px[:,c].mean()) for c in range(3)]})
    if not glyphs: return None
    # строки: группировка по вертикали
    glyphs.sort(key=lambda g: g["y"])
    lines, cur = [], [glyphs[0]]
    for g in glyphs[1:]:
        if abs(g["y"] - cur[-1]["y"]) <= 0.35*max(g["h"], cur[-1]["h"]):
            cur.append(g)
        else:
            lines.append(cur); cur = [g]
    lines.append(cur)
    lines = [l for l in lines if len(l) >= 2]
    if not lines: return None
    main = max(lines, key=lambda l: sum(g["w"] for g in l))
    x0 = min(g["x"] for g in main); x1 = max(g["x"]+g["w"] for g in main)
    y0 = min(g["y"] for g in main); y1 = max(g["y"]+g["h"] for g in main)
    bgr = [float(np.mean([g["bgr"][c] for g in main])) for c in range(3)]
    return {"top_pct": round(100*y0/h,1), "bot_pct": round(100*y1/h,1),
            "cx_pct": round(100*(x0+x1)/2/w,1), "w_pct": round(100*(x1-x0)/w,1),
            "cap_h_pct": round(100*(y1-y0)/h,2),
            "glyph_pct": round(100*float(np.median([g["h"] for g in main]))/h,2),
            "lines": len(lines), "color": color_class(bgr[::-1]),
            "bgr": [round(c) for c in bgr]}

def main(path, out):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cs = cascades(); step = max(1, int(round(STEP*fps)))
    rows, idx = [], -1
    while True:
        idx += 1
        if idx >= total: break
        if idx % step:
            if not cap.grab(): break
            continue
        ok, frame = cap.read()
        if not ok: break
        H0, W0 = frame.shape[:2]
        sm = cv2.resize(frame, (W, int(W*H0/W0)))
        h, w = sm.shape[:2]
        f = face(cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY), cs)
        sl = split_line(sm)
        c = captions(sm)
        hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)
        r = {"t": round(idx/fps, 2), "split": sl,
             "sat": round(float(hsv[:,:,1].mean()),1),
             "val": round(float(hsv[:,:,2].mean()),1)}
        if f:
            x,y,fw,fh = f
            r["face"] = {"h_pct": round(100*fh/h,2), "cx_pct": round(100*(x+fw/2)/w,2),
                         "cy_pct": round(100*(y+fh/2)/h,2),
                         "eye_pct": round(100*(y+fh*0.42)/h,2),
                         "chin_pct": round(100*(y+fh)/h,2)}
        if c: r["cap"] = c
        rows.append(r)
    cap.release()
    pathlib.Path(out).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    sp = sum(1 for r in rows if r["split"])
    print(f"{pathlib.Path(path).name}: {len(rows)} проб | лицо {sum(1 for r in rows if 'face' in r)} | субтитры {sum(1 for r in rows if 'cap' in r)} | вставка сверху {sp} ({100*sp//len(rows)}%)")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
