from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.cleanup import cleanup_dry_run, execute_cleanup
from pipeline.factory.io import atomic_write_json, read_json, sha256_file
from pipeline.factory.phase1 import run_phase1
from pipeline.factory.phase2 import run_phase2
from pipeline.factory.phase3 import run_phase3
from pipeline.factory.state import StateStore
from tests.fakes import RenderedTranscriptFake
from tests.helpers import make_project, make_video


class Phase3DeliveryTests(unittest.TestCase):
    def test_master_archive_package_and_recoverable_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = make_project(root); archive = root / "archive"
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "Delivery fixture",
                "style_version": "v1", "default_grade": "neutral", "archive_root": str(archive),
                "transcription": {"provider": "sidecar"}, "verification_transcription": {"provider": "synthetic"},
                "render_profile": {"width": 320, "height": 180, "fps": 25, "crf": 26, "preset": "ultrafast"},
                "publishing": {"title": "Verified Delivery", "description": "Synthetic acceptance.", "chapter_titles": {"01": "Intro"}},
                "telegram_delivery": {"enabled": False},
            })
            source = make_video(project / "01_raw" / "01_camera.mp4", duration=1.5)
            atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
                "language": "en", "duration_s": 1.5,
                "segments": [{"id": "u1", "start": 0.2, "end": 1.2, "text": "verified final sentence", "decision": "keep"}],
            })
            store = StateStore(project)
            run_phase1(project, store); store.approve("gate1", reviewer="owner")
            run_phase2(project, store, verification_transcriber=RenderedTranscriptFake()); store.approve("gate2", reviewer="owner")
            manifest_path = run_phase3(project, store)
            self.assertEqual(store.read()["state"], "FINAL_REVIEW")
            manifest = read_json(manifest_path)
            receipt = read_json(project / manifest["archive_receipt"]["path"])
            self.assertEqual(receipt["verdict"], "VERIFIED")
            archived_master = Path(next(item["destination"] for item in receipt["entries"] if item["role"] == "master"))
            self.assertEqual(sha256_file(archived_master), manifest["master"]["sha256"])
            chapters = (project / manifest["publishing_package"]["chapters"]["path"]).read_text(encoding="utf-8")
            self.assertTrue(chapters.startswith("00:00 Intro"))
            store.approve("final", reviewer="owner")
            plan_path, plan = cleanup_dry_run(project, store)
            self.assertTrue((project / "03_phase1").is_dir())
            receipt_path = execute_cleanup(project, plan["confirmation_hash"], store)
            self.assertTrue(receipt_path.is_file())
            self.assertTrue((project / "01_raw" / "01_camera.mp4").is_file())
            self.assertTrue((project / "05_final" / manifest["master"]["path"].split("/")[-1]).is_file())
            self.assertEqual(list((project / "03_phase1").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
