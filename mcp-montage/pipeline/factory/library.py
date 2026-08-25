"""Transactional local reusable-asset ingestion with provenance and rights metadata."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json, sha256_file, utc_timestamp


def ingest_approved_assets(project_root: Path, library_root: Path) -> dict[str, Any]:
    source_root = project_root / "02_inputs" / "broll" / "approved"
    library_root.mkdir(parents=True, exist_ok=True)
    catalog_path = library_root / "catalog.json"
    catalog = read_json(catalog_path) if catalog_path.exists() else {"schema_version": 2, "revision": 0, "assets": []}
    existing = {item["sha256"]: item for item in catalog["assets"]}
    ingested = []
    if source_root.is_dir():
        for source in sorted(path for path in source_root.iterdir() if path.is_file() and not path.name.endswith(".metadata.json")):
            metadata_path = source.with_suffix(source.suffix + ".metadata.json")
            if not metadata_path.is_file():
                raise ValueError(f"asset metadata is missing: {source.name}")
            metadata = read_json(metadata_path)
            if metadata.get("rights") not in {"owned", "licensed", "generated"}:
                raise ValueError(f"asset has no acceptable rights record: {source.name}")
            digest = sha256_file(source)
            if digest in existing:
                continue
            asset_id = f"asset-{digest.split(':', 1)[1][:16]}"
            destination = library_root / "originals" / f"{asset_id}{source.suffix.lower()}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if sha256_file(destination) != digest:
                destination.unlink(missing_ok=True)
                raise RuntimeError(f"library copy checksum mismatch: {source.name}")
            record = {
                "id": asset_id, "sha256": digest, "path": destination.relative_to(library_root).as_posix(),
                "description": metadata.get("description", ""), "tags": metadata.get("tags", []),
                "rights": metadata["rights"], "source_project": project_root.name,
                "ingested_at": utc_timestamp(), "provenance": metadata.get("provenance", str(source)),
            }
            catalog["assets"].append(record); existing[digest] = record; ingested.append(record)
    if ingested:
        catalog["revision"] += 1
        atomic_write_json(catalog_path, catalog)
    elif not catalog_path.exists():
        atomic_write_json(catalog_path, catalog)
    return {"schema_version": 1, "ingested": ingested, "catalog_revision": catalog["revision"]}
