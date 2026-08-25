"""Deterministic animated MOTION overlays v2 — semantic templates with audience punch."""

from __future__ import annotations

import math
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .io import working_output
from .media import require_tool, run
from .visual_policy import FORMULA_PUNCH_RE, QUOTED_PUNCH_RE

MOTION_WORKER_VERSION = "motion-dynamic-v7-torso-fit"

FORMULA_EXTRACT_RE = re.compile(
    r"(\d[\d\s]*\d|\d+)\s*(?:→|->|—)\s*(?:[^\d]{0,32}?)(\d[\d\s]*\d|\d+)"
)
MONTH_STACK_RE = re.compile(r"(\d+)\s*месяц", re.I)
CTA_SCHEME_RE = re.compile(r"\bсхема\b", re.I)
AMOUNT_RE = re.compile(r"(\d[\d\s]*\d|\d+)\s*(?:₽|руб|р\.?)\b", re.I)

GOLD = (225, 196, 69, 255)
GOLD_DIM = (225, 196, 69, 140)
GOLD_BRIGHT = (244, 196, 4, 255)
WHITE = (255, 255, 255, 255)
WHITE_DIM = (255, 255, 255, 100)
RED_WARN = (220, 60, 60, 230)
PILL_BG = (11, 18, 32, 210)
DARK_BG = (18, 22, 36, 200)
CARD_BG = (22, 26, 40, 220)


def _layout_cx(width: int, center_x: int | None) -> int:
    """Stable horizontal anchor for motion (match caption chest X)."""
    if center_x is None:
        return width // 2
    return int(min(max(0, center_x), width))


@dataclass(frozen=True)
class MotionSpec:
    template: str
    label: str
    brief: str
    suppress_captions: bool = True


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/times.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _font_bold(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/timesbd.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return _font(size)


def _extract_formula_label(brief: str) -> str:
    match = FORMULA_PUNCH_RE.search(brief) or FORMULA_EXTRACT_RE.search(brief)
    if not match:
        return ""
    left = " ".join(match.group(1).split())
    right = " ".join(match.group(2).split())
    return f"{left} → {right}"


def _brief_what_only(brief: str) -> str:
    """Strip director Зачем:/why notes — punch must come from the what clause only."""
    text = " ".join(str(brief or "").split())
    text = re.split(r"(?i)\.\s*Зачем\s*:", text, maxsplit=1)[0]
    text = re.split(r"(?i)\bЗачем\s*:", text, maxsplit=1)[0]
    return text.strip(" .")


def _extract_audience_punch(brief: str) -> str:
    """Extract readable audience text: quoted «…» spans, amounts, or formula."""
    text = _brief_what_only(brief)
    quoted = QUOTED_PUNCH_RE.findall(text)
    if quoted:
        return " / ".join(quoted[:2])
    formula = _extract_formula_label(text)
    if formula:
        return formula
    amount = AMOUNT_RE.search(text)
    if amount:
        return " ".join(amount.group(0).split())
    return ""


def classify_motion(brief: str) -> MotionSpec:
    """Map director brief → animated template + audience label. Never empty label in v2."""
    text = " ".join(str(brief or "").split())
    if not text:
        return MotionSpec("kinetic_accent", "", text)

    lowered = text.casefold()
    punch = _extract_audience_punch(text)

    formula = _extract_formula_label(text)
    if formula:
        return MotionSpec("formula_split", formula, text)
    if any(token in lowered for token in ("ползёт", "ползет", "индикатор", "кошелёк", "кошелек", "на нуле")):
        label = punch or "0 ₽"
        return MotionSpec("meter_drop", label, text)
    if any(token in lowered for token in ("иконки", "паник", "горящ", "экстренн")):
        return MotionSpec("panic_sequence", punch or "паника", text)
    if any(token in lowered for token in ("два банка", "другом банке", "перевод", "трением", "замок")):
        return MotionSpec("bank_friction", punch or "2 банка", text)
    if MONTH_STACK_RE.search(text) or (
        ("складыва" in lowered or "стопка" in lowered)
        and ("месяц" in lowered or "мес" in lowered or "год" in lowered)
    ):
        months = MONTH_STACK_RE.search(text)
        label = f"{months.group(1)} мес × 6 000" if months else "12 мес × 6 000"
        return MotionSpec("stack_growth", label, text)
    if "весы" in lowered or " vs " in lowered:
        return MotionSpec("scales_tilt", punch or "приоритеты", text)
    if "сдвиг приоритет" in lowered or ("приоритет" in lowered and CTA_SCHEME_RE.search(text)):
        label = punch or ("схема" if CTA_SCHEME_RE.search(text) else "приоритеты")
        return MotionSpec("priority_shift", label, text)
    if punch:
        return MotionSpec("text_punch", punch, text)
    return MotionSpec("kinetic_accent", "", text)


# ---------------------------------------------------------------------------
# Animation helpers
# ---------------------------------------------------------------------------

def _alpha_envelope(frame: int, total: int, fps: int) -> float:
    fade = max(1, int(0.28 * fps))
    if frame < fade:
        return frame / fade
    if frame >= total - fade:
        return max(0.0, (total - frame) / fade)
    return 1.0


def _slide_offset(frame: int, fps: int) -> int:
    settle = max(1, int(0.32 * fps))
    if frame >= settle:
        return 0
    return int(18 * (1.0 - frame / settle))


def _ease_out(t: float) -> float:
    return 1.0 - (1.0 - min(1.0, max(0.0, t))) ** 2.5


def _draw_scrim(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    alpha: float,
    center_x: int | None = None,
) -> None:
    """Dark gradient scrim behind motion zone, anchored on speaker chest X."""
    cx = _layout_cx(width, center_x)
    band_w = int(width * 0.72)
    left = max(0, cx - band_w // 2)
    right = min(width, left + band_w)
    top = int(height * 0.58)
    bottom = int(height * 0.92)
    for y in range(top, bottom):
        t = (y - top) / max(1, bottom - top)
        intensity = 0.65 * math.sin(t * math.pi)
        a = int(intensity * alpha * 160)
        draw.line((left, y, right, y), fill=(0, 0, 0, a))


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    *,
    width: int,
    height: int,
    label: str,
    alpha: float,
    slide_y: int,
    y_norm: float = 0.68,
    font_size_override: int | None = None,
    center_x: int | None = None,
) -> None:
    if not label or alpha <= 0.02:
        return
    fsize = font_size_override or max(28, int(height * 0.045))
    font = _font_bold(fsize)
    band_top = int(height * y_norm) + slide_y
    bbox = draw.multiline_textbbox((0, 0), label, font=font, spacing=6, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad_x, pad_y = max(16, int(height * 0.02)), max(8, int(height * 0.012))
    box_w = text_w + pad_x * 2
    # Off-center talking-head: keep pill inside torso, not frame-wide.
    if center_x is not None:
        max_box = max(220, int(width * 0.28))
        if box_w > max_box:
            # Shrink type until the pill fits the shoulder envelope.
            while fsize > 22 and box_w > max_box:
                fsize -= 2
                font = _font_bold(fsize)
                bbox = draw.multiline_textbbox((0, 0), label, font=font, spacing=6, align="center")
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                box_w = text_w + pad_x * 2
            box_w = min(box_w, max_box)
    box_h = text_h + pad_y * 2
    cx = _layout_cx(width, center_x)
    left = cx - box_w / 2
    top = band_top
    a = int(255 * alpha)
    draw.rounded_rectangle(
        (left, top, left + box_w, top + box_h),
        radius=max(12, width // 36),
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(PILL_BG[3] * alpha)),
    )
    # anchor=mm: text block center == layout cx (same axis as captions / hook).
    draw.multiline_text(
        (cx, top + box_h / 2),
        label,
        font=font,
        fill=(GOLD[0], GOLD[1], GOLD[2], a),
        spacing=6,
        align="center",
        anchor="mm",
    )


# ---------------------------------------------------------------------------
# v2 Templates — semantic, readable in <1s
# ---------------------------------------------------------------------------

def _frame_meter_drop(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, label: str, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    _draw_scrim(draw, width, height, alpha, center_x=center_x)

    # Animated balance counter
    cy = int(height * 0.66)
    big_font = _font_bold(max(42, width // 9))
    small_font = _font(max(20, width // 24))

    # "Wallet" card
    card_w, card_h = int(width * 0.72), int(height * 0.14)
    card_left = cx - card_w // 2
    card_top = cy - card_h // 2
    draw.rounded_rectangle(
        (card_left, card_top, card_left + card_w, card_top + card_h),
        radius=max(14, width // 30),
        fill=(CARD_BG[0], CARD_BG[1], CARD_BG[2], int(CARD_BG[3] * alpha)),
    )

    # Header "баланс"
    draw.text(
        (card_left + 20, card_top + 10),
        "баланс",
        font=small_font,
        fill=(WHITE_DIM[0], WHITE_DIM[1], WHITE_DIM[2], int(WHITE_DIM[3] * alpha)),
    )

    # Animated amount: tick down from some start to 0
    amount_match = AMOUNT_RE.search(label) or AMOUNT_RE.search(str(label))
    end_val = 0
    start_val = 12400
    if amount_match:
        raw = amount_match.group(1).replace(" ", "")
        try:
            end_val = int(raw)
        except ValueError:
            pass
    current_val = int(start_val * (1.0 - _ease_out(progress)))
    display = f"{current_val:,}".replace(",", " ") + " ₽"

    amount_color = RED_WARN if current_val < start_val * 0.15 else GOLD
    draw.text(
        (cx, cy + 8),
        display,
        font=big_font,
        fill=(amount_color[0], amount_color[1], amount_color[2], int(amount_color[3] * alpha)),
        anchor="mm",
    )

    # Progress bar below card
    bar_w = int(card_w * 0.85)
    bar_h = max(8, height // 80)
    bar_left = cx - bar_w // 2
    bar_top = card_top + card_h + 12
    draw.rounded_rectangle(
        (bar_left, bar_top, bar_left + bar_w, bar_top + bar_h),
        radius=bar_h // 2,
        fill=(30, 30, 30, int(180 * alpha)),
    )
    fill_w = max(4, int(bar_w * (1.0 - _ease_out(progress))))
    fill_color = RED_WARN if fill_w < bar_w * 0.15 else GOLD
    draw.rounded_rectangle(
        (bar_left, bar_top, bar_left + fill_w, bar_top + bar_h),
        radius=bar_h // 2,
        fill=(fill_color[0], fill_color[1], fill_color[2], int(220 * alpha)),
    )

    # Label at bottom
    if label:
        label_font = _font(max(22, width // 22))
        label_text = label if "₽" in label else f"→ {label}"
        draw.text(
            (cx, bar_top + bar_h + 24),
            label_text,
            font=label_font,
            fill=(GOLD_DIM[0], GOLD_DIM[1], GOLD_DIM[2], int(200 * alpha)),
            anchor="mt",
        )


def _frame_panic_sequence(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, label: str, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    _draw_scrim(draw, width, height, alpha, center_x=center_x)

    steps = [
        ("🔥", "паника"),
        ("🔍", "ищу выход"),
        ("💰", "занимаю"),
    ]
    cx = _layout_cx(width, center_x)
    base_y = int(height * 0.64)
    step_h = int(height * 0.065)
    active_idx = min(len(steps) - 1, int(progress * len(steps) * 1.1))

    icon_font = _font_bold(max(32, width // 14))
    label_font = _font(max(22, width // 22))

    for i, (icon, text) in enumerate(steps):
        y = base_y + i * (step_h + 12)
        is_active = i == active_idx
        is_past = i < active_idx

        # Step card
        card_w = int(width * 0.65)
        card_left = cx - card_w // 2
        card_alpha = alpha * (1.0 if is_active else (0.4 if is_past else 0.25))
        draw.rounded_rectangle(
            (card_left, y, card_left + card_w, y + step_h),
            radius=10,
            fill=(CARD_BG[0], CARD_BG[1], CARD_BG[2], int(CARD_BG[3] * card_alpha)),
        )

        step_label = f"  {text}"
        txt_color = GOLD if is_active else GOLD_DIM
        txt_alpha = alpha * (1.0 if is_active else 0.5)
        draw.text(
            (card_left + 16, y + step_h // 2),
            step_label,
            font=label_font,
            fill=(txt_color[0], txt_color[1], txt_color[2], int(txt_color[3] * txt_alpha)),
            anchor="lm",
        )

        if is_active:
            scale = 1.0 + 0.15 * math.sin(progress * math.pi * 4)
            active_font = _font_bold(int(max(26, width // 16) * scale))
            draw.text(
                (card_left + card_w - 20, y + step_h // 2),
                "←",
                font=active_font,
                fill=(GOLD_BRIGHT[0], GOLD_BRIGHT[1], GOLD_BRIGHT[2], int(GOLD_BRIGHT[3] * alpha)),
                anchor="rm",
            )


def _frame_formula_split(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, label: str, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    _draw_scrim(draw, width, height, alpha, center_x=center_x)

    if "→" not in label:
        _draw_pill(draw, width=width, height=height, label=label, alpha=alpha, slide_y=0, center_x=center_x)
        return

    parts = [p.strip() for p in label.split("→", 1)]
    cy = int(height * 0.68)
    big_font = _font_bold(max(38, width // 10))
    small_font = _font(max(22, width // 22))

    # Card background
    card_w, card_h = int(width * 0.78), int(height * 0.12)
    card_left = cx - card_w // 2
    card_top = cy - card_h // 2
    draw.rounded_rectangle(
        (card_left, card_top, card_left + card_w, card_top + card_h),
        radius=14,
        fill=(CARD_BG[0], CARD_BG[1], CARD_BG[2], int(CARD_BG[3] * alpha)),
    )

    # Split animation: left and right parts separate
    spread = int(width * 0.12 * _ease_out(progress))
    left_x = cx - spread - 10
    right_x = cx + spread + 10

    # Left value (dims as it "leaves")
    left_alpha = alpha * max(0.3, 1.0 - progress * 0.7)
    draw.text(
        (left_x, cy),
        parts[0],
        font=big_font,
        fill=(WHITE_DIM[0], WHITE_DIM[1], WHITE_DIM[2], int(left_alpha * 200)),
        anchor="rm",
    )

    # Arrow
    draw.text(
        (cx, cy),
        "→",
        font=_font(max(30, width // 16)),
        fill=(GOLD_DIM[0], GOLD_DIM[1], GOLD_DIM[2], int(alpha * 180)),
        anchor="mm",
    )

    # Right value (brightens)
    right_alpha = alpha * min(1.0, 0.3 + progress * 0.7)
    draw.text(
        (right_x, cy),
        parts[1],
        font=big_font,
        fill=(GOLD_BRIGHT[0], GOLD_BRIGHT[1], GOLD_BRIGHT[2], int(right_alpha * 255)),
        anchor="lm",
    )

    # Percentage label below
    pct_match = re.search(r"\((\d+%)\)", str(label))
    if pct_match:
        draw.text(
            (cx, card_top + card_h + 14),
            pct_match.group(1),
            font=small_font,
            fill=(GOLD_DIM[0], GOLD_DIM[1], GOLD_DIM[2], int(alpha * 160)),
            anchor="mt",
        )


def _frame_bank_friction(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, label: str, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    _draw_scrim(draw, width, height, alpha, center_x=center_x)

    cx = _layout_cx(width, center_x)
    y = int(height * 0.66)
    card_w = int(width * 0.30)
    card_h = int(height * 0.10)
    gap = int(width * 0.06)

    left_x = cx - gap - card_w
    right_x = cx + gap

    label_font = _font(max(18, width // 28))
    title_font = _font_bold(max(22, width // 22))

    for i, (x, name) in enumerate([(left_x, "банк 1"), (right_x, "банк 2")]):
        draw.rounded_rectangle(
            (x, y, x + card_w, y + card_h),
            radius=12,
            fill=(CARD_BG[0], CARD_BG[1], CARD_BG[2], int(CARD_BG[3] * alpha)),
            outline=(GOLD[0], GOLD[1], GOLD[2], int(120 * alpha)),
            width=2,
        )
        draw.text(
            (x + card_w // 2, y + card_h // 2),
            name,
            font=title_font,
            fill=(WHITE[0], WHITE[1], WHITE[2], int(220 * alpha)),
            anchor="mm",
        )

    # Animated transfer arrow with friction
    arrow_y = y + card_h // 2
    arrow_progress = _ease_out(min(1.0, progress * 1.3))
    arrow_end_x = cx - gap + int((gap * 2) * min(0.45, arrow_progress * 0.5))

    if progress < 0.55:
        # Arrow going right, hitting friction
        draw.line(
            (left_x + card_w + 8, arrow_y, left_x + card_w + 8 + int(gap * 0.6 * arrow_progress), arrow_y),
            fill=(GOLD[0], GOLD[1], GOLD[2], int(200 * alpha)),
            width=3,
        )
        # Lock icon
        draw.text(
            (cx, arrow_y),
            "🔒",
            font=_font(max(24, width // 20)),
            fill=(RED_WARN[0], RED_WARN[1], RED_WARN[2], int(230 * alpha)),
            anchor="mm",
        )
    else:
        # Friction label
        draw.text(
            (cx, arrow_y - 20),
            "⏳",
            font=_font(max(28, width // 16)),
            fill=(GOLD[0], GOLD[1], GOLD[2], int(220 * alpha)),
            anchor="mm",
        )
        draw.text(
            (cx, arrow_y + 16),
            "ждать",
            font=label_font,
            fill=(GOLD_DIM[0], GOLD_DIM[1], GOLD_DIM[2], int(180 * alpha)),
            anchor="mm",
        )

    # Bottom label
    if label:
        draw.text(
            (cx, y + card_h + 20),
            label,
            font=label_font,
            fill=(GOLD_DIM[0], GOLD_DIM[1], GOLD_DIM[2], int(160 * alpha)),
            anchor="mt",
        )


def _frame_stack_growth(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, label: str, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    _draw_scrim(draw, width, height, alpha, center_x=center_x)

    max_tiles = 6
    visible = min(max_tiles, max(1, int(progress * (max_tiles + 1))))
    tile_w = int(width * 0.50)
    tile_h = int(height * 0.040)
    base_x = cx - tile_w // 2
    base_y = int(height * 0.80)

    small_font = _font(max(16, width // 32))
    label_font = _font_bold(max(22, width // 22))

    for index in range(visible):
        y = base_y - index * (tile_h + 6)
        brightness = 0.5 + 0.5 * (index / max(max_tiles - 1, 1))
        a = int(brightness * alpha * 255)
        draw.rounded_rectangle(
            (base_x, y, base_x + tile_w, y + tile_h),
            radius=8,
            fill=(GOLD[0], GOLD[1], GOLD[2], a),
        )
        month_label = f"мес {index + 1}: 6 000 ₽"
        draw.text(
            (base_x + tile_w // 2, y + tile_h // 2),
            month_label,
            font=small_font,
            fill=(0, 0, 0, int(alpha * 200)),
            anchor="mm",
        )

    # Total label
    total = visible * 6000
    if label:
        draw.text(
            (cx, base_y + tile_h + 20),
            f"= {total:,} ₽".replace(",", " "),
            font=label_font,
            fill=(GOLD_BRIGHT[0], GOLD_BRIGHT[1], GOLD_BRIGHT[2], int(alpha * 240)),
            anchor="mt",
        )


def _frame_scales_tilt(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, label: str, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    _draw_scrim(draw, width, height, alpha, center_x=center_x)

    cy = int(height * 0.72)
    beam_w = int(width * 0.56)
    tilt = int(18 * _ease_out(progress) - 9)

    # Fulcrum
    draw.polygon(
        [(cx - 8, cy + 30), (cx + 8, cy + 30), (cx, cy + 10)],
        fill=(GOLD_DIM[0], GOLD_DIM[1], GOLD_DIM[2], int(180 * alpha)),
    )

    # Beam
    draw.line(
        (cx - beam_w // 2, cy + tilt, cx + beam_w // 2, cy - tilt),
        fill=(GOLD[0], GOLD[1], GOLD[2], int(200 * alpha)),
        width=4,
    )

    # Left pan: "хотелки" (goes up = lighter)
    left_x = cx - beam_w // 2
    pan_w, pan_h = int(width * 0.22), int(height * 0.055)
    draw.rounded_rectangle(
        (left_x - pan_w // 2, cy + tilt - pan_h, left_x + pan_w // 2, cy + tilt),
        radius=8,
        fill=(CARD_BG[0], CARD_BG[1], CARD_BG[2], int(CARD_BG[3] * alpha)),
    )
    draw.text(
        (left_x, cy + tilt - pan_h // 2),
        "хотелки",
        font=_font(max(18, width // 28)),
        fill=(WHITE_DIM[0], WHITE_DIM[1], WHITE_DIM[2], int(alpha * 200)),
        anchor="mm",
    )

    # Right pan: "мечта" (goes down = heavier)
    right_x = cx + beam_w // 2
    draw.rounded_rectangle(
        (right_x - pan_w // 2, cy - tilt - pan_h, right_x + pan_w // 2, cy - tilt),
        radius=8,
        fill=(CARD_BG[0], CARD_BG[1], CARD_BG[2], int(CARD_BG[3] * alpha)),
    )
    draw.text(
        (right_x, cy - tilt - pan_h // 2),
        "мечта",
        font=_font_bold(max(18, width // 28)),
        fill=(GOLD_BRIGHT[0], GOLD_BRIGHT[1], GOLD_BRIGHT[2], int(alpha * 240)),
        anchor="mm",
    )

    # Bottom label
    if label and label != "приоритеты":
        draw.text(
            (cx, cy + 46),
            label,
            font=_font(max(20, width // 24)),
            fill=(GOLD_DIM[0], GOLD_DIM[1], GOLD_DIM[2], int(alpha * 180)),
            anchor="mt",
        )


def _frame_priority_shift(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, label: str, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    _draw_scrim(draw, width, height, alpha, center_x=center_x)

    cx = _layout_cx(width, center_x)
    cy = int(height * 0.68)
    shift = int(30 * _ease_out(progress))

    items = [
        ("хотелки", False),
        ("мечта", True),
        ("подушка", True),
    ]

    item_h = int(height * 0.048)
    item_w = int(width * 0.55)
    start_y = cy - len(items) * (item_h + 8) // 2

    label_font = _font(max(20, width // 24))
    bold_font = _font_bold(max(22, width // 22))

    for i, (text, goes_up) in enumerate(items):
        y_offset = -shift if goes_up else shift
        y = start_y + i * (item_h + 8) + y_offset
        card_left = cx - item_w // 2

        is_priority = goes_up
        bg_alpha = alpha * (0.9 if is_priority else 0.5)
        draw.rounded_rectangle(
            (card_left, y, card_left + item_w, y + item_h),
            radius=10,
            fill=(CARD_BG[0], CARD_BG[1], CARD_BG[2], int(CARD_BG[3] * bg_alpha)),
        )

        arrow = "↑" if goes_up else "↓"
        arrow_color = GOLD_BRIGHT if goes_up else RED_WARN
        draw.text(
            (card_left + 16, y + item_h // 2),
            arrow,
            font=bold_font,
            fill=(arrow_color[0], arrow_color[1], arrow_color[2], int(alpha * 220)),
            anchor="lm",
        )

        txt_font = bold_font if is_priority else label_font
        txt_color = GOLD if is_priority else GOLD_DIM
        draw.text(
            (card_left + 46, y + item_h // 2),
            text,
            font=txt_font,
            fill=(txt_color[0], txt_color[1], txt_color[2], int(alpha * 220)),
            anchor="lm",
        )

    # CTA label at bottom
    if label:
        pill_y = start_y + len(items) * (item_h + 8) + shift + 16
        _draw_pill(draw, width=width, height=height, label=label, alpha=alpha * 0.85,
                   slide_y=0, y_norm=pill_y / height, center_x=center_x)


def _frame_text_punch(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, label: str, slide_y: int, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    _draw_scrim(draw, width, height, alpha, center_x=center_x)
    _draw_pill(draw, width=width, height=height, label=label, alpha=alpha, slide_y=slide_y,
               font_size_override=max(32, int(height * 0.055)), center_x=center_x)


def _frame_kinetic_accent(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    *, progress: float, alpha: float, width: int, height: int, center_x: int | None = None) -> None:
    cx = _layout_cx(width, center_x)
    line_w = int(width * (0.25 + 0.35 * min(1.0, progress * 1.2)))
    x0 = cx - line_w // 2
    y = int(height * 0.80)
    draw.line((x0, y, x0 + line_w, y), fill=(GOLD[0], GOLD[1], GOLD[2], int(180 * alpha)), width=4)


def _render_frame(
    spec: MotionSpec,
    *,
    frame: int,
    total: int,
    fps: int,
    width: int,
    height: int,
    center_x: int | None = None,
) -> Image.Image:
    progress = frame / max(total - 1, 1)
    alpha = _alpha_envelope(frame, total, fps)
    slide = _slide_offset(frame, fps)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    template = spec.template
    if template == "text_punch":
        _frame_text_punch(image, draw, progress=progress, alpha=alpha, width=width,
                          height=height, label=spec.label, slide_y=slide, center_x=center_x)
    elif template == "formula_split":
        _frame_formula_split(image, draw, progress=progress, alpha=alpha,
                             width=width, height=height, label=spec.label, center_x=center_x)
    elif template == "meter_drop":
        _frame_meter_drop(image, draw, progress=progress, alpha=alpha,
                          width=width, height=height, label=spec.label, center_x=center_x)
    elif template == "panic_sequence":
        _frame_panic_sequence(image, draw, progress=progress, alpha=alpha,
                              width=width, height=height, label=spec.label, center_x=center_x)
    elif template == "bank_friction":
        _frame_bank_friction(image, draw, progress=progress, alpha=alpha,
                             width=width, height=height, label=spec.label, center_x=center_x)
    elif template == "stack_growth":
        _frame_stack_growth(image, draw, progress=progress, alpha=alpha,
                            width=width, height=height, label=spec.label, center_x=center_x)
    elif template == "scales_tilt":
        _frame_scales_tilt(image, draw, progress=progress, alpha=alpha,
                           width=width, height=height, label=spec.label, center_x=center_x)
    elif template == "priority_shift":
        _frame_priority_shift(image, draw, progress=progress, alpha=alpha,
                              width=width, height=height, label=spec.label, center_x=center_x)
    else:
        _frame_kinetic_accent(image, draw, progress=progress, alpha=alpha,
                              width=width, height=height, center_x=center_x)
    return image


def render_motion_overlay(
    output: Path,
    *,
    brief: str,
    duration_s: float,
    width: int,
    height: int,
    fps: int,
    center_x: int | None = None,
) -> tuple[Path, MotionSpec]:
    """Render animated RGBA overlay clip for the declared MOTION window."""
    if duration_s <= 0.05:
        raise ValueError("motion duration too short")
    output.parent.mkdir(parents=True, exist_ok=True)
    spec = classify_motion(brief)
    frame_count = max(2, int(round(duration_s * fps)))
    temp_dir = Path(tempfile.mkdtemp(prefix="motion-frames-"))
    try:
        for index in range(frame_count):
            frame = _render_frame(
                spec, frame=index, total=frame_count, fps=fps,
                width=width, height=height, center_x=center_x,
            )
            frame.save(temp_dir / f"frame-{index:04d}.png")
        with working_output(output) as temporary:
            run([
                require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-framerate", str(fps), "-i", str(temp_dir / "frame-%04d.png"),
                "-t", f"{duration_s:.3f}",
                "-c:v", "png", str(temporary),
            ])
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return output, spec


def render_motion_card(
    output: Path,
    *,
    brief: str,
    duration_s: float,
    width: int,
    height: int,
    fps: int,
) -> Path:
    """Backward-compatible entry — delegates to animated overlay."""
    path, _spec = render_motion_overlay(
        output, brief=brief, duration_s=duration_s, width=width, height=height, fps=fps,
        center_x=None,
    )
    return path
