"""Deterministic transcript analysis for human-reviewed editorial candidates."""

from __future__ import annotations

from dataclasses import replace

import math
import re
from difflib import SequenceMatcher
from typing import Any

from .io import canonical_json_hash
from .transcript import TranscriptEntry
from .utterances import (
    RETAKE_MARKER_RE,
    TAKE_PREFIX_RE,
    coalesce_source_transcript,
    coalesce_utterances,
    starts_mid_clause,
    tokens as _tokens,
)


EDITORIAL_WORKER_VERSION = "editorial-analysis-v6"


def _similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return SequenceMatcher(None, left_tokens, right_tokens, autojunk=False).ratio()


def _validated_utterances(source_transcript: dict[str, Any]) -> list[dict[str, Any]]:
    raw = source_transcript.get("utterances")
    if not isinstance(raw, list) or not raw:
        raise ValueError("source transcript has no utterances")
    seen: set[str] = set()
    previous_end = -1.0
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"utterance {index} is not an object")
        utterance_id = str(item.get("id", ""))
        start = float(item.get("start_s", -1))
        end = float(item.get("end_s", -1))
        text = str(item.get("text", "")).strip()
        if (
            not utterance_id or utterance_id in seen or not math.isfinite(start) or not math.isfinite(end)
            or start < 0 or start < previous_end - 1e-6 or end <= start or not text
        ):
            raise ValueError(f"invalid utterance timeline at index {index}")
        seen.add(utterance_id)
        previous_end = end
        result.append(item)
    return result


def _is_retake_marker(text: str) -> bool:
    return bool(RETAKE_MARKER_RE.search(text.strip()))


def _cluster_repetitions(repetitions: list[dict[str, Any]]) -> list[list[str]]:
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for item in repetitions:
        ids = item["utterance_ids"]
        union(str(ids[0]), str(ids[1]))
    buckets: dict[str, list[str]] = {}
    for node in parent:
        buckets.setdefault(find(node), []).append(node)
    return [sorted(members) for members in buckets.values() if len(members) >= 2]


def _prefix_take_candidates(
    utterances: list[dict[str, Any]],
    covered: set[str],
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for utterance in utterances:
        utterance_id = str(utterance["id"])
        if utterance_id in covered:
            continue
        text = str(utterance["text"])
        match = TAKE_PREFIX_RE.search(text)
        if not match:
            continue
        key = match.group(0).casefold()
        buckets.setdefault(key, []).append(utterance)
    takes: list[dict[str, Any]] = []
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda item: float(item["start_s"]))
        keep = ordered[-1]
        cut_ids = [str(item["id"]) for item in ordered[:-1]]
        tokens = _tokens(key)
        token = tokens[0] if tokens else "hook"
        group_id = f"prefix-{token}-{ordered[0]['id']}-{keep['id']}"
        takes.append({
            "id": f"take-{group_id}",
            "take_group": group_id,
            "utterance_ids": [str(item["id"]) for item in ordered],
            "recommended_keep": str(keep["id"]),
            "recommended_cut": cut_ids,
            "reason": "latest-similar-prefix",
        })
    return takes


def _block_take_candidates(
    utterances: list[dict[str, Any]],
    pauses: list[dict[str, Any]],
    *,
    block_pause_s: float,
    repetition_similarity: float,
) -> list[dict[str, Any]]:
    long_breaks = {
        str(item["before_utterance_id"])
        for item in pauses
        if float(item["duration_s"]) >= block_pause_s
    }
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for utterance in utterances:
        if current and str(utterance["id"]) in long_breaks:
            blocks.append(current)
            current = []
        current.append(utterance)
    if current:
        blocks.append(current)
    takes: list[dict[str, Any]] = []
    for left_index, left_block in enumerate(blocks):
        left_head = " ".join(str(item["text"]) for item in left_block[:3])
        for right_block in blocks[left_index + 1:]:
            right_head = " ".join(str(item["text"]) for item in right_block[:3])
            if _similarity(left_head, right_head) < repetition_similarity:
                continue
            members = left_block + right_block
            keep = right_block[-1]
            cut_ids = [str(item["id"]) for item in left_block]
            if str(keep["id"]) in cut_ids:
                continue
            group_id = f"block-{left_block[0]['id']}-{right_block[0]['id']}"
            takes.append({
                "id": f"take-{group_id}",
                "take_group": group_id,
                "utterance_ids": [str(item["id"]) for item in members],
                "recommended_keep": str(keep["id"]),
                "recommended_cut": cut_ids,
                "reason": "latest-similar-block",
            })
    return takes


def analyze_editorial(
    source_transcript: dict[str, Any],
    *,
    pause_threshold_s: float = 0.8,
    repetition_similarity: float = 0.88,
    block_pause_s: float = 5.0,
) -> dict[str, Any]:
    """Propose candidates; Phase 1 may mirror them into visible <cut> tags for review."""
    if not math.isfinite(pause_threshold_s) or pause_threshold_s < 0:
        raise ValueError("pause threshold must be finite and non-negative")
    if not math.isfinite(repetition_similarity) or not 0.0 <= repetition_similarity <= 1.0:
        raise ValueError("repetition similarity must be between 0 and 1")
    if not math.isfinite(block_pause_s) or block_pause_s < 0:
        raise ValueError("block pause threshold must be finite and non-negative")
    utterances = _validated_utterances(source_transcript)
    by_id = {str(item["id"]): item for item in utterances}

    pauses: list[dict[str, Any]] = []
    for left, right in zip(utterances, utterances[1:]):
        duration = round(float(right["start_s"]) - float(left["end_s"]), 6)
        if duration >= pause_threshold_s:
            pauses.append({
                "id": f"pause-{left['id']}-{right['id']}",
                "after_utterance_id": str(left["id"]),
                "before_utterance_id": str(right["id"]),
                "start_s": float(left["end_s"]),
                "end_s": float(right["start_s"]),
                "duration_s": duration,
                "reason": "inter-utterance-pause",
            })

    repetitions: list[dict[str, Any]] = []
    for left_index, left in enumerate(utterances):
        for right in utterances[left_index + 1:]:
            score = _similarity(str(left["text"]), str(right["text"]))
            if score >= repetition_similarity:
                repetitions.append({
                    "id": f"repetition-{left['id']}-{right['id']}",
                    "utterance_ids": [str(left["id"]), str(right["id"])],
                    "similarity": round(score, 6),
                    "reason": "lexical-repetition",
                })

    grouped: dict[str, list[dict[str, Any]]] = {}
    for utterance in utterances:
        take_group = utterance.get("take_group")
        if take_group is not None and str(take_group).strip():
            grouped.setdefault(str(take_group), []).append(utterance)
    takes: list[dict[str, Any]] = []
    covered: set[str] = set()
    for group_id in sorted(grouped):
        members = grouped[group_id]
        if len(members) < 2:
            continue
        keep = members[-1]
        cut_ids = [str(item["id"]) for item in members[:-1]]
        takes.append({
            "id": f"take-{group_id}",
            "take_group": group_id,
            "utterance_ids": [str(item["id"]) for item in members],
            "recommended_keep": str(keep["id"]),
            "recommended_cut": cut_ids,
            "reason": "latest-explicit-take",
        })
        covered.update(str(item["id"]) for item in members)

    for cluster in _cluster_repetitions(repetitions):
        if all(member in covered for member in cluster):
            continue
        members = sorted(cluster, key=lambda item: float(by_id[item]["start_s"]))
        keep = members[-1]
        cut_ids = members[:-1]
        group_id = f"rep-{members[0]}-{keep}"
        takes.append({
            "id": f"take-{group_id}",
            "take_group": group_id,
            "utterance_ids": members,
            "recommended_keep": keep,
            "recommended_cut": cut_ids,
            "reason": "latest-repetition-cluster",
        })
        covered.update(members)

    for take in _block_take_candidates(
        utterances, pauses, block_pause_s=block_pause_s, repetition_similarity=repetition_similarity,
    ):
        if any(utterance_id in covered for utterance_id in take["recommended_cut"]):
            continue
        takes.append(take)
        covered.update(take["utterance_ids"])

    for take in _prefix_take_candidates(utterances, covered):
        takes.append(take)
        covered.update(take["utterance_ids"])

    candidates = [
        *({"id": item["id"], "kind": "pause", "decision": "REVIEW"} for item in pauses),
        *({"id": item["id"], "kind": "repetition", "decision": "REVIEW"} for item in repetitions),
        *({"id": item["id"], "kind": "take", "decision": "REVIEW"} for item in takes),
    ]
    return {
        "schema_version": 1,
        "kind": "editorial-analysis",
        "worker_version": EDITORIAL_WORKER_VERSION,
        "source_transcript_sha256": canonical_json_hash(source_transcript),
        "thresholds": {
            "pause_s": pause_threshold_s,
            "repetition_similarity": repetition_similarity,
            "block_pause_s": block_pause_s,
        },
        "verdict": "CANDIDATES_PROPOSED" if candidates else "NO_CANDIDATES",
        "pause_candidates": pauses,
        "repetition_candidates": repetitions,
        "take_candidates": takes,
        "candidates": candidates,
    }



# Пауза длиннее этой считается самостоятельной тишиной и может быть вырезана;
# всё, что короче, — дыхание внутри мысли, и рвать по нему речь нельзя
# (правило 1 заказчика, 30.08.26: внутри предложения не режем).
SPEECH_CONTINUITY_GAP_S = 1.5


def merge_adjacent_keeps(
    entries: list[TranscriptEntry],
    *,
    max_gap_s: float = SPEECH_CONTINUITY_GAP_S,
) -> list[TranscriptEntry]:
    """Склеить соседние KEEP в одну непрерывную реплику.

    Расшифровка делит речь по дыханию, а не по смыслу: одно предложение приезжает
    тремя блоками. Пока они остаются раздельными, монтаж выбрасывает промежутки
    между ними — речь звучит рублеными кусками, хотя ни одного CUT между ними нет.
    Склейка возвращает цельность: между двумя KEEP звук остаётся нетронутым.
    """
    merged: list[TranscriptEntry] = []
    for entry in entries:
        if entry.kind != "keep" or not merged or merged[-1].kind != "keep":
            merged.append(entry)
            continue
        previous = merged[-1]
        gap = float(entry.start_s) - float(previous.end_s)
        if gap < 0 or gap > max_gap_s:
            merged.append(entry)
            continue
        merged[-1] = replace(
            previous,
            end_s=entry.end_s,
            text=f"{previous.text} {entry.text}".strip(),
            word_ids=tuple(previous.word_ids) + tuple(entry.word_ids),
        )
    return merged


def apply_editorial_proposals(
    entries: list[TranscriptEntry],
    editorial: dict[str, Any],
) -> list[TranscriptEntry]:
    """Mirror editorial take/repetition proposals into visible transcript cut tags.

    Human can flip any proposed <cut> back to <keep> before Gate 1 approval.
    Explicit source cuts keep their original reason.
    """
    proposed: dict[str, str] = {}
    for take in editorial.get("take_candidates", []):
        reason = str(take.get("reason") or "proposed-take")
        if reason == "latest-repetition-cluster":
            reason = "proposed-repetition"
        elif reason == "latest-similar-block":
            reason = "proposed-retake-block"
        elif reason == "latest-similar-prefix":
            reason = "proposed-retake-prefix"
        elif reason == "latest-explicit-take":
            reason = "proposed-take"
        for utterance_id in take.get("recommended_cut", []):
            proposed.setdefault(str(utterance_id), reason)
    for repetition in editorial.get("repetition_candidates", []):
        ids = [str(item) for item in repetition.get("utterance_ids", [])]
        if len(ids) != 2:
            continue
        by_id = {entry.id: entry for entry in entries}
        if ids[0] not in by_id or ids[1] not in by_id:
            continue
        earlier, later = sorted(ids, key=lambda item: by_id[item].start_s)
        proposed.setdefault(earlier, "proposed-repetition")
        _ = later
    result: list[TranscriptEntry] = []
    protected_keep_ids = {
        str(take.get("recommended_keep"))
        for take in editorial.get("take_candidates", [])
        if take.get("recommended_keep")
    }
    for entry in entries:
        if entry.kind == "cut":
            result.append(entry)
            continue
        if _is_retake_marker(entry.text):
            result.append(TranscriptEntry(
                "cut", entry.id, entry.start_s, entry.end_s, entry.word_ids, entry.text, "retake-marker",
            ))
            continue
        reason = proposed.get(entry.id)
        if reason:
            result.append(TranscriptEntry(
                "cut", entry.id, entry.start_s, entry.end_s, entry.word_ids, entry.text, reason,
            ))
            continue
        result.append(entry)
    return _absorb_hanging_clause_keeps(result, protected_keep_ids=protected_keep_ids)


def _cut_allows_hanging_absorb(reason: str | None) -> bool:
    """Only fold tails after editorial/proposed cuts — never after source cuts like false-start."""
    value = str(reason or "").strip()
    return value.startswith("proposed-") or value in {"hanging-clause", "retake-marker"}


def _absorb_hanging_clause_keeps(
    entries: list[TranscriptEntry],
    *,
    protected_keep_ids: set[str] | None = None,
) -> list[TranscriptEntry]:
    """Fold short mid-clause KEEP tails into the preceding CUT so narrative does not hang."""
    protected = protected_keep_ids or set()
    if not entries:
        return entries
    healed: list[TranscriptEntry] = []
    for entry in entries:
        previous = healed[-1] if healed else None
        if (
            previous is not None
            and previous.kind == "cut"
            and entry.kind == "keep"
            and entry.id not in protected
            and _cut_allows_hanging_absorb(previous.reason)
            and starts_mid_clause(entry.text)
            and len(_tokens(entry.text)) <= 8
        ):
            healed[-1] = TranscriptEntry(
                "cut",
                previous.id,
                previous.start_s,
                entry.end_s,
                previous.word_ids + entry.word_ids,
                f"{previous.text} {entry.text}".strip(),
                previous.reason or "hanging-clause",
            )
            continue
        healed.append(entry)
    return healed
