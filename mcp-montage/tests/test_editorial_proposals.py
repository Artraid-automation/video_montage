from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.editorial import analyze_editorial, apply_editorial_proposals
from pipeline.factory.io import atomic_write_json
from pipeline.factory.phase1 import run_phase1
from pipeline.factory.transcript import TranscriptEntry
from tests.helpers import make_project, make_video


class EditorialProposalApplicationTests(unittest.TestCase):
    def test_repetition_and_retake_marker_become_cut_tags_with_reasons(self) -> None:
        transcript = {
            "schema_version": 1,
            "utterances": [
                {"id": "u1", "start_s": 0.0, "end_s": 1.0, "text": "Money leaves because priorities", "word_ids": ["w1"]},
                {"id": "u2", "start_s": 2.0, "end_s": 2.5, "text": "так, заново", "word_ids": ["w2"]},
                {"id": "u3", "start_s": 8.0, "end_s": 9.0, "text": "Money leaves because priorities", "word_ids": ["w3"]},
                {"id": "u4", "start_s": 9.5, "end_s": 10.5, "text": "Write schema in the comments", "word_ids": ["w4"]},
            ],
        }
        editorial = analyze_editorial(transcript, pause_threshold_s=0.8, repetition_similarity=0.86)
        entries = [
            TranscriptEntry("keep", item["id"], float(item["start_s"]), float(item["end_s"]), tuple(item["word_ids"]), item["text"])
            for item in transcript["utterances"]
        ]
        proposed = apply_editorial_proposals(entries, editorial)

        by_id = {item.id: item for item in proposed}
        self.assertEqual(by_id["u1"].kind, "cut")
        self.assertEqual(by_id["u1"].reason, "proposed-repetition")
        self.assertEqual(by_id["u2"].kind, "cut")
        self.assertEqual(by_id["u2"].reason, "retake-marker")
        self.assertEqual(by_id["u3"].kind, "keep")
        self.assertEqual(by_id["u4"].kind, "keep")
        self.assertTrue(any(item.get("reason") == "latest-repetition-cluster" for item in editorial["take_candidates"]))
        self.assertTrue(any(item["id"].startswith("take-") for item in editorial["take_candidates"]))

    def test_hook_phrase_anywhere_keeps_latest_take(self) -> None:
        transcript = {
            "schema_version": 1,
            "utterances": [
                {"id": "u1", "start_s": 0.0, "end_s": 2.0, "text": "Intro then Деньги уходят не потому that priorities", "word_ids": ["w1"]},
                {"id": "u2", "start_s": 3.0, "end_s": 4.0, "text": "filler", "word_ids": ["w2"]},
                {"id": "u3", "start_s": 5.0, "end_s": 7.0, "text": "Final Деньги уходят не потому about priorities and CTA", "word_ids": ["w3"]},
            ],
        }
        editorial = analyze_editorial(transcript, pause_threshold_s=0.5, repetition_similarity=0.99)
        entries = [
            TranscriptEntry("keep", item["id"], float(item["start_s"]), float(item["end_s"]), tuple(item["word_ids"]), item["text"])
            for item in transcript["utterances"]
        ]
        proposed = {item.id: item for item in apply_editorial_proposals(entries, editorial)}
        self.assertEqual(proposed["u1"].kind, "cut")
        self.assertEqual(proposed["u1"].reason, "proposed-retake-prefix")
        self.assertEqual(proposed["u3"].kind, "keep")

    def test_phase1_writes_proposed_cuts_into_transcript_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "Proposed cuts",
                "style_version": "test-style-v1", "transcription": {"provider": "sidecar"},
                "editorial": {"pause_threshold_s": 0.5, "repetition_similarity": 0.86},
            })
            source = make_video(project / "01_raw" / "01_camera.mp4", duration=3.0)
            atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
                "language": "en", "duration_s": 3.0,
                "segments": [
                    {"id": "u0001", "start": 0.1, "end": 0.8, "text": "bad take one about priorities"},
                    {"id": "u0002", "start": 1.0, "end": 1.3, "text": "заново"},
                    {"id": "u0003", "start": 2.0, "end": 2.8, "text": "bad take one about priorities"},
                ],
            })
            run_phase1(project)
            text = (project / "03_phase1" / "segments" / "01" / "transcript.md").read_text(encoding="utf-8")
            self.assertIn("CUT (", text)
            self.assertIn("id=1.1", text)
            self.assertTrue(
                "повтор фразы" in text or "маркер пересъёма" in text,
                msg=text,
            )
            self.assertNotIn("id=u0002", text)
            self.assertIn("KEEP id=1.3", text)
            review = (project / "03_phase1" / "review.md").read_text(encoding="utf-8")
            self.assertIn("## Легенда артефактов", review)
            self.assertIn("MOTION", review)


if __name__ == "__main__":
    unittest.main()
