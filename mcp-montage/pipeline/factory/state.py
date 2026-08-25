"""Durable, locked state ledger with typed gate transitions."""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable

from .artifacts import GATE_VALIDATORS, artifact_record, validate_gate1_approval, validate_gate2_approval, validate_record
from .io import FileLock, atomic_write_json, canonical_json_hash, read_json, utc_timestamp


STATE_DIR = "06_state"
LEDGER_FILE = "ledger.json"

STATES = {
    "NEW", "PHASE1_RUNNING", "GATE1_REVIEW", "PHASE2_PENDING", "PHASE2_RUNNING",
    "GATE2_REVIEW", "REVISIONS_RUNNING", "PHASE3_READY", "PHASE3_RUNNING",
    "FINAL_REVIEW", "COMPLETED", "FAILED_RECOVERABLE",
}

PHASE_STATES = {"phase1": "PHASE1_RUNNING", "phase2": "PHASE2_RUNNING", "phase3": "PHASE3_RUNNING"}
GATE_REVIEW_STATES = {"gate1": "GATE1_REVIEW", "gate2": "GATE2_REVIEW", "final": "FINAL_REVIEW"}
GATE_ALLOWED_FROM = {
    "gate1": {"PHASE1_RUNNING", "GATE1_REVIEW"},
    "gate2": {"PHASE2_RUNNING", "REVISIONS_RUNNING"},
    "final": {"PHASE3_RUNNING", "REVISIONS_RUNNING"},
}


def initial_ledger(project_id: str) -> dict[str, Any]:
    now = utc_timestamp()
    return {
        "schema_version": 2,
        "project_id": project_id,
        "revision": 0,
        "state": "NEW",
        "updated_at": now,
        "run": None,
        "gates": {},
        "approvals": [],
        "revision_request": None,
        "last_error": None,
        "events": [{"id": uuid.uuid4().hex, "at": now, "type": "state_created", "state": "NEW", "details": {}}],
    }


def validate_ledger(value: dict[str, Any]) -> None:
    required = {"schema_version", "project_id", "revision", "state", "updated_at", "run", "gates", "approvals", "revision_request", "last_error", "events"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError(f"invalid state ledger; missing={sorted(required - set(value))}")
    if value["schema_version"] != 2 or value["state"] not in STATES:
        raise ValueError("unsupported state ledger version or state")
    if not isinstance(value["revision"], int) or value["revision"] < 0:
        raise ValueError("state revision must be a non-negative integer")
    if not isinstance(value["events"], list) or not value["events"]:
        raise ValueError("state ledger must contain events")
    event_ids = [item.get("id") for item in value["events"]]
    if None in event_ids or len(event_ids) != len(set(event_ids)):
        raise ValueError("state ledger contains invalid or duplicate event ids")


class StateStore:
    def __init__(self, project_root: Path):
        self.root = project_root.resolve(strict=True)
        self.state_dir = self.root / STATE_DIR
        self.path = self.state_dir / LEDGER_FILE
        self.lock_path = self.state_dir / "ledger.lock"

    def ensure(self) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock_path):
            if self.path.exists():
                return self._read()
            metadata_path = self.root / "project.json"
            project_id = self.root.name
            if metadata_path.is_file():
                metadata = read_json(metadata_path)
                project_id = metadata.get("id", project_id)
            allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            if not project_id or project_id in {".", ".."} or any(char not in allowed for char in project_id):
                raise ValueError(f"unsafe project id: {project_id!r}")
            ledger = initial_ledger(project_id)
            atomic_write_json(self.path, ledger)
            return copy.deepcopy(ledger)

    def _read(self) -> dict[str, Any]:
        value = read_json(self.path)
        validate_ledger(value)
        return value

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self.ensure()
        return copy.deepcopy(self._read())

    def mutate(
        self,
        event_type: str,
        mutator: Callable[[dict[str, Any]], None],
        *,
        expected_revision: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with FileLock(self.lock_path):
            ledger = self._read()
            if expected_revision is not None and ledger["revision"] != expected_revision:
                raise RuntimeError(f"concurrent state update: expected revision {expected_revision}, current {ledger['revision']}")
            before_state = ledger["state"]
            mutator(ledger)
            if ledger["state"] not in STATES:
                raise ValueError(f"mutator produced unknown state: {ledger['state']}")
            ledger["revision"] += 1
            ledger["updated_at"] = utc_timestamp()
            ledger["events"].append({
                "id": uuid.uuid4().hex,
                "at": ledger["updated_at"],
                "type": event_type,
                "state": ledger["state"],
                "details": {"previous_state": before_state, **(details or {})},
            })
            validate_ledger(ledger)
            atomic_write_json(self.path, ledger)
            return copy.deepcopy(ledger)

    def begin_phase(self, phase: str, *, inputs_hash: str, expected_revision: int | None = None) -> dict[str, Any]:
        if phase not in PHASE_STATES:
            raise ValueError(f"unknown phase: {phase}")
        allowed = {"phase1": {"NEW"}, "phase2": {"PHASE2_PENDING"}, "phase3": {"PHASE3_READY"}}[phase]

        def change(ledger: dict[str, Any]) -> None:
            if ledger["state"] == PHASE_STATES[phase] and ledger.get("run", {}).get("inputs_hash") == inputs_hash:
                raise AlreadyApplied(ledger)
            if ledger["state"] not in allowed:
                raise ValueError(f"cannot begin {phase} from {ledger['state']}")
            ledger["state"] = PHASE_STATES[phase]
            ledger["run"] = {
                "id": uuid.uuid4().hex, "phase": phase, "attempt": 1, "checkpoint": "started",
                "inputs_hash": inputs_hash, "started_at": utc_timestamp(), "heartbeat_at": utc_timestamp(),
            }
            ledger["last_error"] = None

        try:
            return self.mutate(f"{phase}_started", change, expected_revision=expected_revision, details={"inputs_hash": inputs_hash})
        except AlreadyApplied as done:
            return copy.deepcopy(done.ledger)


    def restart_phase1(self, *, inputs_hash: str, reason: str) -> dict[str, Any]:
        """Supersede an unapproved Gate 1 and start a fresh fingerprinted run."""
        if not reason.strip():
            raise ValueError("Phase 1 restart requires a reason")
        current = self.read()

        def change(ledger: dict[str, Any]) -> None:
            if ledger["state"] != "GATE1_REVIEW":
                raise ValueError(f"cannot restart Phase 1 from {ledger['state']}")
            gate = ledger.get("gates", {}).get("gate1")
            if not gate or gate.get("status") != "READY":
                raise ValueError("only an unapproved ready Gate 1 can be superseded")
            gate["status"] = "SUPERSEDED"
            gate["superseded_at"] = utc_timestamp()
            gate["superseded_reason"] = reason
            ledger["state"] = "PHASE1_RUNNING"
            ledger["run"] = {"id": uuid.uuid4().hex, "phase": "phase1", "attempt": 1, "checkpoint": "started", "inputs_hash": inputs_hash, "started_at": utc_timestamp(), "heartbeat_at": utc_timestamp()}
            ledger["last_error"] = None

        return self.mutate("gate1_superseded", change, expected_revision=current["revision"], details={"reason": reason, "inputs_hash": inputs_hash})

    def checkpoint(self, name: str, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        def change(ledger: dict[str, Any]) -> None:
            if ledger["state"] not in set(PHASE_STATES.values()) | {"REVISIONS_RUNNING"} or not ledger["run"]:
                raise ValueError(f"no active worker to checkpoint in {ledger['state']}")
            ledger["run"]["checkpoint"] = name
            ledger["run"]["heartbeat_at"] = utc_timestamp()
            if evidence is not None:
                ledger["run"].setdefault("evidence", {})[name] = evidence

        return self.mutate("checkpoint", change, details={"checkpoint": name})

    def fail(self, message: str, *, retryable: bool = True) -> dict[str, Any]:
        def change(ledger: dict[str, Any]) -> None:
            if ledger["state"] not in set(PHASE_STATES.values()) | {"REVISIONS_RUNNING"}:
                raise ValueError(f"cannot fail inactive state {ledger['state']}")
            ledger["last_error"] = {"message": message, "retryable": retryable, "at": utc_timestamp()}
            ledger["state"] = "FAILED_RECOVERABLE" if retryable else ledger["state"]

        return self.mutate("worker_failed", change, details={"message": message, "retryable": retryable})

    def resume(self) -> dict[str, Any]:
        def change(ledger: dict[str, Any]) -> None:
            if ledger["state"] != "FAILED_RECOVERABLE" or not ledger["run"]:
                raise ValueError(f"cannot resume from {ledger['state']}")
            phase = ledger["run"]["phase"]
            target = "REVISIONS_RUNNING" if phase == "revision" else PHASE_STATES[phase]
            ledger["state"] = target
            ledger["run"]["attempt"] += 1
            ledger["run"]["heartbeat_at"] = utc_timestamp()
            ledger["last_error"] = None

        return self.mutate("worker_resumed", change)

    def prepare_gate(self, gate: str, manifest_path: Path) -> dict[str, Any]:
        if gate not in GATE_VALIDATORS:
            raise ValueError(f"unknown gate: {gate}")
        manifest_path = manifest_path.resolve(strict=True)
        manifest = read_json(manifest_path)
        current = self.read()
        if current["state"] not in GATE_ALLOWED_FROM[gate]:
            raise ValueError(f"cannot prepare {gate} from {current['state']}")
        if current["state"] == "REVISIONS_RUNNING":
            expected_gate = (current.get("revision_request") or {}).get("return_gate")
            if expected_gate != gate:
                raise ValueError(f"revision must return to {expected_gate}, not {gate}")
        if manifest.get("project_id") != current["project_id"]:
            raise ValueError("gate manifest project_id does not match state ledger")
        GATE_VALIDATORS[gate](self.root, manifest)
        record = artifact_record(self.root, manifest_path, kind=f"{gate}-manifest" if gate != "final" else "final-manifest")

        def change(ledger: dict[str, Any]) -> None:
            if ledger["state"] not in GATE_ALLOWED_FROM[gate]:
                raise ValueError(f"state changed before gate commit: {ledger['state']}")
            ledger["gates"][gate] = {"status": "READY", "manifest": record, "manifest_content_hash": canonical_json_hash(manifest), "prepared_at": utc_timestamp()}
            ledger["state"] = GATE_REVIEW_STATES[gate]
            ledger["run"] = None
            if gate == (current.get("revision_request") or {}).get("return_gate"):
                ledger["revision_request"] = None

        return self.mutate("gate_ready", change, expected_revision=current["revision"], details={"gate": gate, "manifest": record})

    def _validate_ready_gate(self, ledger: dict[str, Any], gate: str) -> tuple[dict[str, Any], dict[str, Any]]:
        gate_state = ledger.get("gates", {}).get(gate)
        if not gate_state or gate_state.get("status") != "READY":
            raise ValueError(f"{gate} is not ready")
        manifest_path = validate_record(self.root, gate_state["manifest"])
        manifest = read_json(manifest_path)
        if canonical_json_hash(manifest) != gate_state["manifest_content_hash"]:
            raise ValueError(f"{gate} manifest content hash changed")
        GATE_VALIDATORS[gate](self.root, manifest)
        return gate_state, manifest

    def approve(
        self,
        gate: str,
        *,
        reviewer: str,
        accepted_exceptions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if gate not in GATE_REVIEW_STATES:
            raise ValueError(f"unknown gate: {gate}")
        current = self.read()
        if current["state"] != GATE_REVIEW_STATES[gate]:
            for approval in reversed(current["approvals"]):
                if approval["gate"] == gate and current["state"] in {"PHASE2_PENDING", "PHASE3_READY", "COMPLETED"}:
                    return current
            raise ValueError(f"cannot approve {gate} from {current['state']}")
        gate_state, manifest = self._validate_ready_gate(current, gate)
        if gate == "gate1":
            validate_gate1_approval(self.root, manifest)
        elif gate == "gate2":
            validate_gate2_approval(self.root, manifest)
        approval_payload = {
            "schema_version": 2,
            "project_id": current["project_id"],
            "gate": gate,
            "reviewer": reviewer,
            "approved_at": utc_timestamp(),
            "ledger_revision": current["revision"],
            "manifest": gate_state["manifest"],
            "manifest_content_hash": gate_state["manifest_content_hash"],
            "style_version": manifest.get("style_version"),
            "provider_versions": manifest.get("provider_versions", {}),
            "accepted_exceptions": accepted_exceptions or [],
        }
        approval_path = self.state_dir / "approvals" / f"{gate}-r{current['revision']:06d}.json"
        atomic_write_json(approval_path, approval_payload)
        approval_record = artifact_record(self.root, approval_path, kind="approval")
        target = {"gate1": "PHASE2_PENDING", "gate2": "PHASE3_READY", "final": "COMPLETED"}[gate]

        def change(ledger: dict[str, Any]) -> None:
            self._validate_ready_gate(ledger, gate)
            ledger["gates"][gate]["status"] = "APPROVED"
            ledger["gates"][gate]["approval"] = approval_record
            ledger["approvals"].append({"gate": gate, "record": approval_record, "approved_at": approval_payload["approved_at"]})
            ledger["state"] = target

        try:
            return self.mutate("gate_approved", change, expected_revision=current["revision"], details={"gate": gate, "approval": approval_record})
        except Exception:
            approval_path.unlink(missing_ok=True)
            raise

    def assert_approval_current(self, gate: str) -> dict[str, Any]:
        ledger = self.read()
        gate_state = ledger.get("gates", {}).get(gate)
        if not gate_state or gate_state.get("status") != "APPROVED":
            raise ValueError(f"required approval is not current: {gate}")
        validate_record(self.root, gate_state["approval"], "approval")
        manifest_path = validate_record(self.root, gate_state["manifest"])
        manifest = read_json(manifest_path)
        if canonical_json_hash(manifest) != gate_state["manifest_content_hash"]:
            raise ValueError(f"approved {gate} manifest changed")
        GATE_VALIDATORS[gate](self.root, manifest)
        return gate_state

    def request_revision(self, scope: list[str], notes_record: dict[str, Any]) -> dict[str, Any]:
        current = self.read()
        if current["state"] not in {"GATE2_REVIEW", "FINAL_REVIEW"}:
            raise ValueError(f"cannot request revision from {current['state']}")
        return_gate = "gate2" if current["state"] == "GATE2_REVIEW" else "final"

        def change(ledger: dict[str, Any]) -> None:
            validate_record(self.root, notes_record, "revision-notes")
            ledger["revision_request"] = {"return_gate": return_gate, "scope": scope, "notes": notes_record, "requested_at": utc_timestamp()}
            ledger["state"] = "REVISIONS_RUNNING"
            ledger["run"] = {"id": uuid.uuid4().hex, "phase": "revision", "attempt": 1, "checkpoint": "started", "inputs_hash": notes_record["sha256"], "started_at": utc_timestamp(), "heartbeat_at": utc_timestamp()}

        return self.mutate("revision_requested", change, expected_revision=current["revision"], details={"scope": scope, "return_gate": return_gate})


class AlreadyApplied(Exception):
    def __init__(self, ledger: dict[str, Any]):
        self.ledger = ledger
        super().__init__("operation already applied")
