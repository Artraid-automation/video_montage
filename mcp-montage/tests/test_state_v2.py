from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.artifacts import artifact_record
from pipeline.factory.io import canonical_json_hash, read_json
from pipeline.factory.state import StateStore
from tests.helpers import final_manifest, gate1_manifest, gate2_manifest, make_project, write_text


class StateV2Tests(unittest.TestCase):
    def test_typed_full_transition_and_idempotent_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            store = StateStore(project)
            self.assertEqual(store.ensure()["state"], "NEW")
            store.begin_phase("phase1", inputs_hash="sha256:inputs")
            gate1 = gate1_manifest(project)
            self.assertEqual(store.prepare_gate("gate1", gate1)["state"], "GATE1_REVIEW")
            approved1 = store.approve("gate1", reviewer="owner")
            self.assertEqual(approved1["state"], "PHASE2_PENDING")
            self.assertEqual(store.approve("gate1", reviewer="owner")["revision"], approved1["revision"])

            store.assert_approval_current("gate1")
            store.begin_phase("phase2", inputs_hash="sha256:phase2")
            gate1_approval = store.read()["gates"]["gate1"]["approval"]
            gate2 = gate2_manifest(project, gate1_approval)
            store.prepare_gate("gate2", gate2)
            store.approve("gate2", reviewer="owner")
            store.begin_phase("phase3", inputs_hash="sha256:phase3")
            segment_hash = read_json(gate2)["segments"][0]["render"]["sha256"]
            final = final_manifest(project, store.read()["gates"]["gate2"]["approval"], segment_hash)
            store.prepare_gate("final", final)
            self.assertEqual(store.approve("final", reviewer="owner")["state"], "COMPLETED")

    def test_approved_artifact_mutation_blocks_next_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="sha256:inputs")
            gate1 = gate1_manifest(project)
            store.prepare_gate("gate1", gate1); store.approve("gate1", reviewer="owner")
            transcript = project / "03_phase1" / "segments" / "01" / "transcript.md"
            transcript.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed"):
                store.assert_approval_current("gate1")

    def test_revision_returns_to_correct_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            store.prepare_gate("gate1", gate1_manifest(project)); store.approve("gate1", reviewer="owner")
            store.begin_phase("phase2", inputs_hash="y")
            gate2 = gate2_manifest(project, store.read()["gates"]["gate1"]["approval"])
            store.prepare_gate("gate2", gate2)
            notes = write_text(project / "04_phase2" / "revision-notes.md", "[fix blocking] segment 01\n")
            state = store.request_revision(["01"], artifact_record(project, notes, kind="revision-notes"))
            self.assertEqual(state["revision_request"]["return_gate"], "gate2")
            updated = read_json(gate2); updated["revision"] = 2
            from pipeline.factory.io import atomic_write_json
            atomic_write_json(gate2, updated)
            self.assertEqual(store.prepare_gate("gate2", gate2)["state"], "GATE2_REVIEW")

    def test_cas_rejects_stale_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            store = StateStore(project)
            revision = store.ensure()["revision"]
            store.begin_phase("phase1", inputs_hash="x", expected_revision=revision)
            with self.assertRaisesRegex(RuntimeError, "concurrent"):
                store.mutate("stale", lambda ledger: None, expected_revision=revision)

    def test_recoverable_resume_preserves_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            store.checkpoint("transcribed", evidence={"segments": 2})
            store.fail("provider timeout")
            resumed = store.resume()
            self.assertEqual(resumed["state"], "PHASE1_RUNNING")
            self.assertEqual(resumed["run"]["checkpoint"], "transcribed")
            self.assertEqual(resumed["run"]["attempt"], 2)


if __name__ == "__main__":
    unittest.main()
