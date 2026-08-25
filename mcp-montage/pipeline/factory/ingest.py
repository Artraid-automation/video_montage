"""Raw media inventory and logical feed grouping."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import sha256_file, utc_timestamp
from .media import duration_s, probe, streams


MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".mxf", ".avi", ".webm", ".wav", ".mp3", ".m4a", ".aac", ".flac"}
SEGMENT_RE = re.compile(r"^(\d{1,4})(?:[._ -]|$)")


def detect_role(path: Path, report: dict[str, Any]) -> str:
    name = path.stem.lower()
    tokens = set(re.split(r"[._ -]+", name))
    if tokens & {"screen", "screencast", "desktop"}:
        return "screen"
    if tokens & {"mic", "audio", "wav", "lav", "boom"}:
        return "audio"
    has_video = bool(streams(report, "video"))
    has_audio = bool(streams(report, "audio"))
    if has_video and tokens & {"camera", "cam", "aroll", "a-roll"}:
        return "camera"
    if has_video:
        return "camera"
    if has_audio:
        return "audio"
    raise ValueError(f"unsupported media streams: {path.name}")


def scan_raw(project_root: Path, *, allow_number_gaps: bool = False) -> dict[str, Any]:
    project_root = project_root.resolve(strict=True)
    raw_root = project_root / "01_raw"
    if not raw_root.is_dir():
        raise ValueError(f"raw input directory does not exist: {raw_root}")
    paths = sorted(
        (path for path in raw_root.iterdir() if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS),
        key=lambda item: item.name.casefold(),
    )
    if not paths:
        raise ValueError("01_raw contains no supported media")
    records: list[dict[str, Any]] = []
    content_hashes: dict[str, str] = {}
    for path in paths:
        match = SEGMENT_RE.match(path.name)
        if not match:
            if len(paths) == 1:
                number = 1
            else:
                raise ValueError(f"raw filename must start with a segment number: {path.name}")
        else:
            number = int(match.group(1))
        report = probe(path)
        digest = sha256_file(path)
        if digest in content_hashes:
            raise ValueError(f"duplicate raw content: {content_hashes[digest]} and {path.name}")
        content_hashes[digest] = path.name
        relative = path.relative_to(project_root).as_posix()
        records.append({
            "id": f"media-{digest.split(':', 1)[1][:16]}", "segment_number": number,
            "role": detect_role(path, report), "path": relative, "sha256": digest,
            "size_bytes": path.stat().st_size, "duration_s": duration_s(report),
            "streams": report.get("streams", []),
        })
    grouped: dict[int, dict[str, Any]] = {}
    for record in records:
        group = grouped.setdefault(record["segment_number"], {"number": record["segment_number"], "feeds": {}})
        role = record["role"]
        if role in group["feeds"]:
            raise ValueError(f"segment {record['segment_number']:02d} has ambiguous duplicate {role} feeds")
        group["feeds"][role] = record["id"]
    numbers = sorted(grouped)
    if not allow_number_gaps and numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError(f"segment numbering has gaps: {numbers}")
    for number, group in grouped.items():
        if "camera" not in group["feeds"] and "screen" not in group["feeds"]:
            raise ValueError(f"segment {number:02d} has no video feed")
    return {
        "schema_version": 1, "project_id": project_root.name, "generated_at": utc_timestamp(),
        "raw_root": "01_raw", "files": records,
        "segments": [grouped[number] for number in numbers],
    }
