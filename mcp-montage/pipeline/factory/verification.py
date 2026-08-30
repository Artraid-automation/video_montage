"""Rendered transcript comparison and semantic edit fault detection."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from .transcript import TranscriptEntry
from .visual_policy import caption_display_text


def normalize_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return re.findall(r"[\w']+", normalized, flags=re.UNICODE)


def _levenshtein(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, left_token in enumerate(left, 1):
        current = [i]
        for j, right_token in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left_token != right_token),
            ))
        previous = current
    return previous[-1]


def _lcs_length(left: list[str], right: list[str]) -> int:
    row = [0] * (len(right) + 1)
    for left_token in left:
        previous_diagonal = 0
        for index, right_token in enumerate(right, 1):
            previous = row[index]
            if left_token == right_token:
                row[index] = previous_diagonal + 1
            else:
                row[index] = max(row[index], row[index - 1])
            previous_diagonal = previous
    return row[-1]


def adjacent_ngram_echoes(tokens: list[str], *, n: int = 2, min_chars: int = 8) -> list[dict[str, Any]]:
    """Detect immediate repeated n-grams (e.g. работа руками / работа руками)."""
    echoes: list[dict[str, Any]] = []
    if n < 2 or len(tokens) < 2 * n:
        return echoes
    index = 0
    while index <= len(tokens) - 2 * n:
        left = tokens[index : index + n]
        right = tokens[index + n : index + 2 * n]
        joined = " ".join(left)
        if left == right and len(joined) >= min_chars:
            echoes.append({
                "ngram": list(left),
                "at_token": index,
                "text": joined,
            })
            index += n
        else:
            index += 1
    return echoes


RETAKE_OPENERS = frozenset({"вместо"})


def repeated_clause_openers(
    tokens: list[str],
    *,
    openers: frozenset[str] | None = None,
    max_gap_tokens: int = 6,
) -> list[dict[str, Any]]:
    """Catch false-start rephrases like «вместо A, вместо B» within a short window."""
    openers = openers or RETAKE_OPENERS
    hits: list[dict[str, Any]] = []
    last_at: dict[str, int] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        # Prefer multiword opener «то есть»
        if token == "то" and index + 1 < len(tokens) and tokens[index + 1] == "есть":
            key = "то есть"
            span = 2
        elif token in openers:
            key = token
            span = 1
        else:
            index += 1
            continue
        if key in last_at and index - last_at[key] <= max_gap_tokens:
            hits.append({
                "opener": key,
                "at_token": last_at[key],
                "again_at": index,
                "gap_tokens": index - last_at[key],
            })
        last_at[key] = index
        index += span
    return hits


def leading_silence_windows(
    expected: dict[str, Any],
    *,
    max_lead_in_s: float,
) -> list[dict[str, Any]]:
    """KEEP clip starts before first timed word → dead air / sigh in the burn."""
    issues: list[dict[str, Any]] = []
    words = list(expected.get("words") or [])
    for utterance in expected.get("utterances") or []:
        start = float(utterance["start_s"])
        end = float(utterance["end_s"])
        owned = [w for w in words if start - 1e-6 <= float(w["start_s"]) < end - 1e-6]
        if not owned:
            continue
        lead = float(owned[0]["start_s"]) - start
        if lead > max_lead_in_s:
            issues.append({
                "source_entry_id": utterance.get("source_entry_id"),
                "lead_in_s": round(lead, 3),
                "first_word": owned[0].get("text"),
            })
    return issues


def caption_words_for_entry(
    entry: TranscriptEntry,
    words_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    duration = max(0.0, float(entry.end_s) - float(entry.start_s))
    local: list[dict[str, Any]] = []
    for word_id in entry.word_ids:
        raw = words_by_id.get(str(word_id))
        if raw is None:
            continue
        start = float(raw["start_s"])
        end = float(raw["end_s"])
        overlap = min(end, float(entry.end_s)) - max(start, float(entry.start_s))
        if overlap <= 0:
            continue
        # Слово принадлежит ровно одному фрагменту — тому, где звучит его большая
        # часть. Прежний фильтр «хоть немного пересеклись» отдавал слово на границе
        # реза ОБОИМ соседям, и ожидаемая расшифровка ждала его дважды, тогда как в
        # ролике оно звучит один раз. Замер 30.08 на pilot-live3: так задвоились
        # слова на 17 стыках из 51, и самопроверка валила сборку за чужой брак.
        if overlap < 0.5 * max(end - start, 1e-6):
            continue
        local_start = max(0.0, start - float(entry.start_s))
        local_end = min(duration, max(local_start + 0.04, end - float(entry.start_s)))
        tokens = normalize_tokens(str(raw.get("text", "")))
        if not tokens:
            continue
        # Multi-token ASR cells are rare; keep first normalized token for alignment.
        local.append({
            "id": str(word_id),
            "text": tokens[0],
            "start_s": local_start,
            "end_s": local_end,
        })
    return local


def caption_burn_words_for_entry(
    entry: TranscriptEntry,
    words_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Timed caption words with brand spellings for on-screen burn (not verification)."""
    local = caption_words_for_entry(entry, words_by_id)
    burned: list[dict[str, Any]] = []
    index = 0
    while index < len(local):
        current = local[index]
        token = str(current["text"]).casefold().replace("ё", "е")
        nxt = local[index + 1] if index + 1 < len(local) else None
        next_token = str(nxt["text"]).casefold().replace("ё", "е") if nxt else ""
        if token == "про" and next_token.startswith("женщ"):
            burned.append({
                **current,
                "text": "PRO Женщин",
                "end_s": float(nxt["end_s"]),
            })
            index += 2
            continue
        burned.append({**current, "text": caption_display_text(str(current["text"]))})
        index += 1
    return burned


def _source_words_for_entry(
    entry: TranscriptEntry,
    words_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return caption_words_for_entry(entry, words_by_id)


def expected_render_transcript(
    entries: Iterable[TranscriptEntry],
    *,
    source_words: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    words_by_id = {
        str(item["id"]): item
        for item in (source_words or [])
        if isinstance(item, dict) and item.get("id") is not None
    }
    timeline = 0.0
    utterances = []
    words: list[dict[str, Any]] = []
    for entry in entries:
        if entry.kind != "keep":
            continue
        duration = float(entry.end_s) - float(entry.start_s)
        local_words = _source_words_for_entry(entry, words_by_id) if words_by_id else []
        word_ids: list[str] = []
        if local_words:
            for item in local_words:
                word_id = f"expected-{len(words) + 1:06d}"
                words.append({
                    "id": word_id,
                    "text": item["text"],
                    "start_s": timeline + float(item["start_s"]),
                    "end_s": timeline + float(item["end_s"]),
                    "source_word_id": item["id"],
                })
                word_ids.append(word_id)
        else:
            tokens = normalize_tokens(entry.text)
            step = duration / max(len(tokens), 1)
            for index, token in enumerate(tokens):
                word_id = f"expected-{len(words) + 1:06d}"
                words.append({
                    "id": word_id,
                    "text": token,
                    "start_s": timeline + index * step,
                    "end_s": timeline + (index + 1) * step,
                })
                word_ids.append(word_id)
        utterances.append({
            "source_entry_id": entry.id,
            "start_s": timeline,
            "end_s": timeline + duration,
            "text": entry.text,
            "word_ids": word_ids,
            "caption_timing": "source-words" if local_words else "even-slice-fallback",
        })
        timeline += duration
    if not utterances:
        raise ValueError("approved transcript keeps no speech")
    return {"schema_version": 1, "duration_s": timeline, "words": words, "utterances": utterances}


def _timing_drift_report(
    expected_words: list[dict[str, Any]],
    actual_words: list[dict[str, Any]],
    *,
    max_drift_s: float,
) -> dict[str, Any]:
    """Greedy same-token alignment; report share of pairs with |Δstart| above threshold."""
    drifts: list[float] = []
    actual_index = 0
    for expected in expected_words:
        token = normalize_tokens(str(expected.get("text", "")))
        if not token:
            continue
        needle = token[0]
        match = None
        for probe in range(actual_index, len(actual_words)):
            actual_tokens = normalize_tokens(str(actual_words[probe].get("text", "")))
            if actual_tokens and actual_tokens[0] == needle:
                match = actual_words[probe]
                actual_index = probe + 1
                break
        if match is None:
            continue
        drifts.append(abs(float(match["start_s"]) - float(expected["start_s"])))
    if not drifts:
        return {
            "compared": 0,
            "over_threshold": 0,
            "ratio": 0.0,
            "max_drift_s": 0.0,
            "median_drift_s": 0.0,
        }
    ordered = sorted(drifts)
    over = sum(1 for item in drifts if item > max_drift_s)
    mid = ordered[len(ordered) // 2]
    return {
        "compared": len(drifts),
        "over_threshold": over,
        "ratio": round(over / len(drifts), 4),
        "max_drift_s": round(ordered[-1], 3),
        "median_drift_s": round(mid, 3),
    }


def verify_transcript(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    max_wer: float = 0.12,
    min_order_ratio: float = 0.9,
    max_silence_s: float = 1.2,
    max_timing_drift_s: float = 0.85,
    max_timing_drift_ratio: float = 0.25,
    max_lead_in_silence_s: float = 0.8,
    reject_adjacent_echoes: bool = True,
    reject_repeated_openers: bool = True,
) -> dict[str, Any]:
    expected_tokens = normalize_tokens(" ".join(item.get("text", "") for item in expected.get("words", [])))
    actual_tokens = normalize_tokens(" ".join(item.get("text", "") for item in actual.get("words", [])))
    if not expected_tokens or not actual_tokens:
        return {"schema_version": 1, "verdict": "FAIL", "reasons": ["expected or actual transcript is empty"]}
    distance = _levenshtein(expected_tokens, actual_tokens)
    wer = distance / len(expected_tokens)
    order_ratio = _lcs_length(expected_tokens, actual_tokens) / len(expected_tokens)
    long_gaps = []
    actual_words = actual.get("words", [])
    for left, right in zip(actual_words, actual_words[1:]):
        gap = float(right["start_s"]) - float(left["end_s"])
        if gap > max_silence_s:
            long_gaps.append({"after": left.get("text"), "gap_s": round(gap, 3)})
    echoes = adjacent_ngram_echoes(expected_tokens) if reject_adjacent_echoes else []
    openers_expected = repeated_clause_openers(expected_tokens) if reject_repeated_openers else []
    openers_actual = repeated_clause_openers(actual_tokens) if reject_repeated_openers else []
    openers = openers_expected + [
        {**item, "side": "actual"} for item in openers_actual
    ]
    lead_ins = leading_silence_windows(expected, max_lead_in_s=max_lead_in_silence_s)
    timing = _timing_drift_report(
        list(expected.get("words", [])),
        list(actual_words),
        max_drift_s=max_timing_drift_s,
    )
    reasons = []
    if wer > max_wer:
        reasons.append("word error rate exceeds threshold")
    if order_ratio < min_order_ratio:
        reasons.append("ordered token coverage below threshold")
    if long_gaps:
        reasons.append("unexpected long silence")
    if echoes:
        reasons.append("adjacent phrase echo in expected keep")
    if openers_expected or openers_actual:
        reasons.append("repeated clause opener retake in expected keep")
        if openers_actual and not openers_expected:
            reasons[-1] = "repeated clause opener retake in rendered speech"
    if lead_ins:
        reasons.append("leading silence inside keep clip")
    if (
        timing["compared"] >= 12
        and timing["ratio"] > max_timing_drift_ratio
    ):
        reasons.append("speech timing drift exceeds threshold")
    return {
        "schema_version": 1,
        "verdict": "FAIL" if reasons else "PASS",
        "metrics": {
            "wer": round(wer, 6),
            "order_ratio": round(order_ratio, 6),
            "edit_distance": distance,
            "timing_drift": timing,
        },
        "thresholds": {
            "wer_max": max_wer,
            "order_ratio_min": min_order_ratio,
            "silence_s_max": max_silence_s,
            "timing_drift_s_max": max_timing_drift_s,
            "timing_drift_ratio_max": max_timing_drift_ratio,
            "lead_in_silence_s_max": max_lead_in_silence_s,
        },
        "expected_tokens": expected_tokens,
        "actual_tokens": actual_tokens,
        "long_gaps": long_gaps,
        "adjacent_echoes": echoes,
        "repeated_openers": openers,
        "leading_silence": lead_ins,
        "reasons": reasons,
    }
