"""Atomic persistence, hashes, locks, and workspace path safety."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterator


def utc_timestamp() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read valid JSON from {path}: {exc}") from exc


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_project_path(project_root: Path, relative: str, *, must_exist: bool = True) -> Path:
    root = project_root.resolve(strict=True)
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe project-relative path: {relative}")
    path = (root / candidate).resolve(strict=must_exist)
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes project root: {relative}")
    current = root
    for part in candidate.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError(f"symlink is not allowed in artifact path: {relative}")
    return path


class FileLock:
    def __init__(self, path: Path, timeout_s: float = 10.0, stale_s: float = 300.0):
        self.path = path
        self.timeout_s = timeout_s
        self.stale_s = stale_s
        self.fd: int | None = None

    def _break_stale(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age > self.stale_s:
            self.path.unlink(missing_ok=True)

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, json.dumps({"pid": os.getpid(), "at": utc_timestamp()}).encode("utf-8"))
                os.fsync(self.fd)
                return self
            except FileExistsError:
                self._break_stale()
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for state lock: {self.path}")
                time.sleep(0.02)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)


@contextlib.contextmanager
def working_output(final_path: Path) -> Iterator[Path]:
    """Yield a same-directory temp path and atomically promote it on success."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = final_path.with_name(f".{final_path.stem}.{uuid.uuid4().hex}.tmp{final_path.suffix}")
    try:
        yield temporary
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError(f"worker produced no usable output: {temporary}")
        os.replace(temporary, final_path)
    finally:
        temporary.unlink(missing_ok=True)
