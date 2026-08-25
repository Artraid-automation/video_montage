from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json
from pipeline.factory.llm_visual import run_llm_visual
from pipeline.factory.transcript import TranscriptEntry


class LlmVisualTests(unittest.TestCase):
    def test_agent_proposals_require_what_and_why_on_keep_only(self) -> None:
        entries = [
            TranscriptEntry("keep", "u1", 0.0, 2.0, ("w1",), "отложи 10%"),
            TranscriptEntry("cut", "u2", 2.0, 3.0, ("w2",), "заново", "маркер пересъёма"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            atomic_write_json(
                root / "llm-visual-response.json",
                {
                    "schema_version": 1,
                    "prompt_version": "gate1-visual-producer.v1",
                    "segment_id": "01",
                    "proposals": [{
                        "id": "1a",
                        "anchor": "u1",
                        "type": "motion",
                        "what": "10% slice from paycheck bar",
                        "why": "makes the rule concrete",
                    }],
                    "narrative_summary": "One formula beat.",
                    "risks": [],
                },
            )
            plan, result = run_llm_visual(
                "01",
                entries,
                output_dir=root,
                config={"provider": "agent"},
            )
            self.assertEqual(len(plan["scenes"]), 1)
            self.assertIn("Зачем:", plan["scenes"][0]["brief"])
            self.assertEqual(result["proposals"][0]["origin"], "AGENT")

    def test_cut_anchor_is_rejected(self) -> None:
        entries = [
            TranscriptEntry("keep", "u1", 0.0, 1.0, (), "ok"),
            TranscriptEntry("cut", "u2", 1.0, 2.0, (), "bad", "повтор"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            atomic_write_json(
                root / "llm-visual-response.json",
                {
                    "schema_version": 1,
                    "prompt_version": "gate1-visual-producer.v1",
                    "segment_id": "01",
                    "proposals": [{
                        "id": "1a",
                        "anchor": "u2",
                        "type": "motion",
                        "what": "x",
                        "why": "y",
                    }],
                    "narrative_summary": "bad",
                    "risks": [],
                },
            )
            with self.assertRaisesRegex(ValueError, "KEEP"):
                run_llm_visual("01", entries, output_dir=root, config={"provider": "agent"})


if __name__ == "__main__":
    unittest.main()
