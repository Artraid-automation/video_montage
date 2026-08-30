"""Выгрузка сценария для монтажного стола — страницы, где правят пословно.

Стол правит не абзацы, а слова: каждое слово несёт своё время, поэтому по любой
расстановке пометок сразу считается хронометраж будущего ролика. Предложения нужны
как единица быстрого решения — «убрать всю мысль» одним движением.
"""

from __future__ import annotations

import re
from typing import Any

from .transcript import TranscriptEntry

# Конец предложения ищем по знаку препинания на слове: Rev.ai приклеивает его к слову.
SENTENCE_END_RE = re.compile(r"[.!?…]+[\"»)]*$")
# Пауза внутри оставленного куска короче этой остаётся в ролике (правило 14 заказчика).
CONTINUITY_GAP_S = 1.5


def _sentence_breaks(words: list[dict[str, Any]]) -> list[int]:
    """Индексы слов, которыми предложения заканчиваются."""
    breaks: list[int] = []
    for index, word in enumerate(words):
        if SENTENCE_END_RE.search(str(word["text"])):
            breaks.append(index)
    if not breaks or breaks[-1] != len(words) - 1:
        breaks.append(len(words) - 1)
    return breaks


def build_desk_payload(
    entries: list[TranscriptEntry],
    source_transcript: dict[str, Any],
    *,
    project_id: str,
    title: str,
    summary: str | None = None,
    risks: list[str] | None = None,
) -> dict[str, Any]:
    words_by_id = {
        str(item["id"]): item
        for item in source_transcript.get("words") or []
        if item.get("id") is not None
    }
    # Слова реплики берём по её временам, а не по списку идентификаторов: после
    # склейки соседних реплик список остаётся от первой из них, и на столе тогда
    # пропадает больше половины текста (замер 30.08: 123 слова вместо 347).
    all_words = sorted(
        (item for item in words_by_id.values()),
        key=lambda item: float(item["start_s"]),
    )
    words: list[dict[str, Any]] = []
    for entry in entries:
        start, end = float(entry.start_s), float(entry.end_s)
        for raw in all_words:
            middle = (float(raw["start_s"]) + float(raw["end_s"])) / 2
            if not (start - 0.05 <= middle <= end + 0.05):
                continue
            words.append({
                "i": len(words),
                "wid": str(raw["id"]),
                "text": str(raw["text"]),
                "start_s": round(float(raw["start_s"]), 3),
                "end_s": round(float(raw["end_s"]), 3),
                # Решение редактора — стартовое состояние пометки, а не приговор:
                # человек снимает и ставит его кликом.
                "cut": entry.kind != "keep",
                "reason": entry.reason if entry.kind != "keep" else None,
                "entry_id": entry.id,
            })
    if not words:
        raise ValueError("сценарий пуст: в репликах нет слов с временами")

    sentences: list[dict[str, Any]] = []
    start_index = 0
    for end_index in _sentence_breaks(words):
        if end_index < start_index:
            continue
        sentences.append({
            "id": f"s{len(sentences) + 1:03d}",
            "from": start_index,
            "to": end_index,
            "start_s": words[start_index]["start_s"],
        })
        start_index = end_index + 1

    return {
        "schema_version": 1,
        "project_id": project_id,
        "title": title,
        "summary": summary,
        "risks": list(risks or []),
        "source_duration_s": round(float(source_transcript.get("duration_s") or 0.0), 3),
        "continuity_gap_s": CONTINUITY_GAP_S,
        "words": words,
        "sentences": sentences,
    }
