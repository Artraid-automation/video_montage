"""Verified lexical search over the local B-roll catalog."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from .io import read_json, resolve_project_path, sha256_file, working_output
from .senses import sense_query_expansion, senses_catalog_path


SEARCH_WORKER_VERSION = "broll-lexical-search-v2-senses"
ALLOWED_RIGHTS = frozenset({"owned", "licensed", "generated"})
ASSET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[\w']+", value.casefold(), flags=re.UNICODE))


def _validated_assets(library_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    root = library_root.resolve(strict=True)
    catalog = read_json(root / "catalog.json")
    if catalog.get("schema_version") != 2 or not isinstance(catalog.get("assets"), list):
        raise ValueError("unsupported B-roll catalog schema")
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in catalog["assets"]:
        asset_id = str(raw.get("id", ""))
        reason: str | None = None
        if not ASSET_ID_RE.fullmatch(asset_id) or asset_id in seen:
            reason = "invalid-or-duplicate-id"
        else:
            seen.add(asset_id)
        if reason is None and raw.get("rights") not in ALLOWED_RIGHTS:
            reason = "rights-not-allowed"
        if reason is None and not str(raw.get("provenance", "")).strip():
            reason = "provenance-missing"
        path: Path | None = None
        if reason is None:
            relative = Path(str(raw.get("path", "")))
            if relative.is_absolute() or ".." in relative.parts:
                reason = "path-outside-library"
            else:
                try:
                    path = (root / relative).resolve(strict=True)
                except (FileNotFoundError, OSError):
                    reason = "file-missing"
                else:
                    if not path.is_relative_to(root):
                        reason = "path-outside-library"
                    elif not path.is_file():
                        reason = "not-a-regular-file"
        if reason is None:
            try:
                digest = sha256_file(path)
            except OSError:
                reason = "file-unreadable"
            else:
                if not isinstance(raw.get("sha256"), str) or digest != raw["sha256"]:
                    reason = "checksum-mismatch"
        if reason is not None:
            rejected.append({"asset_id": asset_id, "reason": reason})
            continue
        valid.append({**raw, "resolved_path": path})
    return catalog, valid, rejected


def search_catalog(library_root: Path, query: str, *, limit: int = 5) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("search limit must be positive")
    senses_path = senses_catalog_path(library_root)
    expanded = sense_query_expansion(query, catalog_path=senses_path if senses_path.is_file() else None)
    query_terms = _terms(expanded)
    if not query_terms:
        raise ValueError("B-roll search query is empty")
    catalog, assets, rejected = _validated_assets(library_root)
    matches = []
    for asset in assets:
        tag_terms = _terms(" ".join(str(item) for item in asset.get("tags", [])))
        description_terms = _terms(str(asset.get("description", "")))
        tag_hits = sorted(query_terms & tag_terms)
        description_hits = sorted(query_terms & description_terms)
        score = 3 * len(tag_hits) + len(description_hits)
        if not score:
            continue
        matches.append({
            "asset_id": asset["id"],
            "path": str(asset["path"]),
            "sha256": asset["sha256"],
            "rights": asset["rights"],
            "provenance": asset["provenance"],
            "score": score,
            "matched_tags": tag_hits,
            "matched_description": description_hits,
        })
    matches.sort(key=lambda item: (-item["score"], item["asset_id"]))
    return {
        "schema_version": 1,
        "kind": "broll-search-results",
        "worker_version": SEARCH_WORKER_VERSION,
        "catalog_revision": int(catalog.get("revision", 0)),
        "query": query,
        "expanded_query": expanded,
        "matches": matches[:limit],
        "rejected": sorted(rejected, key=lambda item: (item["asset_id"], item["reason"])),
    }


def resolve_catalog_asset(library_root: Path, asset_id: str) -> dict[str, Any]:
    """Resolve one catalog ID only after the same safety checks used by search."""
    if not ASSET_ID_RE.fullmatch(asset_id):
        raise ValueError("invalid B-roll asset id")
    catalog, assets, rejected = _validated_assets(library_root)
    selected = next((item for item in assets if item["id"] == asset_id), None)
    if selected is None:
        reason = next((item["reason"] for item in rejected if item["asset_id"] == asset_id), "asset-not-found")
        raise ValueError(f"B-roll asset is unavailable: {asset_id} ({reason})")
    return {
        "asset_id": selected["id"], "path": selected["path"], "sha256": selected["sha256"],
        "rights": selected["rights"], "provenance": selected["provenance"],
        "catalog_revision": int(catalog.get("revision", 0)),
    }


def stage_asset(library_root: Path, project_root: Path, match: dict[str, Any]) -> str:
    """Copy a verified result into project inputs and return a renderer-safe path."""
    _, assets, _ = _validated_assets(library_root)
    selected = next((item for item in assets if item["id"] == match.get("asset_id")), None)
    if selected is None or selected["sha256"] != match.get("sha256"):
        raise ValueError("B-roll match is stale or no longer authorized")
    root = project_root.resolve(strict=True)
    relative = f"02_inputs/broll/selected/{selected['id']}{selected['resolved_path'].suffix.lower()}"
    destination = resolve_project_path(root, relative, must_exist=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256_file(destination) == selected["sha256"]:
        return relative
    with working_output(destination) as temporary:
        shutil.copy2(selected["resolved_path"], temporary)
        if sha256_file(temporary) != selected["sha256"]:
            raise RuntimeError("staged B-roll checksum mismatch")
    return relative
