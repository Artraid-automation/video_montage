"""Typed artifact records and gate-specific validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .io import canonical_json_hash, read_json, resolve_project_path, sha256_file
from .media import validate_video
from .transcript import parse_fixes
from .broll import ALLOWED_RIGHTS
from .contracts import CrossSegmentTakeAnalysis, EditorialAnalysis, QcReport, SyncReport, TranscriptVerification
from .style_guard import validate_visual_plan_style_wiring


def artifact_record(project_root: Path, path: Path, *, kind: str) -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"artifact is outside project: {resolved}")
    relative = resolved.relative_to(root).as_posix()
    resolve_project_path(root, relative)
    return {"kind": kind, "path": relative, "sha256": sha256_file(resolved), "size_bytes": resolved.stat().st_size}


def validate_record(project_root: Path, record: dict[str, Any], expected_kind: str | None = None) -> Path:
    required = {"kind", "path", "sha256", "size_bytes"}
    if not isinstance(record, dict) or not required.issubset(record):
        raise ValueError(f"invalid artifact record; required={sorted(required)}")
    if expected_kind and record["kind"] != expected_kind:
        raise ValueError(f"artifact kind is {record['kind']}, expected {expected_kind}")
    try:
        path = resolve_project_path(project_root, record["path"])
    except OSError as exc:
        raise ValueError(f"artifact is missing: {record['path']}") from exc
    if not path.is_file():
        raise ValueError(f"artifact is not a file: {record['path']}")
    if path.stat().st_size != record["size_bytes"] or sha256_file(path) != record["sha256"]:
        raise ValueError(f"artifact changed after manifest creation: {record['path']}")
    return path


def _require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(keys - set(value))
    if missing:
        raise ValueError(f"{label} is missing required fields: {missing}")


def _validate_json_verdict(project_root: Path, record: dict[str, Any], kind: str, allowed: set[str]) -> dict[str, Any]:
    path = validate_record(project_root, record, kind)
    payload = read_json(path)
    verdict = payload.get("verdict")
    if verdict not in allowed:
        raise ValueError(f"{kind} verdict is {verdict!r}, expected one of {sorted(allowed)}")
    return payload


def validate_gate1(project_root: Path, manifest: dict[str, Any]) -> None:
    _require_keys(manifest, {"schema_version", "kind", "project_id", "revision", "style_version", "provider_versions", "review", "cross_segment_take_analysis", "film_continuity", "segments"}, "gate1 manifest")
    if manifest["schema_version"] != 1 or manifest["kind"] != "gate1":
        raise ValueError("invalid gate1 schema version or kind")
    validate_record(project_root, manifest["review"], "gate1-review")
    if not isinstance(manifest["provider_versions"], dict) or not manifest["provider_versions"]:
        raise ValueError("gate1 provider_versions must be non-empty")
    if not manifest["segments"]:
        raise ValueError("gate1 requires at least one segment")
    cross_take_path = validate_record(
        project_root, manifest["cross_segment_take_analysis"], "cross-segment-take-analysis"
    )
    cross_take_analysis = CrossSegmentTakeAnalysis.parse(read_json(cross_take_path))
    continuity_path = validate_record(project_root, manifest["film_continuity"], "film-continuity")
    continuity = read_json(continuity_path)
    if continuity.get("kind") != "film-continuity" or continuity.get("schema_version") != 1:
        raise ValueError("invalid film-continuity artifact")
    if continuity.get("verdict") not in {"PASS", "BLOCKED"}:
        raise ValueError(f"film continuity verdict is {continuity.get('verdict')!r}")
    seen: set[str] = set()
    required = {"id", "source_transcript", "editorial_analysis", "transcript", "sync_report", "grade_manifest", "visual_plan", "broll_assets"}
    for segment in manifest["segments"]:
        _require_keys(segment, required, "gate1 segment")
        if segment["id"] in seen:
            raise ValueError(f"duplicate segment id: {segment['id']}")
        seen.add(segment["id"])
        validate_record(project_root, segment["source_transcript"], "source-transcript")
        editorial_path = validate_record(project_root, segment["editorial_analysis"], "editorial-analysis")
        editorial = EditorialAnalysis.parse(read_json(editorial_path))
        validate_record(project_root, segment["transcript"], "editable-transcript")
        sync = SyncReport.parse(_validate_json_verdict(project_root, segment["sync_report"], "sync-report", {"PASS", "NOT_REQUIRED"}))
        grade = _validate_json_verdict(project_root, segment["grade_manifest"], "grade-manifest", {"PASS"})
        if len(grade.get("samples", [])) < 3:
            raise ValueError(f"segment {segment['id']} has fewer than three grade samples")
        for sample in grade["samples"]:
            validate_record(project_root, sample, "grade-sample")
        visual_path = validate_record(project_root, segment["visual_plan"], "visual-plan")
        visual = read_json(visual_path)
        _require_keys(visual, {"schema_version", "kind", "worker_version", "segment_id", "scenes", "searches", "transcript_sha256"}, "visual plan")
        if visual["schema_version"] != 1 or visual["kind"] != "visual-plan" or visual["segment_id"] != segment["id"]:
            raise ValueError(f"segment {segment['id']} has invalid visual plan contract")
        segment_root = (project_root / "03_phase1" / "segments" / segment["id"]).resolve()
        style_wiring_reasons = validate_visual_plan_style_wiring(segment_root)
        if style_wiring_reasons:
            raise ValueError(
                f"segment {segment['id']} style_scenes wiring broken: "
                + "; ".join(style_wiring_reasons)
            )
        if not isinstance(segment["broll_assets"], list):
            raise ValueError(f"segment {segment['id']} broll_assets must be a list")
        broll_records = {}
        for record in segment["broll_assets"]:
            path = validate_record(project_root, record, "library-broll")
            broll_records[record["path"]] = (record, path)
        matched_paths = set()
        searches = {item.get("visual_id"): item for item in visual["searches"] if isinstance(item, dict)}
        for scene in visual["scenes"]:
            if not isinstance(scene, dict) or scene.get("type") not in {"library-broll", "motion", "screen", "none"}:
                raise ValueError(f"segment {segment['id']} has invalid visual scene")
            if scene.get("resolution") != "LIBRARY_MATCH":
                continue
            asset_path = scene.get("asset"); asset_id = scene.get("catalog_asset_id")
            if asset_path not in broll_records or broll_records[asset_path][0]["sha256"] != scene.get("asset_sha256"):
                raise ValueError(f"segment {segment['id']} library B-roll artifact is missing or stale")
            search = searches.get(scene.get("id"), {})
            match = next((item for item in search.get("matches", []) if item.get("asset_id") == asset_id), None)
            if not match or match.get("rights") not in ALLOWED_RIGHTS or not str(match.get("provenance", "")).strip() or match.get("sha256") != scene.get("asset_sha256"):
                raise ValueError(f"segment {segment['id']} library B-roll rights/provenance evidence is invalid")
            matched_paths.add(asset_path)
        if matched_paths != set(broll_records):
            raise ValueError(f"segment {segment['id']} has unbound B-roll artifacts")
        if editorial.source_transcript_sha256 != segment["source_transcript"]["sha256"]:
            raise ValueError(f"segment {segment['id']} editorial analysis is stale")
        if sync.bindings.get("source_transcript_sha256") != segment["source_transcript"]["sha256"]:
            raise ValueError(f"segment {segment['id']} sync report is stale")
        if visual["transcript_sha256"] != segment["transcript"]["sha256"]:
            raise ValueError(f"segment {segment['id']} visual plan is stale")
    expected_bindings = set()
    for segment in manifest["segments"]:
        source = read_json(validate_record(project_root, segment["source_transcript"], "source-transcript"))
        utterances = source.get("utterances")
        if not isinstance(utterances, list):
            raise ValueError(f"segment {segment['id']} source transcript has no utterances")
        expected_bindings.add((
            segment["id"], segment["source_transcript"]["sha256"],
            tuple(str(item.get("id", "")) for item in utterances if isinstance(item, dict)),
        ))
    actual_bindings = {
        (str(item["segment_id"]), str(item["source_transcript_sha256"]), tuple(item["utterance_ids"]))
        for item in cross_take_analysis.input_bindings
    }
    if actual_bindings != expected_bindings:
        raise ValueError("cross-segment take analysis is stale or incomplete")
    continuity_bindings = {
        (str(item["segment_id"]), str(item["transcript_sha256"]))
        for item in continuity.get("input_bindings", [])
    }
    expected_continuity = {
        (segment["id"], segment["transcript"]["sha256"]) for segment in manifest["segments"]
    }
    if continuity_bindings != expected_continuity:
        raise ValueError("film continuity is stale or incomplete relative to Gate 1 transcripts")


def validate_gate1_approval(project_root: Path, manifest: dict[str, Any]) -> None:
    validate_gate1(project_root, manifest)
    continuity = read_json(validate_record(project_root, manifest["film_continuity"], "film-continuity"))
    if continuity.get("verdict") != "PASS":
        raise ValueError(
            "film continuity BLOCKED: cross-segment KEEP duplicates must be CUT before Gate 1 approval"
        )
    for segment in manifest["segments"]:
        grade_path = validate_record(project_root, segment["grade_manifest"], "grade-manifest")
        grade = read_json(grade_path)
        selected = grade.get("selected")
        if not selected or selected not in grade.get("filters", {}):
            raise ValueError(f"segment {segment['id']} has no valid selected grade")


def validate_gate1_lineage(project_root: Path, manifest: dict[str, Any]) -> None:
    """Gate 1 identity for Gate 2: approval↔manifest binding only.

    Editable transcripts may change after Gate 1 via Gate 2 revisions; do not
    re-require live transcript hashes from the frozen Gate 1 snapshot.
    """
    del project_root  # lineage is structural; file freshness is Gate 2's job
    _require_keys(
        manifest,
        {"schema_version", "kind", "project_id", "revision", "segments"},
        "gate1 lineage",
    )
    if manifest["schema_version"] != 1 or manifest["kind"] != "gate1":
        raise ValueError("invalid gate1 schema version or kind")
    if not manifest["segments"]:
        raise ValueError("gate1 requires at least one segment")
    seen: set[str] = set()
    for segment in manifest["segments"]:
        _require_keys(segment, {"id"}, "gate1 lineage segment")
        if segment["id"] in seen:
            raise ValueError(f"duplicate segment id: {segment['id']}")
        seen.add(segment["id"])


def _validate_approval_lineage(
    project_root: Path,
    record: dict[str, Any],
    *,
    expected_gate: str,
    expected_project_id: str,
    expected_manifest_kind: str,
    manifest_validator: Callable[[Path, dict[str, Any]], None],
) -> dict[str, Any]:
    approval_path = validate_record(project_root, record, "approval")
    approval = read_json(approval_path)
    _require_keys(approval, {"schema_version", "project_id", "gate", "manifest", "manifest_content_hash"}, f"{expected_gate} approval")
    if approval["schema_version"] != 2 or approval["gate"] != expected_gate:
        raise ValueError(f"invalid {expected_gate} approval payload")
    if approval["project_id"] != expected_project_id:
        raise ValueError(f"{expected_gate} approval belongs to another project")
    upstream_path = validate_record(project_root, approval["manifest"], expected_manifest_kind)
    upstream = read_json(upstream_path)
    if upstream.get("project_id") != expected_project_id:
        raise ValueError(f"{expected_gate} manifest belongs to another project")
    if canonical_json_hash(upstream) != approval["manifest_content_hash"]:
        raise ValueError(f"{expected_gate} approval is stale")
    manifest_validator(project_root, upstream)
    return upstream

def validate_gate2(project_root: Path, manifest: dict[str, Any]) -> None:
    _require_keys(manifest, {"schema_version", "kind", "project_id", "revision", "gate1_approval", "review", "film_continuity", "segments"}, "gate2 manifest")
    if manifest["schema_version"] != 1 or manifest["kind"] != "gate2":
        raise ValueError("invalid gate2 schema version or kind")
    validate_record(project_root, manifest["review"], "gate2-review")
    gate1 = _validate_approval_lineage(
        project_root,
        manifest["gate1_approval"],
        expected_gate="gate1",
        expected_project_id=manifest["project_id"],
        expected_manifest_kind="gate1-manifest",
        manifest_validator=validate_gate1_lineage,
    )
    continuity_path = validate_record(project_root, manifest["film_continuity"], "film-continuity")
    continuity = read_json(continuity_path)
    if continuity.get("kind") != "film-continuity" or continuity.get("verdict") != "PASS":
        raise ValueError("gate2 film continuity must be PASS before review/approval")
    if not manifest["segments"]:
        raise ValueError("gate2 requires at least one segment")
    gate1_segments = {item["id"]: item for item in gate1["segments"]}
    seen: set[str] = set()
    for segment in manifest["segments"]:
        _require_keys(segment, {"id", "render", "expected_transcript", "rendered_transcript", "verification", "qc", "fixes"}, "gate2 segment")
        if segment["id"] in seen:
            raise ValueError(f"duplicate segment id: {segment['id']}")
        if segment["id"] not in gate1_segments:
            raise ValueError(f"gate2 segment is absent from approved Gate 1: {segment['id']}")
        seen.add(segment["id"])
        render = validate_record(project_root, segment["render"], "segment-render")
        validate_video(render)
        expected = validate_record(project_root, segment["expected_transcript"], "expected-transcript")
        actual = validate_record(project_root, segment["rendered_transcript"], "rendered-transcript")
        verification = TranscriptVerification.parse(_validate_json_verdict(project_root, segment["verification"], "transcript-verification", {"PASS"}))
        qc = QcReport.parse(_validate_json_verdict(project_root, segment["qc"], "segment-qc", {"PASS"}))
        expected_bindings = {"render_sha256": sha256_file(render), "expected_transcript_sha256": sha256_file(expected), "actual_transcript_sha256": sha256_file(actual)}
        if any(verification.bindings.get(key) != value for key, value in expected_bindings.items()):
            raise ValueError(f"segment {segment['id']} transcript verification is stale")
        if qc.bindings.get("render_sha256") != sha256_file(render):
            raise ValueError(f"segment {segment['id']} QC is stale")
        validate_record(project_root, segment["fixes"], "fixes")
    if seen != set(gate1_segments):
        raise ValueError("Gate 2 segment set does not match approved Gate 1")
    expected_continuity = {
        (segment["id"], segment["expected_transcript"]["sha256"]) for segment in manifest["segments"]
    }
    actual_continuity = {
        (str(item["segment_id"]), str(item["transcript_sha256"]))
        for item in continuity.get("input_bindings", [])
    }
    if expected_continuity != actual_continuity:
        raise ValueError("gate2 film continuity is stale relative to expected transcripts")


def validate_gate2_approval(project_root: Path, manifest: dict[str, Any]) -> None:
    validate_gate2(project_root, manifest)
    for segment in manifest["segments"]:
        fixes_path = validate_record(project_root, segment["fixes"], "fixes")
        parsed = parse_fixes(fixes_path.read_text(encoding="utf-8"), allow_empty=True)
        if parsed["fixes"]:
            raise ValueError(f"segment {segment['id']} still has open fixes")


def validate_final(project_root: Path, manifest: dict[str, Any]) -> None:
    _require_keys(manifest, {"schema_version", "kind", "project_id", "revision", "gate2_approval", "master", "qc", "archive_receipt", "publishing_package", "segment_hashes"}, "final manifest")
    if manifest["schema_version"] != 1 or manifest["kind"] != "final":
        raise ValueError("invalid final schema version or kind")
    gate2 = _validate_approval_lineage(
        project_root,
        manifest["gate2_approval"],
        expected_gate="gate2",
        expected_project_id=manifest["project_id"],
        expected_manifest_kind="gate2-manifest",
        manifest_validator=validate_gate2_approval,
    )
    master = validate_record(project_root, manifest["master"], "master")
    validate_video(master)
    qc = QcReport.parse(_validate_json_verdict(project_root, manifest["qc"], "final-qc", {"PASS"}))
    if qc.bindings.get("master_sha256") != manifest["master"]["sha256"]:
        raise ValueError("final QC is stale")
    receipt = _validate_json_verdict(project_root, manifest["archive_receipt"], "archive-receipt", {"VERIFIED"})
    if receipt.get("source_sha256") != manifest["master"]["sha256"]:
        raise ValueError("archive receipt is not bound to the final master")
    archive_root = Path(receipt.get("archive_root", "")).resolve()
    if not receipt.get("entries"):
        raise ValueError("archive receipt has no verified entries")
    for entry in receipt["entries"]:
        destination = Path(entry.get("destination", "")).resolve()
        if not destination.is_relative_to(archive_root) or not destination.is_file():
            raise ValueError("archive receipt destination is missing or unsafe")
        if destination.stat().st_size != entry.get("size_bytes") or sha256_file(destination) != entry.get("sha256"):
            raise ValueError(f"archive destination changed after verification: {destination}")
    package = manifest["publishing_package"]
    _require_keys(package, {"title", "description", "chapters", "manifest"}, "publishing package")
    for kind, record in package.items():
        validate_record(project_root, record, f"publishing-{kind}")
    approved_segment_hashes = [item["render"]["sha256"] for item in gate2["segments"]]
    if manifest["segment_hashes"] != approved_segment_hashes:
        raise ValueError("final master lineage does not match approved Gate 2 renders")


GATE_VALIDATORS: dict[str, Callable[[Path, dict[str, Any]], None]] = {
    "gate1": validate_gate1,
    "gate2": validate_gate2,
    "final": validate_final,
}
