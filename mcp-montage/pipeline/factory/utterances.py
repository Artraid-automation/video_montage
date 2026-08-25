"""Utterance normalization for human-readable Gate 1 blocks."""

from __future__ import annotations

import math
import re
from typing import Any


RETAKE_MARKER_RE = re.compile(
    r"(?i)(?:"
    r"\bзаново\b|\bвозвращаемся\b|\bхерня\b|"
    r"не\s+был\s+последний\s+дубль|последние\s+думали|"
    r"у\s+меня\s+все\s+понравилось|у\s+меня\s+все\s+погасло|"
    r"from\s+the\s+top|take\s+two"
    r")"
)

TAKE_PREFIX_RE = re.compile(
    r"(?i)(?:"
    r"(?:по\s+)?моим\s+наблюдениям\s+деньги\s+уходят|"
    r"деньги\s+уходят\s+не\s+потому"
    r")"
)

SENTENCE_END_RE = re.compile(r'[.!?…]+["»”]?$')
CLAUSE_CONTINUE_RE = re.compile(r"[,:;…—–-]\s*$")


def tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[\w']+", text.casefold(), flags=re.UNICODE))


def starts_mid_clause(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    first = stripped[0]
    return first.islower() or first in "«\"'("


def _should_join_incomplete(previous_text: str, current_text: str) -> bool:
    if SENTENCE_END_RE.search(previous_text.rstrip()):
        return False
    if RETAKE_MARKER_RE.search(previous_text):
        return False
    if TAKE_PREFIX_RE.match(current_text):
        return False
    if RETAKE_MARKER_RE.search(current_text[:80]):
        return False
    return bool(CLAUSE_CONTINUE_RE.search(previous_text.rstrip()) or starts_mid_clause(current_text))


def _utterance_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(item["id"]),
        "start_s": float(item["start_s"]),
        "end_s": float(item["end_s"]),
        "text": str(item["text"]).strip(),
        "word_ids": list(item.get("word_ids") or []),
    }
    if "decision" in item:
        payload["decision"] = str(item["decision"])
    if item.get("reason") is not None:
        payload["reason"] = str(item["reason"])
    if item.get("take_group") is not None:
        payload["take_group"] = str(item["take_group"])
    return payload


def _merge_decision(left: dict[str, Any], right: dict[str, Any]) -> tuple[str | None, str | None]:
    left_decision = left.get("decision")
    right_decision = right.get("decision")
    if left_decision == "keep" or right_decision == "keep":
        return "keep", None
    if left_decision == "cut" or right_decision == "cut":
        reason = left.get("reason") or right.get("reason")
        return "cut", reason
    return left_decision, left.get("reason")


def _append_merge(previous: dict[str, Any], payload: dict[str, Any]) -> None:
    previous["text"] = f"{previous['text']} {payload['text']}".strip()
    previous["end_s"] = payload["end_s"]
    previous["word_ids"] = list(previous["word_ids"]) + list(payload["word_ids"])
    decision, reason = _merge_decision(previous, payload)
    if decision is not None:
        previous["decision"] = decision
    if reason is not None:
        previous["reason"] = reason
    elif decision == "keep":
        previous.pop("reason", None)


def _merge_block(utterances: list[dict[str, Any]]) -> dict[str, Any]:
    first = utterances[0]
    merged = _utterance_payload(first)
    merged["end_s"] = float(utterances[-1]["end_s"])
    merged["text"] = " ".join(str(item["text"]).strip() for item in utterances).strip()
    merged["word_ids"] = [word for item in utterances for word in list(item.get("word_ids") or [])]
    decision, reason = merged.get("decision"), merged.get("reason")
    for item in utterances[1:]:
        decision, reason = _merge_decision({"decision": decision, "reason": reason}, item)
    if decision is not None:
        merged["decision"] = decision
    if reason is not None:
        merged["reason"] = reason
    elif "reason" in merged and decision == "keep":
        merged.pop("reason", None)
    return merged


def _merge_orphan_fragments(
    utterances: list[dict[str, Any]],
    *,
    max_orphan_words: int,
    max_gap_s: float,
) -> list[dict[str, Any]]:
    if not utterances:
        return []
    merged: list[dict[str, Any]] = []
    for item in utterances:
        payload = _utterance_payload(item)
        if not merged:
            merged.append(payload)
            continue
        previous = merged[-1]
        gap = payload["start_s"] - previous["end_s"]
        if (
            len(tokens(payload["text"])) <= max_orphan_words
            and gap <= max_gap_s
            and not TAKE_PREFIX_RE.match(payload["text"])
            and not (
                previous.get("decision")
                and payload.get("decision")
                and previous.get("decision") != payload.get("decision")
            )
        ):
            _append_merge(previous, payload)
            continue
        merged.append(payload)
    return merged


def _merge_incomplete_sentences(
    utterances: list[dict[str, Any]],
    *,
    max_gap_s: float,
) -> list[dict[str, Any]]:
    """Join mid-clause ASR splits so KEEP/CUT blocks stay grammatical."""
    if not utterances:
        return []
    merged: list[dict[str, Any]] = []
    for item in utterances:
        payload = _utterance_payload(item)
        if not merged:
            merged.append(payload)
            continue
        previous = merged[-1]
        gap = payload["start_s"] - previous["end_s"]
        if (
            gap <= max_gap_s
            and _should_join_incomplete(previous["text"], payload["text"])
            and not (
                previous.get("decision")
                and payload.get("decision")
                and previous.get("decision") != payload.get("decision")
            )
        ):
            _append_merge(previous, payload)
            continue
        merged.append(payload)
    return merged


def _merge_take_blocks(utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not utterances:
        return []
    blocks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for item in utterances:
        text = str(item["text"]).strip()
        if TAKE_PREFIX_RE.match(text):
            if current:
                blocks.append(_merge_block(current))
            current = [item]
        elif current:
            current.append(item)
        else:
            blocks.append(_utterance_payload(item))
        if RETAKE_MARKER_RE.search(text) and current:
            blocks.append(_merge_block(current))
            current = []
    if current:
        blocks.append(_merge_block(current))
    return blocks


def coalesce_utterances(
    utterances: list[dict[str, Any]],
    *,
    max_orphan_words: int = 2,
    max_gap_s: float = 0.5,
    incomplete_gap_s: float = 0.8,
) -> list[dict[str, Any]]:
    """Merge ASR mid-phrase splits and whole take attempts for grammatical Gate 1 blocks."""
    if not utterances:
        return []
    if (
        isinstance(max_orphan_words, bool)
        or not isinstance(max_orphan_words, int)
        or max_orphan_words < 1
        or not math.isfinite(max_gap_s)
        or max_gap_s < 0
        or not math.isfinite(incomplete_gap_s)
        or incomplete_gap_s < 0
    ):
        raise ValueError("invalid coalesce thresholds")
    orphan_merged = _merge_orphan_fragments(
        utterances,
        max_orphan_words=max_orphan_words,
        max_gap_s=max_gap_s,
    )
    incomplete_merged = _merge_incomplete_sentences(
        orphan_merged,
        max_gap_s=incomplete_gap_s,
    )
    return _merge_take_blocks(incomplete_merged)


def coalesce_source_transcript(source_transcript: dict[str, Any]) -> dict[str, Any]:
    raw = source_transcript.get("utterances")
    if not isinstance(raw, list) or not raw:
        raise ValueError("source transcript has no utterances")
    return {
        **source_transcript,
        "utterances": coalesce_utterances(raw),
    }
