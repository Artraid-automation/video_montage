from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json, sha256_file
from pipeline.factory.planning import plan_visuals
from pipeline.factory.transcript import TranscriptEntry


class VisualPlanningTests(unittest.TestCase):
    def test_empty_explicit_plan_creates_bounded_stable_auto_proposals(self) -> None:
        entries = [
            TranscriptEntry("keep", f"u{index}", index * 10.0, index * 10.0 + 3.0,
                            (f"w{index}",), f"Topic number {index}")
            for index in range(1, 8)
        ]
        config = {"enabled": True, "cadence_seconds": 20, "max_per_segment": 2}
        first = plan_visuals("01", entries, [], auto_config=config)
        second = plan_visuals("01", entries, [], auto_config=config)
        self.assertEqual(first, second)
        self.assertEqual(len(first["scenes"]), 2)
        self.assertTrue(all(scene["status"] == "PROPOSED" for scene in first["scenes"]))
        self.assertTrue(all(scene["origin"] == "AUTO" for scene in first["scenes"]))

    def test_auto_proposal_uses_motion_fallback_for_empty_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"; project.mkdir()
            entries = [TranscriptEntry("keep", "u1", 0.0, 3.0, ("w1",), "secure workflow")]
            plan = plan_visuals(
                "01", entries, [], library_root=root / "missing-library", project_root=project,
                auto_config={"enabled": True, "cadence_seconds": 10, "max_per_segment": 3},
            )
            self.assertEqual(plan["scenes"][0]["resolution"], "MOTION_FALLBACK")
            self.assertEqual(plan["searches"][0]["matches"], [])

    def test_cut_entries_are_never_auto_visual_anchors(self) -> None:
        entries = [
            TranscriptEntry("cut", "u1", 0.0, 2.0, ("w1",), "discard me"),
            TranscriptEntry("keep", "u2", 2.0, 4.0, ("w2",), "keep me"),
        ]
        plan = plan_visuals("01", entries, [], auto_config={"enabled": True, "max_per_segment": 5})
        self.assertEqual([scene["anchor"] for scene in plan["scenes"]], ["u2"])

    def test_zero_max_disables_auto_proposals(self) -> None:
        entries = [TranscriptEntry("keep", "u1", 0.0, 1.0, ("w1",), "text")]
        plan = plan_visuals("01", entries, [], auto_config={"enabled": True, "max_per_segment": 0})
        self.assertEqual(plan["scenes"], [])

    def test_non_finite_cadence_and_unsafe_ids_are_blocking(self) -> None:
        entries = [TranscriptEntry("keep", "u1", 0.0, 1.0, ("w1",), "text")]
        for invalid in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "finite"):
                plan_visuals("01", entries, [], auto_config={"enabled": True, "cadence_seconds": invalid})
        unsafe = [TranscriptEntry("keep", "bad id", 0.0, 1.0, ("w1",), "text")]
        with self.assertRaisesRegex(ValueError, "schema-safe"):
            plan_visuals("01", unsafe, [], auto_config={"enabled": True})
        with self.assertRaisesRegex(ValueError, "visual id is not schema-safe"):
            plan_visuals("01", entries, [{"id": "bad id", "anchor": "u1", "type": "motion", "brief": "x"}])

    def test_malformed_catalog_fails_closed_instead_of_hiding_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"; project.mkdir()
            library = root / "library"; library.mkdir()
            (library / "catalog.json").write_text("{bad", encoding="utf-8")
            entries = [TranscriptEntry("keep", "u1", 0.0, 1.0, ("w1",), "workflow")]
            with self.assertRaises(Exception):
                plan_visuals("01", entries, [], library_root=library, project_root=project,
                             auto_config={"enabled": True})

    def test_resolves_library_query_and_falls_back_to_motion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            library = base / "library"
            library.mkdir()
            project = base / "project"
            project.mkdir()
            media = library / "originals" / "pipeline.mp4"
            media.parent.mkdir()
            media.write_bytes(b"clip")
            atomic_write_json(library / "catalog.json", {"schema_version": 2, "revision": 3, "assets": [{
                "id": "asset-pipeline", "path": "originals/pipeline.mp4", "sha256": sha256_file(media),
                "description": "three phase pipeline", "tags": ["workflow"], "rights": "owned", "provenance": "shoot-1",
            }]})
            entries = [{"id": "u1"}, {"id": "u2"}]
            configured = [
                {"id": "v1", "anchor": "u1", "type": "library-broll", "brief": "show workflow", "query": "three phase pipeline"},
                {"id": "v2", "anchor": "u2", "type": "library-broll", "brief": "missing concept", "query": "spaceship launch"},
            ]

            plan = plan_visuals("01", entries, configured, library_root=library, project_root=project)

            self.assertEqual(plan["scenes"][0]["type"], "library-broll")
            self.assertEqual(plan["scenes"][0]["asset"], "02_inputs/broll/selected/asset-pipeline.mp4")
            self.assertEqual(plan["scenes"][1]["type"], "motion")
            self.assertEqual(plan["scenes"][1]["resolution"], "MOTION_FALLBACK")

    def test_unknown_anchor_is_blocking(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown anchor"):
            plan_visuals("01", [{"id": "u1"}], [{"anchor": "u9", "type": "motion", "brief": "x"}])


    def test_library_asset_cannot_bypass_catalog_validation_or_staging(self) -> None:
        with self.assertRaisesRegex(ValueError, "library_root and project_root"):
            plan_visuals("01", [{"id": "u1"}], [{"anchor": "u1", "type": "library-broll", "asset": "unverified.mp4", "brief": "x"}])


if __name__ == "__main__":
    unittest.main()
