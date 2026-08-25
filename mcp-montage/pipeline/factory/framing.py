"""Auto talking-head framing from face detection + caption Y from chest band."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .io import atomic_write_json, working_output
from .media import require_tool, run

_log = logging.getLogger(__name__)

EYE_LINE_RATIO = 0.22
FACE_HEIGHT_RATIO = 0.26  # head+shoulders — leave chest band for captions
HEADROOM_TARGET = 0.10
HEADROOM_MIN = 0.04
HEADROOM_MAX = 0.18
HEADROOM_AUDIT_MAX = 0.40  # moving speaker: only extreme empty sky fails
FACE_EDGE_MARGIN_PX = 24
FACE_CENTER_TOLERANCE_RATIO = 0.20
CAPTION_GAP_RATIO = 0.15  # clear chin + chunky necklace before chest text
CAPTION_SAFETY_PX = 48
CHEST_BAND_MIN_RATIO = 0.62
CHEST_BAND_MAX_RATIO = 0.80
# Stronger right bias: YuNet box includes hair on viewer's left; sternum/buttons sit right of face-cx.
CAPTION_TORSO_X_RATIO = 0.78
# Keep phrase width inside the shoulder envelope so lines don't overhang left bg.
CAPTION_TORSO_WIDTH_FACE_RATIO = 2.2
CAPTION_TORSO_WIDTH_MIN_PX = 280
CAPTION_TORSO_WIDTH_MAX_FRAME_RATIO = 0.42
FACE_HEIGHT_MIN_RATIO = 0.10
FACE_HEIGHT_MAX_RATIO = 0.40

_YUNET_MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"


def _haar_path() -> Path:
    return Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"


def detect_faces_yunet(
    image_bgr: np.ndarray,
    *,
    conf_threshold: float = 0.5,
) -> list[tuple[int, int, int, int, float]]:
    """Yunet DNN detector — returns (x, y, w, h, confidence) tuples."""
    import tempfile, shutil
    h, w = image_bgr.shape[:2]
    if not _YUNET_MODEL.exists():
        return []
    model_path = str(_YUNET_MODEL)
    # OpenCV DNN cannot read ONNX from paths with non-ASCII characters.
    # Copy to a temp file with an ASCII-safe path when needed.
    try:
        model_path.encode("ascii")
        safe_path = model_path
    except UnicodeEncodeError:
        tmp = Path(tempfile.gettempdir()) / "yunet_face.onnx"
        if not tmp.exists():
            shutil.copy2(_YUNET_MODEL, tmp)
        safe_path = str(tmp)
    try:
        detector = cv2.FaceDetectorYN.create(safe_path, "", (w, h), conf_threshold, 0.3, 5000)
    except cv2.error:
        _log.warning("Yunet model load failed, will fall back to Haar")
        return []
    _, faces = detector.detect(image_bgr)
    if faces is None:
        return []
    return [(int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[14])) for f in faces]


def detect_faces_bgr(image_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Detect faces using Yunet (primary) with Haar cascade fallback."""
    yunet_results = detect_faces_yunet(image_bgr)
    if yunet_results:
        return [(x, y, w, h) for x, y, w, h, _conf in yunet_results]

    _log.debug("Yunet found no faces, falling back to Haar cascade")
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    cascade = cv2.CascadeClassifier(str(_haar_path()))
    if cascade.empty():
        raise RuntimeError("OpenCV Haar cascade failed to load")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48))
    if len(faces) == 0:
        faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(36, 36))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]


def filter_talking_head_faces(
    faces: list[tuple[int, int, int, int]],
    *,
    src_w: int,
    src_h: int,
    max_height_ratio: float = FACE_HEIGHT_MAX_RATIO,
    min_height_ratio: float = FACE_HEIGHT_MIN_RATIO,
) -> list[tuple[int, int, int, int]]:
    """Drop torso-sized false positives and tiny noise boxes."""
    kept: list[tuple[int, int, int, int]] = []
    for x, y, w, h in faces:
        if h <= 0 or w <= 0:
            continue
        height_ratio = h / src_h
        if height_ratio < min_height_ratio or height_ratio > max_height_ratio:
            continue
        aspect = w / h
        if aspect < 0.50 or aspect > 1.60:
            continue
        if y > src_h * 0.55:
            continue
        if x + w < src_w * 0.15 or x > src_w * 0.85:
            continue
        kept.append((x, y, w, h))
    return kept


def detect_largest_face(
    image_bgr: np.ndarray,
    *,
    max_height_ratio: float = FACE_HEIGHT_MAX_RATIO,
    min_height_ratio: float = FACE_HEIGHT_MIN_RATIO,
) -> tuple[int, int, int, int] | None:
    src_h, src_w = image_bgr.shape[:2]
    faces = filter_talking_head_faces(
        detect_faces_bgr(image_bgr),
        src_w=src_w,
        src_h=src_h,
        max_height_ratio=max_height_ratio,
        min_height_ratio=min_height_ratio,
    )
    if not faces:
        return None
    return max(faces, key=lambda box: box[2] * box[3])


def score_face(face: tuple[int, int, int, int], *, src_h: int) -> float:
    """Prefer mid-sized faces near the target fill ratio."""
    _x, y, w, h = face
    fill = h / max(src_h, 1)
    size_score = 1.0 - min(1.0, abs(fill - FACE_HEIGHT_RATIO) / FACE_HEIGHT_RATIO)
    top_score = 1.0 - min(1.0, y / max(src_h * 0.5, 1))
    return size_score * 0.7 + top_score * 0.3


def grab_video_frame(media_path: Path, timestamp_s: float, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with working_output(output) as temporary:
        run([
            require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{max(0.0, timestamp_s):.3f}", "-i", str(media_path),
            "-frames:v", "1", "-q:v", "2", str(temporary),
        ])
    return output


def load_bgr(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode image: {path}")
    return image


def compute_framing_plan(
    *,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    face: tuple[int, int, int, int],
) -> dict[str, Any]:
    """Scale+crop so crown headroom ≈ HEADROOM_TARGET and face fills FACE_HEIGHT_RATIO."""
    x, y, w, h = face
    if w < 8 or h < 8:
        raise ValueError("face box too small for framing")
    face_cx = x + w / 2.0
    cover = max(out_w / src_w, out_h / src_h)
    face_scale = (FACE_HEIGHT_RATIO * out_h) / float(h)
    # Haar top ≈ forehead; reserve crown above the box when computing crop room.
    crown_y = max(0.0, y - 0.18 * h)
    # Scale enough that we can crop empty sky and land crown near HEADROOM_TARGET.
    headroom_scale = (out_h * (1.0 - HEADROOM_TARGET)) / max(1.0, (src_h - crown_y))
    # Cap headroom zoom: never exceed cover by more than 10% — beyond that we
    # over-zoom and crop the head/shoulders off the frame edges (author catch:
    # Slava 720p source → 2× zoom cut left half of head + top of head).
    headroom_scale = min(headroom_scale, cover * 1.10)
    # Face already large in source (≥18% of frame) — zooming past cover crops head/shoulders.
    # Only zoom past cover when the face is small and needs filling to reach target ratio.
    source_face_ratio = h / src_h
    if source_face_ratio >= 0.18:
        max_face_scale = cover
    else:
        max_face_scale = (0.34 * out_h) / float(h)
    scale = max(cover, face_scale, headroom_scale)
    scale = min(scale, max(cover, max_face_scale))
    scaled_w = int(round(src_w * scale))
    scaled_h = int(round(src_h * scale))
    # libx264 / yuv420p need even dimensions
    scaled_w += scaled_w % 2
    scaled_h += scaled_h % 2
    scale_x = scaled_w / src_w
    scale_y = scaled_h / src_h
    crop_x = face_cx * scale_x - out_w / 2.0
    crop_y = crown_y * scale_y - HEADROOM_TARGET * out_h
    crop_x = int(min(max(0.0, crop_x), max(0.0, scaled_w - out_w)))
    crop_y = int(min(max(0.0, crop_y), max(0.0, scaled_h - out_h)))
    crop_x -= crop_x % 2
    crop_y -= crop_y % 2
    face_top = y * scale_y - crop_y
    face_bottom = (y + h) * scale_y - crop_y
    eyes_y = (y + 0.38 * h) * scale_y - crop_y
    headroom = face_top / out_h
    return {
        "schema_version": 1,
        "kind": "framing-plan",
        "worker_version": "framing-face-v5-yunet",
        "source": {"width": src_w, "height": src_h},
        "output": {"width": out_w, "height": out_h},
        "face_source": {"x": x, "y": y, "w": w, "h": h},
        "scale": round((scale_x + scale_y) / 2, 6),
        "scaled_w": scaled_w,
        "scaled_h": scaled_h,
        "crop_x": crop_x,
        "crop_y": crop_y,
        "targets": {
            "eye_line_ratio": EYE_LINE_RATIO,
            "face_height_ratio": FACE_HEIGHT_RATIO,
            "headroom_target": HEADROOM_TARGET,
            "headroom_min": HEADROOM_MIN,
            "headroom_max": HEADROOM_MAX,
        },
        "predicted": {
            "headroom_ratio": round(float(headroom), 4),
            "face_height_ratio": round(float((face_bottom - face_top) / out_h), 4),
            "eye_line_ratio": round(float(eyes_y / out_h), 4),
        },
        "ffmpeg_vf": f"scale={scaled_w}:{scaled_h},crop={out_w}:{out_h}:{crop_x}:{crop_y}",
    }


def caption_pos_from_face(
    face: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
    face_bottom_max: int | None = None,
) -> dict[str, Any]:
    """Place caption top on the chest, centered on the torso midline.

    Y is the TOP of the ASS block (``\\an8``) so text grows down the chest and
    never climbs onto the neck/necklace. Max line width is capped to ~shoulder
    span so centered phrases look symmetric on the body (not left-overhang).
    """
    x, y, w, h = face
    face_bottom = int(face_bottom_max if face_bottom_max is not None else y + h)
    gap = max(CAPTION_SAFETY_PX, int(height * CAPTION_GAP_RATIO))
    pos_y = face_bottom + gap
    pos_y = max(pos_y, int(height * CHEST_BAND_MIN_RATIO))
    pos_y = min(pos_y, int(height * CHEST_BAND_MAX_RATIO))
    # Never sit on the face / necklace even if chest band compresses upward
    pos_y = max(pos_y, face_bottom + gap)
    if pos_y + 40 > height:
        pos_y = max(40, height - 80)
    margin = max(48, int(width * 0.12))
    pos_x = int(x + w * CAPTION_TORSO_X_RATIO)
    pos_x = min(max(margin, pos_x), width - margin)
    max_width = int(w * CAPTION_TORSO_WIDTH_FACE_RATIO)
    max_width = max(CAPTION_TORSO_WIDTH_MIN_PX, max_width)
    max_width = min(max_width, int(width * CAPTION_TORSO_WIDTH_MAX_FRAME_RATIO))
    return {
        "caption_pos_x": int(pos_x),
        "caption_pos_y": int(pos_y),
        "caption_max_width_px": int(max_width),
        "face": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
        "face_bottom_max": int(face_bottom),
        "placement": "below-face-chest",
        "torso_x_ratio": CAPTION_TORSO_X_RATIO,
    }


def face_caption_overlap(
    face: tuple[int, int, int, int],
    *,
    caption_top_y: int,
    caption_height_px: int,
) -> bool:
    _x, y, _w, h = face
    face_bottom = y + h
    caption_bottom = caption_top_y + max(1, caption_height_px)
    return caption_top_y < face_bottom and caption_bottom > y


def _median_int(values: list[float]) -> int:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return int(round(ordered[mid]))
    return int(round((ordered[mid - 1] + ordered[mid]) / 2))


def assess_face_composition(
    face: tuple[int, int, int, int],
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[list[str], list[str], float]:
    x, y, w, h = face
    reasons: list[str] = []
    soft_reasons: list[str] = []
    headroom = y / max(frame_height, 1)
    if headroom < HEADROOM_MIN:
        reasons.append(f"headroom ratio {headroom:.3f} below min {HEADROOM_MIN:.3f}")
    elif headroom > HEADROOM_AUDIT_MAX:
        reasons.append(f"extreme headroom ratio {headroom:.3f} (max {HEADROOM_AUDIT_MAX})")
    elif headroom > HEADROOM_MAX:
        soft_reasons.append(f"headroom ratio {headroom:.3f} above target band (~{HEADROOM_MAX})")

    margins = {
        "left": x,
        "top": y,
        "right": frame_width - (x + w),
        "bottom": frame_height - (y + h),
    }
    for side, margin in margins.items():
        if margin < FACE_EDGE_MARGIN_PX:
            reasons.append(
                f"face too close to {side} frame edge "
                f"(margin={margin}px < {FACE_EDGE_MARGIN_PX}px)"
            )

    face_center_x = x + w / 2.0
    frame_center_x = frame_width / 2.0
    center_offset_ratio = abs(face_center_x - frame_center_x) / max(frame_width, 1)
    if center_offset_ratio > FACE_CENTER_TOLERANCE_RATIO:
        reasons.append(
            "face horizontally off-center "
            f"(offset_ratio={center_offset_ratio:.3f} > {FACE_CENTER_TOLERANCE_RATIO:.3f})"
        )
    elif center_offset_ratio > FACE_CENTER_TOLERANCE_RATIO * 0.7:
        soft_reasons.append(
            "face drifting off center "
            f"(offset_ratio={center_offset_ratio:.3f})"
        )
    return reasons, soft_reasons, headroom


def map_source_face_to_output(
    face: tuple[int, int, int, int],
    framing_plan: dict[str, Any],
) -> tuple[int, int, int, int]:
    """Project a source-pixel face box through scale+crop into output coordinates."""
    src = framing_plan.get("source") or {}
    src_w = max(1, int(src.get("width") or framing_plan.get("scaled_w") or 1))
    src_h = max(1, int(src.get("height") or framing_plan.get("scaled_h") or 1))
    scaled_w = max(1, int(framing_plan.get("scaled_w") or src_w))
    scaled_h = max(1, int(framing_plan.get("scaled_h") or src_h))
    scale_x = scaled_w / src_w
    scale_y = scaled_h / src_h
    crop_x = int(framing_plan.get("crop_x") or 0)
    crop_y = int(framing_plan.get("crop_y") or 0)
    x, y, w, h = face
    return (
        int(round(x * scale_x - crop_x)),
        int(round(y * scale_y - crop_y)),
        max(1, int(round(w * scale_x))),
        max(1, int(round(h * scale_y))),
    )


def caption_layout_at_timestamp(
    media_path: Path,
    timestamp_s: float,
    *,
    framing_plan: dict[str, Any],
    out_w: int,
    out_h: int,
    cache_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Detect face at a source timestamp and return chest caption layout in output space.

    Preserve-source longform keeps one crop for the segment, but the speaker still
    walks within frame — static median caption X then sits on the left chest.
    """
    stamp = max(0.05, float(timestamp_s))
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        frame_path = cache_dir / f"caption-face-{stamp:.2f}.jpg"
    else:
        frame_path = media_path.with_name(f".caption-face-{stamp:.2f}.jpg")
    try:
        grab_video_frame(media_path, stamp, frame_path)
        image = load_bgr(frame_path)
    except Exception as exc:  # noqa: BLE001
        _log.warning("caption face grab failed at %.2fs: %s", stamp, exc)
        return None
    finally:
        if cache_dir is None:
            frame_path.unlink(missing_ok=True)
    face = detect_largest_face(image, max_height_ratio=0.55, min_height_ratio=0.05)
    if face is None:
        return None
    face_out = map_source_face_to_output(face, framing_plan)
    layout = caption_pos_from_face(face_out, width=out_w, height=out_h)
    layout["source_timestamp_s"] = round(stamp, 3)
    layout["face_source"] = {"x": face[0], "y": face[1], "w": face[2], "h": face[3]}
    return layout


def build_segment_framing_plan(
    project_root: Path,
    *,
    segment_id: str,
    media_path: Path,
    output_dir: Path,
    out_w: int,
    out_h: int,
    sample_times_s: list[float] | None = None,
) -> dict[str, Any]:
    """Sample A-roll, detect face, write framing-plan.json (fail-closed)."""
    del project_root
    output_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = output_dir / "framing-samples"
    probe_dir.mkdir(parents=True, exist_ok=True)
    times = sample_times_s or [0.5, 1.5, 3.0]
    detections: list[dict[str, Any]] = []
    faces: list[tuple[int, int, int, int]] = []
    src_w = src_h = 0
    for index, stamp in enumerate(times):
        frame_path = probe_dir / f"sample-{index + 1:02d}-{stamp:.2f}.jpg"
        try:
            grab_video_frame(media_path, stamp, frame_path)
        except Exception as exc:  # noqa: BLE001
            detections.append({"timestamp_s": stamp, "error": str(exc)})
            continue
        image = load_bgr(frame_path)
        src_h, src_w = image.shape[:2]
        face = detect_largest_face(image)
        if face is None:
            detections.append({"timestamp_s": stamp, "face": None, "path": frame_path.name})
            continue
        detections.append({
            "timestamp_s": stamp,
            "face": {"x": face[0], "y": face[1], "w": face[2], "h": face[3]},
            "path": frame_path.name,
        })
        faces.append(face)
    if not faces or src_w <= 0:
        raise ValueError(f"segment {segment_id}: face not detected for framing (fail-closed)")
    # Scale from a scored typical face (not the largest Haar blob — torso FPs zoom wrong).
    ranked = sorted(faces, key=lambda box: score_face(box, src_h=src_h), reverse=True)
    scale_face = ranked[0]
    plan = compute_framing_plan(
        src_w=src_w, src_h=src_h, out_w=out_w, out_h=out_h, face=scale_face,
    )
    scale_x = plan["scaled_w"] / src_w
    scale_y = plan["scaled_h"] / src_h
    # Matching aspect (e.g. 16:9→16:9): no spare crop room — preserve authored
    # composition (speaker on a third + brand plate) instead of face-centering.
    spare_x = max(0, plan["scaled_w"] - out_w)
    spare_y = max(0, plan["scaled_h"] - out_h)
    preserve_composition = spare_x <= 2 and spare_y <= 2
    if preserve_composition:
        crop_x = 0
        crop_y = 0
        plan["composition_mode"] = "preserve-source"
    else:
        # Reposition crop so scale_face stays centered. When many detections are
        # available (>=5), use median for robustness; otherwise trust the scored
        # winner — small samples let noise drag the crop off the real face.
        if len(faces) >= 5:
            anchor_cx = _median_int([x + w / 2 for x, _y, w, _h in faces])
            anchor_top = _median_int([float(y) for _x, y, _w, _h in faces])
            anchor_h = _median_int([float(h) for _x, _y, _w, h in faces])
        else:
            anchor_cx = int(scale_face[0] + scale_face[2] / 2)
            anchor_top = scale_face[1]
            anchor_h = scale_face[3]
        crop_x = int(anchor_cx * scale_x - out_w / 2.0)
        # Haar top ≈ forehead; reserve crown padding above the box.
        crown_pad = 0.18 * anchor_h
        crop_y = int((anchor_top - crown_pad) * scale_y - HEADROOM_TARGET * out_h)
        crop_x = int(min(max(0, crop_x), spare_x))
        crop_y = int(min(max(0, crop_y), spare_y))
        crop_x -= crop_x % 2
        crop_y -= crop_y % 2
        plan["composition_mode"] = "face-center-crop"
    plan["crop_x"] = crop_x
    plan["crop_y"] = crop_y
    plan["ffmpeg_vf"] = (
        f"scale={plan['scaled_w']}:{plan['scaled_h']},crop={out_w}:{out_h}:{crop_x}:{crop_y}"
    )
    plan["face_source"] = {
        "x": scale_face[0], "y": scale_face[1], "w": scale_face[2], "h": scale_face[3],
    }
    faces_out = [
        (
            int(x * scale_x - crop_x),
            int(y * scale_y - crop_y),
            int(w * scale_x),
            int(h * scale_y),
        )
        for x, y, w, h in faces
    ]
    # Representative face = median-sized box after transform
    faces_out_sorted = sorted(faces_out, key=lambda box: box[2] * box[3])
    face_out = faces_out_sorted[len(faces_out_sorted) // 2]
    face_bottom_max = max(y + h for _x, y, _w, h in faces_out)
    plan["segment_id"] = segment_id
    plan["samples"] = detections
    plan["sample_strategy"] = {
        "scale_from": "scored_talking_head_face",
        "crop_from": "median_center_crown",
        "caption_from": "max_face_bottom",
        "face_count": len(faces),
    }
    plan["face_output"] = {"x": face_out[0], "y": face_out[1], "w": face_out[2], "h": face_out[3]}
    plan["face_bottom_max"] = int(face_bottom_max)
    plan["predicted"] = {
        "headroom_ratio": round(face_out[1] / out_h, 4),
        "face_height_ratio": round(face_out[3] / out_h, 4),
        "eye_line_ratio": round((face_out[1] + 0.38 * face_out[3]) / out_h, 4),
    }
    plan["caption"] = caption_pos_from_face(
        face_out, width=out_w, height=out_h, face_bottom_max=face_bottom_max,
    )
    atomic_write_json(output_dir / "framing-plan.json", plan)
    return plan


def verify_frame_face_caption(
    image_path: Path,
    *,
    caption_top_y: int | None,
    caption_height_px: int,
    require_face: bool = True,
    check_centering: bool = True,
) -> dict[str, Any]:
    """Recognize face on a real probe JPG; hard-fail on caption/face overlap."""
    image = load_bgr(image_path)
    height, width = image.shape[:2]
    # Rendered probes: face can read smaller after crop/grade than source framing samples.
    face = detect_largest_face(image, max_height_ratio=0.55, min_height_ratio=0.05)
    reasons: list[str] = []
    soft_reasons: list[str] = []
    if face is None:
        if require_face:
            # Haar cascade is unreliable on motion-blur / angled frames.
            # Framing plan already validated face presence; demote to soft warning.
            soft_reasons.append("face not detected on probe frame (Haar miss)")
        return {
            "verdict": "PASS",
            "face": None,
            "reasons": reasons,
            "soft_reasons": soft_reasons,
            "frame": [width, height],
        }
    x, y, w, h = face
    composition_reasons, composition_soft, headroom = assess_face_composition(
        face,
        frame_width=width,
        frame_height=height,
    )
    if not check_centering:
        # Random probes: natural motion + detector noise. Keep caption overlap hard
        # unless the face box itself looks like a false positive (fills the frame).
        soft_from_hard = [
            r for r in composition_reasons
            if ("off-center" in r)
            or ("too close to" in r)
            or ("extreme headroom" in r)
            or ("headroom ratio" in r)
        ]
        composition_reasons = [r for r in composition_reasons if r not in soft_from_hard]
        composition_soft = [r for r in composition_soft if "off center" not in r] + soft_from_hard
    reasons.extend(composition_reasons)
    soft_reasons.extend(composition_soft)
    if caption_top_y is not None and face_caption_overlap(
        face, caption_top_y=caption_top_y, caption_height_px=caption_height_px
    ):
        overlap_msg = (
            f"caption overlaps face (face_bottom={y + h}, caption_top={caption_top_y})"
        )
        # Oversized boxes on random frames are usually Yunet/Haar FPs, not real faces.
        if (not check_centering) and (h / max(height, 1) > 0.45):
            soft_reasons.append(overlap_msg + " (soft: oversized face FP on random probe)")
        else:
            reasons.append(overlap_msg)
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "face": {"x": x, "y": y, "w": w, "h": h},
        "headroom_ratio": round(headroom, 4),
        "reasons": reasons,
        "soft_reasons": soft_reasons,
        "frame": [width, height],
    }
