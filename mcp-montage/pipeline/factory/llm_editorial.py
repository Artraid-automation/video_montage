"""Mandatory LLM cohesion pass over heuristic CUT/KEEP proposals."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .io import atomic_write_json, read_json
from .transcript import TranscriptEntry, format_timecode
from .utterances import RETAKE_MARKER_RE


LLM_EDITORIAL_WORKER_VERSION = "llm-editorial-v3"
PROMPT_VERSION = "gate1-editorial-cohesion.v2"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / f"{PROMPT_VERSION}.md"
SUFFIX_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")

HOOK_START_RE = re.compile(
    r"(?i)(?:^|(?<=[.!?…]\s))(?:"
    r"(?:по\s+)?моим\s+наблюдениям\s+деньги\s+уходят|"
    r"деньги\s+уходят\s+не\s+потому|"
    r"короче\s+говоря|"
    r"они\s+уходят\s+не\s+потому|"
    r"они\s+уходят,\s+потому"
    r")"
)
SPLIT_BEFORE_TAKE_RE = re.compile(
    r"(?i)(?<=[.!?…]\s)(?=("
    r"(?:по\s+)?моим\s+наблюдениям\s+деньги\s+уходят|"
    r"деньги\s+уходят\s+не\s+потому|"
    r"короче\s+говоря|"
    r"они\s+уходят\s+не\s+потому"
    r"))"
)


def load_editorial_prompt() -> str:
    if not PROMPT_PATH.is_file():
        raise ValueError(f"missing LLM editorial prompt: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def hook_start_count(text: str) -> int:
    return len(HOOK_START_RE.findall(text.strip()))


def has_false_cohesion(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if hook_start_count(stripped) >= 2:
        return True
    if RETAKE_MARKER_RE.search(stripped) and hook_start_count(stripped) >= 1:
        return True
    return False


def _split_multi_take_text(text: str) -> list[str]:
    parts = [item.strip() for item in SPLIT_BEFORE_TAKE_RE.split(text) if item and item.strip()]
    if len(parts) >= 2:
        return parts
    match = RETAKE_MARKER_RE.search(text)
    if not match:
        return [text.strip()] if text.strip() else []
    cut_at = match.end()
    sentence_end = re.search(r"[.!?…]", text[cut_at:])
    if sentence_end:
        cut_at = cut_at + sentence_end.end()
    left = text[:cut_at].strip()
    right = text[cut_at:].strip()
    return [item for item in (left, right) if item]


def _partition_entry(entry: TranscriptEntry, parts: list[str], *, id_fn) -> list[TranscriptEntry]:
    weights = [max(len(part), 1) for part in parts]
    total = float(sum(weights))
    span = float(entry.end_s) - float(entry.start_s)
    cursor = float(entry.start_s)
    out: list[TranscriptEntry] = []
    for index, part in enumerate(parts, 1):
        is_last = index == len(parts)
        end_s = float(entry.end_s) if is_last else cursor + span * (weights[index - 1] / total)
        if end_s <= cursor:
            end_s = cursor + max(span / len(parts), 0.01)
        out.append(TranscriptEntry(
            kind=entry.kind,
            id=id_fn(index),
            start_s=cursor,
            end_s=end_s,
            word_ids=entry.word_ids if index == 1 else (),
            text=part,
            reason=entry.reason,
        ))
        cursor = end_s
    return out


def explode_multi_take_entries(entries: list[TranscriptEntry]) -> list[TranscriptEntry]:
    """Safety-net split for falsely-cohesive mega blocks."""
    current = list(entries)
    for _ in range(4):
        exploded: list[TranscriptEntry] = []
        changed = False
        for entry in current:
            if not has_false_cohesion(entry.text):
                exploded.append(entry)
                continue
            parts = _split_multi_take_text(entry.text)
            if len(parts) < 2:
                exploded.append(entry)
                continue
            changed = True

            def _id(index: int, parent: str = entry.id) -> str:
                return f"{parent}p{index}" if "p" not in parent and "x" not in parent else f"{parent}x{index}"

            exploded.extend(_partition_entry(entry, parts, id_fn=_id))
        current = exploded
        if not changed:
            break
    return current


def apply_llm_splits(
    entries: list[TranscriptEntry],
    splits: list[dict[str, Any]] | None,
) -> list[TranscriptEntry]:
    """Apply LLM-requested contiguous text partitions before KEEP/CUT decisions."""
    if not splits:
        return list(entries)
    by_id = {entry.id: entry for entry in entries}
    split_map: dict[str, list[TranscriptEntry]] = {}
    for item in splits:
        if not isinstance(item, dict):
            raise ValueError("llm split item must be an object")
        parent_id = str(item.get("id", ""))
        parent = by_id.get(parent_id)
        if parent is None:
            raise ValueError(f"llm split references unknown id: {parent_id}")
        parts_raw = item.get("parts")
        if not isinstance(parts_raw, list) or len(parts_raw) < 2:
            raise ValueError(f"llm split for {parent_id} requires at least 2 parts")
        texts: list[str] = []
        suffixes: list[str] = []
        for index, part in enumerate(parts_raw, 1):
            if not isinstance(part, dict):
                raise ValueError(f"llm split part must be an object for {parent_id}")
            text = str(part.get("text", "")).strip()
            suffix = str(part.get("suffix") or f"p{index}").strip()
            if not text:
                raise ValueError(f"llm split part text empty for {parent_id}/{suffix}")
            if not SUFFIX_RE.fullmatch(suffix):
                raise ValueError(f"llm split suffix invalid for {parent_id}: {suffix}")
            texts.append(text)
            suffixes.append(suffix)
        joined = "".join(texts)
        parent_compact = re.sub(r"\s+", "", parent.text)
        joined_compact = re.sub(r"\s+", "", joined)
        # Allow whitespace normalization between parts, but require full coverage.
        if joined_compact != parent_compact:
            # Try join with single spaces as LLM may drop/add spaces at boundaries.
            spaced = " ".join(texts)
            if re.sub(r"\s+", "", spaced) != parent_compact:
                raise ValueError(
                    f"llm split parts for {parent_id} must contiguous-partition parent text"
                )
            texts = []
            cursor = 0
            normalized_parent = parent.text
            for part_text in [str(p.get("text", "")).strip() for p in parts_raw]:
                # locate next occurrence greedily
                idx = normalized_parent.find(part_text, cursor)
                if idx < 0:
                    raise ValueError(f"llm split part not found in parent {parent_id}: {part_text[:40]}")
                if idx > cursor:
                    gap = normalized_parent[cursor:idx].strip()
                    if gap:
                        raise ValueError(f"llm split leaves uncovered gap in {parent_id}: {gap[:40]}")
                texts.append(part_text)
                cursor = idx + len(part_text)
            if normalized_parent[cursor:].strip():
                raise ValueError(f"llm split leaves uncovered tail in {parent_id}")
        children = _partition_entry(
            parent,
            texts,
            id_fn=lambda index: f"{parent_id}{suffixes[index - 1]}",
        )
        split_map[parent_id] = children
    out: list[TranscriptEntry] = []
    for entry in entries:
        out.extend(split_map.get(entry.id, [entry]))
    return out


def build_llm_editorial_request(
    segment_id: str,
    entries: list[TranscriptEntry],
    *,
    prompt_version: str = PROMPT_VERSION,
) -> dict[str, Any]:
    if not entries:
        raise ValueError("llm editorial requires at least one transcript entry")
    media_end_s = max(float(item.end_s) for item in entries)
    return {
        "schema_version": 2,
        "kind": "llm-editorial-request",
        "worker_version": LLM_EDITORIAL_WORKER_VERSION,
        "prompt_version": prompt_version,
        "segment_id": str(segment_id),
        "media_end_s": media_end_s,
        "media_end_timecode": format_timecode(media_end_s),
        "blocks": [
            {
                "id": entry.id,
                "start_s": entry.start_s,
                "end_s": entry.end_s,
                "text": entry.text,
                "heuristic_kind": entry.kind,
                "heuristic_reason": entry.reason,
                "false_cohesion": has_false_cohesion(entry.text),
            }
            for entry in entries
        ],
    }


def _normalize_decisions(
    decisions: list[Any],
    *,
    expected_ids: list[str],
    text_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("llm editorial decisions must be a non-empty list")
    seen: list[str] = []
    normalized: list[dict[str, Any]] = []
    by_response = {}
    for item in decisions:
        if not isinstance(item, dict):
            raise ValueError("llm editorial decision must be an object")
        entry_id = str(item.get("id", ""))
        kind = str(item.get("kind", ""))
        if entry_id in by_response:
            raise ValueError(f"duplicate llm editorial decision id: {entry_id}")
        if kind not in {"keep", "cut"}:
            raise ValueError(f"invalid llm editorial kind for {entry_id}: {kind}")
        reason = item.get("reason")
        if kind == "keep" and reason not in (None, ""):
            reason = None
        if kind == "cut" and (reason is None or not str(reason).strip()):
            raise ValueError(f"cut decision requires reason: {entry_id}")
        by_response[entry_id] = {
            "id": entry_id,
            "kind": kind,
            "reason": None if reason in (None, "") else str(reason).strip(),
        }
    for entry_id in expected_ids:
        if entry_id in by_response:
            decision = by_response[entry_id]
        else:
            # Safety-net explode may create parts the model did not name → default CUT.
            decision = {"id": entry_id, "kind": "cut", "reason": "внутренние повторы"}
        if decision["kind"] == "keep" and has_false_cohesion(text_by_id.get(entry_id, "")):
            raise ValueError(
                f"KEEP forbidden on multi-take/false-cohesion block {entry_id}; "
                "use splits[] or CUT"
            )
        if entry_id in seen:
            raise ValueError(f"duplicate llm editorial decision id: {entry_id}")
        seen.append(entry_id)
        normalized.append(decision)
    extra = sorted(set(by_response) - set(expected_ids))
    if extra:
        raise ValueError(f"llm editorial decisions reference unknown ids after splits: {extra}")
    return normalized


def validate_llm_editorial_response(
    response: dict[str, Any],
    request: dict[str, Any],
    *,
    working_entries: list[TranscriptEntry],
) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ValueError("llm editorial response must be an object")
    schema_version = int(response.get("schema_version", -1))
    if schema_version not in {1, 2}:
        raise ValueError("llm editorial response schema_version must be 1 or 2")
    if str(response.get("prompt_version", "")) != str(request["prompt_version"]):
        raise ValueError("llm editorial prompt_version mismatch")
    if str(response.get("segment_id", "")) != str(request["segment_id"]):
        raise ValueError("llm editorial segment_id mismatch")
    expected = [item.id for item in working_entries]
    text_by_id = {item.id: item.text for item in working_entries}
    normalized = _normalize_decisions(
        response.get("decisions"),
        expected_ids=expected,
        text_by_id=text_by_id,
    )
    summary = str(response.get("narrative_summary", "")).strip()
    if not summary:
        raise ValueError("llm editorial narrative_summary is required")
    risks = response.get("risks", [])
    if not isinstance(risks, list) or any(not isinstance(item, str) for item in risks):
        raise ValueError("llm editorial risks must be a list of strings")
    coverage_end = max(float(item.end_s) for item in working_entries)
    media_end = float(request.get("media_end_s", coverage_end))
    if coverage_end + 1.0 < media_end:
        raise ValueError(
            f"llm editorial coverage ends at {coverage_end:.3f}s but media_end is {media_end:.3f}s"
        )
    return {
        "schema_version": schema_version,
        "kind": "llm-editorial-result",
        "worker_version": LLM_EDITORIAL_WORKER_VERSION,
        "prompt_version": str(request["prompt_version"]),
        "segment_id": str(request["segment_id"]),
        "request_block_count": len(request["blocks"]),
        "working_block_count": len(expected),
        "splits": response.get("splits") or [],
        "decisions": normalized,
        "narrative_summary": summary,
        "risks": [str(item) for item in risks],
        "coverage_end_s": coverage_end,
        "media_end_s": media_end,
        "source_request": {
            "segment_id": request["segment_id"],
            "prompt_version": request["prompt_version"],
            "block_ids": [str(item["id"]) for item in request["blocks"]],
        },
    }


def apply_llm_editorial_decisions(
    entries: list[TranscriptEntry],
    result: dict[str, Any],
) -> list[TranscriptEntry]:
    by_id = {item["id"]: item for item in result["decisions"]}
    updated: list[TranscriptEntry] = []
    for entry in entries:
        decision = by_id.get(entry.id)
        if decision is None:
            raise ValueError(f"llm editorial missing decision for {entry.id}")
        updated.append(TranscriptEntry(
            kind=decision["kind"],
            id=entry.id,
            start_s=entry.start_s,
            end_s=entry.end_s,
            word_ids=entry.word_ids,
            text=entry.text,
            reason=decision["reason"],
        ))
    return updated


def _provider_fixture(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    fixture_path = config.get("fixture_path")
    if fixture_path:
        return read_json(Path(fixture_path))
    splits: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for block in request["blocks"]:
        if has_false_cohesion(block["text"]):
            parts = _split_multi_take_text(block["text"])
            if len(parts) >= 2:
                splits.append({
                    "id": block["id"],
                    "parts": [{"suffix": f"p{index}", "text": part} for index, part in enumerate(parts, 1)],
                })
                for index, part in enumerate(parts, 1):
                    kind = "keep" if index == len(parts) and block["heuristic_kind"] == "keep" else "cut"
                    if kind == "keep" and has_false_cohesion(part):
                        kind = "cut"
                    decisions.append({
                        "id": f"{block['id']}p{index}",
                        "kind": kind,
                        "reason": None if kind == "keep" else "внутренние повторы",
                    })
                continue
        kind = block["heuristic_kind"]
        reason = block.get("heuristic_reason")
        if kind == "keep" and has_false_cohesion(block["text"]):
            kind = "cut"
            reason = "внутренние повторы"
        decisions.append({
            "id": block["id"],
            "kind": kind,
            "reason": reason or ("эвристика" if kind == "cut" else None),
        })
    return {
        "schema_version": 2,
        "prompt_version": request["prompt_version"],
        "segment_id": request["segment_id"],
        "splits": splits,
        "decisions": decisions,
        "narrative_summary": "Fixture provider applied heuristic decisions with split safety-net.",
        "risks": ["fixture provider — not for production Gate 1"],
    }


def _provider_file(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(config.get("response_path", "")))
    if not path.is_file():
        raise ValueError(
            f"llm editorial file provider missing response: {path}. "
            "Write decisions JSON for the request artifact, then resume."
        )
    return read_json(path)


def _provider_openai(request: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get(str(config.get("api_key_env", "OPENAI_API_KEY")), "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for openai llm editorial provider")
    model = str(config.get("model", "gpt-4.1-mini"))
    prompt = load_editorial_prompt()
    body = {
        "model": model,
        "temperature": float(config.get("temperature", 0.2)),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False, indent=2)},
        ],
    }
    http_request = urllib.request.Request(
        str(config.get("api_url", "https://api.openai.com/v1/chat/completions")),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=float(config.get("timeout_s", 120))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ValueError(f"openai llm editorial request failed: {exc}") from exc
    return json.loads(payload["choices"][0]["message"]["content"])


PROVIDER_REGISTRY: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "fixture": _provider_fixture,
    "file": _provider_file,
    "openai": _provider_openai,
    "agent": _provider_file,
}


def run_llm_editorial(
    segment_id: str,
    entries: list[TranscriptEntry],
    *,
    output_dir: Path,
    config: dict[str, Any] | None = None,
) -> tuple[list[TranscriptEntry], dict[str, Any]]:
    """Mandatory cohesion pass. LLM may split; explode() is only a safety-net."""
    settings = dict(config or {})
    if settings.get("enabled", True) is False:
        raise ValueError("llm editorial is mandatory; set provider=fixture only in tests")
    provider_name = str(settings.get("provider", "fixture"))
    provider = PROVIDER_REGISTRY.get(provider_name)
    if provider is None:
        raise ValueError(f"unknown llm editorial provider: {provider_name}")
    prompt_version = str(settings.get("prompt_version", PROMPT_VERSION))
    output_dir.mkdir(parents=True, exist_ok=True)
    request = build_llm_editorial_request(segment_id, entries, prompt_version=prompt_version)
    atomic_write_json(output_dir / "llm-editorial-request.json", request)
    if provider_name in {"file", "agent"} and "response_path" not in settings:
        settings = {**settings, "response_path": str(output_dir / "llm-editorial-response.json")}
    raw = provider(request, settings)
    working = apply_llm_splits(entries, raw.get("splits") if isinstance(raw, dict) else None)
    working = explode_multi_take_entries(working)
    result = validate_llm_editorial_response(raw, request, working_entries=working)
    result["provider"] = provider_name
    atomic_write_json(output_dir / "llm-editorial.json", result)
    return apply_llm_editorial_decisions(working, result), result
