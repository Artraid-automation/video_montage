"""FFmpeg/ffprobe primitives and deterministic media validation."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence


def require_tool(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"required executable is not available: {name}")
    return executable


def run(command: Sequence[str], *, timeout_s: float | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s
    )
    if result.returncode != 0:
        rendered = " ".join(str(item) for item in command)
        raise RuntimeError(f"command failed ({result.returncode}): {rendered}\n{result.stderr[-4000:]}")
    return result


def probe(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"media file is missing or empty: {path}")
    result = run([
        require_tool("ffprobe"), "-v", "error", "-show_error", "-show_format", "-show_streams",
        "-of", "json", str(path),
    ])
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc
    if value.get("error"):
        raise ValueError(f"ffprobe rejected {path}: {value['error']}")
    return value


def duration_s(report: dict[str, Any]) -> float:
    try:
        return float(report["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("media probe has no valid duration") from exc


def streams(report: dict[str, Any], codec_type: str) -> list[dict[str, Any]]:
    return [item for item in report.get("streams", []) if item.get("codec_type") == codec_type]


def validate_video(path: Path, *, min_duration_s: float = 0.04) -> dict[str, Any]:
    report = probe(path)
    if not streams(report, "video"):
        raise ValueError(f"media has no video stream: {path}")
    if duration_s(report) < min_duration_s:
        raise ValueError(f"video is shorter than {min_duration_s}s: {path}")
    return report


def validate_audio(path: Path, *, min_duration_s: float = 0.04) -> dict[str, Any]:
    report = probe(path)
    if not streams(report, "audio"):
        raise ValueError(f"media has no audio stream: {path}")
    if duration_s(report) < min_duration_s:
        raise ValueError(f"audio is shorter than {min_duration_s}s: {path}")
    return report
