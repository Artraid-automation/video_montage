"""Agent-authored sense catalog — lexical search only (no embedding models)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import read_json

SEARCH_WORKER_VERSION = "sense-lexical-v1"


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[\w'#]+", value.casefold(), flags=re.UNICODE))


def senses_catalog_path(library_root: Path | None = None, *, repo_root: Path | None = None) -> Path:
    if library_root is not None:
        candidate = Path(library_root).resolve()
        # library/broll → sibling senses; or library/senses directly
        if candidate.name == "broll":
            return candidate.parent / "senses" / "catalog.json"
        if candidate.name == "senses":
            return candidate / "catalog.json"
        return candidate / "senses" / "catalog.json"
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / "library" / "senses" / "catalog.json"


def load_sense_catalog(path: Path | None = None) -> dict[str, Any]:
    catalog_path = path or senses_catalog_path()
    data = read_json(catalog_path)
    if data.get("schema_version") != 1 or data.get("kind") != "sense-catalog":
        raise ValueError(f"unsupported sense catalog: {catalog_path}")
    if not isinstance(data.get("senses"), list):
        raise ValueError("sense catalog missing senses list")
    return data


def search_senses(
    query: str,
    *,
    catalog: dict[str, Any] | None = None,
    catalog_path: Path | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    query_terms = _terms(query)
    if not query_terms:
        raise ValueError("sense search query is empty")
    data = catalog or load_sense_catalog(catalog_path)
    scored: list[tuple[int, dict[str, Any]]] = []
    for sense in data["senses"]:
        blob = " ".join(
            [
                str(sense.get("id", "")),
                str(sense.get("title", "")),
                " ".join(str(t) for t in sense.get("tags", [])),
                " ".join(str(t) for t in sense.get("situations", [])),
                " ".join(str(t) for t in sense.get("motion_hints", [])),
                " ".join(str(t) for t in sense.get("broll_hints", [])),
            ]
        )
        hay = _terms(blob)
        overlap = query_terms & hay
        if not overlap:
            continue
        scored.append((len(overlap), {**sense, "matched_terms": sorted(overlap)}))
    scored.sort(key=lambda item: (-item[0], item[1].get("id", "")))
    matches = [item for _, item in scored[:limit]]
    return {
        "schema_version": 1,
        "kind": "sense-search-results",
        "worker_version": SEARCH_WORKER_VERSION,
        "query": query,
        "matches": matches,
    }


def sense_query_expansion(query: str, *, catalog_path: Path | None = None, limit: int = 3) -> str:
    """Append tags from top sense matches so lexical B-roll search can use them later."""
    try:
        result = search_senses(query, catalog_path=catalog_path, limit=limit)
    except ValueError:
        return query
    tags: list[str] = []
    for match in result["matches"]:
        for tag in match.get("tags", []):
            cleaned = str(tag).lstrip("#")
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
    if not tags:
        return query
    return f"{query} {' '.join(tags)}"
