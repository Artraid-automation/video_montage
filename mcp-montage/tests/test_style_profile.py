"""Стиль — данные, а не код: один и тот же кадр судится по-разному разными стилями."""

from __future__ import annotations

import json
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
        self.assertEqual(measured["font_family"], "Rubik ExtraBold")
        self.assertTrue(str(measured["font_file"]).endswith("Rubik-ExtraBold.ttf"))
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


class StyleReachesTheRenderTests(unittest.TestCase):
    """Стиль обязан доехать от project.json до самого ASS.

    Регресс, который это ловит: `render_segment` собирал профиль рендера из
    `config["render_profile"]` и не клал туда имя стиля. Проект был создан под
    измеренным стилем, а субтитры молча рисовались дефолтным золотым serif —
    ошибка видна только в готовом файле.
    """

    def _run(self, style_version: str):
        import tempfile
        from pathlib import Path

        from pipeline.factory.io import atomic_write_json
        from pipeline.factory.phase1 import run_phase1
        from pipeline.factory.phase2 import run_phase2
        from pipeline.factory.state import StateStore
        from tests.helpers import make_video
        from tests.test_phase2_self_verify import RenderedTranscriptFake

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        project = Path(temp.name) / "styled"
        for directory in ("01_raw", "02_inputs", "03_phase1", "04_phase2", "05_final", "06_state"):
            (project / directory).mkdir(parents=True, exist_ok=True)
        atomic_write_json(project / "project.json", {
            "schema_version": 2, "id": "styled", "title": "styled",
            "style_version": style_version, "default_grade": "neutral",
            "transcription": {"provider": "sidecar"},
            "verification_transcription": {"provider": "synthetic"},
            "render_profile": {"width": 320, "height": 180, "fps": 25, "crf": 25, "preset": "ultrafast"},
        })
        source = make_video(project / "01_raw" / "01_camera.mp4", duration=2.2, with_face=True)
        atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
            "language": "ru", "duration_s": 2.2,
            "segments": [{"id": "u1", "start": 0.2, "end": 1.9,
                          "text": "дешёвые дроны нас победят", "decision": "keep"}],
        })
        store = StateStore(project)
        run_phase1(project, store)
        store.approve("gate1", reviewer="test-owner")
        run_phase2(project, store, verification_transcriber=RenderedTranscriptFake())
        contract = json.loads(
            (project / "04_phase2" / "segments" / "01" / "render-contract.json").read_text(encoding="utf-8")
        )
        return contract

    def test_measured_style_reaches_the_render_contract(self) -> None:
        contract = self._run(MEASURED)
        self.assertEqual(contract["style_id"], MEASURED)
        self.assertEqual(contract["caption_color"], "#FFFFFF")
        self.assertEqual(contract["caption_font_class"], "sans")

    def test_default_style_still_renders_gold_serif(self) -> None:
        contract = self._run("dankoe-mevga-v1")
        self.assertEqual(contract["style_id"], "dankoe-mevga-v1")
        self.assertEqual(contract["caption_color"], "#E1C445")
        self.assertEqual(contract["caption_font_class"], "serif")
