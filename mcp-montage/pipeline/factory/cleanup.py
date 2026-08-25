"""Recoverable cleanup with an immutable file allowlist and resumable journal."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .io import atomic_write_json, canonical_json_hash, read_json, resolve_project_path, sha256_file, utc_timestamp
from .state import StateStore

WORK_DIRS = ("03_phase1", "04_phase2")


def _snapshot(project_root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for directory in WORK_DIRS:
        root = resolve_project_path(project_root, directory)
        if root.is_symlink() or root.is_junction():
            raise ValueError(f"cleanup rejects link/reparse directory: {root}")
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.is_symlink():
                raise ValueError(f"cleanup rejects symlink: {path}")
            files.append({"path": path.relative_to(project_root).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return files


def cleanup_dry_run(project_root: Path, store: StateStore | None = None) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve(strict=True)
    store = store or StateStore(project_root)
    ledger = store.read()
    if ledger["state"] != "COMPLETED":
        raise ValueError("cleanup requires COMPLETED state")
    store.assert_approval_current("final")
    files = _snapshot(project_root)
    plan = {"schema_version": 2, "project_id": ledger["project_id"], "created_at": utc_timestamp(), "mode": "quarantine", "files": files, "total_bytes": sum(item["size_bytes"] for item in files), "final_approval_sha256": ledger["gates"]["final"]["approval"]["sha256"]}
    plan["confirmation_hash"] = canonical_json_hash(plan)
    path = project_root / "06_state" / "cleanup-plan.json"
    atomic_write_json(path, plan)
    return path, plan


def execute_cleanup(project_root: Path, confirmation_hash: str, store: StateStore | None = None) -> Path:
    project_root = project_root.resolve(strict=True)
    store = store or StateStore(project_root)
    plan_path = project_root / "06_state" / "cleanup-plan.json"
    plan = read_json(plan_path)
    expected = plan.pop("confirmation_hash")
    if confirmation_hash != expected or canonical_json_hash(plan) != expected:
        raise ValueError("cleanup confirmation hash is invalid or plan changed")
    store.assert_approval_current("final")
    current = _snapshot(project_root)
    if current != plan["files"]:
        raise ValueError("cleanup inputs changed after dry-run; create a new plan")
    quarantine = project_root / "07_quarantine" / plan["created_at"].replace(":", "-")
    quarantine.mkdir(parents=True, exist_ok=True)
    journal_path = project_root / "06_state" / "cleanup-journal.json"
    journal = {"schema_version": 1, "plan_hash": expected, "status": "RUNNING", "entries": []}
    atomic_write_json(journal_path, journal)
    try:
        for item in plan["files"]:
            source = resolve_project_path(project_root, item["path"])
            destination = (quarantine / item["path"]).resolve()
            if not destination.is_relative_to(quarantine.resolve()):
                raise ValueError("cleanup destination escaped quarantine")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            journal["entries"].append({**item, "destination": str(destination), "status": "MOVED"})
            atomic_write_json(journal_path, journal)
        for directory in WORK_DIRS:
            root = resolve_project_path(project_root, directory)
            for child in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
                child.rmdir()
            root.mkdir(exist_ok=True)
        journal["status"] = "QUARANTINED"
        journal["completed_at"] = utc_timestamp()
        atomic_write_json(journal_path, journal)
        receipt = quarantine / "cleanup-receipt.json"
        atomic_write_json(receipt, {**plan, "verdict": "QUARANTINED", "journal": journal, "completed_at": journal["completed_at"]})
        return receipt
    except Exception:
        for entry in reversed(journal["entries"]):
            destination = Path(entry["destination"])
            source = resolve_project_path(project_root, entry["path"])
            source.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and not source.exists():
                os.replace(destination, source)
        journal["status"] = "ROLLED_BACK"
        atomic_write_json(journal_path, journal)
        raise