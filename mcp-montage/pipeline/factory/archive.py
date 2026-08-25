"""Verified archive copy with destination readback and atomic promotion."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable

from .io import sha256_file, utc_timestamp
from .media import validate_video


def _safe_archive_destination(archive_root: Path, project_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if not project_id or project_id in {".", ".."} or any(char not in allowed for char in project_id):
        raise ValueError(f"unsafe archive project id: {project_id!r}")
    destination = (archive_root / project_id).resolve()
    if not destination.is_relative_to(archive_root):
        raise ValueError("archive destination escapes archive_root")
    return destination


def archive_project(
    project_root: Path,
    *,
    archive_root: Path,
    project_id: str,
    master: Path,
    package_files: Iterable[Path],
    raw_files: Iterable[Path],
) -> dict[str, Any]:
    archive_root = archive_root.resolve()
    archive_root.mkdir(parents=True, exist_ok=True)
    final_dir = _safe_archive_destination(archive_root, project_id)
    temporary = archive_root / f".{project_id}.{uuid.uuid4().hex}.tmp"
    package_files = list(package_files)
    raw_files = list(raw_files)
    if final_dir.exists():
        existing_master = final_dir / "final" / master.name
        validate_video(existing_master)
        if sha256_file(existing_master) != sha256_file(master):
            raise ValueError(f"existing archive master does not match source: {final_dir}")
        entries = [{"role": "master", "source": str(master), "destination": str(existing_master), "sha256": sha256_file(master), "size_bytes": master.stat().st_size}]
        for role, sources, folder in (("publishing", package_files, "publishing-package"), ("raw", raw_files, "raw")):
            for source in sources:
                destination = final_dir / folder / source.name
                if not destination.is_file() or sha256_file(destination) != sha256_file(source):
                    raise ValueError(f"existing archive entry does not match source: {destination}")
                entries.append({"role": role, "source": str(source), "destination": str(destination), "sha256": sha256_file(source), "size_bytes": source.stat().st_size})
        return {
            "schema_version": 1, "verdict": "VERIFIED", "verified_at": utc_timestamp(),
            "archive_root": str(archive_root), "archive_directory": str(final_dir),
            "source_sha256": sha256_file(master), "destination_sha256": sha256_file(existing_master),
            "entries": entries, "reused_existing": True,
        }
    entries = []
    try:
        (temporary / "final").mkdir(parents=True)
        destination_master = temporary / "final" / master.name
        shutil.copy2(master, destination_master)
        validate_video(destination_master)
        source_hash = sha256_file(master)
        destination_hash = sha256_file(destination_master)
        if source_hash != destination_hash or master.stat().st_size != destination_master.stat().st_size:
            raise RuntimeError("archive master checksum/size mismatch")
        entries.append({
            "role": "master", "source": str(master), "destination": str(destination_master.relative_to(temporary)),
            "sha256": source_hash, "size_bytes": master.stat().st_size,
        })
        package_dir = temporary / "publishing-package"
        package_dir.mkdir()
        for source in package_files:
            destination = package_dir / source.name
            shutil.copy2(source, destination)
            if sha256_file(source) != sha256_file(destination):
                raise RuntimeError(f"archive package checksum mismatch: {source.name}")
            entries.append({"role": "publishing", "source": str(source), "destination": str(destination.relative_to(temporary)), "sha256": sha256_file(source), "size_bytes": source.stat().st_size})
        raw_dir = temporary / "raw"
        raw_dir.mkdir()
        for source in raw_files:
            destination = raw_dir / source.name
            shutil.copy2(source, destination)
            if sha256_file(source) != sha256_file(destination):
                raise RuntimeError(f"archive raw checksum mismatch: {source.name}")
            entries.append({"role": "raw", "source": str(source), "destination": str(destination.relative_to(temporary)), "sha256": sha256_file(source), "size_bytes": source.stat().st_size})
        os.replace(temporary, final_dir)
        for entry in entries:
            entry["destination"] = str(final_dir / entry["destination"])
        return {
            "schema_version": 1, "verdict": "VERIFIED", "verified_at": utc_timestamp(),
            "archive_root": str(archive_root), "archive_directory": str(final_dir),
            "source_sha256": source_hash, "destination_sha256": destination_hash,
            "entries": entries,
        }
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
