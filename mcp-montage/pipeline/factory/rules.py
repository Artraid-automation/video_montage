"""Atomic reviewed rule promotion with executable failing-before/passing-after evidence."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import artifact_record
from .io import FileLock, atomic_write_json, canonical_json_hash, read_json, utc_timestamp


def _apply(rule: dict[str, Any], value: str) -> str:
    operation = rule.get("operation")
    if operation == "replace_text":
        match = str(rule.get("match", ""))
        if not match:
            raise ValueError("replace_text rule requires non-empty match")
        return value.replace(match, str(rule.get("replacement", "")))
    if operation == "reject_text":
        return "REJECTED" if str(rule.get("match", "")) in value else value
    raise ValueError(f"unsupported executable rule operation: {operation!r}")


def _run_regression(proposal: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    if fixture.get("schema_version") != 1 or not isinstance(fixture.get("cases"), list) or not fixture["cases"]:
        raise ValueError("regression fixture requires non-empty versioned cases")
    results = []
    for index, case in enumerate(fixture["cases"], 1):
        source = str(case["input"])
        expected = str(case["expected"])
        before = source
        after = _apply(proposal, source)
        baseline = before == expected
        treatment = after == expected
        results.append({"case": index, "baseline_pass": baseline, "treatment_pass": treatment, "actual_before": before, "actual_after": after, "expected": expected})
    if any(item["baseline_pass"] for item in results) or not all(item["treatment_pass"] for item in results):
        raise ValueError("rule regression must fail every baseline and pass every treatment")
    return {"verdict": "PASS", "results": results}


def load_approved_rules(project_root: Path) -> dict[str, Any]:
    path = project_root / "02_inputs" / "rules" / "ledger.json"
    return read_json(path) if path.exists() else {"schema_version": 2, "revision": 0, "proposals": [], "approved": [], "version": canonical_json_hash([])}



def add_rule_proposals(project_root: Path, proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules_root = project_root / "02_inputs" / "rules"
    rules_root.mkdir(parents=True, exist_ok=True)
    ledger_path = rules_root / "ledger.json"
    with FileLock(rules_root / "ledger.lock"):
        ledger = load_approved_rules(project_root)
        existing = {item["id"] for item in ledger["proposals"]}
        added = []
        for raw in proposals:
            proposal = dict(raw)
            description = str(proposal.get("description", ""))
            match = __import__("re").fullmatch(r'replace-text\s+match=("[^"]*"|\S+)\s+replacement=("[^"]*"|\S+)', description)
            if not match:
                raise ValueError("rule candidate must be executable replace-text match=... replacement=...")
            values = [value[1:-1] if value.startswith('"') else value for value in match.groups()]
            proposal.update({"operation": "replace_text", "match": values[0], "replacement": values[1], "status": "PROPOSED"})
            proposal["id"] = f"{proposal.get('source_segment', 'project')}-{proposal['id']}"
            if proposal["id"] in existing:
                continue
            existing.add(proposal["id"]); ledger["proposals"].append(proposal); added.append(proposal)
        if added:
            ledger["revision"] += 1
            atomic_write_json(ledger_path, ledger)
        return added

def promote_rule(project_root: Path, *, proposal_id: str, reviewer: str, regression_fixture: Path) -> dict[str, Any]:
    rules_root = project_root / "02_inputs" / "rules"
    rules_root.mkdir(parents=True, exist_ok=True)
    ledger_path = rules_root / "ledger.json"
    lock_path = rules_root / "ledger.lock"
    with FileLock(lock_path):
        ledger = load_approved_rules(project_root)
        # One-time import keeps old proposals readable while the durable format becomes one ledger.
        old = rules_root / "proposals.json"
        if old.exists() and not ledger["proposals"]:
            ledger["proposals"] = read_json(old).get("proposals", [])
        proposal = next((item for item in ledger["proposals"] if item.get("id") == proposal_id), None)
        if proposal is None or proposal.get("status") != "PROPOSED":
            raise ValueError(f"pending rule proposal does not exist: {proposal_id}")
        fixture = read_json(regression_fixture)
        regression = _run_regression(proposal, fixture)
        fixture_record = artifact_record(project_root, regression_fixture, kind="rule-regression-fixture")
        promoted = {**proposal, "status": "APPROVED", "reviewer": reviewer, "approved_at": utc_timestamp(), "regression_fixture": fixture_record, "regression": regression}
        ledger["revision"] += 1
        ledger["approved"].append(promoted)
        proposal["status"] = "PROMOTED"
        ledger["version"] = canonical_json_hash(ledger["approved"])
        atomic_write_json(ledger_path, ledger)
        return promoted