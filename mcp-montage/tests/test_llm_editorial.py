from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.llm_editorial import (
    PROMPT_VERSION,
    apply_llm_editorial_decisions,
    apply_llm_splits,
    build_llm_editorial_request,
    explode_multi_take_entries,
    has_false_cohesion,
    run_llm_editorial,
    validate_llm_editorial_response,
)
from pipeline.factory.transcript import TranscriptEntry


class LlmEditorialTests(unittest.TestCase):
    def test_missing_decision_is_auto_cut_after_safety_explode(self) -> None:
        entries = [
            TranscriptEntry("keep", "u1", 0.0, 1.0, ("w1",), "intro"),
            TranscriptEntry("cut", "u2", 1.0, 2.0, ("w2",), "bad", "повтор"),
        ]
        request = build_llm_editorial_request("03", entries)
        result = validate_llm_editorial_response(
            {
                "schema_version": 2,
                "prompt_version": request["prompt_version"],
                "segment_id": "03",
                "decisions": [{"id": "u1", "kind": "keep", "reason": None}],
                "narrative_summary": "partial",
                "risks": [],
            },
            request,
            working_entries=entries,
        )
        by_id = {item["id"]: item for item in result["decisions"]}
        self.assertEqual(by_id["u2"]["kind"], "cut")
        self.assertEqual(by_id["u2"]["reason"], "внутренние повторы")

    def test_llm_split_partitions_parent_and_decides_parts(self) -> None:
        parent = TranscriptEntry(
            "keep",
            "u58",
            100.0,
            160.0,
            ("w1",),
            "Короче говоря, они уходят не потому, что их мало. Деньги уходят не потому, что их мало.",
        )
        self.assertTrue(has_false_cohesion(parent.text))
        response = {
            "schema_version": 2,
            "prompt_version": PROMPT_VERSION,
            "segment_id": "03",
            "splits": [{
                "id": "u58",
                "parts": [
                    {"suffix": "p1", "text": "Короче говоря, они уходят не потому, что их мало."},
                    {"suffix": "p2", "text": "Деньги уходят не потому, что их мало."},
                ],
            }],
            "decisions": [
                {"id": "u58p1", "kind": "keep", "reason": None},
                {"id": "u58p2", "kind": "cut", "reason": "повтор хука"},
            ],
            "narrative_summary": "Один закрывающий take.",
            "risks": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            atomic_write_json(root / "resp.json", response)
            updated, result = run_llm_editorial(
                "03",
                [parent],
                output_dir=root,
                config={"provider": "file", "response_path": str(root / "resp.json")},
            )
            self.assertEqual([item.id for item in updated], ["u58p1", "u58p2"])
            self.assertEqual(updated[0].kind, "keep")
            self.assertEqual(updated[1].kind, "cut")
            self.assertAlmostEqual(updated[-1].end_s, 160.0)
            self.assertEqual(result["schema_version"], 2)

    def test_keep_on_unsplit_false_cohesion_is_rejected(self) -> None:
        mega = TranscriptEntry(
            "keep",
            "u58",
            100.0,
            200.0,
            ("w1",),
            "Короче говоря, они уходят не потому, что их мало. Деньги уходят не потому, что их мало.",
        )
        request = build_llm_editorial_request("03", [mega])
        with self.assertRaisesRegex(ValueError, "KEEP forbidden|false-cohesion|multi-take"):
            validate_llm_editorial_response(
                {
                    "schema_version": 2,
                    "prompt_version": request["prompt_version"],
                    "segment_id": "03",
                    "decisions": [{"id": "u58", "kind": "keep", "reason": None}],
                    "narrative_summary": "bad",
                    "risks": [],
                },
                request,
                working_entries=[mega],
            )

    def test_apply_preserves_timing_and_text(self) -> None:
        entries = [TranscriptEntry("keep", "u1", 1.5, 2.5, ("w1", "w2"), "текст")]
        result = {"decisions": [{"id": "u1", "kind": "cut", "reason": "мусор"}]}
        updated = apply_llm_editorial_decisions(entries, result)
        self.assertEqual(updated[0].text, "текст")
        self.assertEqual(updated[0].kind, "cut")


if __name__ == "__main__":
    unittest.main()
