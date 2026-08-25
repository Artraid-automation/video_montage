"""Film-level KEEP continuity: segments glue into one master, not isolated clips."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .cross_takes import (
    _lexical_sequence_similarity,
    _segment_key,
    _tokens,
)
from .io import canonical_json_hash
from .transcript import TranscriptEntry


FILM_CONTINUITY_WORKER_VERSION = "film-continuity-v1"


def keeps_from_entries(entries: list[TranscriptEntry]) -> list[dict[str, str]]:
    return [
        {"id": item.id, "text": item.text}
        for item in entries
        if item.kind == "keep"
    ]


def keeps_from_expected_transcript(expected: dict[str, Any]) -> list[dict[str, str]]:
    keeps: list[dict[str, str]] = []
    for index, utterance in enumerate(expected.get("utterances") or []):
        if not isinstance(utterance, dict):
            continue
        text = str(utterance.get("text", "")).strip()
        if not text:
            continue
        keep_id = str(utterance.get("source_entry_id") or utterance.get("id") or f"expected-{index + 1}")
        keeps.append({"id": keep_id, "text": text})
    return keeps


def write_phase2_film_continuity(
    project_root: Path,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rebuild continuity from Gate 2 expected KEEP transcripts (render plan)."""
    from .io import atomic_write_json, read_json, sha256_file

    inputs: list[dict[str, Any]] = []
    for segment in segments:
        segment_id = str(segment["id"])
        expected_path = project_root / segment["expected_transcript"]["path"]
        expected = read_json(expected_path)
        inputs.append(segment_continuity_input(
            segment_id=segment_id,
            transcript_sha256=sha256_file(expected_path),
            keeps=keeps_from_expected_transcript(expected),
        ))
    report = analyze_film_continuity(inputs)
    output = project_root / "04_phase2" / "film-continuity.json"
    atomic_write_json(output, report)
    return report


def segment_continuity_input(
    *,
    segment_id: str,
    transcript_sha256: str,
    keeps: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "transcript_sha256": transcript_sha256,
        "keeps": keeps,
    }


def analyze_film_continuity(
    segments: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.84,
    recommendation_threshold: float = 0.92,
    min_tokens: int = 5,
) -> dict[str, Any]:
    """Compare KEEP texts across segments as the future glued master.

    High-confidence KEEP↔KEEP matches spanning 2+ segments → verdict BLOCKED.
    Uncertain matches are listed but do not block.
    """
    if (
        not math.isfinite(similarity_threshold)
        or not math.isfinite(recommendation_threshold)
        or not 0 <= similarity_threshold <= recommendation_threshold <= 1
        or isinstance(min_tokens, bool)
        or not isinstance(min_tokens, int)
        or min_tokens < 1
    ):
        raise ValueError("invalid film continuity thresholds")

    ordered = sorted(segments, key=lambda item: _segment_key(str(item.get("segment_id", ""))))
    seen_segments: set[str] = set()
    bindings: list[dict[str, Any]] = []
    keeps: list[dict[str, Any]] = []

    for source in ordered:
        segment_id = str(source.get("segment_id", ""))
        sha256 = str(source.get("transcript_sha256", ""))
        raw_keeps = source.get("keeps")
        if not segment_id or segment_id in seen_segments:
            raise ValueError("invalid or duplicate film continuity segment")
        if not sha256.startswith("sha256:"):
            raise ValueError(f"segment {segment_id} missing transcript_sha256")
        if not isinstance(raw_keeps, list):
            raise ValueError(f"segment {segment_id} keeps must be a list")
        seen_segments.add(segment_id)
        keep_ids: list[str] = []
        for ordinal, raw in enumerate(raw_keeps):
            if not isinstance(raw, dict):
                raise ValueError(f"segment {segment_id} keep {ordinal} is invalid")
            keep_id = str(raw.get("id", "")).strip()
            text = str(raw.get("text", "")).strip()
            if not keep_id or not text:
                raise ValueError(f"segment {segment_id} keep {ordinal} needs id and text")
            if keep_id in keep_ids:
                raise ValueError(f"segment {segment_id} duplicate keep id: {keep_id}")
            keep_ids.append(keep_id)
            tokens = _tokens(text)
            if len(tokens) < min_tokens:
                continue
            keeps.append({
                "segment_id": segment_id,
                "keep_id": keep_id,
                "ordinal": ordinal,
                "text": text,
                "tokens": tokens,
            })
        bindings.append({
            "segment_id": segment_id,
            "transcript_sha256": sha256,
            "keep_ids": keep_ids,
        })

    raw_groups: list[list[dict[str, Any]]] = []
    assigned: set[tuple[str, str]] = set()
    for index, anchor in enumerate(keeps):
        anchor_key = (anchor["segment_id"], anchor["keep_id"])
        if anchor_key in assigned:
            continue
        group = [anchor]
        for candidate in keeps[index + 1:]:
            candidate_key = (candidate["segment_id"], candidate["keep_id"])
            if candidate_key in assigned:
                continue
            if candidate["segment_id"] in {item["segment_id"] for item in group}:
                continue
            scores = [
                _lexical_sequence_similarity(candidate["tokens"], member["tokens"])
                for member in group
            ]
            if scores and min(scores) >= similarity_threshold:
                group.append(candidate)
        if len({item["segment_id"] for item in group}) >= 2:
            raw_groups.append(group)
            assigned.update((item["segment_id"], item["keep_id"]) for item in group)

    blocking: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    for members in raw_groups:
        pair_scores = [
            _lexical_sequence_similarity(left["tokens"], right["tokens"])
            for left_index, left in enumerate(members)
            for right in members[left_index + 1:]
        ]
        confidence = round(min(pair_scores), 6) if pair_scores else 0.0
        refs = [
            {"segment_id": item["segment_id"], "keep_id": item["keep_id"]}
            for item in members
        ]
        stable_id = "film-keep-" + canonical_json_hash(refs).split(":", 1)[1][:16]
        if confidence < recommendation_threshold:
            uncertain.append({
                "id": stable_id,
                "members": refs,
                "minimum_similarity": confidence,
                "decision": "REVIEW",
            })
            continue
        latest = max(members, key=lambda item: (_segment_key(item["segment_id"]), item["ordinal"]))
        keep = {"segment_id": latest["segment_id"], "keep_id": latest["keep_id"]}
        cuts = [reference for reference in refs if reference != keep]
        blocking.append({
            "id": stable_id,
            "members": refs,
            "minimum_similarity": confidence,
            "recommended_keep": keep,
            "recommended_cut": cuts,
            "recommendation_policy": "latest-complete-keep-high-confidence",
            "decision": "BLOCK",
        })

    verdict = "BLOCKED" if blocking else "PASS"
    return {
        "schema_version": 1,
        "kind": "film-continuity",
        "worker_version": FILM_CONTINUITY_WORKER_VERSION,
        "input_bindings": bindings,
        "thresholds": {
            "similarity": similarity_threshold,
            "recommendation": recommendation_threshold,
            "min_tokens": min_tokens,
            "metric": "minimum(sequence-ratio, lexical-set-overlap)",
        },
        "verdict": verdict,
        "blocking_groups": blocking,
        "uncertain_matches": uncertain,
    }
