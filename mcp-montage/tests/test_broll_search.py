from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.broll import search_catalog, stage_asset
from pipeline.factory.io import atomic_write_json, sha256_file


class BrollSearchTests(unittest.TestCase):
    def test_search_is_ranked_and_filters_rights_provenance_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            originals = root / "originals"
            originals.mkdir()
            good = originals / "good.mp4"
            good.write_bytes(b"good")
            denied = originals / "denied.mp4"
            denied.write_bytes(b"denied")
            stale = originals / "stale.mp4"
            stale.write_bytes(b"stale")
            atomic_write_json(root / "catalog.json", {
                "schema_version": 2,
                "revision": 7,
                "assets": [
                    {"id": "asset-good", "path": "originals/good.mp4", "sha256": sha256_file(good), "description": "local video library", "tags": ["pipeline", "library"], "rights": "owned", "provenance": "project-a"},
                    {"id": "asset-denied", "path": "originals/denied.mp4", "sha256": sha256_file(denied), "description": "video library", "tags": ["pipeline"], "rights": "unknown", "provenance": "web"},
                    {"id": "asset-no-source", "path": "originals/denied.mp4", "sha256": sha256_file(denied), "description": "video library", "tags": ["pipeline"], "rights": "licensed", "provenance": ""},
                    {"id": "asset-stale", "path": "originals/stale.mp4", "sha256": "sha256:" + "0" * 64, "description": "video library", "tags": ["pipeline"], "rights": "generated", "provenance": "generator-v1"},
                ],
            })

            result = search_catalog(root, "pipeline video library")

            self.assertEqual([item["asset_id"] for item in result["matches"]], ["asset-good"])
            self.assertEqual(result["catalog_revision"], 7)
            self.assertEqual({item["asset_id"] for item in result["rejected"]}, {"asset-denied", "asset-no-source", "asset-stale"})
            self.assertEqual(result, search_catalog(root, "pipeline video library"))

            project = root / "project"
            project.mkdir()
            staged = stage_asset(root, project, result["matches"][0])
            self.assertEqual(staged, "02_inputs/broll/selected/asset-good.mp4")
            self.assertTrue((project / staged).is_file())

    def test_catalog_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root.parent / "outside-broll-test.mp4"
            outside.write_bytes(b"outside")
            try:
                atomic_write_json(root / "catalog.json", {"schema_version": 2, "revision": 1, "assets": [{
                    "id": "escape", "path": "../outside-broll-test.mp4", "sha256": sha256_file(outside),
                    "description": "escape", "tags": [], "rights": "owned", "provenance": "test",
                }]})
                result = search_catalog(root, "escape")
                self.assertEqual(result["matches"], [])
                self.assertEqual(result["rejected"][0]["reason"], "path-outside-library")
            finally:
                outside.unlink(missing_ok=True)


    def test_malicious_id_and_non_regular_asset_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good = root / "good.mp4"
            good.write_bytes(b"good")
            atomic_write_json(root / "catalog.json", {"schema_version": 2, "revision": 1, "assets": [
                {"id": "../../escape", "path": "good.mp4", "sha256": sha256_file(good), "description": "escape", "tags": [], "rights": "owned", "provenance": "test"},
                {"id": "directory", "path": ".", "sha256": "sha256:" + "0" * 64, "description": "directory", "tags": [], "rights": "owned", "provenance": "test"},
            ]})
            result = search_catalog(root, "escape directory")
            self.assertEqual(result["matches"], [])
            self.assertEqual({item["reason"] for item in result["rejected"]}, {"invalid-or-duplicate-id", "not-a-regular-file"})


if __name__ == "__main__":
    unittest.main()
