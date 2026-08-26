"""Gate 2 visual policies — Dan Koe chest captions + motion overlay rules."""

from __future__ import annotations

import re
from typing import Any

from .style_guard import style_recipes_policy
from .style_profile import captions as style_captions
from .style_profile import hook as style_hook
from .style_profile import load_style, style_id_from


# Значения ниже — дефолт стиля dankoe-mevga-v1. Живой источник вида — presets/styles/<id>/style.json
# (см. style_profile.py): код здесь механика, а конкретный вид приходит данными.
CAPTION_MAX_FONT_RATIO = 0.18  # longform 16:9 needs larger type than vertical reels
CAPTION_MIN_FONT_PX = 16
CAPTION_TARGET_FONT_RATIO = 0.045
CAPTION_REQUIRED_ALIGNMENT = 5  # middle-center
CAPTION_REQUIRED_COLOR = "#E1C445"
CAPTION_REQUIRED_FONT_CLASS = "serif"
CAPTION_MAX_WORDS = 6
CAPTION_MAX_LINES = 2

# MeVGa hook title — larger italic gold on chest, not mid-face body captions.
HOOK_TITLE_FONT_RATIO = 0.072
HOOK_TITLE_MIN_TOP_RATIO = 0.48
HOOK_TITLE_Y_CENTER_RATIO = 0.64
HOOK_TITLE_COLOR = "#EAC225"

DEFAULT_STYLE_ID_FOR_REPORT = "dankoe-mevga-v1"

MOTION_MODE_OVERLAY = "overlay"
MOTION_MODE_REPLACE = "replace"  # legacy / forbidden in production Gate 2

WHY_LEAK_RE = re.compile(r"(?i)\bзачем\s*:")
AGENT_NOTE_RE = re.compile(r"(?i)\b(зачем|why|risks?|narrative_summary)\b\s*:")
OVERLAY_META_RE = re.compile(r"(?i)^\(\s*поверх\s+речи[^)]*\)\s*")
DIRECTOR_COPY_RE = re.compile(
    r"(?i)\b("
    r"поверх\s+речи|индикатор|ползёт|иконки|вырезается|тускнеет|плитки|"
    r"складываются|весы|сдвиг\s+приоритетов|акцент\s+cta|анимация|нарисуй|"
    r"показать|покажи|оверлей\s+кроет"
    r")\b"
)
QUOTED_PUNCH_RE = re.compile(r"[«\"]([^»\"]{1,24})[»\"]")
FORMULA_PUNCH_RE = re.compile(
    r"(\d[\d\s]*\d|\d+)\s*(?:→|->)\s*(?:[^\d]{0,24}?)(\d[\d\s]*\d|\d+)(?:\s*\([^)]*\))?"
)
MAX_MOTION_ON_SCREEN_WORDS = 6

# Spoken ASR often mangles org/brand names — burn the canonical form on captions.
CAPTION_BRAND_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bпро\s+женщины\b"), "PRO Женщин"),
    (re.compile(r"(?i)\bпро\s+женщин\b"), "PRO Женщин"),
    # casefold() turns Latin PRO → pro; restore after soft-lowercasing
    (re.compile(r"(?i)\bpro\s+женщины\b"), "PRO Женщин"),
    (re.compile(r"(?i)\bpro\s+женщин\b"), "PRO Женщин"),
    (re.compile(r"(?i)\bэкзесидвижение\b"), "X10 Движение"),
    (re.compile(r"(?i)\bэкдсятьдвижение\b"), "X10 Движение"),
    (re.compile(r"(?i)\bэкзи\s*движение\b"), "X10 Движение"),
    (re.compile(r"(?i)\bx10\s*движение\b"), "X10 Движение"),
)

_CAPTION_ATOMIC_BRANDS = ("PRO Женщин", "X10 Движение")


def caption_display_text(text: str) -> str:
    """Body-caption casing: soft lowercase, then restore known brand spellings."""
    value = " ".join(str(text or "").split())
    if not value:
        return ""
    folded = value.casefold().replace("ё", "е")
    for pattern, replacement in CAPTION_BRAND_REPLACEMENTS:
        folded = pattern.sub(replacement, folded)
    return folded


def is_director_motion_copy(text: str) -> bool:
    """True when on-screen copy still reads like a director brief, not audience copy."""
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return False
    if DIRECTOR_COPY_RE.search(value):
        return True
    if len(value.split()) > MAX_MOTION_ON_SCREEN_WORDS:
        return True
    return False


def motion_on_screen_text(brief: str) -> str:
    """Audience punch only — never burn director notes or salvage quotes from them."""
    text = " ".join(str(brief or "").split())
    if not text:
        return ""
    text = OVERLAY_META_RE.sub("", text).strip(" .")
    split = re.split(r"(?i)\.\s*Зачем\s*:", text, maxsplit=1)
    text = split[0].strip(" .")
    text = WHY_LEAK_RE.split(text, maxsplit=1)[0].strip(" .")
    if not text:
        return ""
    # Director/animation copy must not become on-screen (no «0 ₽» salvage).
    if is_director_motion_copy(text):
        return ""
    if len(text.split()) > MAX_MOTION_ON_SCREEN_WORDS:
        return ""
    return text

def caption_font_size(
    height: int, *, font_ratio: float | None = None, style: dict[str, Any] | None = None
) -> int:
    caps = style_captions(style)
    ratio = float(font_ratio) if font_ratio is not None else float(caps["font_ratio"])
    ratio = max(0.02, min(float(caps["max_font_ratio"]), ratio))
    return max(int(caps["min_font_px"]), round(int(height) * ratio))


def resolve_caption_font_ratio(
    profile: dict[str, Any] | None, *, style: dict[str, Any] | None = None
) -> float:
    caps = style_captions(style)
    raw = (profile or {}).get("caption_font_ratio")
    if raw is None:
        return float(caps["font_ratio"])
    return max(0.02, min(float(caps["max_font_ratio"]), float(raw)))


def resolve_hook_title_font_ratio(
    profile: dict[str, Any] | None, *, style: dict[str, Any] | None = None
) -> float:
    """Hook must stay larger than body captions (Gate 2 / Style Bible)."""
    body = resolve_caption_font_ratio(profile, style=style)
    floor = float(style_hook(style)["font_ratio"])
    return max(floor, round(body * 1.25, 4))


def caption_margin_v(height: int) -> int:
    # Middle-center: small equal margins; chest feel comes from Alignment=5.
    return max(12, round(int(height) * 0.02))


def hex_to_ass_colour(hex_color: str) -> str:
    value = str(hex_color or "").strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"invalid caption color: {hex_color!r}")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return f"&H00{blue:02X}{green:02X}{red:02X}"


def phrase_chunks(
    text: str, *, max_words: int | None = None, style: dict[str, Any] | None = None
) -> list[str]:
    if max_words is None:
        max_words = int(style_captions(style)["max_words"])
    words = " ".join(str(text or "").split()).split(" ")
    if not words or words == [""]:
        return []
    limit = max(1, int(max_words))
    return [" ".join(words[index:index + limit]) for index in range(0, len(words), limit)]


def caption_wrap_width_chars(
    font_size: int, max_width_px: int | None, *, style: dict[str, Any] | None = None
) -> int:
    """Approx ASS line budget so wrapped phrases stay inside the torso envelope."""
    if max_width_px is None or max_width_px <= 0:
        return 28
    # Средняя ширина знака в долях кегля — своя у каждой гарнитуры (в стиле: advance_em).
    advance = max(8.0, float(font_size) * float(style_captions(style)["advance_em"]))
    return max(8, min(28, int(max_width_px / advance)))


def wrap_caption_lines(
    text: str, *, width_chars: int = 28, max_lines: int | None = None,
    style: dict[str, Any] | None = None,
) -> str:
    if max_lines is None:
        max_lines = int(style_captions(style)["max_lines"])
    protected = str(text or "")
    placeholders: dict[str, str] = {}
    for index, brand in enumerate(_CAPTION_ATOMIC_BRANDS):
        if brand in protected:
            key = f"⟦BRAND{index}⟧"
            placeholders[key] = brand
            protected = protected.replace(brand, key)
    words = " ".join(protected.split()).split(" ")
    if not words or words == [""]:
        return ""
    # Narrow torso envelopes need a third line more than an ellipsis / arm overhang.
    line_budget = max(int(max_lines), 3 if width_chars <= 16 else int(max_lines))
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if len(trial) <= width_chars:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= line_budget:
            break
    if current and len(lines) < line_budget:
        lines.append(current)
    elif current and lines:
        lines[-1] = f"{lines[-1]} {current}".strip()
    joined = "\\N".join(lines[:line_budget])
    for key, brand in placeholders.items():
        joined = joined.replace(key, brand)
    return joined


def caption_style_policy(
    *,
    width: int,
    height: int,
    font_size: int,
    alignment: int,
    margin_v: int,
    color: str | None = None,
    font_class: str | None = None,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Соответствие субтитра активному стилю. Требования берутся из стиля, не из кода."""
    caps = style_captions(style)
    reasons: list[str] = []
    max_px = max(int(caps["min_font_px"]), round(int(height) * float(caps["max_font_ratio"])))
    if font_size > max_px:
        reasons.append(f"caption font_size {font_size}px exceeds policy max {max_px}px")
    required_alignment = int(caps["alignment"])
    allowed_alignments = {required_alignment, 8}  # 8 = top-center with face \pos
    if alignment not in allowed_alignments:
        reasons.append(
            f"caption alignment must be {required_alignment} or face-pos top-center (8), got {alignment}"
        )
    if alignment == 2 and 2 not in allowed_alignments:
        reasons.append("bottom TikTok-bar captions are forbidden for this style")
    required_color = str(caps["color"])
    if color is not None and str(color).upper() != required_color.upper():
        reasons.append(f"caption color must be {required_color}, got {color!r}")
    required_class = str(caps["font_class"]).casefold()
    if font_class is not None and str(font_class).casefold() != required_class:
        reasons.append(f"caption font_class must be {required_class}, got {font_class!r}")
    _ = (width, margin_v)  # reserved for future safe-area checks
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "thresholds": {
            "style_id": str((style or {}).get("id", DEFAULT_STYLE_ID_FOR_REPORT)),
            "max_font_ratio": float(caps["max_font_ratio"]),
            "target_font_ratio": float(caps["font_ratio"]),
            "max_font_px": max_px,
            "alignment": required_alignment,
            "color": required_color,
            "font_class": required_class,
            "frame": {"width": width, "height": height},
        },
    }


def motion_brief_policy(briefs: list[str]) -> dict[str, Any]:
    reasons: list[str] = []
    for index, brief in enumerate(briefs):
        value = str(brief or "")
        if AGENT_NOTE_RE.search(value):
            reasons.append(f"motion brief[{index}] leaks producer notes onto screen contract")
        if WHY_LEAK_RE.search(value):
            reasons.append(f"motion brief[{index}] contains Зачем: (forbidden on-screen)")
        if is_director_motion_copy(value):
            reasons.append(
                f"motion brief[{index}] is director/animation copy, not audience punch "
                f"(max {MAX_MOTION_ON_SCREEN_WORDS} words, no stage directions)"
            )
    return {"verdict": "FAIL" if reasons else "PASS", "reasons": reasons}


def motion_compose_policy(motion_mode: str | None, *, motion_count: int) -> dict[str, Any]:
    reasons: list[str] = []
    if motion_count > 0 and motion_mode != MOTION_MODE_OVERLAY:
        reasons.append(
            f"motion_mode must be '{MOTION_MODE_OVERLAY}' when motion scenes exist; "
            f"got {motion_mode!r} (replace-talking-head is forbidden)"
        )
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "expected_mode": MOTION_MODE_OVERLAY,
        "actual_mode": motion_mode,
        "motion_count": motion_count,
    }


def hook_title_policy(contract: dict[str, Any], *, style: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hook must be larger / lower than body captions — MeVGa cold-open, not mid-face ribbon."""
    hook_style = style_hook(style)
    hook_ratio = float(hook_style["font_ratio"])
    hook_min_top = float(hook_style["min_top_ratio"])
    expected = [str(item) for item in (contract.get("style_recipes_expected") or [])]
    reasons: list[str] = []
    if "hook_title" not in expected:
        return {"verdict": "PASS", "reasons": [], "applicable": False}
    hook_fs = contract.get("hook_title_font_size")
    body_fs = contract.get("caption_font_size")
    if hook_fs is None:
        reasons.append("hook_title proposed but hook_title_font_size missing on render-contract")
    elif body_fs is not None and int(hook_fs) <= int(body_fs):
        reasons.append(
            f"hook_title font_size {hook_fs}px must exceed body caption font_size {body_fs}px "
            f"(MeVGa hook is larger italic title, not phrase captions)"
        )
    height = int(contract.get("height") or 0)
    if hook_fs is not None and height > 0:
        ratio = int(hook_fs) / height
        if ratio + 1e-9 < hook_ratio * 0.85:
            reasons.append(
                f"hook_title font_ratio {ratio:.3f} below style target ~{hook_ratio:.3f}"
            )
    y_center = contract.get("hook_title_y_center_ratio")
    if y_center is not None and float(y_center) < hook_min_top:
        reasons.append(
            f"hook_title y_center_ratio {float(y_center):.3f} too high "
            f"(covers upper face; min ~{hook_min_top})"
        )
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "applicable": True,
        "thresholds": {
            "hook_font_ratio": hook_ratio,
            "min_y_center_ratio": hook_min_top,
        },
    }


def evaluate_render_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Blocking Gate 2 check from render-contract.json written by the compositor."""
    if not isinstance(contract, dict):
        return {"verdict": "FAIL", "reasons": ["missing render-contract.json"], "components": {}}
    # Контракт называет свой стиль; без имени действует дефолт — старые проекты не ломаются.
    style = load_style(style_id_from(contract))
    caption = caption_style_policy(
        width=int(contract.get("width", 0)),
        height=int(contract.get("height", 0)),
        font_size=int(contract.get("caption_font_size", 10**9)),
        alignment=int(contract.get("caption_alignment", -1)),
        margin_v=int(contract.get("caption_margin_v", 0)),
        color=str(contract.get("caption_color") or ""),
        font_class=str(contract.get("caption_font_class") or ""),
        style=style,
    )
    on_screen = [str(item) for item in contract.get("motion_on_screen_texts", [])]
    brief_check = motion_brief_policy(on_screen)
    compose = motion_compose_policy(
        contract.get("motion_mode"),
        motion_count=int(contract.get("motion_count", 0)),
    )
    style_check = style_recipes_policy(
        expected_recipes=list(contract.get("style_recipes_expected") or []),
        applied_recipes=list(contract.get("style_recipes_applied") or []),
    )
    hook_check = hook_title_policy(contract, style=style)
    components = {
        "caption_style": caption,
        "motion_brief": brief_check,
        "motion_compose": compose,
        "style_recipes": style_check,
        "hook_title": hook_check,
    }
    reasons = [reason for component in components.values() for reason in component.get("reasons", [])]
    return {
        "schema_version": 3,
        "kind": "visual-render-policy",
        "style_id": str(style.get("id")),
        "verdict": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "components": components,
    }
