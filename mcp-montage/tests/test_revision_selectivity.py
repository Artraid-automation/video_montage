from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json, sha256_file
from pipeline.factory.phase1 import run_phase1
from pipeline.factory.phase2 import run_phase2
from pipeline.factory.revisions import run_revisions
from pipeline.factory.state import StateStore
from tests.fakes import RenderedTranscriptFake
from tests.helpers import make_project, make_video


class RevisionSelectivityTests(unittest.TestCase):
    def test_only_changed_segment_is_rebuilt_and_reverified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "Two segments",
                "style_version": "v1", "default_grade": "neutral",
                "transcription": {"provider": "sidecar"},
                "verification_transcription": {"provider": "synthetic"},
                "render_profile": {"width": 320, "height": 180, "fps": 25, "crf": 26, "preset": "ultrafast"},
            })
            for number, color, text in ((1, "blue", "first useful sentence"), (2, "red", "second stable sentence")):
                source = make_video(project / "01_raw" / f"{number:02d}_camera.mp4", duration=1.4, color=color)
                atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
                    "language": "en", "duration_s": 1.4,
                    "segments": [{"id": f"u{number}", "start": 0.2, "end": 1.1, "text": text, "decision": "keep"}],
                })
            store = StateStore(project)
            run_phase1(project, store); store.approve("gate1", reviewer="owner")
            run_phase2(project, store, verification_transcriber=RenderedTranscriptFake())
            stable = project / "04_phase2" / "segments" / "02" / "review.mp4"
            stable_hash = sha256_file(stable); stable_mtime = stable.stat().st_mtime_ns
            transcript = project / "03_phase1" / "segments" / "01" / "transcript.md"
            transcript.write_text(transcript.read_text(encoding="utf-8").replace("first useful sentence", "first corrected sentence"), encoding="utf-8")
            fixes = project / "04_phase2" / "segments" / "01" / "fixes.md"
            fixes.write_text("# Fixes\n\n- [fix speech] segment=01 transcript-reviewed\n", encoding="utf-8")
            time.sleep(0.01)
            run_revisions(project, store, verification_transcriber=RenderedTranscriptFake())
            self.assertEqual(store.read()["state"], "GATE2_REVIEW")
            self.assertEqual(sha256_file(stable), stable_hash)
            self.assertEqual(stable.stat().st_mtime_ns, stable_mtime)
            self.assertNotIn("[fix speech]", fixes.read_text(encoding="utf-8"))
            self.assertTrue(any((project / "04_phase2" / "revision-history").glob("*-01-fixes.md")))


if __name__ == "__main__":
    unittest.main()
