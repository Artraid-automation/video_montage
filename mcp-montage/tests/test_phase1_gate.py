from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json, read_json, sha256_file
from pipeline.factory.artifacts import validate_gate1
from pipeline.factory.phase1 import refresh_gate1, run_phase1
from pipeline.factory.state import StateStore
from tests.helpers import make_project, make_video


class Phase1IntegrationTests(unittest.TestCase):
    def test_empty_visual_config_still_produces_reviewable_auto_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "Auto visuals",
                "style_version": "test-style-v1", "transcription": {"provider": "sidecar"},
                "visual_planning": {"enabled": True, "cadence_seconds": 20, "max_per_segment": 1},
            })
            source = make_video(project / "01_raw" / "01_camera.mp4", duration=1.0)
            atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
                "language": "en", "duration_s": 1.0,
                "segments": [{"id": "u0001", "start": 0.1, "end": 0.8,
                              "text": "A useful visual workflow", "decision": "keep"}],
            })
            run_phase1(project)
            visual = read_json(project / "03_phase1" / "segments" / "01" / "visual-plan.json")
            self.assertEqual(len(visual["scenes"]), 1)
            self.assertEqual(visual["scenes"][0]["origin"], "AUTO")
            self.assertEqual(visual["scenes"][0]["status"], "PROPOSED")
            self.assertEqual(visual["scenes"][0]["type"], "motion")
            self.assertIn(visual["scenes"][0]["resolution"], {"CONFIGURED", "MOTION_FALLBACK"})
            review = (project / "03_phase1" / "review.md").read_text(encoding="utf-8")
            self.assertIn("Visual proposals: 1", review)
            refresh_gate1(project)
            refreshed = read_json(project / "03_phase1" / "segments" / "01" / "visual-plan.json")
            self.assertEqual(refreshed["scenes"][0]["origin"], "AUTO")
            self.assertEqual(refreshed["scenes"][0]["status"], "PROPOSED")

    def test_real_media_reaches_complete_typed_gate1_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = make_project(base)
            library = base / "library"
            broll = make_video(library / "originals" / "workflow.mp4", duration=0.5, color="red")
            atomic_write_json(library / "catalog.json", {"schema_version": 2, "revision": 1, "assets": [{
                "id": "asset-workflow", "path": "originals/workflow.mp4", "sha256": sha256_file(broll),
                "description": "team workflow", "tags": ["pipeline"], "rights": "owned", "provenance": "fixture",
            }]})
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "Synthetic",
                "style_version": "test-style-v1", "transcription": {"provider": "sidecar"},
                "broll_library_root": str(library),
                "visuals": {"01": [
                    {"anchor": "u0002", "type": "library-broll", "brief": "team workflow", "query": "team workflow"},
                    {"anchor": "u0002", "type": "motion", "brief": "Two-step diagram"},
                ]},
            })
            source = make_video(project / "01_raw" / "01_camera.mp4", duration=2.0)
            atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
                "language": "en", "duration_s": 2.0,
                "segments": [
                    {"id": "u0001", "start": 0.1, "end": 0.7, "text": "bad start", "decision": "cut", "reason": "false-start", "take_group": "intro"},
                    {"id": "u0002", "start": 0.8, "end": 1.7, "text": "final useful sentence", "decision": "keep", "take_group": "intro"},
                ],
            })
            manifest_path = run_phase1(project)
            ledger = StateStore(project).read()
            self.assertEqual(ledger["state"], "GATE1_REVIEW")
            manifest = read_json(manifest_path)
            self.assertEqual(len(manifest["segments"]), 1)
            transcript = (project / "03_phase1" / "segments" / "01" / "transcript.md").read_text(encoding="utf-8")
            self.assertIn("CUT (фальстарт) id=1.1", transcript)
            self.assertIn("KEEP id=1.2", transcript)
            self.assertIn("BROLL 1a (оверлей-начало)", transcript)
            self.assertIn("MOTION 1b (оверлей-начало)", transcript)
            editorial = read_json(project / "03_phase1" / "segments" / "01" / "editorial-analysis.json")
            self.assertEqual(editorial["take_candidates"][0]["recommended_keep"], "u0002")
            visual = read_json(project / "03_phase1" / "segments" / "01" / "visual-plan.json")
            self.assertEqual(visual["scenes"][0]["resolution"], "LIBRARY_MATCH")
            staged_asset = project / visual["scenes"][0]["asset"]
            self.assertTrue(staged_asset.is_file())
            self.assertEqual(manifest["segments"][0]["broll_assets"][0]["sha256"], sha256_file(staged_asset))
            staged_asset.unlink()
            with self.assertRaisesRegex(ValueError, "artifact"):
                validate_gate1(project, manifest)
            refreshed = read_json(refresh_gate1(project))
            validate_gate1(project, refreshed)
            self.assertTrue(staged_asset.is_file())
            self.assertIn("Editorial candidates requiring review: 1", (project / "03_phase1" / "review.md").read_text(encoding="utf-8"))
            grade = read_json(project / "03_phase1" / "segments" / "01" / "grade-manifest.json")
            self.assertGreaterEqual(len(grade["samples"]), 3)
            continuity = read_json(project / "03_phase1" / "film-continuity.json")
            self.assertEqual(continuity["kind"], "film-continuity")
            self.assertIn(continuity["verdict"], {"PASS", "BLOCKED"})
            self.assertIn("film_continuity", refreshed)
            self.assertFalse((project / "04_phase2" / "segments" / "01" / "review.mp4").exists())


if __name__ == "__main__":
    unittest.main()
