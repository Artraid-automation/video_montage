from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.media import duration_s, probe
from pipeline.factory.motion import classify_motion, render_motion_overlay, _extract_audience_punch
from pipeline.factory.transcript import (
    TranscriptEntry,
    VisualEntry,
    resolve_visual_end,
    resolve_visual_start,
)


class MotionTemplateTests(unittest.TestCase):
    def test_tanya_briefs_map_to_templates(self) -> None:
        cases = {
            "(поверх речи) Индикатор счёта ползёт к «0 ₽»": "meter_drop",
            "Иконки паники поверх речи: горящая голова": "panic_sequence",
            "60 000 → вырезается 6 000 (10%)": "formula_split",
            "Два банка: перевод в «чужой» с трением": "bank_friction",
            "12 месяцев: плитки 6к складываются": "stack_growth",
            "Весы: мечта vs хотелки": "scales_tilt",
            "Сдвиг приоритетов + акцент CTA «схема»": "priority_shift",
        }
        for brief, template in cases.items():
            self.assertEqual(classify_motion(brief).template, template, brief)

    def test_formula_label_is_audience_safe(self) -> None:
        spec = classify_motion("60 000 → вырезается 6 000 (10%), остаток тускнеет")
        self.assertEqual(spec.template, "formula_split")
        self.assertIn("→", spec.label)
        self.assertNotIn("Зачем", spec.label)

    def test_motion_window_within_keep(self) -> None:
        entry = TranscriptEntry("u1", "keep", 10.0, 20.0, "text", ())
        visual = VisualEntry("1a", "u1", "motion", "brief", start_s=12.0, end_s=15.0)
        self.assertEqual(resolve_visual_start([entry], visual), 12.0)
        self.assertEqual(resolve_visual_end([entry], visual), 15.0)

    def test_meter_drop_has_label(self) -> None:
        spec = classify_motion("Индикатор счёта ползёт к «0 ₽» / пустой кошелёк")
        self.assertEqual(spec.template, "meter_drop")
        self.assertTrue(spec.label, "meter_drop must have a non-empty audience label")
        self.assertIn("0 ₽", spec.label)

    def test_panic_has_label(self) -> None:
        spec = classify_motion("Иконки паники: горящая голова → искать → тушение")
        self.assertEqual(spec.template, "panic_sequence")
        self.assertTrue(spec.label, "panic_sequence must have a non-empty label")

    def test_suppress_captions_default_true(self) -> None:
        spec = classify_motion("60 000 → 6 000")
        self.assertTrue(spec.suppress_captions)

    def test_extract_audience_punch_quoted(self) -> None:
        punch = _extract_audience_punch("Индикатор ползёт к «0 ₽» / пустой кошелёк")
        self.assertIn("0 ₽", punch)

    def test_extract_ignores_zachem_quotes(self) -> None:
        punch = _extract_audience_punch(
            "Иконки паники: горящая голова. Зачем: оверлей кроет всю «экстренную» клаузу"
        )
        self.assertNotIn("экстренную", punch)

    def test_meter_drop_label_from_what_only(self) -> None:
        spec = classify_motion(
            "Индикатор счёта ползёт к «0 ₽» / пустой кошелёк. Зачем: Боль «на нуле» должна читаться"
        )
        self.assertEqual(spec.template, "meter_drop")
        self.assertEqual(spec.label, "0 ₽")
        self.assertNotIn("на нуле", spec.label)

    def test_extract_audience_punch_formula(self) -> None:
        punch = _extract_audience_punch("60 000 → 6 000 (10%)")
        self.assertIn("→", punch)

    def test_bank_friction_label(self) -> None:
        spec = classify_motion("Два банка: перевод в «чужой» с трением (замок)")
        self.assertEqual(spec.template, "bank_friction")
        self.assertIn("чужой", spec.label)

    def test_stack_growth_readable_label(self) -> None:
        spec = classify_motion("12 месяцев: плитки 6к складываются в стопку")
        self.assertEqual(spec.template, "stack_growth")
        self.assertIn("12", spec.label)
        self.assertIn("6 000", spec.label)


class MotionRenderTests(unittest.TestCase):
    def test_render_produces_short_rgba_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "motion.mov"
            _path, spec = render_motion_overlay(
                output,
                brief="60 000 → 6 000",
                duration_s=2.5,
                width=320,
                height=180,
                fps=25,
            )
            self.assertIn(spec.template, {"formula_split", "text_punch"})
            self.assertTrue(output.is_file())
            self.assertGreater(duration_s(probe(output)), 2.0)

    def test_render_meter_drop_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "meter.mov"
            _path, spec = render_motion_overlay(
                output,
                brief="Индикатор счёта ползёт к «0 ₽»",
                duration_s=3.0,
                width=360,
                height=640,
                fps=25,
            )
            self.assertEqual(spec.template, "meter_drop")
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
