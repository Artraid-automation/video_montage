"""Phase 3: verified master, publishing package, archive, and Final Review."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .archive import archive_project
from .artifacts import artifact_record, validate_record
from .grade import FINAL_GRADE_CANDIDATES, apply_grade, normalize_master_audio
from .io import atomic_write_json, canonical_json_hash, read_json, resolve_project_path, sha256_file
from .jobs import JobLedger
from .library import ingest_approved_assets
from .media import duration_s, probe
from .qc import audio_policy, combined_qc
from .render import concat_clips
from .state import StateStore
from .telegram_delivery import (
    deliver_telegram_master,
    resolve_telegram_delivery_config,
    write_telegram_delivery_report,
)


def _timestamp(seconds: float) -> str:
    whole = int(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _safe_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ_-]+", "-", value.strip()).strip("-").lower()
    return slug or "video"


def _publishing_package(
    project_root: Path,
    config: dict[str, Any],
    segment_paths: list[Path],
    master: Path,
) -> tuple[dict[str, Any], list[Path]]:
    package = project_root / "05_final" / "publishing-package"
    package.mkdir(parents=True, exist_ok=True)
    title_path = package / "title.txt"
    title_path.write_text(
        str(config.get("publishing", {}).get("title", config.get("title", project_root.name))).strip() + "\n",
        encoding="utf-8",
    )
    description_path = package / "description.md"
    description_path.write_text(
        str(config.get("publishing", {}).get("description", "")).strip() + "\n",
        encoding="utf-8",
    )
    chapters_path = package / "chapters.txt"
    cursor = 0.0
    chapters = []
    configured = config.get("publishing", {}).get("chapter_titles", {})
    for index, path in enumerate(segment_paths, 1):
        segment_id = f"{index:02d}"
        chapters.append(f"{_timestamp(cursor)} {configured.get(segment_id, f'Segment {segment_id}')}")
        cursor += duration_s(probe(path))
    chapters_path.write_text("\n".join(chapters) + "\n", encoding="utf-8")
    manifest_path = package / "manifest.json"
    atomic_write_json(manifest_path, {
        "schema_version": 1,
        "project_id": config["id"],
        "master_sha256": sha256_file(master),
        "chapters": chapters,
        "publication": "manual",
        "assets_license_reviewed": True,
    })
    records = {
        "title": artifact_record(project_root, title_path, kind="publishing-title"),
        "description": artifact_record(project_root, description_path, kind="publishing-description"),
        "chapters": artifact_record(project_root, chapters_path, kind="publishing-chapters"),
        "manifest": artifact_record(project_root, manifest_path, kind="publishing-manifest"),
    }
    return records, [title_path, description_path, chapters_path, manifest_path]


def _build_grade_masters(
    project_root: Path,
    *,
    normalized_master: Path,
    final_root: Path,
    profile: dict[str, Any],
    default_grade: str,
) -> tuple[Path, dict[str, Any]]:
    """Produce neutral + two suitable grade masters; return primary master + report."""
    grades_root = final_root / "grades"
    grades_root.mkdir(parents=True, exist_ok=True)
    candidates = list(FINAL_GRADE_CANDIDATES)
    if default_grade not in candidates:
        candidates = [default_grade, *[g for g in FINAL_GRADE_CANDIDATES if g != default_grade]][:3]
    grade_rows: list[dict[str, Any]] = []
    primary = normalized_master
    for name in candidates:
        out = grades_root / f"master-{name}.mp4"
        apply_grade(normalized_master, out, grade_name=name, profile=profile)
        audio = audio_policy(out)
        record = artifact_record(project_root, out, kind="grade-master")
        row = {
            "grade": name,
            "path": record["path"],
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
            "audio": audio,
            "is_primary": name == default_grade,
        }
        grade_rows.append(row)
        if name == default_grade:
            primary = out
    report = {
        "schema_version": 1,
        "kind": "final-grade-candidates",
        "worker_version": "final-grades-v1",
        "default_grade": default_grade,
        "candidates": grade_rows,
        "audio_note": (
            "Loudness normalized once on the concat master (loudnorm I=-14). "
            "Listen here — do not re-check per-segment audio unless a segment was revised."
        ),
    }
    atomic_write_json(grades_root / "manifest.json", report)
    review = final_root / "grade-review.md"
    lines = [
        "# Final grade candidates",
        "",
        f"Primary (config `default_grade`): **{default_grade}**",
        "",
        "Audio: normalized on the glued master (`loudnorm` I=-14 / TP=-1.5). "
        "Check loudness once on these masters — not again on segment review.mp4.",
        "",
        "| grade | file | mean_db | peak_db | audio |",
        "|-------|------|---------|---------|-------|",
    ]
    for row in grade_rows:
        audio = row["audio"]
        mark = " ← primary" if row["is_primary"] else ""
        lines.append(
            f"| `{row['grade']}`{mark} | `{row['path']}` | "
            f"{audio.get('mean_db')} | {audio.get('peak_db')} | {audio.get('verdict')} |"
        )
    lines.append("")
    review.write_text("\n".join(lines), encoding="utf-8")
    return primary, report


def run_phase3(project_root: Path, store: StateStore | None = None, *, test_hook: Callable[[str], None] | None = None) -> Path:
    project_root = project_root.resolve(strict=True)
    store = store or StateStore(project_root)
    config = read_json(project_root / "project.json")
    store.assert_approval_current("gate2")
    gate2_path = validate_record(project_root, store.read()["gates"]["gate2"]["manifest"], "gate2-manifest")
    gate2 = read_json(gate2_path)
    input_hash = canonical_json_hash({
        "gate2_approval": store.read()["gates"]["gate2"]["approval"]["sha256"],
        "config": config,
    })
    current_state = store.read()["state"]
    final_revision = (
        current_state == "REVISIONS_RUNNING"
        and (store.read().get("revision_request") or {}).get("return_gate") == "final"
    )
    if current_state == "PHASE3_READY":
        store.begin_phase("phase3", inputs_hash=input_hash)
    elif current_state != "PHASE3_RUNNING" and not final_revision:
        raise ValueError(f"Phase 3 cannot run from {store.read()['state']}")
    try:
        segment_paths = [
            validate_record(project_root, item["render"], "segment-render")
            for item in gate2["segments"]
        ]
        segment_hashes = [item["render"]["sha256"] for item in gate2["segments"]]
        final_root = project_root / "05_final"
        final_root.mkdir(parents=True, exist_ok=True)
        master_name = _safe_name(
            str(config.get("publishing", {}).get("title", config.get("title", project_root.name)))
        ) + ".mp4"
        master = final_root / master_name
        qc_path = final_root / "qc.json"
        default_grade = str(config.get("default_grade") or "dankoe")
        tg_cfg = resolve_telegram_delivery_config(config)
        final_fingerprint = canonical_json_hash({
            "segment_hashes": segment_hashes,
            "render_profile": config.get("render_profile", {}),
            "publishing": config.get("publishing", {}),
            "title": config.get("title", project_root.name),
            "default_grade": default_grade,
            "final_grades": list(FINAL_GRADE_CANDIDATES),
            "master_audio": "loudnorm-I-14",
            "telegram_delivery": {
                "enabled": tg_cfg["enabled"],
                "width": tg_cfg["width"],
                "height": tg_cfg["height"],
                "speed_factor": tg_cfg["speed_factor"],
                "grade": tg_cfg["grade"],
                "send_as": tg_cfg["send_as"],
            },
        })
        jobs = JobLedger(project_root)
        job_id = "phase3.master-package"
        worker_version = "master-package-v5-tg-delivery"
        reusable = jobs.reusable(job_id, worker_version=worker_version, fingerprint=final_fingerprint)
        if reusable:
            continuity = read_json(validate_record(project_root, gate2["film_continuity"], "film-continuity"))
            if continuity.get("verdict") != "PASS":
                raise ValueError("cannot deliver master while film continuity is not PASS")
            master = reusable.outputs["master"]
            qc_path = reusable.outputs["qc"]
            package_files = [
                reusable.outputs["title"], reusable.outputs["description"],
                reusable.outputs["chapters"], reusable.outputs["package_manifest"],
            ]
            package_records = {
                "title": artifact_record(project_root, package_files[0], kind="publishing-title"),
                "description": artifact_record(project_root, package_files[1], kind="publishing-description"),
                "chapters": artifact_record(project_root, package_files[2], kind="publishing-chapters"),
                "manifest": artifact_record(project_root, package_files[3], kind="publishing-manifest"),
            }
        else:
            jobs.start(job_id, worker_version=worker_version, fingerprint=final_fingerprint)
            try:
                continuity = read_json(validate_record(project_root, gate2["film_continuity"], "film-continuity"))
                if continuity.get("verdict") != "PASS":
                    raise ValueError("cannot concat master while film continuity is not PASS")
                concat_raw = final_root / "_concat-raw.mp4"
                concat_clips(segment_paths, concat_raw, profile=config.get("render_profile", {}))
                normalized = final_root / "_master-loudnorm.mp4"
                normalize_master_audio(concat_raw, normalized, profile=config.get("render_profile", {}))
                profile = {"width": 640, "height": 360, "fps": 25, **config.get("render_profile", {})}
                primary, grade_report = _build_grade_masters(
                    project_root,
                    normalized_master=normalized,
                    final_root=final_root,
                    profile=profile,
                    default_grade=default_grade,
                )
                if primary.resolve() != master.resolve():
                    master.write_bytes(primary.read_bytes())
                expected_duration = sum(duration_s(probe(path)) for path in segment_paths)
                qc = combined_qc(
                    project_root,
                    master,
                    final_root / "probes",
                    expected_duration_s=expected_duration,
                    width=int(profile["width"]),
                    height=int(profile["height"]),
                    fps=int(profile["fps"]),
                    pip_enabled=False,
                    interval_s=float(config.get("visual_probe_interval_s", 2.0)),
                    binding_name="master_sha256",
                )
                qc["grade_candidates"] = grade_report
                qc["master_audio"] = {
                    "loudnorm": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
                    "policy": audio_policy(master),
                }
                atomic_write_json(qc_path, qc)
                if qc["verdict"] != "PASS":
                    raise ValueError(f"final QC failed: {qc['reasons']}")
                package_records, package_files = _publishing_package(
                    project_root, config, segment_paths, master,
                )
                jobs.complete(
                    job_id,
                    worker_version=worker_version,
                    fingerprint=final_fingerprint,
                    outputs={
                        "master": (master, "master"),
                        "qc": (qc_path, "final-qc"),
                        "title": (package_files[0], "publishing-title"),
                        "description": (package_files[1], "publishing-description"),
                        "chapters": (package_files[2], "publishing-chapters"),
                        "package_manifest": (package_files[3], "publishing-manifest"),
                    },
                )
                concat_raw.unlink(missing_ok=True)
                normalized.unlink(missing_ok=True)
            except Exception as exc:
                jobs.fail(job_id, str(exc))
                raise
        raw_manifest = read_json(project_root / "03_phase1" / "manifest.json")
        raw_files = [resolve_project_path(project_root, item["path"]) for item in raw_manifest["files"]]
        archive_root = Path(config.get("archive_root", project_root.parent / "_archive"))
        receipt = archive_project(
            project_root,
            archive_root=archive_root,
            project_id=(
                f"{config['id']}-r{store.read()['revision']:06d}"
                if final_revision
                else config["id"]
            ),
            master=master,
            package_files=package_files,
            raw_files=raw_files,
        )
        receipt_path = final_root / "archive-receipt.json"
        atomic_write_json(receipt_path, receipt)
        if test_hook:
            test_hook("phase3.archive")
        default_library = (
            project_root.parent.parent / "library" / "broll"
            if project_root.parent.name == "projects"
            else project_root.parent / "_library" / "broll"
        )
        fixes_path = final_root / "fixes.md"
        if not fixes_path.exists():
            fixes_path.write_text("# Final fixes\n\n", encoding="utf-8")
        library_report = ingest_approved_assets(
            project_root, Path(config.get("library_root", default_library)),
        )
        library_report_path = final_root / "library-ingestion.json"
        atomic_write_json(library_report_path, library_report)
        # TG derivative only — clean grade masters stay 1.0x / native resolution.
        tg_source = final_root / "grades" / f"master-{tg_cfg['grade']}.mp4"
        if not tg_source.is_file():
            tg_source = master
        tg_report = deliver_telegram_master(
            project_root,
            source_master=tg_source,
            config=config,
            grade_name=str(tg_cfg["grade"]),
        )
        tg_report_path = write_telegram_delivery_report(project_root, tg_report)
        final_manifest: dict[str, Any] = {
            "schema_version": 1,
            "kind": "final",
            "project_id": config["id"],
            "revision": int(config.get("final_revision", 1)),
            "gate2_approval": store.read()["gates"]["gate2"]["approval"],
            "master": artifact_record(project_root, master, kind="master"),
            "qc": artifact_record(project_root, qc_path, kind="final-qc"),
            "archive_receipt": artifact_record(project_root, receipt_path, kind="archive-receipt"),
            "publishing_package": package_records,
            "segment_hashes": segment_hashes,
            "telegram_delivery": artifact_record(
                project_root, tg_report_path, kind="telegram-delivery-report",
            ),
        }
        if tg_report.get("artifact"):
            final_manifest["telegram_file"] = tg_report["artifact"]
        manifest_path = final_root / "final-manifest.json"
        atomic_write_json(manifest_path, final_manifest)
        store.checkpoint(
            "archive-verified",
            evidence={"receipt": artifact_record(project_root, receipt_path, kind="archive-receipt")},
        )
        store.prepare_gate("final", manifest_path)
        return manifest_path
    except Exception as exc:
        if store.read()["state"] in {"PHASE3_RUNNING", "REVISIONS_RUNNING"}:
            store.fail(str(exc), retryable=True)
        raise
