from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.archive import archive_project
from tests.helpers import make_project, make_video


class ArchiveSafetyTests(unittest.TestCase):
    def test_project_id_cannot_escape_archive_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = make_project(root)
            master = make_video(project / "05_final" / "master.mp4")
            with self.assertRaisesRegex(ValueError, "unsafe archive"):
                archive_project(project, archive_root=root / "archive", project_id="../outside", master=master, package_files=[], raw_files=[])
            self.assertFalse((root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
