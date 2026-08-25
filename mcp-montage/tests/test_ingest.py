from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.ingest import scan_raw
from tests.helpers import make_project, make_video


class IngestTests(unittest.TestCase):
    def test_numbered_feeds_are_grouped_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            make_video(project / "01_raw" / "01_camera.mp4")
            make_video(project / "01_raw" / "02_screen.mp4", color="red")
            manifest = scan_raw(project)
            self.assertEqual([item["number"] for item in manifest["segments"]], [1, 2])
            self.assertEqual(manifest["segments"][0]["feeds"].keys(), {"camera"})
            self.assertTrue(manifest["files"][0]["sha256"].startswith("sha256:"))

    def test_number_gap_and_duplicate_role_are_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            make_video(project / "01_raw" / "01_camera.mp4")
            make_video(project / "01_raw" / "03_camera.mp4", color="red")
            with self.assertRaisesRegex(ValueError, "gaps"):
                scan_raw(project)
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            make_video(project / "01_raw" / "01_camera.mp4")
            make_video(project / "01_raw" / "01_cam.mp4", color="red")
            with self.assertRaisesRegex(ValueError, "duplicate camera"):
                scan_raw(project)


if __name__ == "__main__":
    unittest.main()
