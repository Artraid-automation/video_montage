"""Стиль как данные: значения вида берутся из presets/styles/<id>/style.json.

До этого модуля конкретный вид (золотой serif, шесть слов в строке) жил константами
в visual_policy и проверялся как политика — сменить стиль означало править код.
Здесь стиль загружается по идентификатору, а код остаётся механикой.

Отсутствующий или неизвестный стиль откатывается к `DEFAULT_STYLE_ID`, поэтому
старые проекты и контракты без поля `style_id` ведут себя ровно как раньше.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json

DEFAULT_STYLE_ID = "dankoe-mevga-v1"

# Последний рубеж: если файла стиля нет на диске вовсе, механика всё равно обязана
# работать. Значения совпадают с dankoe-mevga-v1/style.json.
_FALLBACK: dict[str, Any] = {
    "id": DEFAULT_STYLE_ID,
    "captions": {
        "font_family": "Times New Roman", "font_class": "serif", "color": "#E1C445",
        "font_ratio": 0.045, "max_font_ratio": 0.18, "min_font_px": 16,
        "alignment": 5, "max_words": 6, "max_lines": 2, "case": "soft-lower",
        "gap_below_chin_ratio": 0.15, "hold_s": None, "appear": "none", "advance_em": 0.48,
    },
    "hook": {"font_ratio": 0.072, "min_top_ratio": 0.48, "y_center_ratio": 0.64, "color": "#EAC225"},
}

_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def styles_root(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / "presets" / "styles"


def load_style(style_id: str | None = None, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Стиль по идентификатору. Неизвестный или битый — молча откатывается к дефолту."""
    wanted = str(style_id or DEFAULT_STYLE_ID)
    root = styles_root(repo_root)
    key = (wanted, str(root))
    if key in _CACHE:
        return _CACHE[key]
    style: dict[str, Any] | None = None
    path = root / wanted / "style.json"
    if path.is_file():
        try:
            data = read_json(path)
            if isinstance(data, dict) and data.get("id") == wanted:
                style = data
        except Exception:
            style = None
    if style is None and wanted != DEFAULT_STYLE_ID:
        style = load_style(DEFAULT_STYLE_ID, repo_root=repo_root)
    if style is None:
        style = _FALLBACK
    _CACHE[key] = style
    return style


def style_value(style: dict[str, Any] | None, section: str, key: str, default: Any = None) -> Any:
    """Значение из секции стиля; None в файле считается «не задано»."""
    if isinstance(style, dict):
        block = style.get(section)
        if isinstance(block, dict) and block.get(key) is not None:
            return block[key]
    fallback = _FALLBACK.get(section)
    if isinstance(fallback, dict) and fallback.get(key) is not None and default is None:
        return fallback[key]
    return default


def style_id_from(source: dict[str, Any] | None) -> str:
    """Идентификатор стиля из контракта или конфига проекта (`style_id` / `style_version`)."""
    if not isinstance(source, dict):
        return DEFAULT_STYLE_ID
    for key in ("style_id", "style_version"):
        value = source.get(key)
        if value:
            return str(value)
    return DEFAULT_STYLE_ID


def captions(style: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(_FALLBACK["captions"])
    if isinstance(style, dict) and isinstance(style.get("captions"), dict):
        merged.update({k: v for k, v in style["captions"].items() if v is not None})
    return merged


def hook(style: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(_FALLBACK["hook"])
    if isinstance(style, dict) and isinstance(style.get("hook"), dict):
        merged.update({k: v for k, v in style["hook"].items() if v is not None})
    return merged


def section(style: dict[str, Any] | None, name: str) -> dict[str, Any]:
    """Необязательная секция (framing / rhythm / camera / audio) — пустая, если её нет."""
    if isinstance(style, dict) and isinstance(style.get(name), dict):
        return dict(style[name])
    return {}
