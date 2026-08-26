"""Стиль — данные, а не код: один и тот же кадр судится по-разному разными стилями."""

from __future__ import annotations

import unittest

from pipeline.factory.style_profile import DEFAULT_STYLE_ID, captions, load_style, section, style_id_from
from pipeline.factory.visual_policy import (
    caption_font_size,
    caption_style_policy,
    evaluate_render_contract,
    phrase_chunks,
)

MEASURED = "strokov-measured-v1"


def _contract(style_id: str | None, **overrides):
    contract = {
        "width": 1080, "height": 1920,
        "caption_font_size": 79,
        "caption_alignment": 5,
        "caption_margin_v": 38,
        "caption_color": "#FFFFFF",
        "caption_font_class": "sans",
        "motion_on_screen_texts": [],
        "motion_mode": "overlay",
        "motion_count": 0,
        "style_recipes_expected": [],
        "style_recipes_applied": [],
    }
    if style_id:
        contract["style_id"] = style_id
    contract.update(overrides)
    return contract


class StyleAsDataTests(unittest.TestCase):
    def test_measured_style_is_loadable_and_differs_from_default(self) -> None:
        default = captions(load_style())
        measured = captions(load_style(MEASURED))
        self.assertEqual(default["color"], "#E1C445")
        self.assertEqual(measured["color"], "#FFFFFF")
        self.assertEqual(measured["font_family"], "Rubik")
        self.assertEqual(measured["max_words"], 1)

    def test_unknown_style_falls_back_to_default(self) -> None:
        self.assertEqual(load_style("no-such-style")["id"], DEFAULT_STYLE_ID)
        self.assertEqual(style_id_from({}), DEFAULT_STYLE_ID)
        self.assertEqual(style_id_from({"style_version": MEASURED}), MEASURED)

    def test_white_sans_captions_pass_under_measured_style(self) -> None:
        report = evaluate_render_contract(_contract(MEASURED))
        self.assertEqual(report["verdict"], "PASS", report["reasons"])
        self.assertEqual(report["style_id"], MEASURED)

    def test_same_captions_fail_under_the_old_gold_serif_style(self) -> None:
        """Именно это раньше делало наш стиль недостижимым: политика знала только золотой serif."""
        report = evaluate_render_contract(_contract(None))
        self.assertEqual(report["verdict"], "FAIL")
        joined = " ".join(report["reasons"])
        self.assertIn("#E1C445", joined)
        self.assertIn("serif", joined)

    def test_font_size_follows_the_style_ratio(self) -> None:
        measured = load_style(MEASURED)
        # 0.0411 * 1920 = 79 px — кегль, при котором строчная буква выходит 41 px (замер референса)
        self.assertEqual(caption_font_size(1920, style=measured), 79)
        self.assertEqual(caption_font_size(1920), 86)  # дефолтный стиль: 0.045

    def test_word_by_word_captions_come_from_the_style(self) -> None:
        measured = load_style(MEASURED)
        self.assertEqual(phrase_chunks("дешёвые дроны нас победят", style=measured),
                         ["дешёвые", "дроны", "нас", "победят"])
        self.assertEqual(phrase_chunks("дешёвые дроны нас победят"),
                         ["дешёвые дроны нас победят"])

    def test_measured_style_carries_rhythm_and_camera_numbers(self) -> None:
        measured = load_style(MEASURED)
        self.assertAlmostEqual(section(measured, "rhythm")["pause_cut_threshold_s"], 0.15)
        self.assertAlmostEqual(section(measured, "camera")["zoom_rate_pct_per_s"], 2.5)
        self.assertAlmostEqual(section(measured, "audio")["target_lra"], 1.5)


if __name__ == "__main__":
    unittest.main()
