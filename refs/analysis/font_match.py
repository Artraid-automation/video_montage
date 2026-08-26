#!/usr/bin/env python3
"""Опознание гарнитуры: маска слова из видео сравнивается с тем же словом,
отрисованным каждым кандидатом. Сравнение по форме, а не по названию."""
import json, pathlib, sys, cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

VIDEO = 'src/ref4.mp4'; WORDS = 'analysis/ref4-words.json'
FONTS = sorted(pathlib.Path('fonts').glob('*.ttf'))

def white_text_mask(frame):
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = ((hsv[:,:,2] > 225) & (hsv[:,:,1] < 55)).astype(np.uint8)
    band = np.zeros_like(m); band[int(h*0.40):int(h*0.72), :] = 1
    m = m*band
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = [i for i in range(1,n) if stats[i][4] > 200 and 0.015*h < stats[i][3] < 0.08*h]
    if len(keep) < 3: return None
    ys = [stats[i][1] for i in keep]; med = np.median(ys)
    keep = [i for i in keep if abs(stats[i][1]-med) < 0.02*h]
    if len(keep) < 3: return None
    out = np.zeros_like(m)
    for i in keep: out[lab == i] = 1
    ys, xs = np.where(out>0)
    return out[ys.min():ys.max()+1, xs.min():xs.max()+1]

def render(fontpath, text, px):
    for wght in (900, 800, 700):
        try:
            f = ImageFont.truetype(str(fontpath), px)
            try: f.set_variation_by_axes([wght])
            except Exception:
                if wght != 700: continue
            img = Image.new('L', (px*len(text)+px*2, px*3), 0)
            ImageDraw.Draw(img).text((px, px), text, font=f, fill=255)
            a = np.array(img)
            ys, xs = np.where(a > 128)
            if len(ys) == 0: continue
            return a[ys.min():ys.max()+1, xs.min():xs.max()+1] > 128, wght
        except Exception:
            continue
    return None, None

def compare(ref, cand):
    H = 120
    def norm(m):
        h, w = m.shape
        return cv2.resize(m.astype(np.uint8), (max(1,int(w*H/h)), H), interpolation=cv2.INTER_AREA) > 0.5
    a, b = norm(ref), norm(cand)
    W = max(a.shape[1], b.shape[1])
    a = np.pad(a, ((0,0),(0,W-a.shape[1]))); b = np.pad(b, ((0,0),(0,W-b.shape[1])))
    iou = (a & b).sum() / max(1, (a | b).sum())
    ar = ref.shape[1]/ref.shape[0]; ac = cand.shape[1]/cand.shape[0]
    ink_r = ref.mean(); ink_c = cand.mean()
    return {"iou": round(float(iou),4),
            "aspect_ref": round(ar,3), "aspect_cand": round(ac,3),
            "aspect_err": round(abs(ar-ac)/ar,3),
            "ink_err": round(abs(ink_r-ink_c)/ink_r,3)}

words = json.loads(pathlib.Path(WORDS).read_text(encoding='utf-8'))
cands = [w for w in words if len(w['w'].strip('.,!?—')) >= 8][:60]
cap = cv2.VideoCapture(VIDEO); fps = cap.get(cv2.CAP_PROP_FPS)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
want = {}
for w in cands:
    want[int(round((w['s']+w['e'])/2*fps))] = w['w'].strip('.,!?—').lower()
samples, idx = [], -1
while True:
    idx += 1
    if idx >= total: break
    if idx not in want:
        if not cap.grab(): break
        continue
    ok, fr = cap.read()
    if not ok: break
    m = white_text_mask(fr)
    if m is not None and m.shape[1] > 120:
        samples.append((want[idx], m))
cap.release()
print(f"взято образцов: {len(samples)}")
scores = {}
for fp in FONTS:
    per = []
    for text, ref in samples[:14]:
        cand, wght = render(fp, text, 96)
        if cand is None: continue
        per.append(compare(ref, cand))
    if not per: continue
    scores[fp.stem] = {
        "iou": round(float(np.mean([p['iou'] for p in per])),4),
        "aspect_err": round(float(np.mean([p['aspect_err'] for p in per])),3),
        "ink_err": round(float(np.mean([p['ink_err'] for p in per])),3),
        "n": len(per)}
rank = sorted(scores.items(), key=lambda kv: (-kv[1]['iou'], kv[1]['aspect_err']))
print(f"\n{'шрифт':14} {'совпадение':>11} {'ошибка ширины':>14} {'ошибка веса':>12}")
for k,v in rank:
    print(f"{k:14} {v['iou']:>11.3f} {v['aspect_err']:>14.3f} {v['ink_err']:>12.3f}")
pathlib.Path('analysis/font-match.json').write_text(json.dumps(dict(rank), ensure_ascii=False, indent=2), encoding='utf-8')
