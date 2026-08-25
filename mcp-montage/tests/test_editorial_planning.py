from __future__ import annotations

import unittest
import math

from pipeline.factory.contracts import EditorialAnalysis
from pipeline.factory.editorial import analyze_editorial


class EditorialPlanningTests(unittest.TestCase):
    def test_detects_pauses_repetitions_and_explicit_take_groups_deterministically(self) -> None:
        transcript = {
            "schema_version": 1,
            "utterances": [
                {"id": "u1", "start_s": 0.0, "end_s": 1.0, "text": "Let us ship this feature", "word_ids": ["w1"], "take_group": "intro"},
                {"id": "u2", "start_s": 1.2, "end_s": 2.0, "text": "Let us ship this feature", "word_ids": ["w2"], "take_group": "intro"},
                {"id": "u3", "start_s": 3.1, "end_s": 4.0, "text": "Now verify the result", "word_ids": ["w3"]},
            ],
        }
        first = analyze_editorial(transcript, pause_threshold_s=0.8, repetition_similarity=0.9)
        second = analyze_editorial(transcript, pause_threshold_s=0.8, repetition_similarity=0.9)

        self.assertEqual(first, second)
        self.assertEqual(first["verdict"], "CANDIDATES_PROPOSED")
        self.assertEqual(first["pause_candidates"][0]["after_utterance_id"], "u2")
        self.assertEqual(first["repetition_candidates"][0]["utterance_ids"], ["u1", "u2"])
        take = first["take_candidates"][0]
        self.assertEqual(take["recommended_keep"], "u2")
        self.assertEqual(take["recommended_cut"], ["u1"])
        self.assertTrue(all(item["decision"] == "REVIEW" for item in first["candidates"]))

    def test_rejects_reordered_or_invalid_utterances(self) -> None:
        with self.assertRaisesRegex(ValueError, "utterance timeline"):
            analyze_editorial({"utterances": [
                {"id": "u1", "start_s": 1.0, "end_s": 2.0, "text": "one", "word_ids": ["w1"]},
                {"id": "u2", "start_s": 0.0, "end_s": 1.0, "text": "two", "word_ids": ["w2"]},
            ]})
        with self.assertRaisesRegex(ValueError, "utterance timeline"):
            analyze_editorial({"utterances": [
                {"id": "u1", "start_s": math.nan, "end_s": 1.0, "text": "one", "word_ids": ["w1"]},
            ]})
        valid = {"utterances": [{"id": "u1", "start_s": 0.0, "end_s": 1.0, "text": "one", "word_ids": ["w1"]}]}
        for invalid in (math.nan, math.inf):
            with self.assertRaisesRegex(ValueError, "pause threshold"):
                analyze_editorial(valid, pause_threshold_s=invalid)

    def test_typed_contract_rejects_ghost_or_malformed_detail_candidates(self) -> None:
        source = {"utterances": [
            {"id": "u1", "start_s": 0.0, "end_s": 1.0, "text": "same", "word_ids": ["w1"], "take_group": "a"},
            {"id": "u2", "start_s": 2.0, "end_s": 3.0, "text": "same", "word_ids": ["w2"], "take_group": "a"},
        ]}
        artifact = analyze_editorial(source, pause_threshold_s=0.5)
        EditorialAnalysis.parse(artifact)
        ghost = {**artifact, "pause_candidates": []}
        with self.assertRaisesRegex(ValueError, "candidate collections"):
            EditorialAnalysis.parse(ghost)
        malformed = {**artifact, "take_candidates": "not-a-list"}
        with self.assertRaisesRegex(ValueError, "must be a list"):
            EditorialAnalysis.parse(malformed)


if __name__ == "__main__":
    unittest.main()
