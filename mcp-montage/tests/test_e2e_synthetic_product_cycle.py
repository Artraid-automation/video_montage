from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json, read_json
from tests.helpers import make_project, make_video


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "pipeline" / "studio.py"


def cli(*args: object) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(CLI), *(str(item) for item in args)], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(f"CLI failed: {args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


class SyntheticProductCycleTests(unittest.TestCase):
    def test_cli_runs_both_human_gates_to_completed_master(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = make_project(root); archive = root / "archive"
            atomic_write_json(project / "project.json", {
                "schema_version": 2, "id": project.name, "title": "CLI E2E", "style_version": "v1",
                "default_grade": "neutral", "archive_root": str(archive),
                "transcription": {"provider": "sidecar"}, "verification_transcription": {"provider": "external-command", "command": [sys.executable, str(ROOT / "tests" / "render_asr_command.py")], "version": "fixture-v1"},
                "render_profile": {"width": 320, "height": 180, "fps": 25, "crf": 26, "preset": "ultrafast"},
                "publishing": {"title": "CLI Product", "description": "E2E", "chapter_titles": {"01": "Start"}},
            })
            source = make_video(project / "01_raw" / "01_camera.mp4", duration=1.5, with_face=True)
            atomic_write_json(source.with_suffix(source.suffix + ".transcript.json"), {
                "language": "en", "duration_s": 1.5,
                "segments": [{"id": "u1", "start": 0.2, "end": 1.2, "text": "complete product cycle", "decision": "keep"}],
            })
            self.assertIn("GATE1_REVIEW", cli("start", project).stdout)
            self.assertIn("GATE2_REVIEW", cli("approve", project, "gate1", "--reviewer", "owner").stdout)
            cli("approve", project, "gate2", "--reviewer", "owner")
            self.assertIn("FINAL_REVIEW", cli("finalize", project).stdout)
            cli("accept-final", project, "--reviewer", "owner")
            status = read_json(project / "06_state" / "ledger.json")
            self.assertEqual(status["state"], "COMPLETED")
            final = read_json(project / "05_final" / "final-manifest.json")
            self.assertTrue((project / final["master"]["path"]).is_file())
            self.assertTrue((archive / project.name).is_dir())


if __name__ == "__main__":
    unittest.main()
