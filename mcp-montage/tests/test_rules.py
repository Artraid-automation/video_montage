from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.rules import promote_rule
from tests.helpers import make_project, write_text


class RulePromotionTests(unittest.TestCase):
    def test_rule_requires_reviewed_proposal_and_regression_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = make_project(Path(temp))
            proposals = project / "02_inputs" / "rules" / "proposals.json"
            atomic_write_json(proposals, {"schema_version": 1, "proposals": [{
                "id": "rule-001", "scope": "profile", "description": "normalize phrase", "status": "PROPOSED",
                "operation": "replace_text", "match": "bad", "replacement": "good",
            }]})
            fixture = write_text(project / "02_inputs" / "rules" / "fixtures" / "pip.json", '{"schema_version":1,"cases":[{"input":"bad example","expected":"good example"}]}')
            promoted = promote_rule(project, proposal_id="rule-001", reviewer="owner", regression_fixture=fixture)
            self.assertEqual(promoted["status"], "APPROVED")
            approved = read_json(project / "02_inputs" / "rules" / "ledger.json")
            self.assertTrue(approved["version"].startswith("sha256:"))
            with self.assertRaisesRegex(ValueError, "pending rule proposal"):
                promote_rule(project, proposal_id="rule-001", reviewer="owner", regression_fixture=fixture)


if __name__ == "__main__":
    unittest.main()
