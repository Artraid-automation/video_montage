"""Durable worker-job ledger used for safe, content-addressed resume.

The state ledger owns product transitions.  This ledger owns only worker execution:
whether an idempotent unit of work may be reused, and which immutable outputs prove
that it completed under a particular worker contract.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import artifact_record, validate_record
from .io import FileLock, atomic_write_json, read_json, utc_timestamp


JOBS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ReusableJob:
    job_id: str
    outputs: dict[str, Path]
    metadata: dict[str, Any]
    attempt: int


class JobLedger:
    """Atomic ledger for versioned, independently resumable worker jobs."""

    def __init__(self, project_root: Path):
        self.root = project_root.resolve(strict=True)
        state_dir = self.root / "06_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "jobs.json"
        self.lock_path = state_dir / "jobs.lock"

    @staticmethod
    def _initial() -> dict[str, Any]:
        return {"schema_version": JOBS_SCHEMA_VERSION, "revision": 0, "jobs": {}}

    @staticmethod
    def _validate(value: dict[str, Any]) -> None:
        if not isinstance(value, dict) or value.get("schema_version") != JOBS_SCHEMA_VERSION:
            raise ValueError("unsupported jobs ledger schema")
        if not isinstance(value.get("revision"), int) or value["revision"] < 0:
            raise ValueError("jobs ledger revision must be a non-negative integer")
        if not isinstance(value.get("jobs"), dict):
            raise ValueError("jobs ledger must contain a jobs object")
        for job_id, job in value["jobs"].items():
            required = {"id", "status", "worker_version", "fingerprint", "attempt", "updated_at"}
            if not isinstance(job, dict) or not required.issubset(job) or job["id"] != job_id:
                raise ValueError(f"invalid job record: {job_id}")
            if job["status"] not in {"RUNNING", "COMPLETED", "FAILED"}:
                raise ValueError(f"invalid job status: {job_id}")
            if not isinstance(job["attempt"], int) or job["attempt"] < 1:
                raise ValueError(f"invalid job attempt: {job_id}")

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._initial()
        value = read_json(self.path)
        self._validate(value)
        return value

    def read(self) -> dict[str, Any]:
        with FileLock(self.lock_path):
            return copy.deepcopy(self._read_unlocked())

    def _write_unlocked(self, value: dict[str, Any]) -> None:
        value["revision"] += 1
        self._validate(value)
        atomic_write_json(self.path, value)

    def start(self, job_id: str, *, worker_version: str, fingerprint: str) -> dict[str, Any]:
        if not job_id or not worker_version or not fingerprint:
            raise ValueError("job id, worker version, and fingerprint are required")
        with FileLock(self.lock_path):
            ledger = self._read_unlocked()
            previous = ledger["jobs"].get(job_id)
            attempt = int(previous.get("attempt", 0)) + 1 if previous else 1
            now = utc_timestamp()
            ledger["jobs"][job_id] = {
                "id": job_id,
                "execution_id": uuid.uuid4().hex,
                "status": "RUNNING",
                "worker_version": worker_version,
                "fingerprint": fingerprint,
                "attempt": attempt,
                "started_at": now,
                "updated_at": now,
                "outputs": {},
                "metadata": {},
            }
            self._write_unlocked(ledger)
            return copy.deepcopy(ledger["jobs"][job_id])

    def complete(
        self,
        job_id: str,
        *,
        worker_version: str,
        fingerprint: str,
        outputs: dict[str, tuple[Path, str]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not outputs:
            raise ValueError("completed job must declare at least one output")
        records = {
            name: artifact_record(self.root, path, kind=kind)
            for name, (path, kind) in outputs.items()
        }
        with FileLock(self.lock_path):
            ledger = self._read_unlocked()
            job = ledger["jobs"].get(job_id)
            if not job or job["status"] != "RUNNING":
                raise ValueError(f"job is not running: {job_id}")
            if job["worker_version"] != worker_version or job["fingerprint"] != fingerprint:
                raise ValueError(f"job contract changed while running: {job_id}")
            job["status"] = "COMPLETED"
            job["outputs"] = records
            job["metadata"] = copy.deepcopy(metadata or {})
            job["updated_at"] = utc_timestamp()
            job["completed_at"] = job["updated_at"]
            self._write_unlocked(ledger)
            return copy.deepcopy(job)

    def fail(self, job_id: str, message: str) -> None:
        with FileLock(self.lock_path):
            ledger = self._read_unlocked()
            job = ledger["jobs"].get(job_id)
            if not job or job["status"] != "RUNNING":
                return
            job["status"] = "FAILED"
            job["error"] = message
            job["updated_at"] = utc_timestamp()
            self._write_unlocked(ledger)

    def reusable(self, job_id: str, *, worker_version: str, fingerprint: str) -> ReusableJob | None:
        """Return a completed job only after all output records validate now."""
        with FileLock(self.lock_path):
            ledger = self._read_unlocked()
            job = copy.deepcopy(ledger["jobs"].get(job_id))
        if not job or job["status"] != "COMPLETED":
            return None
        if job["worker_version"] != worker_version or job["fingerprint"] != fingerprint:
            return None
        outputs = job.get("outputs")
        if not isinstance(outputs, dict) or not outputs:
            return None
        try:
            resolved = {name: validate_record(self.root, record) for name, record in outputs.items()}
        except (OSError, ValueError):
            return None
        return ReusableJob(job_id, resolved, copy.deepcopy(job.get("metadata", {})), int(job["attempt"]))
