"""Content-addressed dependency fingerprints and selective invalidation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import canonical_json_hash, read_json, sha256_file


def segment_fingerprint(
    project_root: Path,
    *,
    segment_id: str,
    raw_records: list[dict[str, Any]],
    transcript_path: Path,
    visual_plan_path: Path,
    sync_report_path: Path,
    grade_manifest_path: Path,
    style_version: str,
    provider_versions: dict[str, str],
    rule_versions: dict[str, str],
    render_profile: dict[str, Any],
) -> str:
    payload = {
        "segment_id": segment_id,
        "raw": sorted((item["id"], item["sha256"], item["role"]) for item in raw_records),
        "transcript": sha256_file(transcript_path),
        "visual_plan": sha256_file(visual_plan_path),
        "sync_report": sha256_file(sync_report_path),
        "grade_manifest": sha256_file(grade_manifest_path),
        "grade_selected": read_json(grade_manifest_path).get("selected"),
        "style_version": style_version,
        "provider_versions": provider_versions,
        "rule_versions": rule_versions,
        "render_profile": render_profile,
        "renderer_contract": "segment-renderer-v3",
    }
    return canonical_json_hash(payload)
