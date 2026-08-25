from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.jobs import JobLedger
from pipeline.factory.phase1 import run_phase1
from pipeline.factory.phase2 import run_phase2
from pipeline.factory.phase3 import run_phase3
from pipeline.factory.state import StateStore
from tests.fakes import RenderedTranscriptFake
from tests.helpers import make_project, make_video


def base_config(project: Path, archive: Path) -> dict:
    return {
        "schema_version": 2, "id": project.name, "title": "Resume fixture", "style_version": "v1",
        "default_grade": "neutral", "archive_root": str(archive),
        "transcription": {"provider": "sidecar"}, "verification_transcription": {"provider": "synthetic"},
        "render_profile": {"width": 320, "height": 180, "fps": 25, "crf": 26, "preset": "ultrafast"},
        "telegram_delivery": {"enabled": False},
    }


def source_fixture(project: Path) -> None:
    source = make_video(project / "01_raw" / "01_camera.mp4", duration=1.4)
    atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
        "language": "en", "duration_s": 1.4,
        "segments": [{"id": "u1", "start": 0.2, "end": 1.1, "text": "resume keeps decisions", "decision": "keep"}],
    })


class ResumeFaultMatrixTests(unittest.TestCase):
    def test_phase1_resumes_after_ingest_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = make_project(root); source_fixture(project)
            config = base_config(project, root / "archive")
            atomic_write_json(project / "project.json", config); store = StateStore(project)
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                run_phase1(project, store, test_hook=lambda point: (_ for _ in ()).throw(RuntimeError("injected failure")) if point == "phase1.ingested" else None)
            self.assertEqual(store.read()["run"]["checkpoint"], "ingested")
            store.resume(); run_phase1(project, store)
            self.assertEqual(store.read()["state"], "GATE1_REVIEW")

    def test_phase3_reuses_verified_archive_after_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = make_project(root); source_fixture(project)
            config = base_config(project, root / "archive"); atomic_write_json(project / "project.json", config)
            store = StateStore(project)
            run_phase1(project, store); store.approve("gate1", reviewer="owner")
            run_phase2(project, store, verification_transcriber=RenderedTranscriptFake()); store.approve("gate2", reviewer="owner")
            with self.assertRaisesRegex(RuntimeError, "after archive"):
                run_phase3(project, store, test_hook=lambda point: (_ for _ in ()).throw(RuntimeError("after archive")) if point == "phase3.archive" else None)
            self.assertEqual(store.read()["state"], "FAILED_RECOVERABLE")
            final_job = JobLedger(project).read()["jobs"]["phase3.master-package"]
            self.assertEqual(final_job["status"], "COMPLETED")
            master = next((project / "05_final").glob("*.mp4"))
            master_mtime = master.stat().st_mtime_ns
            store.resume(); run_phase3(project, store)
            self.assertEqual(store.read()["state"], "FINAL_REVIEW")
            self.assertEqual(JobLedger(project).read()["jobs"]["phase3.master-package"]["attempt"], 1)
            self.assertEqual(master.stat().st_mtime_ns, master_mtime)
            receipt = read_json(project / "05_final" / "archive-receipt.json")
            self.assertTrue(receipt["reused_existing"])


    def test_phase2_resume_skips_completed_valid_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = make_project(root); source_fixture(project)
            config = base_config(project, root / "archive")
            atomic_write_json(project / "project.json", config)
            store = StateStore(project)
            run_phase1(project, store); store.approve("gate1", reviewer="owner")

            with self.assertRaisesRegex(RuntimeError, "after segment 01"):
                run_phase2(project, store, verification_transcriber=RenderedTranscriptFake(), test_hook=lambda point: (_ for _ in ()).throw(RuntimeError("after segment 01")) if point == "phase2.segment.01" else None)
            completed = JobLedger(project).read()["jobs"]["phase2.segment.01"]
            self.assertEqual(completed["status"], "COMPLETED")
            render = project / "04_phase2" / "segments" / "01" / "review.mp4"
            render_mtime = render.stat().st_mtime_ns

            store.resume(); run_phase2(project, store, verification_transcriber=RenderedTranscriptFake())

            resumed = JobLedger(project).read()["jobs"]["phase2.segment.01"]
            self.assertEqual(resumed["attempt"], 1)
            self.assertEqual(render.stat().st_mtime_ns, render_mtime)
            self.assertEqual(store.read()["state"], "GATE2_REVIEW")



    def test_phase1_resume_skips_completed_valid_segment_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = make_project(root); source_fixture(project)
            config = base_config(project, root / "archive")
            atomic_write_json(project / "project.json", config)
            store = StateStore(project)
            with patch.object(store, "prepare_gate", side_effect=RuntimeError("gate commit fault")):
                with self.assertRaisesRegex(RuntimeError, "gate commit fault"):
                    run_phase1(project, store)
            completed = JobLedger(project).read()["jobs"]["phase1.segment.01"]
            self.assertEqual(completed["status"], "COMPLETED")
            transcript = project / "03_phase1" / "segments" / "01" / "source-transcript.json"
            transcript_mtime = transcript.stat().st_mtime_ns

            store.resume(); run_phase1(project, store)

            resumed = JobLedger(project).read()["jobs"]["phase1.segment.01"]
            self.assertEqual(resumed["attempt"], 1)
            self.assertEqual(transcript.stat().st_mtime_ns, transcript_mtime)
            self.assertEqual(store.read()["state"], "GATE1_REVIEW")



if __name__ == "__main__":
    unittest.main()
