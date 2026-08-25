#!/usr/bin/env python3
"""Численный разбор референса: крупность плана (лицо), зона субтитров, цвет.
Шаг 0.25 с. Анализ на уменьшенной копии, координаты нормируются в доли кадра."""
import sys, json, cv2, numpy as np, pathlib

STEP = 0.25
W = 540  # рабочая ширина

def face_cascades():
    base = pathlib.Path(cv2.data.haarcascades)
    return [cv2.CascadeClassifier(str(base / n)) for n in
            ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml")]

def largest_face(gray, cascades):
    best = None
    for c in cascades:
        for (x, y, w, h) in c.detectMultiScale(gray, 1.15, 5, minSize=(40, 40)):
            if best is None or w * h > best[2] * best[3]:
                best = (int(x), int(y), int(w), int(h))
        if best is not None:
            break
    return best

def caption_box(frame):
    """Яркий/жёлтый текст в нижних 60% кадра, окружённый тёмной обводкой."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v, s = hsv[:, :, 2], hsv[:, :, 1]
    bright = ((v > 225) & (s < 60)).astype(np.uint8)          # белый
    yellow = ((v > 190) & (s > 90) & (hsv[:, :, 0] > 15) & (hsv[:, :, 0] < 40)).astype(np.uint8)
    mask = cv2.bitwise_or(bright, yellow)
    mask[: int(h * 0.35), :] = 0                               # верх не смотрим
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 25), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = [s_ for s_ in stats[1:] if s_[4] > 300 and 0.012 * h < s_[3] < 0.12 * h and s_[2] > 0.05 * w]
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
    glyph = float(np.median([b[3] for b in boxes]))
    ys, xs = np.where(mask[y0:y1, x0:x1] > 0)
    if len(ys) == 0:
        return None
    px = frame[y0:y1, x0:x1][ys, xs]
    return {"x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0),
            "glyph_h": glyph, "bgr": [float(px[:, i].mean()) for i in range(3)]}

def main(path, out):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    casc = face_cascades()
    # Последовательное чтение: seek по кадру на 60 fps даёт часы вместо минут.
    step_frames = max(1, int(round(STEP * fps)))
    rows, idx = [], -1
    while True:
        idx += 1
        if idx >= total:
            break
        if idx % step_frames:
            if not cap.grab():
                break
            continue
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        H0, W0 = frame.shape[:2]
        small = cv2.resize(frame, (W, int(W * H0 / W0)))
        h, w = small.shape[:2]
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        f = largest_face(gray, casc)
        cap_box = caption_box(small)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        row = {"t": round(t, 2),
               "sat": round(float(hsv[:, :, 1].mean()), 1),
               "val": round(float(hsv[:, :, 2].mean()), 1),
               "contrast": round(float(gray.std()), 1)}
        if f:
            x, y, fw, fh = f
            row["face"] = {"h_pct": round(100 * fh / h, 2), "w_pct": round(100 * fw / w, 2),
                           "cx_pct": round(100 * (x + fw / 2) / w, 2),
                           "cy_pct": round(100 * (y + fh / 2) / h, 2),
                           "eye_y_pct": round(100 * (y + fh * 0.4) / h, 2)}
        if cap_box:
            row["cap"] = {"top_pct": round(100 * cap_box["y"] / h, 2),
                          "bot_pct": round(100 * (cap_box["y"] + cap_box["h"]) / h, 2),
                          "cx_pct": round(100 * (cap_box["x"] + cap_box["w"] / 2) / w, 2),
                          "w_pct": round(100 * cap_box["w"] / w, 2),
                          "glyph_pct": round(100 * cap_box["glyph_h"] / h, 2),
                          "bgr": [round(c) for c in cap_box["bgr"]]}
        rows.append(row)
    cap.release()
    pathlib.Path(out).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"{pathlib.Path(path).name}: {len(rows)} проб, лицо в {sum(1 for r in rows if 'face' in r)}, субтитры в {sum(1 for r in rows if 'cap' in r)}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
