"""Render approved segments, re-transcribe, self-verify, and assemble Gate 2."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .artifacts import artifact_record
from .film_continuity import write_phase2_film_continuity
from .io import atomic_write_json, canonical_json_hash, read_json, resolve_project_path, sha256_file
from .jobs import JobLedger
from .providers import Transcriber, build_transcriber
from .qc import combined_qc
from .verification import verify_transcript
from .render import render_segment
from .state import StateStore
from .transcript import load_transcript


def _write_review(project_root: Path, results: list[dict[str, Any]], *, continuity: dict[str, Any] | None = None) -> Path:
    lines = ["# Gate 2 — проверка смонтированных сегментов", "", "Каждый сегмент необходимо посмотреть полностью.", ""]
    if continuity is not None:
        lines.extend([
            "## Цельный фильм",
            "",
            f"- Continuity verdict: **{continuity.get('verdict')}**",
            f"- Blocking KEEP duplicates: {len(continuity.get('blocking_groups', []))}",
            "- Artifact: [`film-continuity.json`](film-continuity.json)",
            "",
        ])
    for result in results:
        segment_id = result["segment_id"]
        metrics = result["verification"].get("metrics", {})
        audit = (result["qc"].get("visual_audit") or {})
        lines.extend([
            f"## Segment {segment_id}", "",
            f"- Video: [`segments/{segment_id}/review.mp4`](segments/{segment_id}/review.mp4)",
            f"- Transcript verification: **{result['verification']['verdict']}**; WER={metrics.get('wer')}",
            f"- Technical/visual QC: **{result['qc']['verdict']}**",
            f"- Visual render policy: **{(result['qc'].get('visual_render_policy') or {}).get('verdict', 'missing')}**",
            f"- Visual audit (key+random+MOTION): **{audit.get('verdict', 'missing')}**",
            f"- Cache hit: `{str(result['cache_hit']).lower()}`",
            f"- Fixes: [`segments/{segment_id}/fixes.md`](segments/{segment_id}/fixes.md)", "",
        ])
        key_frames = audit.get("key_frames") or []
        if key_frames:
            lines.append("### Key composition probes (обязательная сверка)")
            lines.append("")
            for frame in key_frames:
                rel = str(frame.get("path", "")).replace("04_phase2/", "")
                lines.append(
                    f"- `{frame.get('id')}` @ {frame.get('timestamp_s')}s — "
                    f"[`{rel}`]({rel.replace(f'segments/{segment_id}/', f'segments/{segment_id}/')})"
                )
            lines.append("")
        random_frames = audit.get("random_frames") or []
        if random_frames:
            lines.append("### Random frame probes (обязательная сверка)")
            lines.append("")
            for frame in random_frames:
                rel = str(frame.get("path", "")).replace(f"04_phase2/", "")
                lines.append(
                    f"- `{frame.get('id')}` @ {frame.get('timestamp_s')}s — "
                    f"[`{rel}`]({rel.replace(f'segments/{segment_id}/', f'segments/{segment_id}/')})"
                )
            lines.append("")
        motion_checks = audit.get("motion_checks") or []
        if motion_checks:
            lines.append("### Per-MOTION checks")
            lines.append("")
            for motion in motion_checks:
                lines.append(
                    f"- MOTION `{motion.get('id')}` "
                    f"{motion.get('render_start_s')}–{motion.get('render_end_s')}s → "
                    f"**{motion.get('verdict')}**; on_screen={motion.get('on_screen')!r}"
                )
                for frame in motion.get("frames") or []:
                    rel = str(frame.get("path", ""))
                    short = rel.split(f"segments/{segment_id}/", 1)[-1]
                    lines.append(f"  - {frame.get('role')} @ {frame.get('timestamp_s')}s — [`{short}`](segments/{segment_id}/{short})")
            lines.append("")
        elif (result["qc"].get("visual_render_policy") or {}).get("components", {}).get("motion_compose", {}).get("motion_count", 0):
            lines.append("- **WARNING:** motions declared but visual_audit has no motion_checks")
            lines.append("")
    lines.extend([
        "## Правило gate", "",
        "Добавить адресные `[fix ...]` в файл сегмента. Blocking fix запрещает approval.",
        "Постмонтажный transcript и verification относятся к реальному render, а не к исходному plan.",
        "Gate 2 QC includes **visual_render_policy** and mandatory **visual_audit** "
        "(seeded random screenshots + separate probe set for every MOTION).", "",
    ])
    path = project_root / "04_phase2" / "review.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path



def _segment_source_media(project_root: Path, raw_manifest: dict[str, Any], group: dict[str, Any]) -> Path | None:
    """Исходник сегмента — опора для гейта застываний: с ним сравнивается рендер."""
    media = {item["id"]: item for item in raw_manifest.get("files", [])}
    feeds = group.get("feeds") or {}
    record = media.get(feeds.get("camera")) or media.get(feeds.get("screen"))
    if not record:
        return None
    path = resolve_project_path(project_root, record["path"])
    return path if path.is_file() else None



def _duration_tolerance(contract: dict[str, Any], *, base_s: float = 0.35) -> float:
    """Допуск по длительности с поправкой на покадровое округление планов.

    Длина плана кратна кадру, поэтому на 52 планах при 25 к/с сборка законно
    оказывается на полсекунды длиннее плана монтажа. Судить это как брак нельзя,
    но и открывать допуск настежь тоже: он растёт ровно на половину кадра за план.
    """
    fps = float(contract.get("fps") or 0)
    clips = float(contract.get("clip_count") or 0)
    if fps <= 0 or clips <= 0:
        return base_s
    return base_s + clips * 0.5 / fps


def run_phase2(project_root: Path, store: StateStore | None = None, *, segment_scope: set[str] | None = None, verification_transcriber: Transcriber | None = None, test_hook: Callable[[str], None] | None = None) -> Path:
    project_root = project_root.resolve(strict=True)
    store = store or StateStore(project_root)
    config = read_json(project_root / "project.json")
    ledger = store.read()
    if ledger["state"] != "REVISIONS_RUNNING":
        store.assert_approval_current("gate1")
    raw_manifest = read_json(project_root / "03_phase1" / "manifest.json")
    input_hash = canonical_json_hash({
        "gate1": ledger["gates"]["gate1"]["approval"]["sha256"],
        "config": config, "scope": sorted(segment_scope) if segment_scope else "all",
    })
    if ledger["state"] == "PHASE2_PENDING":
        store.begin_phase("phase2", inputs_hash=input_hash)
    elif ledger["state"] not in {"PHASE2_RUNNING", "REVISIONS_RUNNING"}:
        raise ValueError(f"Phase 2 cannot run from {ledger['state']}")
    segment_ids = [f"{item['number']:02d}" for item in raw_manifest["segments"]]
    jobs = JobLedger(project_root)
    if verification_transcriber is None:
        verification_transcriber = build_transcriber(config.get("verification_transcription", {}))
    if segment_scope is not None:
        unknown = segment_scope - set(segment_ids)
        if unknown:
            raise ValueError(f"revision references unknown segments: {sorted(unknown)}")
    results = []
    try:
        for segment_id in segment_ids:
            output_root = project_root / "04_phase2" / "segments" / segment_id
            if segment_scope is not None and segment_id not in segment_scope:
                required = [output_root / name for name in ("review.mp4", "rendered-transcript.json", "verification.json", "qc.json", "fixes.md")]
                if not all(path.is_file() for path in required):
                    raise ValueError(f"unchanged segment {segment_id} has no verified previous render")
                results.append({
                    "segment_id": segment_id, "cache_hit": True,
                    "output": required[0], "actual_path": required[1], "verification_path": required[2], "qc_path": required[3],
                    "verification": read_json(required[2]), "qc": read_json(required[3]),
                })
                continue
            group = next(item for item in raw_manifest["segments"] if f"{item['number']:02d}" == segment_id)
            media = {item["id"]: item for item in raw_manifest["files"]}
            phase1_root = project_root / "03_phase1" / "segments" / segment_id
            job_fingerprint = canonical_json_hash({
                "raw": sorted((media[item_id]["id"], media[item_id]["sha256"]) for item_id in group["feeds"].values()),
                "transcript": sha256_file(phase1_root / "transcript.md"),
                "visual_plan": sha256_file(phase1_root / "visual-plan.json"),
                "sync_report": sha256_file(phase1_root / "sync-report.json"),
                "grade_manifest": sha256_file(phase1_root / "grade-manifest.json"),
                "style_version": config.get("style_version", "default-v1"),
                "rule_versions": config.get("rule_versions", {}),
                "render_profile": config.get("render_profile", {}),
                "verification_transcription": config.get("verification_transcription", {}),
                "transcript_verification": config.get("transcript_verification", {}),
                "visual_probe_interval_s": config.get("visual_probe_interval_s", 2.0),
                "visual_render_policy": "gate2-v4",
                "renderer_contract": "segment-renderer-v5",
                "visual_audit": "gate2-visual-audit-v4-composition",
            })
            job_id = f"phase2.segment.{segment_id}"
            worker_version = "segment-compose-asr-verify-qc-v16"
            reusable = jobs.reusable(job_id, worker_version=worker_version, fingerprint=job_fingerprint)
            if reusable:
                result = {
                    "segment_id": segment_id,
                    "fingerprint": reusable.metadata["render_fingerprint"],
                    "cache_hit": True,
                    "job_reused": True,
                    "output": reusable.outputs["render"],
                    "expected_path": reusable.outputs["expected_transcript"],
                    "actual_path": reusable.outputs["rendered_transcript"],
                    "verification_path": reusable.outputs["verification"],
                    "qc_path": reusable.outputs["qc"],
                    "verification": read_json(reusable.outputs["verification"]),
                    "qc": read_json(reusable.outputs["qc"]),
                }
            else:
                jobs.start(job_id, worker_version=worker_version, fingerprint=job_fingerprint)
                try:
                    result = render_segment(project_root, segment_id=segment_id, raw_manifest=raw_manifest, config=config, output_root=output_root)
                    actual = verification_transcriber.transcribe(result["output"])
                    actual_path = output_root / "rendered-transcript.json"
                    atomic_write_json(actual_path, actual)
                    verification = verify_transcript(result["expected"], actual, **config.get("transcript_verification", {}))
                    verification.update({
                        "provider": verification_transcriber.name, "provider_version": verification_transcriber.version,
                        "bindings": {"render_sha256": sha256_file(result["output"]), "expected_transcript_sha256": sha256_file(result["expected_path"]), "actual_transcript_sha256": sha256_file(actual_path)},
                    })
                    verification_path = output_root / "verification.json"
                    atomic_write_json(verification_path, verification)
                    profile = {
                        "width": 640, "height": 360, "fps": 25,
                        # Имя стиля едет вместе с профилем рендера: субтитры и политика Gate 2
                        # обязаны судить один и тот же вид.
                        "style_version": config.get("style_version"),
                        **config.get("render_profile", {}),
                    }
                    phase1_root = project_root / "03_phase1" / "segments" / segment_id
                    source_transcript = read_json(phase1_root / "source-transcript.json")
                    entries, visuals = load_transcript(phase1_root / "transcript.md", source_transcript)
                    qc = combined_qc(
                        project_root,
                        result["output"],
                        output_root / "probes",
                        expected_duration_s=result["expected"]["duration_s"],
                        width=int(profile["width"]),
                        height=int(profile["height"]),
                        fps=int((result.get("contract") or {}).get("fps") or profile["fps"]),
                        duration_tolerance_s=_duration_tolerance(result.get("contract") or {}),
                        pip_enabled=bool(group["feeds"].get("camera") and group["feeds"].get("screen")),
                        captions_enabled=bool(profile.get("captions", True)),
                        interval_s=float(config.get("visual_probe_interval_s", 2.0)),
                        render_contract=result.get("contract"),
                        require_visual_render_policy=True,
                        transcript_entries=entries,
                        visuals=visuals,
                        require_visual_audit=True,
                        random_audit_count=int(config.get("gate2_random_probe_count", 5)),
                        source_media_path=_segment_source_media(project_root, raw_manifest, group),
                    )
                    qc_path = output_root / "qc.json"
                    atomic_write_json(qc_path, qc)
                    result.update({"actual_path": actual_path, "verification_path": verification_path, "qc_path": qc_path, "verification": verification, "qc": qc})
                except Exception as exc:
                    jobs.fail(job_id, str(exc))
                    raise
            if result["verification"]["verdict"] != "PASS" or result["qc"]["verdict"] != "PASS":
                if not reusable:
                    jobs.fail(job_id, f"worker verdicts: verification={result['verification']['verdict']}, qc={result['qc']['verdict']}")
                # Причина обязана ехать в сообщении: «self-verification failed» без
                # списка претензий заставляет лезть в JSON руками при каждом падении.
                failed_reasons = list(result["verification"].get("reasons") or []) + list(result["qc"].get("reasons") or [])
                detail = "; ".join(str(item) for item in failed_reasons[:6]) or "no reasons recorded"
                raise ValueError(f"segment {segment_id} self-verification failed: {detail}")
            fixes = output_root / "fixes.md"
            if fixes.exists() and segment_scope is not None:
                history = project_root / "04_phase2" / "revision-history"
                history.mkdir(parents=True, exist_ok=True)
                archived = history / f"r{ledger['revision']:06d}-{segment_id}-fixes.md"
                archived.write_text(fixes.read_text(encoding="utf-8"), encoding="utf-8")
                fixes.write_text("# Fixes\n\n", encoding="utf-8")
            elif not fixes.exists():
                fixes.write_text("# Fixes\n\n", encoding="utf-8")
            if not reusable:
                jobs.complete(
                    job_id,
                    worker_version=worker_version,
                    fingerprint=job_fingerprint,
                    outputs={
                        "render": (result["output"], "segment-render"),
                        "expected_transcript": (result["expected_path"], "expected-transcript"),
                        "rendered_transcript": (result["actual_path"], "rendered-transcript"),
                        "verification": (result["verification_path"], "transcript-verification"),
                        "qc": (result["qc_path"], "segment-qc"),
                        "fixes": (fixes, "fixes"),
                    },
                    metadata={"render_fingerprint": result["fingerprint"]},
                )
            results.append(result)
            store.checkpoint(f"segment-{segment_id}-verified", evidence={"fingerprint": result["fingerprint"], "cache_hit": result["cache_hit"], "job_reused": bool(reusable)})
            if test_hook:
                test_hook(f"phase2.segment.{segment_id}")
        gate1_approval = store.read()["gates"]["gate1"]["approval"]
        segment_rows_for_manifest = []
        for result in results:
            segment_id = result["segment_id"]
            output_root = project_root / "04_phase2" / "segments" / segment_id
            segment_rows_for_manifest.append({
                "id": segment_id,
                "render": artifact_record(project_root, output_root / "review.mp4", kind="segment-render"),
                "expected_transcript": artifact_record(project_root, output_root / "expected-transcript.json", kind="expected-transcript"),
                "rendered_transcript": artifact_record(project_root, output_root / "rendered-transcript.json", kind="rendered-transcript"),
                "verification": artifact_record(project_root, output_root / "verification.json", kind="transcript-verification"),
                "qc": artifact_record(project_root, output_root / "qc.json", kind="segment-qc"),
                "fixes": artifact_record(project_root, output_root / "fixes.md", kind="fixes"),
            })
        continuity = write_phase2_film_continuity(project_root, segment_rows_for_manifest)
        if continuity["verdict"] != "PASS":
            raise ValueError(
                "film continuity BLOCKED after Phase 2: cross-segment KEEP duplicates in expected transcripts"
            )
        review = _write_review(project_root, results, continuity=continuity)
        continuity_path = project_root / "04_phase2" / "film-continuity.json"
        manifest: dict[str, Any] = {
            "schema_version": 1, "kind": "gate2", "project_id": config["id"],
            "revision": int(config.get("render_revision", 1)), "gate1_approval": gate1_approval,
            "review": artifact_record(project_root, review, kind="gate2-review"),
            "film_continuity": artifact_record(project_root, continuity_path, kind="film-continuity"),
            "segments": segment_rows_for_manifest,
        }
        manifest_path = project_root / "04_phase2" / "gate2-manifest.json"
        atomic_write_json(manifest_path, manifest)
        store.prepare_gate("gate2", manifest_path)
        return manifest_path
    except Exception as exc:
        if store.read()["state"] in {"PHASE2_RUNNING", "REVISIONS_RUNNING"}:
            store.fail(str(exc), retryable=True)
        raise
