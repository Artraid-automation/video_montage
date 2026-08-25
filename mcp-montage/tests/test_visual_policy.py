from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.phase1 import run_phase1
from pipeline.factory.phase2 import run_phase2
from pipeline.factory.qc import combined_qc
from pipeline.factory.state import StateStore
from pipeline.factory.visual_policy import (
    CAPTION_REQUIRED_ALIGNMENT,
    CAPTION_REQUIRED_COLOR,
    CAPTION_REQUIRED_FONT_CLASS,
    caption_display_text,
    caption_font_size,
    evaluate_render_contract,
    motion_on_screen_text,
    phrase_chunks,
    wrap_caption_lines,
)
from tests.fakes import RenderedTranscriptFake
from tests.helpers import make_project, make_video


class VisualPolicyUnitTests(unittest.TestCase):
    def test_caption_display_restores_brand_names(self) -> None:
        self.assertIn("PRO Женщин", caption_display_text("я пришла про женщины и это"))
        self.assertIn("PRO Женщин", caption_display_text("пришла PRO Женщин и"))
        self.assertIn("X10 Движение", caption_display_text("в мою жизнь экзесидвижение, чему"))
        self.assertIn("X10 Движение", caption_display_text("X10 Движение силы"))
        self.assertEqual(wrap_caption_lines("пришла PRO Женщин", width_chars=8), "пришла\\NPRO Женщин")

    def test_motion_on_screen_strips_why(self) -> None:
        text = motion_on_screen_text("60 000 → 6 000. Зачем: формула на экране пока звучит цифра.")
        self.assertEqual(text, "60 000 → 6 000")
        self.assertNotIn("Зачем", text)

    def test_director_brief_becomes_audience_punch_or_empty(self) -> None:
        # Full animation directions must never burn onto the frame (no quote salvage).
        self.assertEqual(
            motion_on_screen_text(
                "(поверх речи ~3.2с) Индикатор счёта ползёт к «0 ₽» / пустой кошелёк. Зачем: боль"
            ),
            "",
        )
        self.assertEqual(
            motion_on_screen_text(
                "Иконки паники поверх речи: горящая голова → искать/занять → тушение. Зачем: x"
            ),
            "",
        )
        self.assertEqual(motion_on_screen_text("60 000 → 6 000. Зачем: формула"), "60 000 → 6 000")

    def test_director_copy_fails_policy(self) -> None:
        contract = {
            "width": 720,
            "height": 1280,
            "caption_font_size": caption_font_size(1280),
            "caption_alignment": CAPTION_REQUIRED_ALIGNMENT,
            "caption_margin_v": 24,
            "caption_color": CAPTION_REQUIRED_COLOR,
            "caption_font_class": CAPTION_REQUIRED_FONT_CLASS,
            "motion_mode": "overlay",
            "motion_count": 1,
            "motion_on_screen_texts": ["Индикатор счёта ползёт к «0 ₽» / пустой кошелёк"],
            "motion_raw_briefs": ["…"],
        }
        report = evaluate_render_contract(contract)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(any("director" in reason or "audience" in reason for reason in report["reasons"]))

    def test_phrase_chunks_max_six_words(self) -> None:
        chunks = phrase_chunks("one two three four five six seven eight")
        self.assertEqual(chunks, ["one two three four five six", "seven eight"])

    def test_replace_mode_fails_when_motions_exist(self) -> None:
        contract = {
            "width": 720,
            "height": 1280,
            "caption_font_size": caption_font_size(1280),
            "caption_alignment": CAPTION_REQUIRED_ALIGNMENT,
            "caption_margin_v": 24,
            "caption_color": CAPTION_REQUIRED_COLOR,
            "caption_font_class": CAPTION_REQUIRED_FONT_CLASS,
            "motion_mode": "replace",
            "motion_count": 1,
            "motion_on_screen_texts": ["60 000 → 6 000"],
            "motion_raw_briefs": ["60 000 → 6 000. Зачем: audit only"],
        }
        report = evaluate_render_contract(contract)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(any("overlay" in reason for reason in report["reasons"]))

    def test_raw_why_allowed_when_on_screen_clean(self) -> None:
        contract = {
            "width": 720,
            "height": 1280,
            "caption_font_size": caption_font_size(1280),
            "caption_alignment": CAPTION_REQUIRED_ALIGNMENT,
            "caption_margin_v": 24,
            "caption_color": CAPTION_REQUIRED_COLOR,
            "caption_font_class": CAPTION_REQUIRED_FONT_CLASS,
            "motion_mode": "overlay",
            "motion_count": 1,
            "motion_on_screen_texts": ["60 000 → 6 000"],
            "motion_raw_briefs": ["60 000 → 6 000. Зачем: audit only"],
        }
        self.assertEqual(evaluate_render_contract(contract)["verdict"], "PASS")

    def test_bottom_bar_captions_fail(self) -> None:
        contract = {
            "width": 720,
            "height": 1280,
            "caption_font_size": caption_font_size(1280),
            "caption_alignment": 2,
            "caption_margin_v": 64,
            "caption_color": CAPTION_REQUIRED_COLOR,
            "caption_font_class": CAPTION_REQUIRED_FONT_CLASS,
            "motion_mode": None,
            "motion_count": 0,
            "motion_on_screen_texts": [],
        }
        report = evaluate_render_contract(contract)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(any("mid-center" in reason or "bottom" in reason for reason in report["reasons"]))

    def test_giant_caption_fails(self) -> None:
        contract = {
            "width": 720,
            "height": 1280,
            "caption_font_size": 250,
            "caption_alignment": CAPTION_REQUIRED_ALIGNMENT,
            "caption_margin_v": 24,
            "caption_color": CAPTION_REQUIRED_COLOR,
            "caption_font_class": CAPTION_REQUIRED_FONT_CLASS,
            "motion_mode": None,
            "motion_count": 0,
            "motion_on_screen_texts": [],
        }
        report = evaluate_render_contract(contract)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(any("font_size" in reason for reason in report["reasons"]))

    def test_missing_contract_fails_closed(self) -> None:
        report = evaluate_render_contract(None)  # type: ignore[arg-type]
        self.assertEqual(report["verdict"], "FAIL")


class CombinedQcVisualPolicyTests(unittest.TestCase):
    def test_require_policy_without_contract_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = make_video(root / "clip.mp4", duration=1.0)
            qc = combined_qc(
                root,
                media,
                root / "probes",
                expected_duration_s=1.0,
                width=320,
                height=180,
                fps=25,
                pip_enabled=False,
                require_visual_render_policy=True,
                render_contract=None,
            )
            self.assertEqual(qc["verdict"], "FAIL")
            self.assertEqual(qc["visual_render_policy"]["verdict"], "FAIL")


class Phase2VisualContractTests(unittest.TestCase):
    def test_phase2_writes_overlay_contract_and_policy_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "Synthetic",
                "style_version": "test-v1", "default_grade": "neutral",
                "transcription": {"provider": "sidecar"},
                "verification_transcription": {"provider": "synthetic"},
                "render_profile": {"width": 720, "height": 1280, "fps": 25, "crf": 25, "preset": "ultrafast"},
                "visuals": {"01": [{
                    "anchor": "u2",
                    "type": "motion",
                    "brief": "Card what. Зачем: must never burn into pixels.",
                }]},
            })
            source = make_video(project / "01_raw" / "01_camera.mp4", duration=2.2, with_face=True)
            atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
                "language": "en", "duration_s": 2.2,
                "segments": [
                    {"id": "u1", "start": 0.1, "end": 0.6, "text": "discard", "decision": "cut", "reason": "false-start"},
                    {"id": "u2", "start": 0.8, "end": 1.9, "text": "keep this final useful sentence", "decision": "keep"},
                ],
            })
            store = StateStore(project)
            run_phase1(project, store)
            store.approve("gate1", reviewer="test-owner")
            run_phase2(project, store, verification_transcriber=RenderedTranscriptFake())
            contract = read_json(project / "04_phase2" / "segments" / "01" / "render-contract.json")
            self.assertEqual(contract["motion_mode"], "overlay")
            self.assertEqual(contract["motion_count"], 1)
            self.assertIn(contract["caption_alignment"], {CAPTION_REQUIRED_ALIGNMENT, 8})
            self.assertEqual(contract["caption_color"], CAPTION_REQUIRED_COLOR)
            self.assertEqual(contract["caption_font_class"], CAPTION_REQUIRED_FONT_CLASS)
            self.assertEqual(contract.get("caption_placement"), "face-chest")
            self.assertIsNotNone(contract.get("caption_pos_y"))
            self.assertTrue((project / "04_phase2" / "segments" / "01" / "framing-plan.json").is_file())
            self.assertTrue(all("Зачем" not in text for text in contract["motion_on_screen_texts"]))
            qc = read_json(project / "04_phase2" / "segments" / "01" / "qc.json")
            self.assertEqual(qc["verdict"], "PASS")
            self.assertEqual(qc["visual_render_policy"]["verdict"], "PASS")
            self.assertEqual(qc["schema_version"], 4)
            audit = qc["visual_audit"]
            self.assertEqual(audit["verdict"], "PASS")
            self.assertGreaterEqual(len(audit["random_frames"]), 3)
            self.assertGreaterEqual(len(audit["motion_checks"]), 1)
            self.assertTrue((project / "04_phase2" / "segments" / "01" / "probes" / "gate2-audit" / "manifest.json").is_file())
            review = (project / "04_phase2" / "review.md").read_text(encoding="utf-8")
            self.assertIn("Random frame probes", review)
            self.assertIn("Per-MOTION checks", review)


if __name__ == "__main__":
    unittest.main()
