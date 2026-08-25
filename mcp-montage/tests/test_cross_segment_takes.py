from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.contracts import CrossSegmentTakeAnalysis
from pipeline.factory.cross_takes import analyze_cross_segment_takes
from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.phase1 import refresh_gate1, run_phase1
from tests.helpers import make_project, make_video


def transcript(segment_id: str, *texts: str) -> dict:
    utterances = []
    for index, text in enumerate(texts, 1):
        utterances.append({
            "id": f"u{index:04d}",
            "start_s": float(index - 1),
            "end_s": float(index) - 0.1,
            "text": text,
            "word_ids": [f"{segment_id}-w{index}"],
        })
    return {"schema_version": 1, "utterances": utterances}


class CrossSegmentTakeTests(unittest.TestCase):
    def test_stable_high_confidence_group_recommends_latest_but_only_for_review(self) -> None:
        sources = [
            {"segment_id": "01", "sha256": "sha256:" + "1" * 64, "transcript": transcript("01", "Build a reliable video editing pipeline today")},
            {"segment_id": "02", "sha256": "sha256:" + "2" * 64, "transcript": transcript("02", "Build a reliable video editing pipeline today")},
            {"segment_id": "03", "sha256": "sha256:" + "3" * 64, "transcript": transcript("03", "This sentence is unrelated to the other takes")},
        ]

        first = analyze_cross_segment_takes(sources)
        second = analyze_cross_segment_takes(list(reversed(sources)))

        self.assertEqual(first, second)
        self.assertEqual(len(first["groups"]), 1)
        group = first["groups"][0]
        self.assertEqual(group["recommended_keep"], {"segment_id": "02", "utterance_id": "u0001"})
        self.assertEqual(group["recommended_cut"], [{"segment_id": "01", "utterance_id": "u0001"}])
        self.assertEqual(group["decision"], "REVIEW")
        self.assertEqual(first["candidates"], [{"id": group["id"], "kind": "cross-segment-take", "decision": "REVIEW"}])

    def test_phase1_binds_project_level_analysis_without_applying_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "Cross takes",
                "transcription": {"provider": "sidecar"},
            })
            for number in (1, 2):
                media = make_video(project / "01_raw" / f"{number:02d}_camera.mp4", duration=1.2, color="blue" if number == 1 else "green")
                atomic_write_json(media.with_suffix(media.suffix + ".transcript.json"), {
                    "language": "en", "duration_s": 1.2,
                    "segments": [{"id": "u0001", "start": 0.1, "end": 1.0, "text": "A repeated complete project-level sentence"}],
                })

            gate = read_json(run_phase1(project))
            record = gate["cross_segment_take_analysis"]
            analysis = read_json(project / record["path"])

            self.assertEqual(analysis["groups"][0]["recommended_keep"]["segment_id"], "02")
            self.assertEqual(analysis["groups"][0]["decision"], "REVIEW")
            first_transcript = (project / "03_phase1/segments/01/transcript.md").read_text(encoding="utf-8")
            self.assertIn("KEEP id=1.1", first_transcript)
            review = (project / "03_phase1/review.md").read_text(encoding="utf-8")
            self.assertIn("Cross-segment take candidates requiring review: 1", review)
            first_attempt = read_json(project / "06_state/jobs.json")["jobs"]["phase1.cross-segment-takes"]["attempt"]
            refresh_gate1(project)
            reused_attempt = read_json(project / "06_state/jobs.json")["jobs"]["phase1.cross-segment-takes"]["attempt"]
            self.assertEqual(reused_attempt, first_attempt)
            config = read_json(project / "project.json")
            config["cross_segment_takes"] = {"similarity_threshold": 0.80, "recommendation_threshold": 0.95}
            atomic_write_json(project / "project.json", config)
            refresh_gate1(project)
            invalidated_attempt = read_json(project / "06_state/jobs.json")["jobs"]["phase1.cross-segment-takes"]["attempt"]
            self.assertEqual(invalidated_attempt, first_attempt + 1)


    def test_borderline_match_is_reported_without_cut_recommendation(self) -> None:
        sources = [
            {"segment_id": "01", "sha256": "sha256:" + "1" * 64, "transcript": transcript("01", "one two three four five six seven eight nine ten")},
            {"segment_id": "02", "sha256": "sha256:" + "2" * 64, "transcript": transcript("02", "one two three four five six seven eight nine changed")},
        ]

        result = analyze_cross_segment_takes(sources)

        self.assertEqual(result["groups"], [])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["verdict"], "NO_CANDIDATES")
        self.assertEqual(result["uncertain_matches"][0]["decision"], "REVIEW")
        self.assertNotIn("recommended_cut", result["uncertain_matches"][0])


    def test_contract_rejects_ghost_members_and_actionable_uncertain_match(self) -> None:
        high = analyze_cross_segment_takes([
            {"segment_id": "01", "sha256": "sha256:" + "1" * 64, "transcript": transcript("01", "one two three four five six")},
            {"segment_id": "02", "sha256": "sha256:" + "2" * 64, "transcript": transcript("02", "one two three four five six")},
        ])
        high["groups"][0]["members"][0]["utterance_id"] = "ghost"
        high["groups"][0]["recommended_cut"][0]["utterance_id"] = "ghost"
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            CrossSegmentTakeAnalysis.parse(high)

        for invalid_confidence in (float("nan"), float("inf"), 1.1):
            invalid = analyze_cross_segment_takes([
                {"segment_id": "01", "sha256": "sha256:" + "1" * 64, "transcript": transcript("01", "one two three four five six")},
                {"segment_id": "02", "sha256": "sha256:" + "2" * 64, "transcript": transcript("02", "one two three four five six")},
            ])
            invalid["groups"][0]["minimum_similarity"] = invalid_confidence
            with self.assertRaisesRegex(ValueError, "recommendation"):
                CrossSegmentTakeAnalysis.parse(invalid)
        invalid_policy = analyze_cross_segment_takes([
            {"segment_id": "01", "sha256": "sha256:" + "1" * 64, "transcript": transcript("01", "one two three four five six")},
            {"segment_id": "02", "sha256": "sha256:" + "2" * 64, "transcript": transcript("02", "one two three four five six")},
        ])
        invalid_policy["groups"][0]["recommendation_policy"] = "auto-cut"
        with self.assertRaisesRegex(ValueError, "recommendation"):
            CrossSegmentTakeAnalysis.parse(invalid_policy)

        uncertain = analyze_cross_segment_takes([
            {"segment_id": "01", "sha256": "sha256:" + "1" * 64, "transcript": transcript("01", "one two three four five six seven eight nine ten")},
            {"segment_id": "02", "sha256": "sha256:" + "2" * 64, "transcript": transcript("02", "one two three four five six seven eight nine changed")},
        ])
        uncertain["uncertain_matches"][0]["decision"] = "CUT"
        uncertain["uncertain_matches"][0]["recommended_cut"] = [{"segment_id": "01", "utterance_id": "u0001"}]
        with self.assertRaisesRegex(ValueError, "uncertain"):
            CrossSegmentTakeAnalysis.parse(uncertain)

    def test_threshold_types_alias_order_and_single_segment_are_deterministic(self) -> None:
        with self.assertRaisesRegex(ValueError, "thresholds"):
            analyze_cross_segment_takes([], min_tokens=1.5)
        aliases = [
            {"segment_id": "1", "sha256": "sha256:" + "1" * 64, "transcript": transcript("1", "one two three four five six")},
            {"segment_id": "01", "sha256": "sha256:" + "2" * 64, "transcript": transcript("01", "one two three four five six")},
        ]
        self.assertEqual(analyze_cross_segment_takes(aliases), analyze_cross_segment_takes(list(reversed(aliases))))
        single = analyze_cross_segment_takes([aliases[0]])
        self.assertEqual(single["verdict"], "NO_CANDIDATES")
        CrossSegmentTakeAnalysis.parse(single)


if __name__ == "__main__":
    unittest.main()
