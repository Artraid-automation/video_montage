"""Fail-closed wiring for MeVGa style recipes (hook_title / framework_list).

Author catch (Slava): style-scenes.json existed, visual-plan dropped style_scenes,
render burned body captions only. These guards make that path impossible to green-light.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json


# Recipes that must be burned by the compositor (not default body captions).
RENDERABLE_STYLE_RECIPES = frozenset({"hook_title", "framework_list"})


def collect_expected_recipes(style_scenes: list[Any] | None) -> list[str]:
    """Unique renderable recipe ids from style_scenes, stable order."""
    found: list[str] = []
    seen: set[str] = set()
    for item in style_scenes or []:
        if not isinstance(item, dict):
            continue
        recipe = str(item.get("recipe") or "").strip()
        if recipe not in RENDERABLE_STYLE_RECIPES:
            continue
        if recipe in seen:
            continue
        seen.add(recipe)
        found.append(recipe)
    return found


def load_sidecar_style_scenes(segment_root: Path) -> list[dict[str, Any]]:
    """Prefer style-scenes.json; fall back to llm-visual.json style_scenes."""
    style_path = segment_root / "style-scenes.json"
    if style_path.is_file():
        payload = read_json(style_path)
        scenes = payload.get("scenes") if isinstance(payload, dict) else None
        if isinstance(scenes, list) and scenes:
            return [item for item in scenes if isinstance(item, dict)]
    llm_path = segment_root / "llm-visual.json"
    if llm_path.is_file():
        payload = read_json(llm_path)
        scenes = payload.get("style_scenes") if isinstance(payload, dict) else None
        if isinstance(scenes, list) and scenes:
            return [item for item in scenes if isinstance(item, dict)]
    return []


def reconcile_style_scenes(
    visual_plan: dict[str, Any],
    *,
    segment_root: Path | None = None,
    style_scenes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ensure visual_plan carries style_scenes from explicit list or sidecars."""
    plan = dict(visual_plan)
    scenes = style_scenes
    if scenes is None and segment_root is not None:
        existing = plan.get("style_scenes")
        if isinstance(existing, list) and existing:
            scenes = [item for item in existing if isinstance(item, dict)]
        else:
            scenes = load_sidecar_style_scenes(segment_root)
    if scenes:
        plan["style_scenes"] = list(scenes)
        if not plan.get("scenes"):
            plan["status"] = "STYLE_SCENES_ONLY"
    return plan


def validate_visual_plan_style_wiring(segment_root: Path) -> list[str]:
    """Return blocking reasons if sidecars propose styles that visual-plan dropped."""
    reasons: list[str] = []
    plan_path = segment_root / "visual-plan.json"
    if not plan_path.is_file():
        return reasons
    plan = read_json(plan_path)
    sidecar = load_sidecar_style_scenes(segment_root)
    expected = collect_expected_recipes(sidecar)
    if not expected:
        return reasons
    plan_scenes = plan.get("style_scenes") if isinstance(plan, dict) else None
    if not isinstance(plan_scenes, list) or not plan_scenes:
        reasons.append(
            "visual-plan.json missing style_scenes while style-scenes.json/llm-visual "
            f"proposes {expected}"
        )
        return reasons
    planned = collect_expected_recipes(plan_scenes)
    missing = [recipe for recipe in expected if recipe not in planned]
    if missing:
        reasons.append(
            f"visual-plan style_scenes missing recipes {missing} "
            f"(sidecar expected {expected}, plan has {planned})"
        )
    return reasons


def style_recipes_policy(
    *,
    expected_recipes: list[str] | None,
    applied_recipes: list[str] | None,
) -> dict[str, Any]:
    """Gate 2: proposed renderable recipes must appear on the render contract."""
    want = sorted({
        str(item) for item in (expected_recipes or [])
        if str(item) in RENDERABLE_STYLE_RECIPES
    })
    got = sorted({
        str(item) for item in (applied_recipes or [])
        if str(item) in RENDERABLE_STYLE_RECIPES
    })
    reasons: list[str] = []
    missing = [recipe for recipe in want if recipe not in got]
    if missing:
        reasons.append(
            f"style recipes proposed but not burned into render: missing={missing}, "
            f"expected={want}, applied={got}"
        )
    return {
        "verdict": "FAIL" if reasons else "PASS",
        "reasons": reasons,
        "expected": want,
        "applied": got,
    }
