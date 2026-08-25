"""Durable product-level state machine for the three-phase video pipeline."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


STATE_DIR = "06_state"
STATE_FILE = "project-state.json"
EVENTS_FILE = "events.jsonl"
APPROVALS_FILE = "approvals.jsonl"

RUNNING_STATES = {"PHASE1_RUNNING", "PHASE2_RUNNING", "REVISIONS_RUNNING", "PHASE3_RUNNING"}
GATE_STATES = {"gate1": "GATE1_REVIEW", "gate2": "GATE2_REVIEW"}
GATE_TARGETS = {"gate1": "PHASE2_RUNNING", "gate2": "PHASE3_READY"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def state_path(project_root: Path) -> Path:
    return project_root.resolve() / STATE_DIR / STATE_FILE


def load_state(project_root: Path) -> dict[str, Any]:
    path = state_path(project_root)
    if not path.is_file():
        raise ValueError(f"project state does not exist: {path}; run start first")
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _event(project_root: Path, state: dict[str, Any], event: str, **details: Any) -> None:
    _append_jsonl(project_root / STATE_DIR / EVENTS_FILE, {
        "at": utc_now(), "project_id": state["project_id"], "event": event,
        "state": state["state"], "details": details,
    })


def ensure_state(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    if not project_root.is_dir():
        raise ValueError(f"project directory does not exist: {project_root}")
    path = state_path(project_root)
    if path.exists():
        return load_state(project_root)
    metadata_path = project_root / "project.json"
    project_id = project_root.name
    if metadata_path.is_file():
        project_id = json.loads(metadata_path.read_text(encoding="utf-8")).get("id", project_id)
    state = {
        "schema_version": 1,
        "project_id": project_id,
        "state": "NEW",
        "revision": 0,
        "updated_at": utc_now(),
        "active_gate": None,
        "gate_artifacts": {},
        "last_error": None,
        "recover_to": None,
    }
    _write_json(path, state)
    _event(project_root, state, "state_created")
    return state


def transition(project_root: Path, expected: Iterable[str], target: str, event: str, **details: Any) -> dict[str, Any]:
    project_root = project_root.resolve()
    state = load_state(project_root)
    expected_set = set(expected)
    if state["state"] not in expected_set:
        raise ValueError(f"cannot {event}: state is {state['state']}, expected {sorted(expected_set)}")
    previous = state["state"]
    state.update({"state": target, "revision": state["revision"] + 1, "updated_at": utc_now()})
    _write_json(state_path(project_root), state)
    _event(project_root, state, event, previous_state=previous, **details)
    return state


def start(project_root: Path) -> dict[str, Any]:
    state = ensure_state(project_root)
    if state["state"] != "NEW":
        raise ValueError(f"cannot start: state is {state['state']}; use status or resume")
    return transition(project_root, {"NEW"}, "PHASE1_RUNNING", "phase1_started")


def mark_gate_ready(project_root: Path, gate: str, artifacts: Iterable[Path]) -> dict[str, Any]:
    """Worker API: validate artifacts and stop the product at a human gate."""
    if gate not in GATE_STATES:
        raise ValueError(f"unknown gate: {gate}")
    expected = "PHASE1_RUNNING" if gate == "gate1" else "PHASE2_RUNNING"
    project_root = project_root.resolve()
    records = []
    for raw_path in artifacts:
        path = raw_path.resolve()
        if not path.is_file() or not path.is_relative_to(project_root):
            raise ValueError(f"gate artifact must be an existing project file: {path}")
        records.append({"path": path.relative_to(project_root).as_posix(), "hash": artifact_hash(path)})
    if not records:
        raise ValueError("a gate requires at least one human-facing artifact")
    state = load_state(project_root)
    if state["state"] != expected:
        raise ValueError(f"cannot prepare {gate}: state is {state['state']}, expected {expected}")
    state["gate_artifacts"][gate] = records
    state["active_gate"] = gate
    state.update({"state": GATE_STATES[gate], "revision": state["revision"] + 1, "updated_at": utc_now()})
    _write_json(state_path(project_root), state)
    _event(project_root, state, "gate_ready", gate=gate, artifacts=records)
    return state


def approve(project_root: Path, gate: str, reviewer: str = "user") -> dict[str, Any]:
    if gate not in GATE_STATES:
        raise ValueError(f"unknown gate: {gate}")
    project_root = project_root.resolve()
    state = load_state(project_root)
    if state["state"] != GATE_STATES[gate] or state.get("active_gate") != gate:
        raise ValueError(f"cannot approve {gate}: state is {state['state']}")
    artifacts = state.get("gate_artifacts", {}).get(gate, [])
    if not artifacts:
        raise ValueError(f"cannot approve {gate}: no bound artifacts")
    for record in artifacts:
        path = project_root / record["path"]
        if not path.is_file() or artifact_hash(path) != record["hash"]:
            raise ValueError(f"cannot approve {gate}: artifact changed or missing: {record['path']}")
    approval = {
        "schema_version": 1, "project_id": state["project_id"], "gate": gate,
        "approved_at": utc_now(), "reviewer": reviewer, "artifacts": artifacts,
    }
    _append_jsonl(project_root / STATE_DIR / APPROVALS_FILE, approval)
    state["active_gate"] = None
    state.update({"state": GATE_TARGETS[gate], "revision": state["revision"] + 1, "updated_at": utc_now()})
    _write_json(state_path(project_root), state)
    _event(project_root, state, "gate_approved", gate=gate, reviewer=reviewer)
    return state


def request_revision(project_root: Path) -> dict[str, Any]:
    return transition(project_root, {"GATE2_REVIEW", "FINAL_REVIEW"}, "REVISIONS_RUNNING", "revision_requested")


def finalize(project_root: Path) -> dict[str, Any]:
    return transition(project_root, {"PHASE3_READY"}, "PHASE3_RUNNING", "phase3_started")


def mark_final_review(project_root: Path, artifacts: Iterable[Path]) -> dict[str, Any]:
    """Worker API: bind master/QC/archive evidence and stop for final acceptance."""
    project_root = project_root.resolve()
    state = load_state(project_root)
    if state["state"] != "PHASE3_RUNNING":
        raise ValueError(f"cannot prepare final review: state is {state['state']}")
    records = []
    for raw_path in artifacts:
        path = raw_path.resolve()
        if not path.is_file() or not path.is_relative_to(project_root):
            raise ValueError(f"final artifact must be an existing project file: {path}")
        records.append({"path": path.relative_to(project_root).as_posix(), "hash": artifact_hash(path)})
    if not records:
        raise ValueError("final review requires bound master/QC/archive evidence")
    state["gate_artifacts"]["final"] = records
    state["active_gate"] = "final"
    state.update({"state": "FINAL_REVIEW", "revision": state["revision"] + 1, "updated_at": utc_now()})
    _write_json(state_path(project_root), state)
    _event(project_root, state, "final_review_ready", artifacts=records)
    return state


def accept_final(project_root: Path, reviewer: str = "user") -> dict[str, Any]:
    project_root = project_root.resolve()
    state = load_state(project_root)
    if state["state"] != "FINAL_REVIEW" or state.get("active_gate") != "final":
        raise ValueError(f"cannot accept final: state is {state['state']}")
    artifacts = state.get("gate_artifacts", {}).get("final", [])
    if not artifacts:
        raise ValueError("cannot accept final: no bound artifacts")
    for record in artifacts:
        path = project_root / record["path"]
        if not path.is_file() or artifact_hash(path) != record["hash"]:
            raise ValueError(f"cannot accept final: artifact changed or missing: {record['path']}")
    acceptance = {"schema_version": 1, "project_id": state["project_id"], "gate": "final", "approved_at": utc_now(), "reviewer": reviewer, "artifacts": artifacts}
    _append_jsonl(project_root / STATE_DIR / APPROVALS_FILE, acceptance)
    state["active_gate"] = None
    state.update({"state": "COMPLETED", "revision": state["revision"] + 1, "updated_at": utc_now()})
    _write_json(state_path(project_root), state)
    _event(project_root, state, "final_accepted", reviewer=reviewer)
    return state


def fail_recoverable(project_root: Path, message: str) -> dict[str, Any]:
    state = load_state(project_root)
    if state["state"] not in RUNNING_STATES:
        raise ValueError(f"cannot record recoverable failure from {state['state']}")
    recover_to = state["state"]
    state.update({
        "state": "FAILED_RECOVERABLE", "recover_to": recover_to, "last_error": message,
        "revision": state["revision"] + 1, "updated_at": utc_now(),
    })
    _write_json(state_path(project_root), state)
    _event(project_root, state, "recoverable_failure", recover_to=recover_to, message=message)
    return state


def resume(project_root: Path) -> dict[str, Any]:
    state = load_state(project_root)
    target = state.get("recover_to")
    if state["state"] != "FAILED_RECOVERABLE" or target not in RUNNING_STATES:
        raise ValueError(f"cannot resume from {state['state']}")
    state.update({
        "state": target, "recover_to": None, "last_error": None,
        "revision": state["revision"] + 1, "updated_at": utc_now(),
    })
    _write_json(state_path(project_root), state)
    _event(project_root, state, "resumed")
    return state
