from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.artifacts import artifact_record
from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.state import StateStore
from tests.helpers import gate1_manifest, gate2_manifest, make_project


class GateContractTests(unittest.TestCase):
    def test_gate1_missing_bundle_member_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            manifest_path = gate1_manifest(project)
            manifest = read_json(manifest_path)
            del manifest["segments"][0]["sync_report"]
            atomic_write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "missing required"):
                store.prepare_gate("gate1", manifest_path)

    def test_dummy_mp4_cannot_reach_gate2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            store.prepare_gate("gate1", gate1_manifest(project)); store.approve("gate1", reviewer="owner")
            store.begin_phase("phase2", inputs_hash="y")
            manifest = gate2_manifest(project, store.read()["gates"]["gate1"]["approval"], real_video=False)
            with self.assertRaises((ValueError, RuntimeError)):
                store.prepare_gate("gate2", manifest)

    def test_failing_qc_cannot_reach_gate2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="x")
            store.prepare_gate("gate1", gate1_manifest(project)); store.approve("gate1", reviewer="owner")
            store.begin_phase("phase2", inputs_hash="y")
            manifest_path = gate2_manifest(project, store.read()["gates"]["gate1"]["approval"])
            manifest = read_json(manifest_path)
            qc_path = project / manifest["segments"][0]["qc"]["path"]
            atomic_write_json(qc_path, {"schema_version": 1, "verdict": "FAIL"})
            manifest["segments"][0]["qc"] = artifact_record(project, qc_path, kind="segment-qc")
            atomic_write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "verdict"):
                store.prepare_gate("gate2", manifest_path)


if __name__ == "__main__":
    unittest.main()
