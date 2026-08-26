"""Рез пауз между словами — приём, на котором держится плотность референса.

`editorial.py` ищет паузы между высказываниями с порогом в районе секунды: это про
«убрать провал в речи». Здесь другой масштаб — промежутки между соседними словами
от десятых долей секунды. Именно из них берётся ритм: в измеренных референсах пауз
длиннее 0.3 с не остаётся вовсе, речь занимает 92–97% хронометража, а 75–85% склеек
приходятся ровно на стык слов (см. style/REFERENCE_TEARDOWN.md).

Модуль ничего не режет сам: он готовит план с числами, решение остаётся за агентом
и человеком на Gate 1.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLD_S = 0.15
DEFAULT_KEEP_S = 0.06
DEFAULT_NOISE_DB = -32.0

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def _words(source_transcript: dict[str, Any]) -> list[dict[str, Any]]:
    words = source_transcript.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("source transcript has no words: word-level pause cutting needs them")
    out: list[dict[str, Any]] = []
    for item in words:
        start = float(item.get("start_s", item.get("start", 0.0)))
        end = float(item.get("end_s", item.get("end", start)))
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError(f"invalid word timing: {item}")
        out.append({"id": str(item.get("id") or f"w{len(out) + 1:06d}"), "start_s": start, "end_s": end})
    out.sort(key=lambda item: item["start_s"])
    return out


def word_gap_cuts(
    source_transcript: dict[str, Any],
    *,
    threshold_s: float = DEFAULT_THRESHOLD_S,
    keep_s: float = DEFAULT_KEEP_S,
) -> list[dict[str, Any]]:
    """Промежутки между словами, которые стоит вырезать.

    `keep_s` остаётся на стыке специально: срез в ноль склеивает слова в кашу,
    а в референсах девяностый перцентиль паузы держится на 0.04–0.10 с.
    """
    if not math.isfinite(threshold_s) or threshold_s <= 0:
        raise ValueError("pause threshold must be finite and positive")
    if not math.isfinite(keep_s) or keep_s < 0:
        raise ValueError("keep_s must be finite and non-negative")
    if keep_s >= threshold_s:
        raise ValueError("keep_s must be shorter than the threshold, otherwise nothing is cut")
    words = _words(source_transcript)
    cuts: list[dict[str, Any]] = []
    for left, right in zip(words, words[1:]):
        gap = round(float(right["start_s"]) - float(left["end_s"]), 6)
        if gap < threshold_s:
            continue
        start = round(float(left["end_s"]) + keep_s / 2.0, 6)
        end = round(float(right["start_s"]) - keep_s / 2.0, 6)
        if end <= start:
            continue
        cuts.append({
            "id": f"gap-{left['id']}-{right['id']}",
            "after_word_id": left["id"],
            "before_word_id": right["id"],
            "gap_s": gap,
            "start_s": start,
            "end_s": end,
            "removed_s": round(end - start, 6),
            "reason": "inter-word-pause",
        })
    return cuts


def silence_windows(
    audio_path: Path, *, noise_db: float = DEFAULT_NOISE_DB, min_s: float = 0.10
) -> list[tuple[float, float]]:
    """Участки тишины по энергии сигнала. Не зависит от того, верно ли распознано слово."""
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    stream = f"{result.stdout}\n{result.stderr}"
    starts = [float(value) for value in _SILENCE_START.findall(stream)]
    ends = [float(value) for value in _SILENCE_END.findall(stream)]
    windows: list[tuple[float, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else None
        if end is None or end <= start:
            continue
        windows.append((round(start, 6), round(end, 6)))
    return windows


def confirm_with_audio(
    cuts: list[dict[str, Any]], windows: list[tuple[float, float]], *, min_overlap: float = 0.5
) -> list[dict[str, Any]]:
    """Помечает, подтверждается ли каждый рез тишиной в звуке.

    Расшифровка может ошибиться в границе слова; звук — нет. Неподтверждённый рез
    не отбрасывается, а помечается: решение остаётся за гейтом.
    """
    confirmed: list[dict[str, Any]] = []
    for cut in cuts:
        span = max(1e-6, float(cut["end_s"]) - float(cut["start_s"]))
        covered = 0.0
        for start, end in windows:
            overlap = min(float(cut["end_s"]), end) - max(float(cut["start_s"]), start)
            if overlap > 0:
                covered += overlap
        share = round(covered / span, 4)
        item = dict(cut)
        item["audio_silence_share"] = share
        item["audio_confirmed"] = share >= min_overlap
        confirmed.append(item)
    return confirmed


def apply_cuts_to_words(
    source_transcript: dict[str, Any], cuts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Тайминги слов после реза — чтобы субтитры считались по новой шкале, а не по старой."""
    words = _words(source_transcript)
    ordered = sorted(cuts, key=lambda item: float(item["start_s"]))
    shifted: list[dict[str, Any]] = []
    for word in words:
        removed = sum(
            float(cut["removed_s"]) for cut in ordered if float(cut["end_s"]) <= float(word["start_s"]) + 1e-9
        )
        shifted.append({
            "id": word["id"],
            "start_s": round(float(word["start_s"]) - removed, 6),
            "end_s": round(float(word["end_s"]) - removed, 6),
        })
    return shifted


def cut_plan(
    source_transcript: dict[str, Any],
    *,
    audio_path: Path | None = None,
    threshold_s: float = DEFAULT_THRESHOLD_S,
    keep_s: float = DEFAULT_KEEP_S,
    noise_db: float = DEFAULT_NOISE_DB,
) -> dict[str, Any]:
    """План реза пауз с числами: сколько уходит, сколько склеек, какая плотность выйдет."""
    cuts = word_gap_cuts(source_transcript, threshold_s=threshold_s, keep_s=keep_s)
    windows: list[tuple[float, float]] = []
    if audio_path is not None and Path(audio_path).is_file():
        windows = silence_windows(Path(audio_path), noise_db=noise_db)
        cuts = confirm_with_audio(cuts, windows)
    words = _words(source_transcript)
    source_duration = round(float(words[-1]["end_s"]) - float(words[0]["start_s"]), 6) if words else 0.0
    removed = round(sum(float(item["removed_s"]) for item in cuts), 6)
    speech = round(sum(float(item["end_s"]) - float(item["start_s"]) for item in words), 6)
    after = round(source_duration - removed, 6)
    return {
        "schema_version": 1,
        "kind": "pause-cut-plan",
        "thresholds": {"threshold_s": threshold_s, "keep_s": keep_s, "noise_db": noise_db},
        "cuts": cuts,
        "cut_count": len(cuts),
        "removed_s": removed,
        "source_duration_s": source_duration,
        "duration_after_s": after,
        "speech_share_before": round(speech / source_duration, 4) if source_duration > 0 else 0.0,
        "speech_share_after": round(speech / after, 4) if after > 0 else 0.0,
        "audio_checked": bool(windows),
    }
