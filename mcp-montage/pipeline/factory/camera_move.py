"""Движение кадра: ступень крупности на склейке и медленный наезд внутри плана.

Зачем это вообще нужно. Рез паузы внутри говорящей головы — это jump cut: фон и поза
почти те же, и стык «дёргает». В измеренных референсах он замаскирован двумя приёмами
сразу: при склейке крупность меняется на 11–20%, а внутри плана кадр медленно идёт
на зрителя — движение есть в 62–80% планов, наездов вчетверо-всемеро больше отъездов,
скорость 1.9–3.5% в секунду (style/REFERENCE_TEARDOWN.md, раздел 4).

То есть движение здесь не украшение, а обслуживание реза пауз. Поэтому модуль живёт
рядом с ними, а числа берёт из стиля, а не из кода.

Раскладка детерминированная: одинаковый вход даёт одинаковый план, иначе повторный
рендер после `resume` пересобрал бы кадр иначе и сломал бы переиспользование по отпечатку.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

DEFAULTS: dict[str, float] = {
    "zoom_share": 0.70,
    "zoom_rate_pct_per_s": 2.5,
    "zoom_in_share": 0.80,
    "zoom_max_pct": 12.0,
    "cut_scale_step_pct": 15.0,
    "cut_scale_step_min_pct": 9.0,
    "cut_scale_step_max_pct": 25.0,
}


def _setting(camera: dict[str, Any] | None, key: str) -> float:
    value = (camera or {}).get(key)
    if value is None:
        return float(DEFAULTS[key])
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"camera setting {key} must be finite, got {value!r}")
    return number


def _dice(seed: str, salt: str) -> float:
    """Ровное псевдослучайное число из имени — повторяемое между запусками."""
    digest = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def shot_plan(
    shots: list[dict[str, Any]],
    *,
    camera: dict[str, Any] | None = None,
    seed: str = "segment",
) -> list[dict[str, Any]]:
    """План движения для последовательности планов.

    На вход — планы с `id` и `duration_s`. На выходе для каждого: стартовая крупность
    (ступень относительно предыдущего плана) и наезд к концу плана.
    """
    zoom_share = _setting(camera, "zoom_share")
    rate = _setting(camera, "zoom_rate_pct_per_s")
    zoom_in_share = _setting(camera, "zoom_in_share")
    zoom_max = _setting(camera, "zoom_max_pct")
    step_target = _setting(camera, "cut_scale_step_pct")
    step_min = _setting(camera, "cut_scale_step_min_pct")
    step_max = _setting(camera, "cut_scale_step_max_pct")
    if not 0.0 <= zoom_share <= 1.0:
        raise ValueError("zoom_share must be between 0 and 1")
    if not 0.0 <= zoom_in_share <= 1.0:
        raise ValueError("zoom_in_share must be between 0 and 1")
    if step_min > step_max:
        raise ValueError("cut_scale_step_min_pct must not exceed cut_scale_step_max_pct")

    plan: list[dict[str, Any]] = []
    previous_scale = 1.0
    for index, shot in enumerate(shots):
        shot_id = str(shot.get("id") or f"shot-{index + 1:03d}")
        duration = float(shot.get("duration_s") or 0.0)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError(f"shot {shot_id} has invalid duration")

        if index == 0:
            start_scale = 1.0
            step_pct = 0.0
        else:
            spread = max(0.0, min(step_target - step_min, step_max - step_target))
            step_pct = step_target + (_dice(seed, f"{shot_id}:step") * 2.0 - 1.0) * spread
            step_pct = max(step_min, min(step_max, step_pct))
            # Крупность гуляет вокруг исходной: два наезда подряд без отхода
            # довели бы лицо до макро к середине ролика.
            closer = previous_scale <= 1.0 or _dice(seed, f"{shot_id}:dir") < 0.35
            start_scale = previous_scale * (1.0 + step_pct / 100.0) if closer else previous_scale / (1.0 + step_pct / 100.0)
            start_scale = max(1.0, min(1.0 + step_max / 100.0, start_scale))

        moves = _dice(seed, f"{shot_id}:move") < zoom_share
        zoom_pct = 0.0
        if moves and duration > 0:
            magnitude = min(zoom_max, rate * duration)
            forward = _dice(seed, f"{shot_id}:sign") < zoom_in_share
            zoom_pct = magnitude if forward else -magnitude
        end_scale = max(1.0, start_scale * (1.0 + zoom_pct / 100.0))

        plan.append({
            "shot_id": shot_id,
            "duration_s": round(duration, 6),
            "cut_step_pct": round(step_pct, 3),
            "start_scale": round(start_scale, 5),
            "end_scale": round(end_scale, 5),
            "zoom_pct": round(zoom_pct, 3),
            "moves": bool(moves and duration > 0 and abs(zoom_pct) > 1e-6),
        })
        previous_scale = start_scale
    return plan


def zoom_filter(
    entry: dict[str, Any], *, width: int, height: int, fps: int, supersample: int = 2
) -> str:
    """Фильтр ffmpeg для одного плана: наезд от start_scale к end_scale.

    Кадр сперва увеличивается, и только потом идёт zoompan: он позиционирует окно
    целыми пикселями, и на исходном разрешении медленный наезд заметно дрожит.
    """
    if width <= 0 or height <= 0 or fps <= 0:
        raise ValueError("zoom filter needs positive width, height and fps")
    start = float(entry["start_scale"])
    end = float(entry["end_scale"])
    duration = max(float(entry.get("duration_s") or 0.0), 1.0 / fps)
    frames = max(1, int(round(duration * fps)))
    ss = max(1, int(supersample))
    if abs(end - start) < 1e-6:
        # Статичный план: обычный кроп по центру, без покадрового пересчёта.
        # `fps` обязателен и здесь: без него неподвижный план выходил в частоте
        # исходника, движущийся — в частоте профиля, и склейка разнородных частот
        # затыкала стыки стоп-кадрами (замер 30.08: 21 план из 50 шёл в 25 к/с).
        if abs(start - 1.0) < 1e-6:
            return f"scale={width}:{height},fps={fps}"
        return (
            f"scale={width * ss}:{height * ss},"
            f"crop=w=iw/{start:.5f}:h=ih/{start:.5f},"
            f"scale={width}:{height},fps={fps}"
        )
    per_frame = (end - start) / float(frames)
    # `fps` ДО zoompan обязателен: счётчик `on` идёт по входным кадрам, и без приведения
    # частоты 60-кадровый исходник проходит вдвое больше шагов, чем заложено в план
    # (проверено рендером: заказ +7.5% превращался в +45%).
    # min/max — предохранитель: даже если кадров придёт больше, масштаб встанет на конечный.
    limit = f"min({start:.5f}+{per_frame:.8f}*on,{end:.5f})" if end > start else (
        f"max({start:.5f}{per_frame:+.8f}*on,{end:.5f})"
    )
    return (
        f"scale={width * ss}:{height * ss},fps={fps},"
        f"zoompan=z='{limit}'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={width}x{height}:fps={fps}"
    )


def describe(plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка плана в тех же величинах, в которых мерился референс."""
    if not plan:
        return {"shots": 0, "moving_share": 0.0, "zoom_in_share": 0.0,
                "median_step_pct": 0.0, "median_zoom_pct": 0.0}
    moving = [item for item in plan if item["moves"]]
    steps = sorted(item["cut_step_pct"] for item in plan[1:]) or [0.0]
    zooms = sorted(abs(item["zoom_pct"]) for item in moving) or [0.0]
    ins = sum(1 for item in moving if item["zoom_pct"] > 0)
    return {
        "shots": len(plan),
        "moving_share": round(len(moving) / len(plan), 3),
        "zoom_in_share": round(ins / len(moving), 3) if moving else 0.0,
        "median_step_pct": round(steps[len(steps) // 2], 3),
        "median_zoom_pct": round(zooms[len(zooms) // 2], 3),
    }
