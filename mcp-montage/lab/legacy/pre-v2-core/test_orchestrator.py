from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from orchestrator import (
    accept_final, approve, fail_recoverable, finalize, load_state,
    mark_final_review, mark_gate_ready, resume, start,
)


class OrchestratorTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        project = root / "pilot"
        project.mkdir()
        (project / "project.json").write_text(json.dumps({"id": "pilot"}), encoding="utf-8")
        return project

    def test_gate_cannot_be_skipped_and_approval_is_bound_to_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            self.assertEqual(start(project)["state"], "PHASE1_RUNNING")
            with self.assertRaisesRegex(ValueError, "cannot approve"):
                approve(project, "gate1")

            review = project / "03_phase1" / "review.md"
            review.parent.mkdir()
            review.write_text("ready", encoding="utf-8")
            self.assertEqual(mark_gate_ready(project, "gate1", [review])["state"], "GATE1_REVIEW")
            review.write_text("changed after review", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed or missing"):
                approve(project, "gate1")

    def test_gate_approval_and_recoverable_resume_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            start(project)
            review = project / "03_phase1" / "review.md"
            review.parent.mkdir()
            review.write_text("ready", encoding="utf-8")
            mark_gate_ready(project, "gate1", [review])
            self.assertEqual(approve(project, "gate1", reviewer="owner")["state"], "PHASE2_RUNNING")
            self.assertEqual(fail_recoverable(project, "renderer stopped")["state"], "FAILED_RECOVERABLE")
            self.assertEqual(resume(project)["state"], "PHASE2_RUNNING")
            self.assertEqual(load_state(project)["last_error"], None)
            self.assertEqual(len((project / "06_state" / "approvals.jsonl").read_text(encoding="utf-8").splitlines()), 1)


    def test_complete_product_state_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            start(project)
            phase1 = project / "03_phase1" / "review.md"
            phase1.parent.mkdir()
            phase1.write_text("phase 1", encoding="utf-8")
            mark_gate_ready(project, "gate1", [phase1])
            approve(project, "gate1")
            phase2 = project / "04_phase2" / "review.md"
            phase2.parent.mkdir()
            phase2.write_text("phase 2 verified", encoding="utf-8")
            mark_gate_ready(project, "gate2", [phase2])
            self.assertEqual(approve(project, "gate2")["state"], "PHASE3_READY")
            self.assertEqual(finalize(project)["state"], "PHASE3_RUNNING")
            master = project / "05_final" / "master.mp4"
            master.parent.mkdir()
            master.write_bytes(b"verified master fixture")
            mark_final_review(project, [master])
            self.assertEqual(accept_final(project)["state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
