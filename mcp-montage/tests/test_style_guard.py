from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json
from pipeline.factory.style_guard import (
    collect_expected_recipes,
    reconcile_style_scenes,
    style_recipes_policy,
    validate_visual_plan_style_wiring,
)
from pipeline.factory.visual_policy import (
    CAPTION_REQUIRED_ALIGNMENT,
    CAPTION_REQUIRED_COLOR,
    CAPTION_REQUIRED_FONT_CLASS,
    caption_font_size,
    evaluate_render_contract,
)


def _ok_contract(**extra: object) -> dict:
    base = {
        "width": 720,
        "height": 1280,
        "caption_font_size": caption_font_size(1280),
        "caption_alignment": CAPTION_REQUIRED_ALIGNMENT,
        "caption_margin_v": 24,
        "caption_color": CAPTION_REQUIRED_COLOR,
        "caption_font_class": CAPTION_REQUIRED_FONT_CLASS,
        "motion_mode": None,
        "motion_count": 0,
        "motion_on_screen_texts": [],
        "style_recipes_expected": [],
        "style_recipes_applied": [],
    }
    base.update(extra)
    return base


class StyleGuardTests(unittest.TestCase):
    def test_collect_expected_skips_body_captions(self) -> None:
        recipes = collect_expected_recipes([
            {"recipe": "hook_title"},
            {"recipe": "captions_body"},
            {"recipe": "framework_list"},
            {"recipe": "framework_list"},
        ])
        self.assertEqual(recipes, ["hook_title", "framework_list"])

    def test_validate_fails_when_plan_drops_sidecar_scenes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            atomic_write_json(root / "style-scenes.json", {
                "scenes": [
                    {"id": "s1", "recipe": "framework_list", "anchor": "u0017", "lines": ["a", "b", "c"]},
                ],
            })
            atomic_write_json(root / "visual-plan.json", {
                "schema_version": 1,
                "kind": "visual-plan",
                "scenes": [],
                "status": "NO_VISUALS_PROPOSED",
            })
            reasons = validate_visual_plan_style_wiring(root)
            self.assertTrue(reasons)
            self.assertIn("missing style_scenes", reasons[0])

    def test_reconcile_pulls_sidecar_into_empty_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = [
                {"id": "s1", "recipe": "hook_title", "anchor": "u0016", "title": "Hi"},
            ]
            atomic_write_json(root / "style-scenes.json", {"scenes": scenes})
            plan = reconcile_style_scenes(
                {"schema_version": 1, "kind": "visual-plan", "scenes": [], "status": "NO_VISUALS_PROPOSED"},
                segment_root=root,
            )
            self.assertEqual(plan["style_scenes"], scenes)
            self.assertEqual(plan["status"], "STYLE_SCENES_ONLY")

    def test_gate2_fails_when_expected_recipes_not_applied(self) -> None:
        report = evaluate_render_contract(_ok_contract(
            style_recipes_expected=["hook_title", "framework_list"],
            style_recipes_applied=["hook_title"],
        ))
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(any("not burned" in reason for reason in report["reasons"]))
        style = report["components"]["style_recipes"]
        self.assertEqual(style["expected"], ["framework_list", "hook_title"])
        self.assertEqual(style["applied"], ["hook_title"])
        self.assertNotIn("framework_list", style["applied"])

    def test_gate2_passes_when_recipes_match(self) -> None:
        report = evaluate_render_contract(_ok_contract(
            style_recipes_expected=["framework_list", "hook_title"],
            style_recipes_applied=["hook_title", "framework_list"],
            hook_title_font_size=92,
            caption_font_size=58,
            hook_title_y_center_ratio=0.64,
            height=1280,
        ))
        self.assertEqual(report["verdict"], "PASS")

    def test_hook_title_smaller_than_body_fails(self) -> None:
        report = evaluate_render_contract(_ok_contract(
            style_recipes_expected=["hook_title"],
            style_recipes_applied=["hook_title"],
            hook_title_font_size=40,
            caption_font_size=58,
            hook_title_y_center_ratio=0.64,
            height=1280,
        ))
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(any("hook_title font_size" in r for r in report["reasons"]))

    def test_hook_title_too_high_fails(self) -> None:
        report = evaluate_render_contract(_ok_contract(
            style_recipes_expected=["hook_title"],
            style_recipes_applied=["hook_title"],
            hook_title_font_size=92,
            caption_font_size=58,
            hook_title_y_center_ratio=0.35,
            height=1280,
        ))
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(any("y_center_ratio" in r for r in report["reasons"]))

    def test_style_recipes_policy_unit(self) -> None:
        result = style_recipes_policy(
            expected_recipes=["framework_list"],
            applied_recipes=[],
        )
        self.assertEqual(result["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
