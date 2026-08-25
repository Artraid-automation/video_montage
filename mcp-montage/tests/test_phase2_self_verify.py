from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.media import validate_video
from pipeline.factory.phase1 import run_phase1
from pipeline.factory.phase2 import run_phase2
from pipeline.factory.state import StateStore
from tests.fakes import RenderedTranscriptFake
from tests.helpers import make_project, make_video


def prepare_project(root: Path, *, transcript_fault: str | None = None) -> tuple[Path, StateStore]:
    project = make_project(root)
    config = {
        "schema_version": 2, "id": project.name, "title": "Synthetic",
        "style_version": "test-v1", "default_grade": "neutral",
        "transcription": {"provider": "sidecar"},
        "verification_transcription": {"provider": "synthetic"},
        "render_profile": {"width": 320, "height": 180, "fps": 25, "crf": 25, "preset": "ultrafast"},
        "visuals": {"01": [{"anchor": "u2", "type": "motion", "brief": "Verified motion card"}]},
    }
    if transcript_fault:
        config["fault_injection"] = {"transcript": {"01": transcript_fault}}
    atomic_write_json(project / "project.json", config)
    source = make_video(project / "01_raw" / "01_camera.mp4", duration=2.2)
    atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
        "language": "en", "duration_s": 2.2,
        "segments": [
            {"id": "u1", "start": 0.1, "end": 0.6, "text": "discard this start", "decision": "cut", "reason": "false-start"},
            {"id": "u2", "start": 0.8, "end": 1.9, "text": "keep this final useful sentence", "decision": "keep"},
        ],
    })
    store = StateStore(project)
    run_phase1(project, store)
    store.approve("gate1", reviewer="test-owner")
    return project, store


class Phase2IntegrationTests(unittest.TestCase):
    def test_render_is_retranscribed_verified_and_stops_at_gate2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, store = prepare_project(Path(temp))
            manifest_path = run_phase2(project, store, verification_transcriber=RenderedTranscriptFake())
            self.assertEqual(store.read()["state"], "GATE2_REVIEW")
            manifest = read_json(manifest_path)
            render = project / manifest["segments"][0]["render"]["path"]
            validate_video(render)
            verification = read_json(project / "04_phase2" / "segments" / "01" / "verification.json")
            self.assertEqual(verification["verdict"], "PASS")
            self.assertEqual(verification["metrics"]["wer"], 0.0)
            probes = read_json(project / "04_phase2" / "segments" / "01" / "qc.json")["frame_integrity"]
            self.assertGreaterEqual(len(probes["frames"]), 3)

    def test_intentional_retranscription_deletion_blocks_gate2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, store = prepare_project(Path(temp), transcript_fault="delete")
            with self.assertRaisesRegex(ValueError, "self-verification failed"):
                run_phase2(project, store, verification_transcriber=RenderedTranscriptFake("delete"))
            self.assertEqual(store.read()["state"], "FAILED_RECOVERABLE")
            self.assertNotIn("gate2", store.read()["gates"])


if __name__ == "__main__":
    unittest.main()
