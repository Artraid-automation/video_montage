"""Technical and sampled visual QC for rendered media."""

from __future__ import annotations

import fractions
import subprocess
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from .artifacts import artifact_record
from .io import sha256_file, working_output
from .media import duration_s, probe, require_tool, run, streams
from .visual_policy import evaluate_render_contract
from .visual_audit import build_gate2_visual_audit, motion_windows_on_render_timeline
from .transcript import TranscriptEntry, VisualEntry


def _rate(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    return float(fractions.Fraction(value))


def technical_qc(
    path: Path,
    *,
    expected_duration_s: float,
    width: int,
    height: int,
    fps: int,
    duration_tolerance_s: float = 0.35,
) -> dict[str, Any]:
    report = probe(path)
    video = streams(report, "video")
    audio = streams(report, "audio")
    reasons = []
    if len(video) != 1:
        reasons.append("expected exactly one video stream")
    if len(audio) != 1:
        reasons.append("expected exactly one audio stream")
    if video:
        if (video[0].get("width"), video[0].get("height")) != (width, height):
            reasons.append("resolution mismatch")
        # ``avg_frame_rate`` is duration-derived and drifts slightly in MP4 when
        # audio and video end on different time bases. For a CFR render,
        # ``r_frame_rate`` is the stream's declared cadence.
        declared_rate = video[0].get("r_frame_rate")
        actual_fps = _rate(declared_rate) or _rate(video[0].get("avg_frame_rate"))
        # Accept NTSC 30000/1001 (~29.97) when profile asks for 30, and similar CFR drift.
        if abs(actual_fps - float(fps)) > 0.05:
            reasons.append("frame rate mismatch")
    actual_duration = duration_s(report)
    if abs(actual_duration - expected_duration_s) > duration_tolerance_s:
        reasons.append("duration mismatch")
    return {
        "schema_version": 1, "verdict": "FAIL" if reasons else "PASS",
        "path": str(path), "actual": {"duration_s": actual_duration, "video": video, "audio": audio},
        "expected": {"duration_s": expected_duration_s, "width": width, "height": height, "fps": fps},
        "thresholds": {"duration_tolerance_s": duration_tolerance_s}, "reasons": reasons,
    }



def _freeze_runs(media_path: Path, *, noise: float, min_run_s: float) -> list[dict[str, float]]:
    command = [
        require_tool("ffmpeg"), "-hide_banner", "-nostats", "-v", "info", "-i", str(media_path),
        "-vf", f"freezedetect=n={noise}:d={min_run_s}", "-map", "0:v", "-an", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    runs: list[dict[str, float]] = []
    pending: float | None = None
    for line in result.stderr.splitlines():
        if "freeze_start" in line:
            pending = float(line.rsplit(":", 1)[1])
        elif "freeze_duration" in line and pending is not None:
            runs.append({"start_s": round(pending, 3), "duration_s": round(float(line.rsplit(":", 1)[1]), 3)})
            pending = None
    return runs


def motion_integrity(
    media_path: Path,
    *,
    source_media_path: Path | None = None,
    max_added_freeze_share: float = 0.03,
    max_freeze_run_s: float = 0.5,
    freeze_noise: float = 0.003,
    max_av_drift_s: float = 0.25,
    min_duration_s: float = 20.0,
) -> dict[str, Any]:
    """Застывания картинки и расхождение картинки со звуком.

    Два брака, которые до 30.08 проходили гейт насквозь: склейка планов с разной
    частотой кадров затыкала стыки стоп-кадрами, а видеодорожка при этом уезжала
    от звуковой. Ни один прежний блок этого не мерил — техпроверка смотрела только
    общую длительность файла, а она сходилась.
    """
    report = probe(media_path)
    video = streams(report, "video")
    audio = streams(report, "audio")
    duration = duration_s(report)
    reasons: list[str] = []
    freezes = _freeze_runs(media_path, noise=freeze_noise, min_run_s=max_freeze_run_s)
    frozen_s = sum(item["duration_s"] for item in freezes)
    freeze_share = frozen_s / duration if duration > 0 else 0.0
    # Судим не статичность съёмки, а застывания, ВНЕСЁННЫЕ монтажом: у неподвижно
    # снятого плана доля замерших кадров и так высокая, и наказывать за это нельзя.
    # Поэтому доля в рендере сравнивается с той же долей в исходнике.
    source_share = 0.0
    if source_media_path is not None and Path(source_media_path).is_file():
        source_report = probe(Path(source_media_path))
        source_duration = duration_s(source_report)
        source_runs = _freeze_runs(Path(source_media_path), noise=freeze_noise, min_run_s=max_freeze_run_s)
        source_frozen = sum(item["duration_s"] for item in source_runs)
        source_share = source_frozen / source_duration if source_duration > 0 else 0.0
    added_share = freeze_share - source_share
    # На коротком ролике доля неустойчива: один статичный план весит десятки
    # процентов хронометража. Судим только материал разумной длины.
    if duration >= min_duration_s and added_share > max_added_freeze_share:
        reasons.append(
            f"montage added frozen picture {added_share:.1%} of runtime "
            f"({frozen_s:.1f}s of {duration:.1f}s in render vs {source_share:.1%} in source, "
            f"limit {max_added_freeze_share:.0%})"
        )
    video_duration = float(video[0].get("duration") or 0.0) if video else 0.0
    audio_duration = float(audio[0].get("duration") or 0.0) if audio else 0.0
    drift = video_duration - audio_duration
    if video_duration > 0 and audio_duration > 0 and abs(drift) > max_av_drift_s:
        reasons.append(
            f"picture and sound run apart by {drift:+.2f}s (video {video_duration:.2f}s, audio {audio_duration:.2f}s)"
        )
    return {
        "schema_version": 1,
        "verdict": "FAIL" if reasons else "PASS",
        "metrics": {
            "frozen_s": round(frozen_s, 3),
            "freeze_share": round(freeze_share, 4),
            "source_freeze_share": round(source_share, 4),
            "added_freeze_share": round(added_share, 4),
            "freeze_count": len(freezes),
            "longest_freeze_s": round(max((item["duration_s"] for item in freezes), default=0.0), 3),
            "video_duration_s": round(video_duration, 3),
            "audio_duration_s": round(audio_duration, 3),
            "av_drift_s": round(drift, 3),
        },
        "thresholds": {
            "max_added_freeze_share": max_added_freeze_share,
            "max_freeze_run_s": max_freeze_run_s,
            "max_av_drift_s": max_av_drift_s,
            "min_duration_s": min_duration_s,
        },
        "judged": duration >= min_duration_s,
        "freezes": freezes[:40],
        "reasons": reasons,
    }


def visual_probes(
    project_root: Path,
    media_path: Path,
    output_dir: Path,
    *,
    interval_s: float = 2.0,
    black_mean_threshold: float = 2.0,
) -> dict[str, Any]:
    report = probe(media_path)
    duration = duration_s(report)
    # FFmpeg 8.x rejects -ss within ~100ms of EOF on some MP4 masters.
    end_ts = max(0.0, duration - 0.2)
    times = {0.0, end_ts, duration / 2}
    cursor = interval_s
    while cursor < duration:
        times.add(cursor)
        cursor += interval_s
    frames = []
    reasons = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, timestamp in enumerate(sorted(times), 1):
        frame = output_dir / f"probe-{index:03d}-{timestamp:.3f}.jpg"
        with working_output(frame) as temporary:
            run([
                require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{timestamp:.3f}", "-i", str(media_path), "-frames:v", "1", "-q:v", "3", str(temporary),
            ])
        with Image.open(frame) as image:
            grayscale = image.convert("L")
            mean = ImageStat.Stat(grayscale).mean[0]
            dimensions = image.size
        if mean < black_mean_threshold:
            reasons.append(f"near-black probe at {timestamp:.3f}s")
        frames.append({"timestamp_s": timestamp, "mean_luma": round(mean, 3), "dimensions": list(dimensions), "artifact": artifact_record(project_root, frame, kind="visual-probe")})
    return {"schema_version": 1, "verdict": "FAIL" if reasons else "PASS", "frames": frames, "reasons": reasons}


def audio_policy(
    media_path: Path,
    *,
    max_peak_db: float = -0.1,
    min_mean_db: float = -40.0,
    target_mean_db_min: float = -24.0,
    target_mean_db_max: float = -12.0,
) -> dict[str, Any]:
    """Segment/master loudness gate. After Phase 3 loudnorm, mean should sit in broadcast-ish band."""
    measured = run([require_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(media_path), "-af", "volumedetect", "-f", "null", "-"])
    text = measured.stderr
    mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", text)
    peak_match = re.search(r"max_volume:\s*(-?[0-9.]+) dB", text)
    reasons = []
    if not mean_match or not peak_match:
        reasons.append("audio loudness metrics unavailable")
        mean_db = peak_db = None
    else:
        mean_db, peak_db = float(mean_match.group(1)), float(peak_match.group(1))
        if peak_db > max_peak_db:
            reasons.append(f"audio peak {peak_db:.1f} dB exceeds policy max {max_peak_db}")
        if mean_db < min_mean_db:
            reasons.append("audio is effectively silent")
        if mean_db is not None and not (target_mean_db_min <= mean_db <= target_mean_db_max):
            # Soft signal for masters: still PASS but recorded for Final Review.
            pass
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "mean_db": mean_db,
        "peak_db": peak_db,
        "thresholds": {
            "max_peak_db": max_peak_db,
            "min_mean_db": min_mean_db,
            "target_mean_db_min": target_mean_db_min,
            "target_mean_db_max": target_mean_db_max,
        },
        "reasons": reasons,
    }


def layout_policy(*, width: int, height: int, pip_enabled: bool, captions_enabled: bool = True, margin_px: int = 24) -> dict[str, Any]:
    reasons = []
    overlays = []
    if pip_enabled:
        pip_width = max(120, width // 4)
        pip_height = round(pip_width * 9 / 16)
        box = {"x": width - pip_width - margin_px, "y": height - pip_height - margin_px, "width": pip_width, "height": pip_height}
        overlays.append({"kind": "pip", **box})
        if min(box["x"], box["y"], margin_px) < 0 or box["x"] + box["width"] > width or box["y"] + box["height"] > height:
            reasons.append("PiP rectangle escapes frame")
    if captions_enabled:
        caption_width = width - 2 * margin_px - (max(120, width // 4) + margin_px if pip_enabled else 0)
        overlays.append({"kind": "captions", "x": margin_px, "y": round(height * 0.72), "width": caption_width, "height": round(height * 0.20)})
        if caption_width <= 0:
            reasons.append("caption safe area has no width")
    return {"verdict": "FAIL" if reasons else "PASS", "frame": {"width": width, "height": height}, "safe_margin_px": margin_px, "overlays": overlays, "reasons": reasons}


def combined_qc(
    project_root: Path,
    media_path: Path,
    output_dir: Path,
    *,
    expected_duration_s: float,
    width: int,
    height: int,
    fps: int,
    pip_enabled: bool,
    captions_enabled: bool = True,
    interval_s: float = 2.0,
    binding_name: str = "render_sha256",
    render_contract: dict[str, Any] | None = None,
    require_visual_render_policy: bool = False,
    transcript_entries: list[TranscriptEntry] | None = None,
    visuals: list[VisualEntry] | None = None,
    require_visual_audit: bool = False,
    random_audit_count: int = 3,
    source_media_path: Path | None = None,
    duration_tolerance_s: float = 0.35,
) -> dict[str, Any]:
    technical = technical_qc(
        media_path, expected_duration_s=expected_duration_s, width=width, height=height, fps=fps,
        duration_tolerance_s=duration_tolerance_s,
    )
    frame_integrity = visual_probes(project_root, media_path, output_dir, interval_s=interval_s)
    layout = layout_policy(width=width, height=height, pip_enabled=pip_enabled, captions_enabled=captions_enabled)
    audio = audio_policy(media_path)
    motion = motion_integrity(media_path, source_media_path=source_media_path)
    components: list[dict[str, Any]] = [technical, frame_integrity, layout, audio, motion]
    visual_render: dict[str, Any] | None = None
    if require_visual_render_policy or render_contract is not None:
        visual_render = evaluate_render_contract(render_contract)
        components.append(visual_render)
    visual_audit: dict[str, Any] | None = None
    if require_visual_audit:
        render_sha = sha256_file(media_path)
        motions = motion_windows_on_render_timeline(transcript_entries or [], visuals or [])
        contract = render_contract or {}
        caption_pos_y = contract.get("caption_pos_y")
        caption_font_size = contract.get("caption_font_size")
        expected_styles = [str(item) for item in (contract.get("style_recipes_expected") or [])]
        visual_audit = build_gate2_visual_audit(
            project_root,
            media_path,
            output_dir / "gate2-audit",
            render_sha256=render_sha,
            motions=motions,
            random_count=random_audit_count,
            caption_pos_y=int(caption_pos_y) if caption_pos_y is not None else None,
            caption_font_size=int(caption_font_size) if caption_font_size is not None else None,
            require_caption_gaps=bool(
                captions_enabled and caption_pos_y is not None and motions
            ),
            require_hook_title_clearance="hook_title" in expected_styles,
        )
        components.append(visual_audit)
    reasons = [reason for component in components for reason in component.get("reasons", [])]
    schema = 2
    if visual_render is not None:
        schema = 3
    if visual_audit is not None:
        schema = 4
    payload: dict[str, Any] = {
        "schema_version": schema,
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in components) else "FAIL",
        # Блок движения обязан быть виден в отчёте, а не только влиять на вердикт:
        # иначе застывания и расхождение дорожек нечем предъявить.
        "motion_integrity": motion,
        "bindings": {binding_name: sha256_file(media_path)},
        "technical": technical,
        "frame_integrity": frame_integrity,
        "layout_policy": layout,
        "audio_policy": audio,
        "reasons": reasons,
    }
    if visual_render is not None:
        payload["visual_render_policy"] = visual_render
    if visual_audit is not None:
        payload["visual_audit"] = visual_audit
    return payload