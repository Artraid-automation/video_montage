from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from pipeline.factory.artifacts import artifact_record
from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.state import StateStore
from tests.helpers import gate1_manifest, gate2_manifest, make_project, make_video


class EvidenceBindingTests(unittest.TestCase):
    def test_old_verification_cannot_be_reused_for_changed_render(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            store.prepare_gate("gate1", gate1_manifest(project)); store.approve("gate1", reviewer="owner")
            store.begin_phase("phase2", inputs_hash="y")
            manifest_path = gate2_manifest(project, store.read()["gates"]["gate1"]["approval"])
            manifest = read_json(manifest_path)
            render = project / manifest["segments"][0]["render"]["path"]
            make_video(render, duration=0.9, color="red")
            manifest["segments"][0]["render"] = artifact_record(project, render, kind="segment-render")
            atomic_write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "stale"):
                store.prepare_gate("gate2", manifest_path)

    def test_corrupted_archive_blocks_final_approval(self) -> None:
        # Covered at product level by validate_final's destination readback; this fixture
        # asserts the destination, not merely the local receipt, is authoritative.
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            store.prepare_gate("gate1", gate1_manifest(project)); store.approve("gate1", reviewer="owner")
            store.begin_phase("phase2", inputs_hash="y")
            gate2 = gate2_manifest(project, store.read()["gates"]["gate1"]["approval"])
            store.prepare_gate("gate2", gate2); store.approve("gate2", reviewer="owner")
            from tests.helpers import final_manifest
            final = final_manifest(project, store.read()["gates"]["gate2"]["approval"], "sha256:segment")
            receipt = read_json(project / "05_final" / "archive-receipt.json")
            Path(receipt["entries"][0]["destination"]).write_bytes(b"corrupted")
            store.begin_phase("phase3", inputs_hash="z")
            with self.assertRaisesRegex(ValueError, "changed after verification"):
                store.prepare_gate("final", final)


    def test_fake_gate1_approval_and_expected_transcript_binding_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            store.prepare_gate("gate1", gate1_manifest(project)); store.approve("gate1", reviewer="owner")
            store.begin_phase("phase2", inputs_hash="y")
            manifest_path = gate2_manifest(project, store.read()["gates"]["gate1"]["approval"])
            manifest = read_json(manifest_path)
            fake = project / "06_state" / "fake-approval.json"
            atomic_write_json(fake, {"schema_version": 2, "gate": "gate1"})
            manifest["gate1_approval"] = artifact_record(project, fake, kind="approval")
            atomic_write_json(manifest_path, manifest)
            with self.assertRaises(ValueError):
                store.prepare_gate("gate2", manifest_path)

            manifest = read_json(gate2_manifest(project, store.read()["gates"]["gate1"]["approval"]))
            verification_path = project / manifest["segments"][0]["verification"]["path"]
            verification = read_json(verification_path)
            verification["bindings"]["expected_transcript_sha256"] = "sha256:forged"
            atomic_write_json(verification_path, verification)
            manifest["segments"][0]["verification"] = artifact_record(project, verification_path, kind="transcript-verification")
            atomic_write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "stale"):
                store.prepare_gate("gate2", manifest_path)

    def test_final_segment_lineage_must_equal_approved_gate2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            store.prepare_gate("gate1", gate1_manifest(project)); store.approve("gate1", reviewer="owner")
            store.begin_phase("phase2", inputs_hash="y")
            gate2 = gate2_manifest(project, store.read()["gates"]["gate1"]["approval"])
            store.prepare_gate("gate2", gate2); store.approve("gate2", reviewer="owner")
            from tests.helpers import final_manifest
            final = final_manifest(project, store.read()["gates"]["gate2"]["approval"], "sha256:forged")
            store.begin_phase("phase3", inputs_hash="z")
            with self.assertRaisesRegex(ValueError, "lineage"):
                store.prepare_gate("final", final)

if __name__ == "__main__":
    unittest.main()
