"""Strict editable transcript and revision-note contracts."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .utterances import coalesce_source_transcript


LEGACY_ENTRY_RE = re.compile(
    r'^<(keep|cut) id="([A-Za-z0-9_.-]+)" start="([0-9]+(?:\.[0-9]+)?)" '
    r'end="([0-9]+(?:\.[0-9]+)?)" words="([A-Za-z0-9_.,-]+)"(?: reason="([^"]*)")?>(.*)</\1>$'
)
LEGACY_VISUAL_RE = re.compile(
    r'^<visual id="([A-Za-z0-9_.-]+)" anchor="([A-Za-z0-9_.-]+)" '
    r'type="(library-broll|motion|screen|none)"(?: asset="([^"]*)")?>(.*)</visual>$'
)
ENTRY_HEADER_RE = re.compile(
    r'^\[([0-9:.]+)(?: (?:->|—) ([0-9:.]+))?\] (KEEP|CUT)'
    r'(?: \(([^)]+)\)| reason=([A-Za-z0-9_.-]+))? id=([A-Za-z0-9_.-]+)'
    r'(?: words=([A-Za-z0-9_.,-]+))?\s*$'
)
SEGMENT_END_RE = re.compile(r'^\[([0-9:.]+)\] КОНЕЦ СЕГМЕНТА\s*$')
VISUAL_SPAN_RE = re.compile(
    r'^\[([0-9:.]+)\] (MOTION|BROLL|FOOTAGE|SCREEN|NONE) ([A-Za-z0-9]+)'
    r' \((?:оверлей-)?(начало|конец)\)(?: @([A-Za-z0-9_.-]+))?(?: asset=([A-Za-z0-9_./\\-]+))?\s*$'
)
LEGACY_VISUAL_HEADER_RE = re.compile(
    r'^\[([0-9:.]+)\] (MOTION|BROLL|FOOTAGE|SCREEN|NONE) id=([A-Za-z0-9_.-]+) '
    r'anchor=([A-Za-z0-9_.-]+)(?: asset=([A-Za-z0-9_./\\-]+))?\s*$'
)
FIX_RE = re.compile(
    r'^- \[fix (blocking|speech|visual|audio|metadata)\] segment=([A-Za-z0-9_.-]+) '
    r'(?:range=([0-9:.]+)-([0-9:.]+) )?(.+)$'
)
RULE_RE = re.compile(r'^- \[rule candidate\] scope=(project|profile|global) (.+)$')

CUT_REASON_LABEL_RU: dict[str, str] = {
    "retake-marker": "маркер пересъёма",
    "proposed-repetition": "повтор фразы",
    "proposed-retake-prefix": "повтор начала дубля",
    "proposed-retake-block": "повтор блока",
    "proposed-take": "предложенный дубль",
    "false-start": "фальстарт",
}
CUT_REASON_CODE_BY_LABEL: dict[str, str] = {
    label.casefold(): code for code, label in CUT_REASON_LABEL_RU.items()
}
VISUAL_TYPE_BY_LABEL = {
    "MOTION": "motion",
    "BROLL": "library-broll",
    "FOOTAGE": "screen",
    "SCREEN": "screen",
    "NONE": "none",
}
VISUAL_LABEL_BY_TYPE = {
    "motion": "MOTION",
    "library-broll": "BROLL",
    "screen": "SCREEN",
    "none": "NONE",
}


@dataclass(frozen=True)
class TranscriptEntry:
    kind: str
    id: str
    start_s: float
    end_s: float
    word_ids: tuple[str, ...]
    text: str
    reason: str | None = None


@dataclass(frozen=True)
class VisualEntry:
    id: str
    anchor: str
    type: str
    brief: str
    asset: str | None = None
    end_s: float | None = None
    start_s: float | None = None


MOTION_MIN_DURATION_S = 1.8
MOTION_DEFAULT_DURATION_S = 3.0
MOTION_MAX_DURATION_S = 4.5


def compact_segment_number(segment_id: str) -> str:
    return str(int(str(segment_id)))


def compact_entry_id(segment_id: str, entry_id: str) -> str:
    match = re.fullmatch(r"u0*([0-9]+)((?:p[0-9]+|x[0-9]+)+)?", entry_id)
    if match:
        base = f"{compact_segment_number(segment_id)}.{int(match.group(1))}"
        suffix = match.group(2) or ""
        return f"{base}{suffix}"
    return entry_id


def expand_entry_id(segment_id: str | None, display_id: str) -> str:
    if not segment_id:
        return display_id
    match = re.fullmatch(
        rf"{re.escape(compact_segment_number(segment_id))}\.([0-9]+)((?:p[0-9]+|x[0-9]+)+)?",
        display_id,
    )
    if match:
        base = f"u{int(match.group(1)):04d}"
        suffix = match.group(2) or ""
        return f"{base}{suffix}"
    return display_id


def compact_visual_id(segment_id: str, index: int) -> str:
    if index < 1 or index > 26:
        raise ValueError("visual index must be between 1 and 26")
    return f"{compact_segment_number(segment_id)}{chr(ord('a') + index - 1)}"


def strip_speech_markup(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") == 2:
        return stripped[2:-2].strip()
    return stripped


def format_timecode(seconds: float) -> str:
    if seconds < 0 or not (seconds == seconds):  # NaN check
        raise ValueError(f"invalid seconds: {seconds}")
    total_ms = int(round(float(seconds) * 1000))
    minutes, ms = divmod(total_ms, 60_000)
    secs, millis = divmod(ms, 1000)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes}:{secs:02d}.{millis:03d}"


def parse_timecode(value: str) -> float:
    parts = value.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid timecode: {value}")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def validate_entries(entries: Iterable[TranscriptEntry], valid_word_ids: set[str] | None = None) -> list[TranscriptEntry]:
    values = list(entries)
    ids: set[str] = set()
    previous_end = -1.0
    for entry in values:
        if entry.kind not in {"keep", "cut"}:
            raise ValueError(f"unknown transcript entry kind: {entry.kind}")
        if entry.id in ids:
            raise ValueError(f"duplicate transcript entry id: {entry.id}")
        ids.add(entry.id)
        if entry.start_s < 0 or entry.end_s < entry.start_s:
            raise ValueError(f"invalid time range for {entry.id}")
        resolved_end = entry.end_s if entry.end_s > entry.start_s else entry.start_s
        if entry.start_s < previous_end - 1e-6:
            raise ValueError(f"overlapping or reordered transcript entry: {entry.id}")
        previous_end = resolved_end
        if valid_word_ids is not None:
            if not entry.word_ids:
                raise ValueError(f"transcript entry has no stable word ids: {entry.id}")
            if not set(entry.word_ids).issubset(valid_word_ids):
                raise ValueError(f"transcript entry references unknown word ids: {entry.id}")
    return values


def _anchor_entry(entries: list[TranscriptEntry], anchor: str) -> TranscriptEntry:
    for entry in entries:
        if entry.id == anchor:
            return entry
    raise ValueError(f"visual anchor not found: {anchor}")


def _anchor_start(entries: list[TranscriptEntry], anchor: str) -> float:
    return _anchor_entry(entries, anchor).start_s


def resolve_visual_start(
    entries: list[TranscriptEntry],
    visual: VisualEntry,
    *,
    start_offset_s: float = 0.0,
) -> float:
    if visual.start_s is not None:
        return float(visual.start_s)
    anchor = _anchor_entry(entries, visual.anchor)
    offset = max(0.0, float(start_offset_s))
    start = float(anchor.start_s) + offset
    if start >= float(anchor.end_s):
        return float(anchor.start_s)
    return start


def resolve_visual_end(
    entries: list[TranscriptEntry],
    visual: VisualEntry,
    *,
    default_duration_s: float = MOTION_DEFAULT_DURATION_S,
    start_offset_s: float = 0.0,
) -> float:
    if visual.end_s is not None:
        return float(visual.end_s)
    anchor = _anchor_entry(entries, visual.anchor)
    start = resolve_visual_start(entries, visual, start_offset_s=start_offset_s)
    duration = min(max(float(default_duration_s), MOTION_MIN_DURATION_S), MOTION_MAX_DURATION_S)
    end = start + duration
    # Prefer staying inside the spoken clause; if clause is shorter than min, use full clause.
    if end > float(anchor.end_s):
        end = float(anchor.end_s)
    if end - start < MOTION_MIN_DURATION_S and float(anchor.end_s) - start >= MOTION_MIN_DURATION_S:
        end = start + MOTION_MIN_DURATION_S
        if end > float(anchor.end_s):
            end = float(anchor.end_s)
    if end <= start:
        end = min(float(anchor.end_s), start + MOTION_MIN_DURATION_S)
    return end


def format_cut_reason_label(reason: str | None) -> str | None:
    if not reason:
        return None
    return CUT_REASON_LABEL_RU.get(reason, reason)


def parse_cut_reason_label(label: str | None) -> str | None:
    if not label:
        return None
    stripped = label.strip()
    if not stripped:
        return None
    return CUT_REASON_CODE_BY_LABEL.get(stripped.casefold(), stripped)


def render_transcript(
    entries: Iterable[TranscriptEntry],
    visuals: Iterable[VisualEntry] = (),
    *,
    segment_id: str | None = None,
    default_motion_duration_s: float = MOTION_DEFAULT_DURATION_S,
    media_end_s: float | None = None,
) -> str:
    values = validate_entries(entries)
    visual_values = list(visuals)
    coverage_end = max((float(item.end_s) for item in values), default=0.0)
    segment_end = float(media_end_s) if media_end_s is not None else coverage_end
    lines = [
        "# Editable transcript",
        "",
        "<!-- Preview-safe Gate 1. KEEP/CUT = речь. MOTION = оверлей ПОВЕРХ речи (не вставка после фразы). -->",
        "",
    ]
    if values:
        coverage = (
            f"<!-- coverage: {format_timecode(values[0].start_s)} — "
            f"{format_timecode(coverage_end)} "
            f"({len(values)} blocks); конец сегмента {format_timecode(segment_end)} -->"
        )
        lines.extend([coverage, ""])

    visuals_by_anchor: dict[str, list[VisualEntry]] = {}
    for visual in visual_values:
        visuals_by_anchor.setdefault(visual.anchor, []).append(visual)

    def display_entry_id(entry_id: str) -> str:
        return compact_entry_id(segment_id, entry_id) if segment_id else entry_id

    for entry in values:
        kind = "KEEP" if entry.kind == "keep" else "CUT"
        duration = float(entry.end_s) - float(entry.start_s)
        if duration >= 8.0 or _is_split_entry_id(entry.id):
            header = f"[{format_timecode(entry.start_s)} — {format_timecode(entry.end_s)}] {kind}"
        else:
            header = f"[{format_timecode(entry.start_s)}] {kind}"
        if entry.kind == "cut" and entry.reason:
            header += f" ({format_cut_reason_label(entry.reason)})"
        header += f" id={display_entry_id(entry.id)}"
        lines.append(header)
        lines.append(f"**{entry.text}**")
        lines.append("")
        for visual in visuals_by_anchor.get(entry.id, []):
            label = VISUAL_LABEL_BY_TYPE.get(visual.type)
            if label is None:
                raise ValueError(f"unsupported visual type: {visual.type}")
            start_s = resolve_visual_start(values, visual)
            end_s = resolve_visual_end(
                values, visual, default_duration_s=default_motion_duration_s,
            )
            hold = max(0.0, end_s - start_s)
            start_header = (
                f"[{format_timecode(start_s)}] {label} {visual.id} (оверлей-начало) "
                f"@{display_entry_id(visual.anchor)}"
            )
            if visual.asset:
                start_header += f" asset={visual.asset}"
            lines.append(start_header)
            lines.append(f"(поверх речи ~{hold:.1f}с) {visual.brief}")
            lines.append("")
            lines.append(f"[{format_timecode(end_s)}] {label} {visual.id} (оверлей-конец)")
            lines.append("")
    if values:
        lines.append(f"[{format_timecode(segment_end)}] КОНЕЦ СЕГМЕНТА")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _flush_block(
    *,
    kind: str,
    payload: dict[str, Any],
    body_lines: list[str],
    entries: list[TranscriptEntry],
    visuals: list[VisualEntry],
    line_number: int,
) -> None:
    body = "\n".join(body_lines).strip()
    if kind == "entry":
        if not body:
            raise ValueError(f"empty transcript entry body near line {line_number}")
        entries.append(TranscriptEntry(
            kind=payload["kind"],
            id=payload["id"],
            start_s=payload["start_s"],
            end_s=payload["end_s"],
            word_ids=payload["word_ids"],
            text=strip_speech_markup(body),
            reason=payload.get("reason"),
        ))
        return
    if kind == "visual":
        if not body:
            raise ValueError(f"empty visual brief near line {line_number}")
        brief = body
        if brief.startswith("(поверх речи"):
            closing = brief.find(") ")
            if closing >= 0:
                brief = brief[closing + 2 :].strip()
        visuals.append(VisualEntry(
            id=payload["id"],
            anchor=payload["anchor"],
            type=payload["type"],
            brief=brief,
            asset=payload.get("asset"),
            end_s=payload.get("end_s"),
            start_s=payload.get("stamp_s"),
        ))
        return
    raise ValueError(f"unknown transcript block kind: {kind}")


def parse_transcript(
    text: str,
    *,
    valid_word_ids: set[str] | None = None,
    segment_id: str | None = None,
) -> tuple[list[TranscriptEntry], list[VisualEntry]]:
    legacy = any(
        LEGACY_ENTRY_RE.fullmatch(line.strip()) or LEGACY_VISUAL_RE.fullmatch(line.strip())
        for line in text.splitlines()
        if line.strip()
    )
    if legacy:
        return _parse_legacy_transcript(text, valid_word_ids=valid_word_ids)

    entries: list[TranscriptEntry] = []
    visuals: list[VisualEntry] = []
    current_kind: str | None = None
    current_payload: dict[str, Any] | None = None
    body_lines: list[str] = []
    last_header_line = 0

    def commit(line_number: int) -> None:
        nonlocal current_kind, current_payload, body_lines
        if current_kind is None or current_payload is None:
            return
        _flush_block(
            kind=current_kind,
            payload=current_payload,
            body_lines=body_lines,
            entries=entries,
            visuals=visuals,
            line_number=line_number,
        )
        current_kind = None
        current_payload = None
        body_lines = []

    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
            if stripped.startswith("#") or stripped.startswith("<!--"):
                commit(line_number)
            elif current_kind is not None and body_lines:
                commit(line_number)
            continue
        if SEGMENT_END_RE.fullmatch(stripped):
            commit(line_number)
            continue
        entry_header = ENTRY_HEADER_RE.fullmatch(stripped)
        if entry_header:
            commit(line_number)
            start, end, kind, reason_label, reason_code, entry_id, words = entry_header.groups()
            start_s = parse_timecode(start)
            current_kind = "entry"
            current_payload = {
                "kind": kind.lower(),
                "id": expand_entry_id(segment_id, entry_id),
                "start_s": start_s,
                "end_s": parse_timecode(end) if end else start_s,
                "word_ids": tuple(item for item in (words or "").split(",") if item),
                "reason": reason_code or parse_cut_reason_label(reason_label),
            }
            last_header_line = line_number
            continue
        span_header = VISUAL_SPAN_RE.fullmatch(stripped)
        if span_header:
            stamp, label, visual_id, marker, anchor, asset = span_header.groups()
            stamp_s = parse_timecode(stamp)
            if marker == "конец":
                commit(line_number)
                updated = False
                for index, visual in enumerate(visuals):
                    if visual.id != visual_id:
                        continue
                    visuals[index] = VisualEntry(
                        visual.id,
                        visual.anchor,
                        visual.type,
                        visual.brief,
                        visual.asset,
                        stamp_s,
                        visual.start_s,
                    )
                    updated = True
                    break
                if not updated:
                    raise ValueError(f"motion end without start at line {line_number}: {raw}")
                last_header_line = line_number
                continue
            commit(line_number)
            if not anchor:
                raise ValueError(f"motion start requires @anchor at line {line_number}")
            current_kind = "visual"
            current_payload = {
                "id": visual_id,
                "anchor": expand_entry_id(segment_id, anchor),
                "type": VISUAL_TYPE_BY_LABEL[label],
                "asset": asset,
                "stamp_s": stamp_s,
            }
            last_header_line = line_number
            continue
        visual_header = LEGACY_VISUAL_HEADER_RE.fullmatch(stripped)
        if visual_header:
            commit(line_number)
            stamp, label, visual_id, anchor, asset = visual_header.groups()
            current_kind = "visual"
            current_payload = {
                "id": visual_id,
                "anchor": expand_entry_id(segment_id, anchor),
                "type": VISUAL_TYPE_BY_LABEL[label],
                "asset": asset,
                "stamp_s": parse_timecode(stamp),
            }
            last_header_line = line_number
            continue
        if current_kind is None:
            raise ValueError(f"invalid transcript markup at line {line_number}: {raw}")
        body_lines.append(line)

    commit(last_header_line or 1)
    validate_entries(entries, valid_word_ids)
    entry_ids = {item.id for item in entries}
    visual_ids: set[str] = set()
    for visual in visuals:
        if visual.id in visual_ids:
            raise ValueError(f"duplicate visual id: {visual.id}")
        visual_ids.add(visual.id)
        if visual.anchor not in entry_ids:
            raise ValueError(f"visual {visual.id} references unknown anchor {visual.anchor}")
    return entries, visuals


def _parse_legacy_transcript(
    text: str, *, valid_word_ids: set[str] | None = None
) -> tuple[list[TranscriptEntry], list[VisualEntry]]:
    entries: list[TranscriptEntry] = []
    visuals: list[VisualEntry] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("<!--"):
            continue
        match = LEGACY_ENTRY_RE.fullmatch(line)
        if match:
            kind, entry_id, start, end, words, reason, body = match.groups()
            if "<" in body or ">" in body:
                raise ValueError(f"invalid transcript markup at line {line_number}: nested tags are not allowed")
            entries.append(TranscriptEntry(
                kind=kind, id=entry_id, start_s=float(start), end_s=float(end),
                word_ids=tuple(item for item in words.split(",") if item),
                text=html.unescape(body), reason=html.unescape(reason) if reason else None,
            ))
            continue
        visual = LEGACY_VISUAL_RE.fullmatch(line)
        if visual:
            visual_id, anchor, visual_type, asset, brief = visual.groups()
            visuals.append(VisualEntry(
                visual_id, anchor, visual_type, html.unescape(brief),
                html.unescape(asset) if asset else None,
            ))
            continue
        raise ValueError(f"invalid transcript markup at line {line_number}: {raw}")
    validate_entries(entries, valid_word_ids)
    entry_ids = {item.id for item in entries}
    visual_ids: set[str] = set()
    for visual in visuals:
        if visual.id in visual_ids:
            raise ValueError(f"duplicate visual id: {visual.id}")
        visual_ids.add(visual.id)
        if visual.anchor not in entry_ids:
            raise ValueError(f"visual {visual.id} references unknown anchor {visual.anchor}")
    return entries, visuals


def _is_split_entry_id(entry_id: str) -> bool:
    return bool(re.search(r"(?:p|x)[0-9]+", entry_id))


def _utterance_id_aliases(utterance_id: str) -> list[str]:
    """u2 / u0002 (and split suffixes) resolve to the same source utterance."""
    match = re.fullmatch(r"(u)0*([0-9]+)((?:p[0-9]+|x[0-9]+)+)?", str(utterance_id))
    if not match:
        return [str(utterance_id)]
    prefix, number, suffix = match.group(1), int(match.group(2)), match.group(3) or ""
    return list(dict.fromkeys([
        str(utterance_id),
        f"{prefix}{number}{suffix}",
        f"{prefix}{number:04d}{suffix}",
    ]))


def _source_utterance(
    by_id: dict[str, dict[str, Any]],
    entry_id: str,
) -> dict[str, Any] | None:
    for alias in _utterance_id_aliases(entry_id):
        found = by_id.get(alias)
        if found is not None:
            return found
    return None


def enrich_entries_from_source(
    entries: list[TranscriptEntry],
    source_transcript: dict[str, Any],
) -> list[TranscriptEntry]:
    """Fill end times and word IDs from source utterances while keeping human text/kind."""
    coalesced = coalesce_source_transcript(source_transcript)
    by_id = {str(item["id"]): item for item in coalesced["utterances"]}
    enriched: list[TranscriptEntry] = []
    for entry in entries:
        source = _source_utterance(by_id, entry.id)
        if source is None:
            parent_match = re.fullmatch(r"(u0*[0-9]+)((?:p[0-9]+|x[0-9]+)+)", entry.id)
            if parent_match is None:
                raise ValueError(f"transcript entry id not found in source utterances: {entry.id}")
            parent = _source_utterance(by_id, parent_match.group(1))
            if parent is None:
                raise ValueError(
                    f"transcript split {entry.id} has unknown parent {parent_match.group(1)}"
                )
            if entry.end_s <= entry.start_s:
                raise ValueError(
                    f"split entry {entry.id} requires start—end timecodes in transcript.md "
                    "(round-trip must preserve part bounds)"
                )
            enriched.append(TranscriptEntry(
                kind=entry.kind,
                id=entry.id,
                start_s=entry.start_s,
                end_s=entry.end_s,
                word_ids=entry.word_ids or tuple(str(item) for item in parent.get("word_ids") or ()),
                text=entry.text,
                reason=entry.reason,
            ))
            continue
        word_ids = tuple(str(item) for item in source.get("word_ids") or [])
        if entry.word_ids:
            word_ids = entry.word_ids
        enriched.append(TranscriptEntry(
            kind=entry.kind,
            id=entry.id,
            start_s=float(source["start_s"]),
            end_s=float(source["end_s"]),
            word_ids=word_ids,
            text=entry.text,
            reason=entry.reason,
        ))
    return validate_entries(enriched)


def load_transcript(path: Path, source_transcript: dict[str, Any]) -> tuple[list[TranscriptEntry], list[VisualEntry]]:
    valid_ids = {word["id"] for word in source_transcript.get("words", [])}
    segment_id = path.parent.name if path.parent.name.isdigit() else None
    entries, visuals = parse_transcript(
        path.read_text(encoding="utf-8"),
        valid_word_ids=None,
        segment_id=segment_id,
    )
    enriched = enrich_entries_from_source(entries, source_transcript)
    validate_entries(enriched, valid_word_ids=valid_ids or None)
    return enriched, visuals


def parse_fixes(text: str, *, allow_empty: bool = False) -> dict[str, Any]:
    fixes: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = FIX_RE.fullmatch(line)
        if match:
            kind, segment, start, end, description = match.groups()
            item: dict[str, Any] = {
                "id": f"fix-{len(fixes) + 1:03d}", "kind": kind, "segment_id": segment,
                "description": description, "status": "OPEN", "blocking": kind == "blocking",
            }
            if start and end:
                item["start_s"] = parse_timecode(start)
                item["end_s"] = parse_timecode(end)
                if item["end_s"] <= item["start_s"]:
                    raise ValueError(f"fix range is reversed at line {line_number}")
            fixes.append(item)
            continue
        rule = RULE_RE.fullmatch(line)
        if rule:
            scope, description = rule.groups()
            rules.append({"id": f"rule-{len(rules) + 1:03d}", "scope": scope, "description": description, "status": "PROPOSED"})
            continue
        raise ValueError(f"invalid revision note at line {line_number}: {raw}")
    if not fixes and not rules and not allow_empty:
        raise ValueError("revision notes contain no fixes or rule candidates")
    return {"schema_version": 1, "fixes": fixes, "rule_candidates": rules}
