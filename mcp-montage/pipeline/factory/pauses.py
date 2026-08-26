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

_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?[\d.]+)\s*dB")
# `-inf` — это не мусор, а абсолютная тишина. Без него окна выпадали из выборки,
# и время всех последующих уезжало: шкала строится по их порядковому номеру.
_RMS_LEVEL = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?(?:inf|[\d.]+))")
SILENT_FLOOR_DB = -100.0
WINDOW_S = 0.05
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


def rms_windows(audio_path: Path, *, window_s: float = WINDOW_S) -> list[tuple[float, float]]:
    """Уровень сигнала по окнам: (время начала окна, RMS в dB)."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio_path),
         "-af", f"astats=metadata=1:reset=1:length={window_s},"
                "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    levels: list[float] = []
    for value in _RMS_LEVEL.findall(result.stdout + result.stderr):
        levels.append(SILENT_FLOOR_DB if value.endswith("inf") else float(value))
    return [(round(index * window_s, 6), level) for index, level in enumerate(levels)]


def adaptive_noise_db(
    audio_path: Path, *, below_median_db: float = 10.0, floor_db: float = -60.0
) -> float:
    """Порог тишины от фактического уровня записи, а не абсолютной константой.

    В сведённом ролике тишина уходит под −50 dB, в сырой записи всегда есть фон комнаты.
    У живого исходника (−23 LUFS) абсолютный порог −32 dB не нашёл ни одной паузы,
    хотя почти четверть записи тише −45 dB.
    """
    levels = [level for _, level in rms_windows(audio_path)]
    if not levels:
        return DEFAULT_NOISE_DB
    levels.sort()
    median = levels[len(levels) // 2]
    return round(max(floor_db, min(-20.0, median - float(below_median_db))), 2)


def silence_windows(
    audio_path: Path,
    *,
    noise_db: float | None = None,
    min_s: float = 0.10,
    window_s: float = WINDOW_S,
) -> list[tuple[float, float]]:
    """Участки тишины по уровню сигнала. Не зависит от того, верно ли распознано слово.

    Считается по окнам, а не через `silencedetect`: тот работает по мгновенной амплитуде
    и рвёт паузу на любом щелчке или вдохе — на живой записи он не нашёл ни одного
    участка там, где по уровню тишины почти четверть хронометража.
    """
    levels = rms_windows(audio_path, window_s=window_s)
    if not levels:
        return []
    threshold = adaptive_noise_db(audio_path) if noise_db is None else float(noise_db)
    windows: list[tuple[float, float]] = []
    run_start: float | None = None
    for start, level in levels:
        quiet = level < threshold
        if quiet and run_start is None:
            run_start = start
        elif not quiet and run_start is not None:
            if start - run_start >= min_s:
                windows.append((round(run_start, 6), round(start, 6)))
            run_start = None
    if run_start is not None:
        end = levels[-1][0] + window_s
        if end - run_start >= min_s:
            windows.append((round(run_start, 6), round(end, 6)))
    return windows


def silence_cuts(
    audio_path: Path,
    *,
    threshold_s: float = DEFAULT_THRESHOLD_S,
    keep_s: float = DEFAULT_KEEP_S,
    noise_db: float | None = None,
    edge_pad_s: float = 0.03,
) -> list[dict[str, Any]]:
    """Резы прямо из тишины в звуке — основной источник, а не подтверждение.

    Пословные тайминги ASR для этого не годятся. На живом исходнике whisper large-v3
    растянул слова так, что речь заняла 93% хронометража и нашлось четыре паузы,
    тогда как по уровню сигнала тишины было 55% и 149 участков. Модель тянет границу
    слова через паузу; звук не тянет.

    `edge_pad_s` отступает от краёв тишины, чтобы не срезать атаку следующего слова
    и хвост предыдущего.
    """
    if keep_s >= threshold_s:
        raise ValueError("keep_s must be shorter than the threshold, otherwise nothing is cut")
    windows = silence_windows(audio_path, noise_db=noise_db, min_s=threshold_s)
    cuts: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(windows, 1):
        inner_start = start + edge_pad_s + keep_s / 2.0
        inner_end = end - edge_pad_s - keep_s / 2.0
        if inner_end - inner_start <= 0:
            continue
        cuts.append({
            "id": f"silence-{index:04d}",
            "gap_s": round(end - start, 6),
            "start_s": round(inner_start, 6),
            "end_s": round(inner_end, 6),
            "removed_s": round(inner_end - inner_start, 6),
            "reason": "silence-in-signal",
            "audio_confirmed": True,
            "audio_silence_share": 1.0,
        })
    return cuts


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
    noise_db: float | None = None,
) -> dict[str, Any]:
    """План реза пауз с числами: сколько уходит, сколько склеек, какая плотность выйдет.

    Источник пауз — звук, если он доступен. Расшифровка используется как запасной
    вариант и для сверки: её тайминги на сырых дублях систематически съедают паузы.
    """
    words: list[dict[str, Any]] = []
    word_cuts: list[dict[str, Any]] = []
    try:
        words = _words(source_transcript)
        word_cuts = word_gap_cuts(source_transcript, threshold_s=threshold_s, keep_s=keep_s)
    except ValueError:
        words = []
        word_cuts = []

    source = "words"
    cuts = word_cuts
    audio_available = audio_path is not None and Path(audio_path).is_file()
    if audio_available:
        cuts = silence_cuts(
            Path(audio_path), threshold_s=threshold_s, keep_s=keep_s, noise_db=noise_db
        )
        source = "audio"
    if not words and not audio_available:
        raise ValueError("neither word timings nor audio available: nothing to plan from")

    # Длительность берём из самого файла, а не из слов: на сырых дублях whisper
    # выдал тайминги до 469-й секунды при медиа в 200 секунд.
    source_duration = 0.0
    if audio_available:
        # media.duration_s принимает отчёт probe, а не путь — вызов с путём молча уходил
        # в except и длительность оставалась ложной.
        from .media import duration_s as _media_duration
        from .media import probe as _media_probe
        try:
            source_duration = round(float(_media_duration(_media_probe(Path(audio_path)))), 6)
        except Exception:
            source_duration = 0.0
    if source_duration <= 0:
        media_end = max(
            (float(words[-1]["end_s"]) if words else 0.0),
            (max((float(item["end_s"]) for item in cuts), default=0.0)),
        )
        media_start = min(
            (float(words[0]["start_s"]) if words else 0.0),
            (min((float(item["start_s"]) for item in cuts), default=0.0)),
        )
        source_duration = round(media_end - media_start, 6)
    # Резы за пределами медиа — след растянутых таймингов, в план они не идут.
    cuts = [item for item in cuts if float(item["end_s"]) <= source_duration + 1e-6]
    removed = round(sum(float(item["removed_s"]) for item in cuts), 6)
    after = round(source_duration - removed, 6)
    speech = round(source_duration - sum(float(item["gap_s"]) for item in cuts), 6)
    return {
        "schema_version": 2,
        "kind": "pause-cut-plan",
        "pause_source": source,
        "thresholds": {"threshold_s": threshold_s, "keep_s": keep_s, "noise_db": noise_db},
        "cuts": cuts,
        "cut_count": len(cuts),
        "removed_s": removed,
        "source_duration_s": source_duration,
        "duration_after_s": after,
        "speech_share_before": round(speech / source_duration, 4) if source_duration > 0 else 0.0,
        "speech_share_after": round(speech / after, 4) if after > 0 else 0.0,
        "audio_checked": audio_available,
        # Расхождение источников — сигнал, а не мелочь: если ASR видит на порядок меньше
        # пауз, чем звук, его тайминги растянуты и по ним резать нельзя.
        "word_cut_count": len(word_cuts),
    }


def apply_cuts_to_entries(entries: list[Any], cuts: list[dict[str, Any]]) -> list[Any]:
    """Вырезает паузы из монтажных записей, разбивая их по вырезанным окнам.

    До этого план реза оставался предложением: паузы считались, но в рендер уходили
    целиком, и самопроверка справедливо валила сегмент за «unexpected long silence».

    Запись, внутри которой оказалась пауза, распадается на две — с теми же словами,
    поделёнными по границе. Записи, целиком попавшие в вырезаемое окно, исчезают.
    """
    from dataclasses import replace

    windows = sorted(
        ((float(item["start_s"]), float(item["end_s"])) for item in cuts),
        key=lambda pair: pair[0],
    )
    if not windows:
        return list(entries)

    result: list[Any] = []
    for entry in entries:
        if getattr(entry, "kind", "keep") != "keep":
            result.append(entry)
            continue
        pieces = [(float(entry.start_s), float(entry.end_s))]
        for cut_start, cut_end in windows:
            nxt: list[tuple[float, float]] = []
            for start, end in pieces:
                if cut_end <= start or cut_start >= end:
                    nxt.append((start, end))
                    continue
                if start < cut_start:
                    nxt.append((start, min(cut_start, end)))
                if end > cut_end:
                    nxt.append((max(cut_end, start), end))
            pieces = [(a, b) for a, b in nxt if b - a > 1e-6]
        if not pieces:
            continue
        if len(pieces) == 1 and abs(pieces[0][0] - entry.start_s) < 1e-6 and abs(pieces[0][1] - entry.end_s) < 1e-6:
            result.append(entry)
            continue
        for index, (start, end) in enumerate(pieces, 1):
            suffix = "" if len(pieces) == 1 else f"-p{index}"
            result.append(replace(
                entry,
                id=f"{entry.id}{suffix}",
                start_s=round(start, 6),
                end_s=round(end, 6),
            ))
    return result
