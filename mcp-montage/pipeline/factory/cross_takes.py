"""Project-level detection of repeated takes across separately numbered source files."""

from __future__ import annotations

from difflib import SequenceMatcher
import math
import re
from typing import Any

from .io import canonical_json_hash


CROSS_TAKES_WORKER_VERSION = "cross-segment-takes-v1"


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[\w']+", text.casefold(), flags=re.UNICODE))


def _lexical_sequence_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    if not left or not right:
        return 0.0
    sequence = SequenceMatcher(None, left, right, autojunk=False).ratio()
    overlap = len(set(left) & set(right)) / max(len(set(left)), len(set(right)))
    return min(sequence, overlap)


def _segment_key(segment_id: str) -> tuple[int, int, str]:
    return (0, int(segment_id), segment_id) if segment_id.isdigit() else (1, 0, segment_id)


def analyze_cross_segment_takes(
    sources: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.84,
    recommendation_threshold: float = 0.92,
    min_tokens: int = 5,
) -> dict[str, Any]:
    """Return conservative, review-only cross-file take recommendations.

    A recommended group is complete-link: every pair must clear the high-confidence
    threshold. This deliberately favors missed candidates over destructive false cuts.
    """
    if (
        not math.isfinite(similarity_threshold)
        or not math.isfinite(recommendation_threshold)
        or not 0 <= similarity_threshold <= recommendation_threshold <= 1
        or isinstance(min_tokens, bool)
        or not isinstance(min_tokens, int)
        or min_tokens < 1
    ):
        raise ValueError("invalid cross-segment take thresholds")
    ordered_sources = sorted(sources, key=lambda item: _segment_key(str(item.get("segment_id", ""))))
    segment_ids: set[str] = set()
    bindings: list[dict[str, str]] = []
    utterances: list[dict[str, Any]] = []
    for source in ordered_sources:
        segment_id = str(source.get("segment_id", ""))
        sha256 = str(source.get("sha256", ""))
        transcript = source.get("transcript")
        if not segment_id or segment_id in segment_ids or not sha256.startswith("sha256:") or not isinstance(transcript, dict):
            raise ValueError("invalid or duplicate cross-segment source binding")
        segment_ids.add(segment_id)
        raw_utterances = transcript.get("utterances")
        if not isinstance(raw_utterances, list):
            raise ValueError(f"segment {segment_id} source transcript has no utterances")
        binding_utterance_ids = [str(item.get("id", "")) for item in raw_utterances if isinstance(item, dict)]
        if len(binding_utterance_ids) != len(raw_utterances) or not all(binding_utterance_ids) or len(set(binding_utterance_ids)) != len(binding_utterance_ids):
            raise ValueError(f"segment {segment_id} source transcript has invalid utterance identities")
        bindings.append({
            "segment_id": segment_id,
            "source_transcript_sha256": sha256,
            "utterance_ids": binding_utterance_ids,
        })
        for ordinal, raw in enumerate(raw_utterances):
            if not isinstance(raw, dict):
                raise ValueError(f"segment {segment_id} utterance {ordinal} is invalid")
            utterance_id = str(raw.get("id", ""))
            text = str(raw.get("text", "")).strip()
            tokens = _tokens(text)
            if not utterance_id or not text:
                raise ValueError(f"segment {segment_id} utterance {ordinal} has no identity or text")
            if len(tokens) >= min_tokens:
                utterances.append({
                    "segment_id": segment_id,
                    "utterance_id": utterance_id,
                    "ordinal": ordinal,
                    "text": text,
                    "tokens": tokens,
                })

    # Greedy complete-link clustering is deterministic because all inputs are sorted.
    raw_groups: list[list[dict[str, Any]]] = []
    assigned: set[tuple[str, str]] = set()
    for index, anchor in enumerate(utterances):
        anchor_key = (anchor["segment_id"], anchor["utterance_id"])
        if anchor_key in assigned:
            continue
        group = [anchor]
        for candidate in utterances[index + 1:]:
            candidate_key = (candidate["segment_id"], candidate["utterance_id"])
            if candidate_key in assigned or candidate["segment_id"] in {item["segment_id"] for item in group}:
                continue
            scores = [_lexical_sequence_similarity(candidate["tokens"], member["tokens"]) for member in group]
            if scores and min(scores) >= similarity_threshold:
                group.append(candidate)
        if len({item["segment_id"] for item in group}) >= 2:
            raw_groups.append(group)
            assigned.update((item["segment_id"], item["utterance_id"]) for item in group)

    groups: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    for members in raw_groups:
        pair_scores = [
            _lexical_sequence_similarity(left["tokens"], right["tokens"])
            for left_index, left in enumerate(members)
            for right in members[left_index + 1:]
        ]
        confidence = round(min(pair_scores), 6)
        refs = [{"segment_id": item["segment_id"], "utterance_id": item["utterance_id"]} for item in members]
        stable_id = "cross-take-" + canonical_json_hash(refs).split(":", 1)[1][:16]
        if confidence < recommendation_threshold:
            uncertain.append({"id": stable_id, "members": refs, "minimum_similarity": confidence, "decision": "REVIEW"})
            continue
        latest = max(members, key=lambda item: (_segment_key(item["segment_id"]), item["ordinal"]))
        keep = {"segment_id": latest["segment_id"], "utterance_id": latest["utterance_id"]}
        cuts = [reference for reference in refs if reference != keep]
        groups.append({
            "id": stable_id,
            "members": refs,
            "minimum_similarity": confidence,
            "recommended_keep": keep,
            "recommended_cut": cuts,
            "recommendation_policy": "latest-complete-take-high-confidence",
            "decision": "REVIEW",
        })

    candidates = [{"id": group["id"], "kind": "cross-segment-take", "decision": "REVIEW"} for group in groups]
    return {
        "schema_version": 1,
        "kind": "cross-segment-take-analysis",
        "worker_version": CROSS_TAKES_WORKER_VERSION,
        "input_bindings": bindings,
        "thresholds": {
            "similarity": similarity_threshold,
            "recommendation": recommendation_threshold,
            "min_tokens": min_tokens,
            "metric": "minimum(sequence-ratio, lexical-set-overlap)",
        },
        "verdict": "CANDIDATES_PROPOSED" if candidates else "NO_CANDIDATES",
        "groups": groups,
        "uncertain_matches": uncertain,
        "candidates": candidates,
        "auto_apply": False,
    }
