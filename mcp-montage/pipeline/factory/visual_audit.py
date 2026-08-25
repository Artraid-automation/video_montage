"""Mandatory Gate 2 visual audit: random frame samples + per-MOTION probes."""

from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageStat

from .artifacts import artifact_record
from .framing import detect_largest_face, load_bgr, verify_frame_face_caption
from .io import atomic_write_json, working_output
from .media import duration_s, probe, require_tool, run
from .transcript import (
    TranscriptEntry,
    VisualEntry,
    resolve_visual_end,
    resolve_visual_start,
)
from .visual_policy import HOOK_TITLE_MIN_TOP_RATIO, is_director_motion_copy, motion_on_screen_text

# Gold #E1C445 band — body captions must be visible outside MOTION windows.
GOLD_R_MIN = 180
GOLD_G_MIN = 140
GOLD_B_MAX = 120
CAPTION_GAP_MIN_GOLD_PX = 250
CAPTION_GAP_BAND_PX = 160


def dense_gold_row_clusters(path: Path, *, min_width_ratio: float = 0.02) -> list[tuple[int, int]]:
    """Return (start_row, end_row) clusters of dense gold/yellow text pixels."""
    image = load_bgr(path)
    _height, width = image.shape[:2]
    bgr = image.astype(np.int16)
    blue, green, red = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
    mask = (
        (red > 160)
        & (green > 120)
        & (blue < 120)
        & (red > blue + 40)
        & (green > blue + 30)
    )
    row_counts = mask.sum(axis=1)
    dense = np.where(row_counts > width * min_width_ratio)[0]
    if len(dense) == 0:
        return []
    gaps = np.where(np.diff(dense) > 15)[0]
    starts = [int(dense[0])] + [int(dense[i + 1]) for i in gaps]
    ends = [int(dense[i]) for i in gaps] + [int(dense[-1])]
    return [(start, end) for start, end in zip(starts, ends) if end - start >= 8]


def verify_hook_title_clear_of_face(path: Path) -> dict[str, Any]:
    """Fail when large gold title sits over eyes/upper face (Slava author catch).

    Ignore sparse gold (jewelry, warm brick, skin): real MeVGa titles are dense
    multi-line plates. Overlap is judged against the eye line, not the whole face
    box — a chest title may start below the chin while gold anti-alias spills a
    few rows into the lower face bbox.
    """
    image = load_bgr(path)
    height, width = image.shape[:2]
    face = detect_largest_face(image, max_height_ratio=0.55, min_height_ratio=0.05)
    clusters = dense_gold_row_clusters(path)
    reasons: list[str] = []
    if face is None:
        return {
            "verdict": "PASS",
            "reasons": [],
            "soft_reasons": ["hook probe: face not detected for title clearance"],
            "clusters": clusters,
            "face": None,
        }
    _x, face_y, _w, face_h = face
    face_bottom = face_y + face_h
    eye_line = face_y + int(0.40 * face_h)
    min_title_top = max(int(height * HOOK_TITLE_MIN_TOP_RATIO), eye_line + 8)
    bgr = image.astype(np.int16)
    blue, green, red = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
    gold_mask = (
        (red > 160)
        & (green > 120)
        & (blue < 120)
        & (red > blue + 40)
        & (green > blue + 30)
    )
    # Title plates are dense; necklaces / brick warmth are sparse (~2–5% of row).
    min_mean_frac = 0.10
    for start, end in clusters:
        if end - start < 24:
            continue
        mean_frac = float(gold_mask[start : end + 1].sum(axis=1).mean()) / max(width, 1)
        if mean_frac < min_mean_frac:
            continue
        # Over eyes / forehead only — chest titles below eye_line are OK.
        if start < eye_line and end > face_y:
            reasons.append(
                f"hook title overlaps upper face "
                f"(gold_rows={start}-{end}, eye_line={eye_line}, face={face_y}-{face_bottom})"
            )
            break
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "soft_reasons": [],
        "clusters": clusters,
        "face": {"x": face[0], "y": face[1], "w": face[2], "h": face[3]},
        "min_title_top": min_title_top,
    }


def _grab_frame(media_path: Path, timestamp_s: float, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with working_output(output) as temporary:
        run([
            require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{max(0.0, timestamp_s):.3f}", "-i", str(media_path),
            "-frames:v", "1", "-q:v", "3", str(temporary),
        ])
    return output


def _frame_stats(path: Path, *, black_mean_threshold: float = 2.0) -> dict[str, Any]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        mean = float(ImageStat.Stat(rgb.convert("L")).mean[0])
        width, height = rgb.size
    reasons: list[str] = []
    if mean < black_mean_threshold:
        reasons.append(f"near-black frame mean_luma={mean:.2f}")
    return {
        "mean_luma": round(mean, 3),
        "dimensions": [width, height],
        "reasons": reasons,
    }


def _clamp_timestamp(value: float, duration_s: float) -> float:
    if duration_s <= 0.05:
        return 0.0
    return min(max(0.0, value), max(0.0, duration_s - 0.05))


def key_frame_timestamps(duration_s: float) -> list[tuple[str, float]]:
    """Deterministic composition checkpoints: start / middle / near-end."""
    if duration_s <= 0.05:
        return [("start", 0.0)]
    end_ts = _clamp_timestamp(max(0.0, duration_s - 0.2), duration_s)
    mid_ts = _clamp_timestamp(duration_s / 2.0, duration_s)
    return [("start", 0.0), ("mid", mid_ts), ("end", end_ts)]


def count_gold_caption_pixels(
    path: Path,
    *,
    caption_pos_y: int | None,
    band_px: int = CAPTION_GAP_BAND_PX,
) -> int:
    """Count gold-ish pixels in the chest caption band on a probe JPG."""
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        top = int(caption_pos_y if caption_pos_y is not None else height * 0.68)
        top = max(0, min(height - 1, top))
        bottom = min(height, top + max(40, band_px))
        crop = rgb.crop((0, top, width, bottom))
        pixels = crop.load()
        count = 0
        cw, ch = crop.size
        for y in range(ch):
            for x in range(cw):
                red, green, blue = pixels[x, y][:3]
                if red >= GOLD_R_MIN and green >= GOLD_G_MIN and blue <= GOLD_B_MAX:
                    count += 1
        return count


def caption_gap_timestamps(
    duration_s: float,
    motions: list[dict[str, Any]],
    *,
    max_gaps: int = 4,
    min_gap_s: float = 0.45,
) -> list[float]:
    """Sample midpoints of KEEP spans that fall outside MOTION windows."""
    if duration_s <= 0.1:
        return []
    blocked = sorted(
        (
            float(item.get("render_start_s", 0.0)),
            float(item.get("render_end_s", 0.0)),
        )
        for item in motions
        if float(item.get("render_end_s", 0.0)) > float(item.get("render_start_s", 0.0))
    )
    free: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in blocked:
        if start > cursor + min_gap_s:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if duration_s > cursor + min_gap_s:
        free.append((cursor, duration_s))
    stamps: list[float] = []
    for start, end in free:
        mid = (start + end) / 2
        stamps.append(_clamp_timestamp(mid, duration_s))
        if len(stamps) >= max_gaps:
            break
    return stamps


def _seeded_rng(render_sha256: str) -> random.Random:
    digest = hashlib.sha256(render_sha256.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def motion_windows_on_render_timeline(
    entries: list[TranscriptEntry],
    visuals: list[VisualEntry],
) -> list[dict[str, Any]]:
    """Map each MOTION onto the concatenated KEEP render timeline."""
    kept = [item for item in entries if item.kind == "keep"]
    cursor = 0.0
    by_id = {item.id: item for item in kept}
    windows: list[dict[str, Any]] = []
    for entry in kept:
        clip_dur = max(0.0, float(entry.end_s) - float(entry.start_s))
        for visual in visuals:
            if visual.type != "motion" or visual.anchor != entry.id:
                continue
            if visual.anchor not in by_id:
                continue
            source_start = resolve_visual_start(kept, visual)
            source_end = resolve_visual_end(kept, visual, default_duration_s=3.0)
            local_start = max(0.0, source_start - float(entry.start_s))
            local_end = min(clip_dur, max(local_start + 0.2, source_end - float(entry.start_s)))
            # Compositor respects declared overlay window on the render timeline.
            render_start = cursor + local_start
            render_end = cursor + local_end
            on_screen = motion_on_screen_text(visual.brief)
            windows.append({
                "id": visual.id,
                "anchor": visual.anchor,
                "render_start_s": round(render_start, 3),
                "render_end_s": round(render_end, 3),
                "on_screen": on_screen,
                "raw_brief": visual.brief,
            })
        cursor += clip_dur
    return windows


def build_gate2_visual_audit(
    project_root: Path,
    media_path: Path,
    output_dir: Path,
    *,
    render_sha256: str,
    motions: list[dict[str, Any]],
    random_count: int = 5,
    black_mean_threshold: float = 2.0,
    caption_pos_y: int | None = None,
    caption_font_size: int | None = None,
    require_caption_gaps: bool = False,
    require_hook_title_clearance: bool = False,
) -> dict[str, Any]:
    """Write mandatory random + per-MOTION frame probes and return the audit report."""
    if random_count < 1:
        raise ValueError("random_count must be >= 1")
    media_path = media_path.resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    duration = duration_s(probe(media_path))
    reasons: list[str] = []
    rng = _seeded_rng(render_sha256)
    caption_h = int(caption_font_size or 48) * 3  # multi-line ASS chunks

    key_frames: list[dict[str, Any]] = []
    for label, stamp in key_frame_timestamps(duration):
        path = output_dir / f"key-{label}-{stamp:.3f}.jpg"
        _grab_frame(media_path, stamp, path)
        stats = _frame_stats(path, black_mean_threshold=black_mean_threshold)
        # Body-caption overlap check is for speech frames; skip on start when hook owns the plate.
        check_body_caption = not (require_hook_title_clearance and label == "start")
        face_check = verify_frame_face_caption(
            path,
            caption_top_y=caption_pos_y if check_body_caption else None,
            caption_height_px=caption_h,
            require_face=caption_pos_y is not None,
        )
        if face_check["verdict"] != "PASS":
            reasons.extend(f"key[{label}]: {msg}" for msg in face_check["reasons"])
        hook_check = None
        if require_hook_title_clearance and label == "start":
            hook_check = verify_hook_title_clear_of_face(path)
            if hook_check["verdict"] != "PASS":
                reasons.extend(f"key[{label}] hook: {msg}" for msg in hook_check["reasons"])
        record = artifact_record(project_root, path, kind="gate2-visual-probe")
        item = {
            "id": f"key-{label}",
            "timestamp_s": round(stamp, 3),
            "path": record["path"],
            "sha256": record["sha256"],
            "face_check": face_check,
            **stats,
        }
        if hook_check is not None:
            item["hook_title_check"] = hook_check
        if stats["reasons"]:
            reasons.extend(f"key[{label}]: {msg}" for msg in stats["reasons"])
        key_frames.append(item)

    random_frames: list[dict[str, Any]] = []
    for index in range(random_count):
        stamp = _clamp_timestamp(rng.uniform(0.08, max(0.08, duration - 0.08)), duration)
        path = output_dir / f"random-{index + 1:02d}-{stamp:.3f}.jpg"
        _grab_frame(media_path, stamp, path)
        stats = _frame_stats(path, black_mean_threshold=black_mean_threshold)
        face_check = verify_frame_face_caption(
            path,
            caption_top_y=caption_pos_y,
            caption_height_px=caption_h,
            require_face=caption_pos_y is not None,
            check_centering=False,
        )
        if face_check["verdict"] != "PASS":
            reasons.extend(f"random[{index + 1:02d}]: {msg}" for msg in face_check["reasons"])
        record = artifact_record(project_root, path, kind="gate2-visual-probe")
        item = {
            "id": f"random-{index + 1:02d}",
            "timestamp_s": round(stamp, 3),
            "path": record["path"],
            "sha256": record["sha256"],
            "face_check": face_check,
            **stats,
        }
        if stats["reasons"]:
            reasons.extend(f"random[{item['id']}]: {msg}" for msg in stats["reasons"])
        random_frames.append(item)

    motion_checks: list[dict[str, Any]] = []
    for motion in motions:
        motion_id = str(motion.get("id") or "motion")
        start = float(motion.get("render_start_s", -1))
        end = float(motion.get("render_end_s", -1))
        on_screen = str(motion.get("on_screen") or "")
        motion_reasons: list[str] = []
        if end <= start or start < 0 or end > duration + 0.35:
            motion_reasons.append(
                f"motion {motion_id} window [{start:.3f},{end:.3f}] is outside render "
                f"(duration={duration:.3f}s)"
            )
        if is_director_motion_copy(on_screen):
            motion_reasons.append(f"motion {motion_id} on_screen is director copy")
        stamps: list[tuple[str, float]] = []
        if end > start and start >= 0:
            mid = (start + end) / 2
            stamps = [
                ("start", _clamp_timestamp(start + 0.12, duration)),
                ("mid", _clamp_timestamp(mid, duration)),
            ]
            if end - start >= 0.6:
                stamps.append(("end", _clamp_timestamp(end - 0.12, duration)))
        frames: list[dict[str, Any]] = []
        for label, stamp in stamps:
            path = output_dir / f"motion-{motion_id}-{label}-{stamp:.3f}.jpg"
            try:
                _grab_frame(media_path, stamp, path)
            except Exception as exc:  # noqa: BLE001
                motion_reasons.append(f"motion {motion_id} {label} grab failed: {exc}")
                continue
            stats = _frame_stats(path, black_mean_threshold=black_mean_threshold)
            face_check = verify_frame_face_caption(
                path,
                caption_top_y=caption_pos_y,
                caption_height_px=caption_h,
                require_face=False,
            )
            if face_check["verdict"] != "PASS":
                motion_reasons.extend(
                    f"motion[{motion_id}/{label}]: {msg}" for msg in face_check["reasons"]
                )
            record = artifact_record(project_root, path, kind="gate2-visual-probe")
            frames.append({
                "id": f"motion-{motion_id}-{label}",
                "role": label,
                "timestamp_s": round(stamp, 3),
                "path": record["path"],
                "sha256": record["sha256"],
                "face_check": face_check,
                **stats,
            })
            if stats["reasons"]:
                motion_reasons.extend(
                    f"motion[{motion_id}/{label}]: {msg}" for msg in stats["reasons"]
                )
        if not frames and not motion_reasons:
            motion_reasons.append(f"motion {motion_id} produced no probe frames")
        verdict = "FAIL" if motion_reasons else "PASS"
        if motion_reasons:
            reasons.extend(motion_reasons)
        motion_checks.append({
            "id": motion_id,
            "anchor": motion.get("anchor"),
            "render_start_s": start,
            "render_end_s": end,
            "on_screen": on_screen,
            "verdict": verdict,
            "frames": frames,
            "reasons": motion_reasons,
        })

    caption_gap_checks: list[dict[str, Any]] = []
    gap_stamps = caption_gap_timestamps(duration, motions) if motions else []
    for index, stamp in enumerate(gap_stamps, 1):
        path = output_dir / f"caption-gap-{index:02d}-{stamp:.3f}.jpg"
        gap_reasons: list[str] = []
        try:
            _grab_frame(media_path, stamp, path)
        except Exception as exc:  # noqa: BLE001
            gap_reasons.append(f"caption-gap[{index:02d}] grab failed: {exc}")
            reasons.extend(gap_reasons)
            caption_gap_checks.append({
                "id": f"caption-gap-{index:02d}",
                "timestamp_s": round(stamp, 3),
                "verdict": "FAIL",
                "reasons": gap_reasons,
            })
            continue
        stats = _frame_stats(path, black_mean_threshold=black_mean_threshold)
        gold_px = count_gold_caption_pixels(path, caption_pos_y=caption_pos_y)
        if require_caption_gaps and gold_px < CAPTION_GAP_MIN_GOLD_PX:
            gap_reasons.append(
                f"caption-gap[{index:02d}] @{stamp:.3f}s missing body captions "
                f"(gold_px={gold_px} < {CAPTION_GAP_MIN_GOLD_PX}); "
                f"MOTION must not suppress captions outside its window"
            )
        if stats["reasons"]:
            gap_reasons.extend(stats["reasons"])
        if gap_reasons:
            reasons.extend(gap_reasons)
        record = artifact_record(project_root, path, kind="gate2-visual-probe")
        caption_gap_checks.append({
            "id": f"caption-gap-{index:02d}",
            "timestamp_s": round(stamp, 3),
            "path": record["path"],
            "sha256": record["sha256"],
            "gold_px": gold_px,
            "verdict": "FAIL" if gap_reasons else "PASS",
            "reasons": gap_reasons,
            **stats,
        })

    verdict = "FAIL" if reasons else "PASS"
    report = {
        "schema_version": 1,
        "kind": "gate2-visual-audit",
        "worker_version": "gate2-visual-audit-v4-composition",
        "bindings": {"render_sha256": render_sha256},
        "duration_s": duration,
        "key_frames": key_frames,
        "random_count": random_count,
        "random_frames": random_frames,
        "motion_checks": motion_checks,
        "caption_gap_checks": caption_gap_checks,
        "require_caption_gaps": require_caption_gaps,
        "caption_pos_y": caption_pos_y,
        "verdict": verdict,
        "reasons": reasons,
    }
    atomic_write_json(output_dir / "manifest.json", report)
    return report
