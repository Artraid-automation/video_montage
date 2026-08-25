"""Deterministic color-grade sample generation and master grade encodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .artifacts import artifact_record
from .io import working_output
from .media import require_tool, run


GRADE_FILTERS = {
    "neutral": "null",
    "warm": "eq=contrast=1.04:saturation=1.08:gamma=1.02,colorbalance=rs=.04:bs=-.025",
    "punchy": "eq=contrast=1.12:saturation=1.12:gamma=0.98",
    # Cool shadows, natural skin — MeVGa / Dan Koe talking-head intent.
    "dankoe": "eq=contrast=1.06:saturation=0.94:gamma=1.03,colorbalance=bs=.07:rs=-.03:gs=-.015",
}

# Final Review default trio: untouched + style pack + warm skin.
FINAL_GRADE_CANDIDATES = ("neutral", "dankoe", "warm")


def generate_grade_samples(
    project_root: Path,
    source: Path,
    output_dir: Path,
    *,
    representative_s: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for name, filter_graph in GRADE_FILTERS.items():
        output = output_dir / f"{name}.jpg"
        with working_output(output) as temporary:
            run([
                require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{max(representative_s, 0.0):.3f}", "-i", str(source),
                "-frames:v", "1", "-vf", filter_graph, "-q:v", "2", str(temporary),
            ])
        with Image.open(output) as image:
            image.verify()
        records.append(artifact_record(project_root, output, kind="grade-sample"))
    return {
        "schema_version": 1, "verdict": "PASS", "selected": None,
        "samples": records, "filters": GRADE_FILTERS,
    }


def apply_grade(
    source: Path,
    output: Path,
    *,
    grade_name: str,
    profile: dict[str, Any] | None = None,
) -> Path:
    """Re-encode `source` with a named grade filter into `output`."""
    if grade_name not in GRADE_FILTERS:
        raise ValueError(f"unknown grade: {grade_name}")
    profile = profile or {}
    crf = str(profile.get("crf", 20))
    preset = str(profile.get("preset", "veryfast"))
    vf = GRADE_FILTERS[grade_name]
    output.parent.mkdir(parents=True, exist_ok=True)
    with working_output(output) as temporary:
        command = [
            require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
        ]
        # Always force yuv420p: colorbalance/eq and upstream overlays often
        # promote to yuv444p (High 4:4:4), which Telegram plays as black+audio.
        if vf == "null":
            command.extend(["-vf", "format=yuv420p"])
        else:
            command.extend(["-vf", f"{vf},format=yuv420p"])
        command.extend([
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-preset", preset, "-crf", crf,
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(temporary),
        ])
        run(command)
    return output


def normalize_master_audio(
    source: Path,
    output: Path,
    *,
    target_i: float = -14.0,
    target_tp: float = -1.5,
    target_lra: float = 11.0,
    profile: dict[str, Any] | None = None,
) -> Path:
    """Loudness-normalize master audio for Shorts/Reels (post-concat)."""
    profile = profile or {}
    crf = str(profile.get("crf", 20))
    preset = str(profile.get("preset", "veryfast"))
    _ = (crf, preset)  # video is copied; kept for signature stability
    output.parent.mkdir(parents=True, exist_ok=True)
    af = f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}"
    with working_output(output) as temporary:
        run([
            require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-c:v", "copy",
            "-af", af, "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(temporary),
        ])
    return output
