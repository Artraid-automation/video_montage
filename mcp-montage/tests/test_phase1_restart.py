from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.state import StateStore
from tests.helpers import gate1_manifest, make_project


class Phase1RestartTests(unittest.TestCase):
    def test_unapproved_gate1_can_be_superseded_for_provider_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="old")
            store.prepare_gate("gate1", gate1_manifest(project))
            ledger = store.restart_phase1(inputs_hash="new", reason="ASR provider upgrade")
            self.assertEqual(ledger["state"], "PHASE1_RUNNING")
            self.assertEqual(ledger["run"]["inputs_hash"], "new")
            self.assertEqual(ledger["gates"]["gate1"]["status"], "SUPERSEDED")

    def test_approved_gate1_cannot_be_restarted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp)); store = StateStore(project)
            store.ensure(); store.begin_phase("phase1", inputs_hash="old")
            store.prepare_gate("gate1", gate1_manifest(project)); store.approve("gate1", reviewer="owner")
            with self.assertRaisesRegex(ValueError, "cannot restart"):
                store.restart_phase1(inputs_hash="new", reason="too late")


if __name__ == "__main__":
    unittest.main()
