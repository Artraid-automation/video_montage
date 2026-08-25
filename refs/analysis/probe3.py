#!/usr/bin/env python3
"""Проход 3: настоящее движение кадра (масштаб по фону, не по лицу) и тайминг субтитров.
Масштаб считается аффинным преобразованием по точкам ПЕРИФЕРИИ кадра — голова в центре
двигается сама по себе и на зум не влияет."""
import sys, json, cv2, numpy as np, pathlib

STEP = 0.05        # шаг проб — на 60 fps это каждый третий кадр
W = 360            # рабочая ширина

def periphery_mask(h, w):
    m = np.zeros((h, w), np.uint8); m[:] = 255
    m[int(h*0.15):int(h*0.85), int(w*0.20):int(w*0.80)] = 0   # центр (человек) не берём
    return m

def text_mask(frame):
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v, s, hh = hsv[:,:,2], hsv[:,:,1], hsv[:,:,0]
    m = (((v>225)&(s<60)) | ((v>180)&(s>90)&(hh>15)&(hh<45))).astype(np.uint8)
    band = np.zeros_like(m); band[int(h*0.38):int(h*0.80), :] = 1
    return m*band

def main(path, out):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(STEP*fps)))
    prev_gray = prev_mask = None
    mask_p = None
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
        if mask_p is None: mask_p = periphery_mask(h, w)
        gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
        tm = text_mask(sm)
        r = {"t": round(idx/fps, 3)}
        if prev_gray is not None:
            p0 = cv2.goodFeaturesToTrack(prev_gray, 250, 0.01, 8, mask=mask_p)
            if p0 is not None and len(p0) >= 12:
                p1, stt, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, p0, None,
                                                      winSize=(21,21), maxLevel=3)
                good0, good1 = p0[stt==1], p1[stt==1]
                if len(good0) >= 12:
                    M, inl = cv2.estimateAffinePartial2D(good0, good1, method=cv2.RANSAC,
                                                         ransacReprojThreshold=2.0)
                    if M is not None:
                        sc = float(np.sqrt(M[0,0]**2 + M[0,1]**2))
                        r["scale"] = round(sc, 5)
                        r["dx"] = round(float(M[0,2]), 2); r["dy"] = round(float(M[1,2]), 2)
                        r["inliers"] = int(inl.sum()) if inl is not None else 0
            # смена картинки целиком (склейка)
            r["framediff"] = round(float(np.mean(cv2.absdiff(gray, prev_gray))), 2)
        # субтитр: площадь и центр текстовой маски + признак смены слова
        area = int(tm.sum())
        r["text_area"] = area
        if prev_mask is not None and (area > 0 or prev_mask.sum() > 0):
            inter = int((tm & prev_mask).sum()); union = int((tm | prev_mask).sum())
            r["text_iou"] = round(inter/union, 3) if union else 1.0
        if area > 0:
            ys, xs = np.where(tm > 0)
            r["text_box"] = [round(100*xs.min()/w,1), round(100*ys.min()/h,1),
                             round(100*xs.max()/w,1), round(100*ys.max()/h,1)]
        prev_gray, prev_mask = gray, tm
        rows.append(r)
    cap.release()
    pathlib.Path(out).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"{pathlib.Path(path).name}: {len(rows)} проб, масштаб посчитан в {sum(1 for r in rows if 'scale' in r)}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
