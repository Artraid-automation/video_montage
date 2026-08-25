"""Engine-independent visual plan construction."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable

from .broll import resolve_catalog_asset, search_catalog, stage_asset
from .transcript import compact_visual_id


VISUAL_PLANNER_VERSION = "visual-planner-v4"
SUPPORTED_TYPES = frozenset({"library-broll", "motion", "screen", "none"})
STABLE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _entry_id(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("id", ""))
    return str(getattr(entry, "id", ""))


def _entry_value(entry: Any, name: str, default: Any = None) -> Any:
    if isinstance(entry, dict):
        return entry.get(name, default)
    return getattr(entry, name, default)


def _automatic_visuals(segment_id: str, entries: list[Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Legacy cadence proposals. Off by default — Gate 1 visuals are agent-authored."""
    if not bool(config.get("enabled", False)):
        return []
    cadence = float(config.get("cadence_seconds", 30.0))
    maximum = int(config.get("max_per_segment", 6))
    if not math.isfinite(cadence) or cadence <= 0:
        raise ValueError("automatic visual cadence_seconds must be finite and positive")
    if maximum < 0 or maximum > 100:
        raise ValueError("automatic visual max_per_segment must be between 0 and 100")
    if maximum == 0:
        return []
    selected: list[dict[str, Any]] = []
    last_start: float | None = None
    for entry in entries:
        if str(_entry_value(entry, "kind", "keep")) != "keep":
            continue
        start = float(_entry_value(entry, "start_s", 0.0))
        if last_start is not None and start - last_start < cadence:
            continue
        anchor = _entry_id(entry)
        text = " ".join(str(_entry_value(entry, "text", "")).split())
        brief = text[:240] or f"Visual support for {anchor}"
        selected.append({
            "id": compact_visual_id(segment_id, len(selected) + 1),
            "anchor": anchor,
            "type": "library-broll",
            "brief": brief,
            "query": " ".join(text.split()[:16]) or anchor,
            "origin": "AUTO",
            "status": "PROPOSED",
        })
        last_start = start
        if len(selected) >= maximum:
            break
    return selected


def plan_visuals(
    segment_id: str,
    entries: Iterable[Any],
    configured: list[dict[str, Any]],
    *,
    library_root: Path | None = None,
    project_root: Path | None = None,
    auto_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry_values = list(entries)
    entry_ids = {_entry_id(item) for item in entry_values}
    if len(entry_ids) != len(entry_values) or any(not STABLE_ID_RE.fullmatch(item) for item in entry_ids):
        raise ValueError("visual planning requires unique schema-safe transcript entry ids")
    configured_values = list(configured)
    if not configured_values and auto_config is not None:
        configured_values = _automatic_visuals(segment_id, entry_values, auto_config)
    scenes: list[dict[str, Any]] = []
    searches: list[dict[str, Any]] = []
    for index, raw in enumerate(configured_values, 1):
        anchor = str(raw.get("anchor", ""))
        if anchor not in entry_ids:
            raise ValueError(f"configured visual references unknown anchor: {anchor}")
        visual_type = str(raw.get("type", "motion"))
        if visual_type not in SUPPORTED_TYPES:
            raise ValueError(f"unsupported visual type: {visual_type}")
        scene: dict[str, Any] = {
            "id": str(raw.get("id") or compact_visual_id(segment_id, index)),
            "anchor": anchor,
            "type": visual_type,
            "brief": str(raw.get("brief", "")),
            "asset": raw.get("asset"),
            "resolution": "CONFIGURED",
            "origin": str(raw.get("origin", "CONFIGURED")),
            "status": "PROPOSED",
        }
        if not STABLE_ID_RE.fullmatch(scene["id"]):
            raise ValueError(f"visual id is not schema-safe: {scene['id']}")
        if visual_type == "library-broll":
            query = str(raw.get("query") or scene["brief"]).strip()
            if library_root is None or project_root is None:
                if scene["origin"] != "AUTO":
                    raise ValueError("library-broll requires library_root and project_root")
                result = {
                    "schema_version": 1, "kind": "broll-search-results", "catalog_revision": 0,
                    "query": query, "matches": [], "rejected": [],
                }
            elif scene["asset"]:
                match = resolve_catalog_asset(library_root, str(scene["asset"]))
                result = {
                    "schema_version": 1, "kind": "broll-search-results",
                    "catalog_revision": match["catalog_revision"], "query": f"id:{match['asset_id']}",
                    "matches": [match], "rejected": [],
                }
            else:
                result = search_catalog(library_root, query, limit=3) if (library_root / "catalog.json").is_file() else {
                    "schema_version": 1, "kind": "broll-search-results", "catalog_revision": 0,
                    "query": query, "matches": [], "rejected": [],
                }
            searches.append({"visual_id": scene["id"], **result})
            if result["matches"]:
                match = result["matches"][0]
                scene["asset"] = stage_asset(library_root, project_root, match)
                scene["catalog_asset_id"] = match["asset_id"]
                scene["asset_sha256"] = match["sha256"]
                scene["resolution"] = "LIBRARY_MATCH"
            else:
                scene["type"] = "motion"
                scene["asset"] = None
                scene["resolution"] = "MOTION_FALLBACK"
                scene["brief"] = scene["brief"] or query
        if any(existing["id"] == scene["id"] for existing in scenes):
            raise ValueError(f"duplicate visual id: {scene['id']}")
        scenes.append(scene)
    return {
        "schema_version": 1,
        "kind": "visual-plan",
        "worker_version": VISUAL_PLANNER_VERSION,
        "segment_id": segment_id,
        "status": "PROPOSED" if scenes else "NO_VISUALS_PROPOSED",
        "scenes": scenes,
        "searches": searches,
    }
