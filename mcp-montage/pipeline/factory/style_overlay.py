"""Dan Koe style overlays: hook title and framework list plates."""

from __future__ import annotations

import shutil
import textwrap
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .io import working_output
from .media import require_tool, run
from .visual_policy import (
    CAPTION_TARGET_FONT_RATIO,
    HOOK_TITLE_COLOR,
    HOOK_TITLE_FONT_RATIO,
    HOOK_TITLE_MIN_TOP_RATIO,
    HOOK_TITLE_Y_CENTER_RATIO,
)


HOOK_TITLE_MAX_BOTTOM_RATIO = 0.88


def _font(size: int, *, italic: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if italic:
        candidates.extend([
            Path("C:/Windows/Fonts/timesi.ttf"),
            Path("C:/Windows/Fonts/georgiai.ttf"),
        ])
    candidates.extend([
        Path("C:/Windows/Fonts/times.ttf"),
        Path("C:/Windows/Fonts/timesbd.ttf"),
        Path("C:/Windows/Fonts/georgia.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ])
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _hex_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def hook_title_font_size(height: int, *, font_ratio: float | None = None) -> int:
    ratio = float(font_ratio) if font_ratio is not None else HOOK_TITLE_FONT_RATIO
    return max(42, int(round(int(height) * ratio)))


def render_hook_title_card(
    output: Path,
    *,
    title: str,
    duration_s: float,
    width: int,
    height: int,
    fps: int,
    color: str = HOOK_TITLE_COLOR,
    face_bottom_y: int | None = None,
    center_x: int | None = None,
    font_ratio: float | None = None,
    min_font_px: int | None = None,
) -> dict[str, Any]:
    """Large italic gold title on chest — distinct from body phrase captions.

    MeVGa reference: title block sits below the face (chest), not over eyes/nose.
    Horizontal center follows speaker chest X when provided (longform off-center).
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    card = output.with_suffix(".title.png")
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font_size = hook_title_font_size(height, font_ratio=font_ratio)
    floor_px = int(min_font_px) if min_font_px is not None else max(42, int(height * HOOK_TITLE_FONT_RATIO * 0.85))
    font_size = max(font_size, floor_px)
    font = _font(font_size, italic=True)
    # Prefer short stacked lines like MeVGa (3–5 lines), not one long ribbon.
    wrap_cols = 10 if font_size >= int(height * 0.09) else 12
    lines = textwrap.wrap(title.strip().replace("\n", " "), width=wrap_cols)[:5] or ["Title"]
    text = "\n".join(lines)
    spacing = max(8, font_size // 6)
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    anchor_x = int(center_x) if center_x is not None else width // 2
    # Italic fonts often have negative left bearing — center on ink, not (0, tw).
    x = anchor_x - (bbox[0] + bbox[2]) / 2
    # Below chin + necklace; prefer mid-chest, never sit on the face box.
    gap = max(56, int(height * 0.15))
    if face_bottom_y is not None and face_bottom_y > 0:
        y = float(face_bottom_y + gap)
    else:
        y = height * HOOK_TITLE_Y_CENTER_RATIO - th / 2
    # Soft floor: keep title in the lower-mid frame, but face clearance wins.
    min_top = max(height * HOOK_TITLE_MIN_TOP_RATIO, (face_bottom_y or 0) + gap)
    max_top = height * HOOK_TITLE_MAX_BOTTOM_RATIO - th
    y = max(min_top, min(y, max_top))
    # Cap title width to torso envelope — wrap tighter before shrinking below body captions.
    max_title_w = int(width * 0.42) if center_x is not None else int(width * 0.55)
    if tw > max_title_w and wrap_cols > 6:
        wrap_cols = max(6, wrap_cols - 2)
        lines = textwrap.wrap(title.strip().replace("\n", " "), width=wrap_cols)[:5] or ["Title"]
        text = "\n".join(lines)
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = anchor_x - (bbox[0] + bbox[2]) / 2
        max_top = height * HOOK_TITLE_MAX_BOTTOM_RATIO - th
        y = max(min_top, min(y, max_top))
    if tw > max_title_w and font_size > floor_px:
        shrink = max(floor_px, int(font_size * max_title_w / max(tw, 1)))
        font = _font(shrink, italic=True)
        font_size = shrink
        spacing = max(8, font_size // 6)
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = anchor_x - (bbox[0] + bbox[2]) / 2
        max_top = height * HOOK_TITLE_MAX_BOTTOM_RATIO - th
        y = max(min_top, min(y, max_top))
    fill = _hex_rgb(color)
    draw.multiline_text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 200), spacing=spacing, align="center")
    draw.multiline_text((x, y), text, font=font, fill=(*fill, 255), spacing=spacing, align="center")
    image.save(card)
    try:
        with working_output(output) as temporary:
            run([
                require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-i", str(card), "-t", f"{duration_s:.3f}",
                "-r", str(fps), "-c:v", "png", str(temporary),
            ])
    finally:
        card.unlink(missing_ok=True)
    return {
        "hook_title_font_size": font_size,
        "hook_title_font_ratio": round(font_size / max(height, 1), 4),
        "hook_title_color": color,
        "hook_title_italic": True,
        "hook_title_pos_y": int(round(y)),
        "hook_title_pos_x": int(round(anchor_x)),
        "hook_title_height_px": int(th),
        "hook_title_y_center_ratio": round((y + th / 2) / max(height, 1), 4),
        "body_caption_font_ratio": CAPTION_TARGET_FONT_RATIO,
    }


def _draw_list_frame(
    *,
    width: int,
    height: int,
    cleaned: list[str],
    active_index: int,
    reveal_count: int,
) -> Image.Image:
    """Transparent text plate — A-roll blur/darken happens in the compositor."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _font(max(26, width // 16))
    text_lines: list[tuple[int, str]] = []
    for index, line in enumerate(cleaned):
        if index >= reveal_count:
            break
        wrapped = textwrap.wrap(f"{index + 1}. {line}", width=20) or [f"{index + 1}. {line}"]
        text_lines.append((index, "\n".join(wrapped)))
    # Center the visible stack vertically (MeVGa ~mid-frame).
    line_step = max(48, height // 12)
    block_h = line_step * max(1, len(text_lines))
    y = int(height * 0.42 - block_h / 2)
    for index, chunk in text_lines:
        active = index == active_index
        fill = (255, 255, 255, 255) if active else (102, 102, 102, 160)
        bbox = draw.multiline_textbbox((0, 0), chunk, font=font, spacing=6, align="center")
        tw = bbox[2] - bbox[0]
        x = (width - tw) / 2
        draw.multiline_text((x + 2, y + 2), chunk, font=font, fill=(0, 0, 0, 200), spacing=6, align="center")
        draw.multiline_text((x, y), chunk, font=font, fill=fill, spacing=6, align="center")
        y += line_step
    return image


def render_framework_list_card(
    output: Path,
    *,
    lines: list[str],
    duration_s: float,
    width: int,
    height: int,
    fps: int,
    active_index: int = 0,
    active_from: int | None = None,
    active_to: int | None = None,
    progressive: bool = True,
) -> Path:
    """MeVGa-style numbered list: progressive spotlight over duration.

    Transparent text plate; compositor must blur+darken A-roll underneath.
    When progressive=True, reveal lines 1..k and spotlight k as time advances
    from active_from (default 0) to active_to (default last line).
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    cleaned = [str(item).strip() for item in lines if str(item).strip()][:8]
    if not cleaned:
        cleaned = ["Step"]
    start_i = active_from if active_from is not None else 0
    end_i = active_to if active_to is not None else (len(cleaned) - 1)
    start_i = max(0, min(start_i, len(cleaned) - 1))
    end_i = max(start_i, min(end_i, len(cleaned) - 1))

    if not progressive or duration_s < 0.4 or start_i == end_i:
        # Static single spotlight (tests / short clips).
        idx = active_index if not progressive else end_i
        idx = max(0, min(idx, len(cleaned) - 1))
        card = output.with_suffix(".list.png")
        _draw_list_frame(
            width=width, height=height, cleaned=cleaned,
            active_index=idx, reveal_count=idx + 1,
        ).save(card)
        try:
            with working_output(output) as temporary:
                run([
                    require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", str(card), "-t", f"{duration_s:.3f}",
                    "-r", str(fps), "-c:v", "png", str(temporary),
                ])
        finally:
            card.unlink(missing_ok=True)
        return output

    # Progressive: one PNG per spotlight step, concat via ffmpeg concat demuxer.
    steps = end_i - start_i + 1
    step_dur = max(0.35, duration_s / steps)
    frame_dir = Path(tempfile.mkdtemp(prefix="fwlist_"))
    try:
        concat_lines: list[str] = []
        for step in range(steps):
            idx = start_i + step
            frame_path = frame_dir / f"step-{step:02d}.png"
            _draw_list_frame(
                width=width, height=height, cleaned=cleaned,
                active_index=idx, reveal_count=idx + 1,
            ).save(frame_path)
            # Last step absorbs leftover duration so total ≈ duration_s.
            dur = step_dur if step < steps - 1 else max(0.35, duration_s - step_dur * (steps - 1))
            concat_lines.append(f"file '{frame_path.as_posix()}'")
            concat_lines.append(f"duration {dur:.3f}")
        # concat demuxer needs the last file repeated without duration
        concat_lines.append(f"file '{(frame_dir / f'step-{steps - 1:02d}.png').as_posix()}'")
        list_file = frame_dir / "concat.txt"
        list_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        with working_output(output) as temporary:
            run([
                require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-r", str(fps), "-t", f"{duration_s:.3f}", "-c:v", "png", str(temporary),
            ])
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)
    return output


def gold_caption_color() -> str:
    return CAPTION_REQUIRED_COLOR
