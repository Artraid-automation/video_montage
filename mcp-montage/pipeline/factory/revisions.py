"""Executable, scoped revision operations for Gate 2 and Final Review."""
from __future__ import annotations

import re
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .artifacts import artifact_record, validate_record
from .io import atomic_write_json, read_json, utc_timestamp
from .phase2 import run_phase2
from .phase3 import run_phase3
from .rules import add_rule_proposals
from .state import StateStore
from .transcript import VisualEntry, load_transcript, parse_fixes, render_transcript

COMMAND = re.compile(r"^(cut|keep|replace-text|set-visual|remove-visual|transcript-reviewed|set-title|set-description)(?:\s+(.*))?$")


def _arguments(value: str) -> tuple[str, dict[str, str]]:
    match = COMMAND.fullmatch(value.strip())
    if not match:
        raise ValueError(f"fix is not executable: {value!r}")
    operation, tail = match.groups()
    args: dict[str, str] = {}
    if tail:
        for item in re.findall(r'(\w[\w-]*)=("[^"]*"|\S+)', tail):
            args[item[0]] = item[1][1:-1] if item[1].startswith('"') else item[1]
    return operation, args


def collect_revision_notes(project_root: Path, gate: str) -> dict[str, Any]:
    roots = [project_root / "05_final"] if gate == "final" else sorted((project_root / "04_phase2" / "segments").glob("*"))
    fixes: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    source_files = []
    for root in roots:
        notes_path = root / "fixes.md"
        if not notes_path.is_file():
            continue
        parsed = parse_fixes(notes_path.read_text(encoding="utf-8"), allow_empty=True)
        for item in parsed["fixes"]:
            operation, arguments = _arguments(item["description"])
            item.update({"operation": operation, "arguments": arguments})
            if gate == "gate2" and item["segment_id"] != root.name:
                raise ValueError(f"fix in {notes_path} targets {item['segment_id']}, expected {root.name}")
            if gate == "final" and operation not in {"set-title", "set-description"}:
                raise ValueError("Final Review accepts metadata operations only; segment edits belong at Gate 2")
            fixes.append(item)
        rules.extend({**item, "source_segment": root.name} for item in parsed["rule_candidates"])
        if parsed["fixes"] or parsed["rule_candidates"]:
            source_files.append(notes_path.relative_to(project_root).as_posix())
    if not fixes and not rules:
        raise ValueError(f"{gate} contains no revision notes")
    return {"schema_version": 2, "gate": gate, "created_at": utc_timestamp(), "fixes": fixes, "rule_candidates": rules, "source_files": source_files}


def _apply_segment_fix(project_root: Path, fix: dict[str, Any], gate1: dict[str, Any]) -> dict[str, Any]:
    segment_id = fix["segment_id"]
    root = project_root / "03_phase1" / "segments" / segment_id
    transcript_path = root / "transcript.md"
    source_path = root / "source-transcript.json"
    source = read_json(source_path)
    entries, visuals = load_transcript(transcript_path, source)
    operation, args = fix["operation"], fix["arguments"]
    approved_segment = next(item for item in gate1["segments"] if item["id"] == segment_id)
    before_hash = artifact_record(project_root, transcript_path, kind="editable-transcript")["sha256"]
    if operation == "transcript-reviewed":
        if before_hash == approved_segment["transcript"]["sha256"]:
            raise ValueError(f"fix {fix['id']} claims transcript-reviewed but transcript did not change")
    elif operation in {"cut", "keep", "replace-text"}:
        entry_id = args.get("entry")
        if not entry_id or not any(item.id == entry_id for item in entries):
            raise ValueError(f"fix {fix['id']} references unknown transcript entry")
        changed = []
        for item in entries:
            if item.id != entry_id:
                changed.append(item); continue
            values = item.__dict__.copy()
            if operation in {"cut", "keep"}: values["kind"] = operation
            else:
                if "text" not in args: raise ValueError("replace-text requires text=\"...\"")
                values["text"] = args["text"]
            changed.append(type(item)(**values))
        entries = changed
    elif operation in {"set-visual", "remove-visual"}:
        anchor = args.get("entry")
        if not anchor or not any(item.id == anchor for item in entries):
            raise ValueError("visual operation references unknown entry")
        visuals = [item for item in visuals if item.anchor != anchor]
        if operation == "set-visual":
            visual_type = args.get("type")
            if visual_type not in {"library-broll", "motion", "screen", "none"}:
                raise ValueError("set-visual requires a supported type")
            visuals.append(VisualEntry(args.get("id", f"revision-{fix['id']}"), anchor, visual_type, args.get("brief", ""), args.get("asset")))
    else:
        raise ValueError(f"operation {operation} is not a segment operation")
    transcript_path.write_text(render_transcript(entries, visuals, segment_id=segment_id), encoding="utf-8")
    after_hash = artifact_record(project_root, transcript_path, kind="editable-transcript")["sha256"]
    if before_hash == after_hash and operation != "transcript-reviewed":
        raise ValueError(f"fix {fix['id']} made no change")
    return {"fix_id": fix["id"], "status": "APPLIED", "before_sha256": before_hash, "after_sha256": after_hash}


def _apply_final_fix(project_root: Path, fix: dict[str, Any]) -> dict[str, Any]:
    config_path = project_root / "project.json"
    config = read_json(config_path)
    before = dict(config)
    key = "title" if fix["operation"] == "set-title" else "description"
    config.setdefault("publishing", {})[key] = fix["arguments"].get("value", "")
    atomic_write_json(config_path, config)
    return {"fix_id": fix["id"], "status": "APPLIED", "field": f"publishing.{key}", "before": before.get("publishing", {}).get(key), "after": config["publishing"][key]}


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _stage_revision_files(
    project_root: Path, gate: str, fixes: list[dict[str, Any]], gate1: dict[str, Any]
) -> tuple[dict[Path, bytes], list[dict[str, Any]]]:
    """Apply every fix to an isolated tree so validation cannot partially mutate the project."""
    with tempfile.TemporaryDirectory() as temp:
        staging_root = Path(temp) / project_root.name
        staging_root.mkdir()
        if gate == "final":
            target = staging_root / "project.json"
            shutil.copy2(project_root / "project.json", target)
            outcomes = [_apply_final_fix(staging_root, item) for item in fixes]
            return {project_root / "project.json": target.read_bytes()}, outcomes
        touched = sorted({item["segment_id"] for item in fixes})
        for segment_id in touched:
            source_root = project_root / "03_phase1" / "segments" / segment_id
            target_root = staging_root / "03_phase1" / "segments" / segment_id
            target_root.mkdir(parents=True)
            shutil.copy2(source_root / "transcript.md", target_root / "transcript.md")
            shutil.copy2(source_root / "source-transcript.json", target_root / "source-transcript.json")
        outcomes = [_apply_segment_fix(staging_root, item, gate1) for item in fixes]
        staged = {
            project_root / "03_phase1" / "segments" / segment_id / "transcript.md":
                (staging_root / "03_phase1" / "segments" / segment_id / "transcript.md").read_bytes()
            for segment_id in touched
        }
        return staged, outcomes


def _validate_rule_candidates(candidates: list[dict[str, Any]]) -> None:
    pattern = re.compile(r'replace-text\s+match=("[^"]*"|\S+)\s+replacement=("[^"]*"|\S+)')
    for candidate in candidates:
        if not pattern.fullmatch(str(candidate.get("description", ""))):
            raise ValueError("rule candidate must be executable replace-text match=... replacement=...")


def _restore_snapshots(snapshots: dict[Path, bytes | None]) -> None:
    for path, payload in reversed(list(snapshots.items())):
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_write_bytes(path, payload)


def run_revisions(project_root: Path, store: StateStore | None = None, *, verification_transcriber: Any | None = None) -> Path:
    project_root = project_root.resolve(strict=True)
    store = store or StateStore(project_root)
    initial = store.read()
    state = initial["state"]
    if state not in {"GATE2_REVIEW", "FINAL_REVIEW"}:
        raise ValueError(f"revisions can start only at a review gate, current={state}")
    gate = "final" if state == "FINAL_REVIEW" else "gate2"
    notes = collect_revision_notes(project_root, gate)
    _validate_rule_candidates(notes["rule_candidates"])
    gate1 = read_json(validate_record(project_root, initial["gates"]["gate1"]["manifest"], "gate1-manifest"))
    staged, applied = _stage_revision_files(project_root, gate, notes["fixes"], gate1)
    if len(applied) != len(notes["fixes"]):
        raise RuntimeError("not every revision fix was staged")

    transaction_id = uuid.uuid4().hex
    revision_number = initial["revision"] + 1
    revisions_root = project_root / "06_state" / "revisions"
    notes_path = revisions_root / f"revision-{revision_number:06d}.json"
    journal_path = revisions_root / f"transaction-{transaction_id}.json"
    rules_path = project_root / "02_inputs" / "rules" / "ledger.json"
    affected = [*staged, notes_path, rules_path]
    snapshots = {path: path.read_bytes() if path.exists() else None for path in affected}
    journal = {
        "schema_version": 1, "transaction_id": transaction_id, "status": "PREPARED", "gate": gate,
        "expected_ledger_revision": initial["revision"],
        "affected_paths": [path.relative_to(project_root).as_posix() for path in affected],
        "created_at": utc_timestamp(),
    }
    atomic_write_json(journal_path, journal)
    committed = False
    try:
        journal["status"] = "APPLYING"
        atomic_write_json(journal_path, journal)
        for path, payload in staged.items():
            _atomic_write_bytes(path, payload)
        notes["outcomes"] = applied
        notes["rule_proposals_added"] = add_rule_proposals(project_root, notes["rule_candidates"]) if notes["rule_candidates"] else []
        atomic_write_json(notes_path, notes)
        if store.read()["revision"] != initial["revision"]:
            raise RuntimeError("concurrent state update before revision commit")
        scope = sorted({item["segment_id"] for item in notes["fixes"]})
        store.request_revision(scope, artifact_record(project_root, notes_path, kind="revision-notes"))
        committed = True
        journal.update({"status": "COMMITTED", "committed_at": utc_timestamp()})
        atomic_write_json(journal_path, journal)
    except Exception as exc:
        if not committed:
            _restore_snapshots(snapshots)
            journal.update({"status": "ROLLED_BACK", "rolled_back_at": utc_timestamp(), "error": str(exc)})
            atomic_write_json(journal_path, journal)
        raise

    if gate == "final":
        (project_root / "05_final" / "fixes.md").write_text("# Final fixes\n\n", encoding="utf-8")
        return run_phase3(project_root, store)
    return run_phase2(project_root, store, segment_scope=set(scope), verification_transcriber=verification_transcriber)
