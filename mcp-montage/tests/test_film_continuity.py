from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.film_continuity import analyze_film_continuity


class FilmContinuityTests(unittest.TestCase):
    def test_near_identical_keep_across_segments_is_blocked(self) -> None:
        report = analyze_film_continuity([
            {
                "segment_id": "01",
                "transcript_sha256": "sha256:a",
                "keeps": [{
                    "id": "u1",
                    "text": "If you are always broke by month end the problem is missing order not low income",
                }],
            },
            {
                "segment_id": "02",
                "transcript_sha256": "sha256:b",
                "keeps": [{
                    "id": "u9",
                    "text": "If you are always broke by month end the problem is missing order not low income",
                }],
            },
        ])
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(len(report["blocking_groups"]), 1)
        group = report["blocking_groups"][0]
        self.assertEqual(group["recommended_keep"]["segment_id"], "02")
        self.assertEqual(
            [item["segment_id"] for item in group["recommended_cut"]],
            ["01"],
        )

    def test_complementary_keeps_pass(self) -> None:
        report = analyze_film_continuity([
            {
                "segment_id": "01",
                "transcript_sha256": "sha256:a",
                "keeps": [{"id": "u1", "text": "Pain of being broke with no system at all"}],
            },
            {
                "segment_id": "02",
                "transcript_sha256": "sha256:b",
                "keeps": [{"id": "u2", "text": "On payday move ten percent to another bank"}],
            },
        ])
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["blocking_groups"], [])

    def test_uncertain_only_does_not_block(self) -> None:
        # Score ~0.92 sits in soft band: similarity 0.84, recommendation 0.95 → uncertain, PASS.
        report = analyze_film_continuity(
            [
                {
                    "segment_id": "01",
                    "transcript_sha256": "sha256:a",
                    "keeps": [{
                        "id": "u1",
                        "text": "If you are always broke by month end the problem is missing order",
                    }],
                },
                {
                    "segment_id": "02",
                    "transcript_sha256": "sha256:b",
                    "keeps": [{
                        "id": "u2",
                        "text": "If you are always broke by month end the problem is missing system",
                    }],
                },
            ],
            similarity_threshold=0.84,
            recommendation_threshold=0.95,
        )
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["blocking_groups"], [])
        self.assertTrue(report["uncertain_matches"])

    def test_gate1_approval_blocked_when_continuity_blocked(self) -> None:
        from pipeline.factory.artifacts import validate_gate1_approval
        from pipeline.factory.io import atomic_write_json, read_json
        from tests.helpers import gate1_manifest, make_project

        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            manifest_path = gate1_manifest(project)
            continuity_path = project / "03_phase1" / "film-continuity.json"
            payload = read_json(continuity_path)
            payload["verdict"] = "BLOCKED"
            payload["blocking_groups"] = [{
                "id": "film-keep-test",
                "members": [
                    {"segment_id": "01", "keep_id": "w1"},
                    {"segment_id": "02", "keep_id": "w2"},
                ],
                "minimum_similarity": 0.99,
                "recommended_keep": {"segment_id": "02", "keep_id": "w2"},
                "recommended_cut": [{"segment_id": "01", "keep_id": "w1"}],
                "recommendation_policy": "latest-complete-keep-high-confidence",
                "decision": "BLOCK",
            }]
            atomic_write_json(continuity_path, payload)
            manifest = read_json(manifest_path)
            from pipeline.factory.artifacts import artifact_record
            manifest["film_continuity"] = artifact_record(project, continuity_path, kind="film-continuity")
            atomic_write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "film continuity BLOCKED"):
                validate_gate1_approval(project, read_json(manifest_path))


if __name__ == "__main__":
    unittest.main()
