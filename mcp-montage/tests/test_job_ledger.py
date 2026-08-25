from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.jobs import JobLedger
from tests.helpers import make_project, write_text


class JobLedgerTests(unittest.TestCase):
    def test_completed_job_is_reused_only_with_matching_contract_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            output = write_text(project / "03_phase1" / "worker.txt", "result")
            jobs = JobLedger(project)

            jobs.start("phase1.worker", worker_version="worker-v1", fingerprint="sha256:input")
            jobs.complete(
                "phase1.worker",
                worker_version="worker-v1",
                fingerprint="sha256:input",
                outputs={"result": (output, "worker-result")},
                metadata={"value": 7},
            )

            reused = jobs.reusable("phase1.worker", worker_version="worker-v1", fingerprint="sha256:input")
            self.assertIsNotNone(reused)
            self.assertEqual(reused.metadata["value"], 7)
            self.assertIsNone(jobs.reusable("phase1.worker", worker_version="worker-v2", fingerprint="sha256:input"))
            self.assertIsNone(jobs.reusable("phase1.worker", worker_version="worker-v1", fingerprint="sha256:other"))

            output.write_text("corrupt", encoding="utf-8")
            self.assertIsNone(jobs.reusable("phase1.worker", worker_version="worker-v1", fingerprint="sha256:input"))

    def test_restarting_invalid_or_interrupted_job_increments_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            jobs = JobLedger(project)
            jobs.start("phase2.segment.01", worker_version="render-v1", fingerprint="sha256:a")
            jobs.start("phase2.segment.01", worker_version="render-v1", fingerprint="sha256:a")
            record = jobs.read()["jobs"]["phase2.segment.01"]
            self.assertEqual(record["status"], "RUNNING")
            self.assertEqual(record["attempt"], 2)


if __name__ == "__main__":
    unittest.main()
