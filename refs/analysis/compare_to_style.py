#!/usr/bin/env python3
"""Линейка приёмки: меряет НАШ ролик тем же прибором, что и референсы, и печатает разницу.

Смысл в том, чтобы «похоже / не похоже» перестало быть спором о вкусе. Прогон даёт
таблицу расхождений по тем же величинам, в которых снят эталон.
"""
import json, pathlib, subprocess, sys
import numpy as np

REPO = pathlib.Path(__file__).resolve().parents[2]
PROBE2 = pathlib.Path(__file__).with_name("probe2.py")
PROBE3 = pathlib.Path(__file__).with_name("probe3.py")


def pctl(v, p):
    return float(np.percentile(v, p)) if len(v) else None


def measure(video: pathlib.Path, workdir: pathlib.Path) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    p2 = workdir / "probe2.json"
    p3 = workdir / "probe3.json"
    python = sys.executable
    for script, out in ((PROBE2, p2), (PROBE3, p3)):
        if not out.is_file():
            subprocess.run([python, str(script), str(video), str(out)], check=True)
    rows2 = json.loads(p2.read_text(encoding="utf-8"))
    rows3 = json.loads(p3.read_text(encoding="utf-8"))
    faces = [r["face"] for r in rows2 if "face" in r and r["face"]["cy_pct"] < 55]
    caps = [r["cap"] for r in rows2 if "cap" in r]
    t = np.array([r["t"] for r in rows3])
    fd = np.array([r.get("framediff", 0.0) for r in rows3])
    thr = max(12.0, float(np.percentile(fd, 97)))
    cuts, merged = [float(t[k]) for k in range(1, len(rows3)) if fd[k] > thr], []
    for c in cuts:
        if not merged or c - merged[-1] > 0.25:
            merged.append(c)
    shots = np.diff([0.0] + merged + [float(t[-1])])
    words = []
    for tt in [r["t"] for r in rows3 if r.get("text_iou", 1.0) < 0.35 and r.get("text_area", 0) > 0]:
        if not words or tt - words[-1] > 0.12:
            words.append(tt)
    holds = np.diff(words) if len(words) > 2 else np.array([])
    return {
        "eye_pct": pctl([f["eye_pct"] for f in faces], 50),
        "face_cx_pct": pctl([f["cx_pct"] for f in faces], 50),
        "face_h_pct": pctl([f["h_pct"] for f in faces], 50),
        "chin_pct": pctl([f["chin_pct"] for f in faces], 50),
        "caption_glyph_pct": pctl([c["glyph_pct"] for c in caps], 50),
        "caption_bottom_pct": pctl([c["bot_pct"] for c in caps], 50),
        "caption_width_pct": pctl([c["w_pct"] for c in caps], 50),
        "single_line_share": (sum(1 for c in caps if c["lines"] == 1) / len(caps)) if caps else None,
        "caption_hold_s": pctl(holds, 50) if len(holds) else None,
        "shot_s": pctl(shots, 50),
        "cut_every_s": float(t[-1]) / max(1, len(merged)),
    }


LABELS = {
    "eye_pct": "линия глаз, % сверху",
    "face_cx_pct": "центр лица по X, %",
    "face_h_pct": "высота лица, % кадра",
    "chin_pct": "подбородок, % сверху",
    "caption_glyph_pct": "высота буквы, % кадра",
    "caption_bottom_pct": "низ строки, % сверху",
    "caption_width_pct": "ширина блока, % кадра",
    "single_line_share": "доля кадров с одной строкой",
    "caption_hold_s": "слово держится, с",
    "shot_s": "длина плана, с",
    "cut_every_s": "склейка каждые, с",
}


def main(video: str, workdir: str) -> int:
    target = json.loads((REPO / "style" / "measured-v1.json").read_text(encoding="utf-8"))["profile"]
    got = measure(pathlib.Path(video), pathlib.Path(workdir))
    print(f"{'величина':34} {'эталон':>10} {'коридор':>16} {'наш ролик':>11}  вердикт")
    for key, label in LABELS.items():
        ref = target.get(key)
        mine = got.get(key)
        if ref is None or mine is None:
            print(f"{label:34} {'—':>10} {'—':>16} {('—' if mine is None else round(mine,2)):>11}  нет данных")
            continue
        low, high = ref["range"]
        pad = max(0.06 * abs(ref["value"]), 0.02)
        ok = (low - pad) <= mine <= (high + pad)
        print(f"{label:34} {ref['value']:>10.2f} {f'{low:.2f}–{high:.2f}':>16} {mine:>11.2f}  "
              f"{'в коридоре' if ok else 'РАСХОЖДЕНИЕ'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
