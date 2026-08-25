from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json
from pipeline.factory.phase1 import run_phase1
from pipeline.factory.phase2 import run_phase2
from pipeline.factory.phase3 import run_phase3
from pipeline.factory.revisions import run_revisions
from pipeline.factory.state import StateStore
from tests.fakes import RenderedTranscriptFake
from tests.helpers import make_project, make_video


class FinalRevisionTests(unittest.TestCase):
    def test_final_metadata_fix_is_applied_and_returns_to_final_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = make_project(root)
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "Before", "style_version": "v1",
                "default_grade": "neutral", "archive_root": str(root / "archive"),
                "transcription": {"provider": "sidecar"},
                "render_profile": {"width": 320, "height": 180, "fps": 25, "crf": 26, "preset": "ultrafast"},
                "telegram_delivery": {"enabled": False},
            })
            source = make_video(project / "01_raw" / "01_camera.mp4", duration=1.2)
            atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
                "language": "en", "duration_s": 1.2,
                "segments": [{"id": "u1", "start": 0.1, "end": 1.0, "text": "final review metadata", "decision": "keep"}],
            })
            store = StateStore(project)
            run_phase1(project, store); store.approve("gate1", reviewer="owner")
            run_phase2(project, store, verification_transcriber=RenderedTranscriptFake()); store.approve("gate2", reviewer="owner")
            run_phase3(project, store)
            (project / "05_final" / "fixes.md").write_text('# Final fixes\n\n- [fix metadata] segment=final set-title value="After"\n', encoding="utf-8")
            run_revisions(project, store)
            self.assertEqual(store.read()["state"], "FINAL_REVIEW")
            self.assertEqual(__import__("json").loads((project / "project.json").read_text(encoding="utf-8"))["publishing"]["title"], "After")
            self.assertTrue(any((root / "archive").glob("fixture-r*")))


if __name__ == "__main__":
    unittest.main()
