"""Phase 1: ingest, transcript planning, sync, grade samples, and Gate 1 assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .artifacts import artifact_record
from .broll import SEARCH_WORKER_VERSION
from .cross_takes import CROSS_TAKES_WORKER_VERSION, analyze_cross_segment_takes
from .film_continuity import (
    FILM_CONTINUITY_WORKER_VERSION,
    analyze_film_continuity,
    keeps_from_entries,
    segment_continuity_input,
)
from .editorial import EDITORIAL_WORKER_VERSION, analyze_editorial, apply_editorial_proposals
from .pauses import DEFAULT_KEEP_S, DEFAULT_THRESHOLD_S, apply_cuts_to_entries, cut_plan
from .style_profile import load_style, section as style_section, style_id_from
from .llm_editorial import LLM_EDITORIAL_WORKER_VERSION, run_llm_editorial
from .llm_visual import LLM_VISUAL_WORKER_VERSION, run_llm_visual
from .utterances import coalesce_source_transcript
from .grade import generate_grade_samples
from .ingest import scan_raw
from .io import atomic_write_json, canonical_json_hash, read_json, resolve_project_path, sha256_file
from .jobs import JobLedger
from .planning import VISUAL_PLANNER_VERSION, plan_visuals
from .providers import build_transcriber
from .rules import load_approved_rules
from .state import StateStore
from .style_guard import reconcile_style_scenes
from .sync import analyze_sync
from .transcript import TranscriptEntry, VisualEntry, render_transcript


def _media_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in manifest["files"]}


def _library_root(project_root: Path, config: dict[str, Any]) -> Path:
    configured = config.get("broll_library_root")
    if configured:
        candidate = Path(str(configured))
        return (project_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if project_root.parent.name == "projects":
        return (project_root.parent.parent / "library" / "broll").resolve()
    return (project_root.parent / "_library" / "broll").resolve()


def _catalog_fingerprint(library_root: Path) -> str:
    catalog = library_root / "catalog.json"
    return sha256_file(catalog) if catalog.is_file() else "catalog:missing"


def _cross_segment_take_artifact(
    project_root: Path, config: dict[str, Any], segment_records: list[dict[str, Any]], jobs: JobLedger,
) -> Path:
    sources = [{
        "segment_id": item["id"],
        "sha256": item["source_transcript"]["sha256"],
        "transcript": read_json(resolve_project_path(project_root, item["source_transcript"]["path"])),
    } for item in segment_records]
    settings = config.get("cross_segment_takes", {})
    fingerprint = canonical_json_hash({
        "worker_version": CROSS_TAKES_WORKER_VERSION,
        "sources": [(item["segment_id"], item["sha256"]) for item in sources],
        "settings": settings,
    })
    job_id = "phase1.cross-segment-takes"
    reusable = jobs.reusable(job_id, worker_version=CROSS_TAKES_WORKER_VERSION, fingerprint=fingerprint)
    if reusable:
        return reusable.outputs["analysis"]
    jobs.start(job_id, worker_version=CROSS_TAKES_WORKER_VERSION, fingerprint=fingerprint)
    try:
        analysis = analyze_cross_segment_takes(sources, **settings)
        output = project_root / "03_phase1" / "cross-segment-take-analysis.json"
        atomic_write_json(output, analysis)
        jobs.complete(
            job_id, worker_version=CROSS_TAKES_WORKER_VERSION, fingerprint=fingerprint,
            outputs={"analysis": (output, "cross-segment-take-analysis")},
            metadata={"candidate_count": len(analysis["candidates"])},
        )
        return output
    except Exception as exc:
        jobs.fail(job_id, str(exc))
        raise


def _broll_records(project_root: Path, visual_plan: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for scene in visual_plan.get("scenes", []):
        if scene.get("resolution") != "LIBRARY_MATCH":
            continue
        asset = scene.get("asset")
        if not isinstance(asset, str) or not asset:
            raise ValueError(f"library scene {scene.get('id')} has no staged asset")
        record = artifact_record(project_root, resolve_project_path(project_root, asset), kind="library-broll")
        if record["sha256"] != scene.get("asset_sha256"):
            raise ValueError(f"library scene {scene.get('id')} staged asset hash is stale")
        records.append(record)
    return records


def _pause_cut_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    """Порог реза пауз берётся из стиля: плотность речи — часть вида, а не настройка кода.

    Явная настройка в `config["pauses"]` перебивает стиль — так пилотный проект можно
    провести на другом пороге, не заводя ради этого новый стиль.
    """
    rhythm = style_section(load_style(style_id_from(config)), "rhythm")
    raw = dict(config.get("pauses") or {})
    return {
        "threshold_s": float(raw.get("threshold_s", rhythm.get("pause_cut_threshold_s", DEFAULT_THRESHOLD_S))),
        "keep_s": float(raw.get("keep_s", rhythm.get("keep_pause_s", DEFAULT_KEEP_S))),
    }


def _pause_cuts_enabled(config: dict[str, Any]) -> bool:
    """Резать ли паузы фактически. По умолчанию нет — старые проекты не меняют поведение."""
    raw = dict(config.get("pauses") or {})
    if "apply" in raw:
        return bool(raw["apply"])
    rhythm = style_section(load_style(style_id_from(config)), "rhythm")
    return bool(rhythm.get("apply_pause_cuts", False))


def _editorial_analyze_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    raw = dict(config.get("editorial", {}))
    raw.pop("llm", None)
    allowed = {"pause_threshold_s", "repetition_similarity", "block_pause_s"}
    return {key: raw[key] for key in allowed if key in raw}


def _editorial_llm_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = dict(config.get("editorial", {}).get("llm") or {})
    # Tests and synthetic sidecars default to deterministic fixture pass-through.
    # Real projects should set provider to agent/openai/file.
    return {
        "provider": raw.get("provider", "fixture"),
        **{key: value for key, value in raw.items() if key != "provider"},
    }


def _visual_llm_config(config: dict[str, Any], segment_id: str | None = None) -> dict[str, Any]:
    raw = dict(config.get("visual_llm") or {})
    editorial_provider = str(_editorial_llm_config(config).get("provider", "fixture"))
    default_provider = "agent" if editorial_provider == "agent" else "fixture"
    settings = {
        "provider": raw.get("provider", default_provider),
        "style_version": config.get("style_version", "dankoe-mevga-v1"),
        **{key: value for key, value in raw.items() if key != "provider"},
    }
    if segment_id is not None:
        settings["configured"] = list(config.get("visuals", {}).get(segment_id, []))
        settings["auto_config"] = config.get("visual_planning", {"enabled": False})
    return settings


def _entries(source_transcript: dict[str, Any], approved_rules: list[dict[str, Any]] | None = None) -> list[TranscriptEntry]:
    entries = []
    approved_rules = approved_rules or []
    for utterance in source_transcript["utterances"]:
        decision = utterance.get("decision", "keep")
        if decision not in {"keep", "cut"}:
            raise ValueError(f"utterance {utterance['id']} has invalid decision {decision}")
        text = utterance["text"]
        for rule in approved_rules:
            if rule.get("operation") == "replace_text":
                text = text.replace(str(rule["match"]), str(rule.get("replacement", "")))
        entries.append(TranscriptEntry(
            kind=decision, id=utterance["id"], start_s=float(utterance["start_s"]),
            end_s=float(utterance["end_s"]), word_ids=tuple(utterance["word_ids"]),
            text=text, reason=utterance.get("reason"),
        ))
    return entries


def _write_review(
    project_root: Path,
    segment_rows: list[dict[str, Any]],
    warnings: list[str],
    cross_take_count: int,
    *,
    continuity: dict[str, Any] | None = None,
) -> Path:
    lines = ["# Gate 1 — монтажное решение", "", "## Blocking warnings", ""]
    lines.extend([f"- {warning}" for warning in warnings] or ["- Нет."])
    if continuity and continuity.get("verdict") == "BLOCKED":
        lines.append(
            f"- **FILM CONTINUITY BLOCKED:** {len(continuity.get('blocking_groups', []))} "
            "KEEP-дублей между сегментами — склейка в один ролик запрещена, пока не CUT "
            "(см. раздел «Цельный фильм» и `film-continuity.json`)."
        )
    lines.extend([
        "",
        "## Легенда артефактов",
        "",
        "- `transcript.md` — интерфейс монтажа в preview-safe виде: `[0:12.000 -> 0:13.500] KEEP/CUT`, рядом `[MOTION]` / `[BROLL]` / `[FOOTAGE]`. Это **не** субтитры.",
        "- Captions в Phase 2 собираются из блоков `KEEP`. `CUT` вырезается. Visual-метки — план вставок на якоре фразы.",
        "- `grade-samples/` — 3 JPG варианта цвета (neutral/warm/punchy); выбор в `grade-manifest.json` → `selected`.",
        "- `editorial-analysis.json` — машинные кандидаты (паузы/повторы/тейки). Читать JSON не обязательно: предложения зеркалятся в `CUT`.",
        "- `Editorial candidates requiring review` — сколько кандидатов система пометила; сверь KEEP/CUT и MOTION briefs.",
        "- `film-continuity.json` — проверка, что KEEP всех сегментов можно склеить в **один** ролик без дублей.",
        "",
        "## Сегменты",
        "",
    ])
    for row in segment_rows:
        lines.extend([
            f"### {row['id']}", "",
            f"- Source: `{row['source']}`",
            f"- Transcript: [`segments/{row['id']}/transcript.md`](segments/{row['id']}/transcript.md)",
            f"- Sync: **{row['sync']}**",
            f"- Grade samples: `segments/{row['id']}/grade-samples/`",
            f"- Editorial analysis: `segments/{row['id']}/editorial-analysis.json`",
            f"- Editorial candidates requiring review: {row['editorial_candidate_count']}",
            f"- Visual plan: `segments/{row['id']}/visual-plan.json`",
            f"- Visual proposals: {row['visual_count']}",
            f"- B-roll matches / motion fallbacks: {row['broll_match_count']} / {row['motion_fallback_count']}", "",
        ])
    continuity = continuity or {"verdict": "PASS", "blocking_groups": [], "uncertain_matches": []}
    lines.extend([
        "## Цельный фильм (склейка сегментов)",
        "",
        "Сегменты — **части одного ролика**, не независимые клипы. Phase 3 склеит KEEP в master.",
        f"- Continuity verdict: **{continuity.get('verdict', 'PASS')}**",
        f"- Blocking KEEP duplicates: {len(continuity.get('blocking_groups', []))}",
        f"- Uncertain matches (review only): {len(continuity.get('uncertain_matches', []))}",
        "- Artifact: [`film-continuity.json`](film-continuity.json)",
        "",
    ])
    for group in continuity.get("blocking_groups", []):
        keep = group.get("recommended_keep", {})
        cuts = group.get("recommended_cut", [])
        members = ", ".join(
            f"{item['segment_id']}/{item['keep_id']}" for item in group.get("members", [])
        )
        cut_txt = ", ".join(f"{item['segment_id']}/{item['keep_id']}" for item in cuts)
        lines.extend([
            f"- **BLOCK** `{group.get('id')}` sim={group.get('minimum_similarity')}: {members}",
            f"  - recommended KEEP: `{keep.get('segment_id')}/{keep.get('keep_id')}`",
            f"  - recommended CUT: `{cut_txt}`",
            "",
        ])
    lines.extend([
        "## Обязательная проверка", "",
        "1. Прочитать каждый `transcript.md`; менять KEEP/CUT, текст и MOTION/BROLL briefs.",
        "2. Предложенные `CUT` можно вернуть в `KEEP` и наоборот — Phase 2 режет только CUT.",
        "3. Выбрать grade в `grade-manifest.json`.",
        "4. Проверить sync report и visual placements.",
        "5. Снять **FILM CONTINUITY BLOCKED** (CUT дублирующих KEEP между сегментами), иначе approval невозможен.",
        "6. После правок выполнить refresh Gate 1; approval привязан к новым hashes.", "",
        "Project-level analysis: `cross-segment-take-analysis.json`.",
        f"Cross-segment take candidates requiring review: {cross_take_count}",
        "Кандидаты зеркалятся в transcript как предлагаемые CUT; финальное решение за автором на Gate 1.", "",
        "Phase 2 не запускается без валидного approval.", "",
    ])
    path = project_root / "03_phase1" / "review.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _build_continuity_from_records(project_root: Path, segment_records: list[dict[str, Any]]) -> dict[str, Any]:
    from .transcript import load_transcript

    inputs: list[dict[str, Any]] = []
    for record in segment_records:
        segment_id = record["id"]
        transcript_path = project_root / record["transcript"]["path"]
        source_path = project_root / record["source_transcript"]["path"]
        source = read_json(source_path)
        entries, _visuals = load_transcript(transcript_path, source)
        inputs.append(segment_continuity_input(
            segment_id=segment_id,
            transcript_sha256=record["transcript"]["sha256"],
            keeps=keeps_from_entries(entries),
        ))
    return analyze_film_continuity(inputs)


def assemble_gate1(
    project_root: Path, project_config: dict[str, Any], segment_records: list[dict[str, Any]],
    cross_take_path: Path,
) -> Path:
    cross_take_analysis = read_json(cross_take_path)
    continuity = _build_continuity_from_records(project_root, segment_records)
    continuity_path = project_root / "03_phase1" / "film-continuity.json"
    atomic_write_json(continuity_path, continuity)
    warnings: list[str] = []
    if continuity["verdict"] == "BLOCKED":
        warnings.append(
            "Film continuity BLOCKED: resolve cross-segment KEEP duplicates before Gate 1 approval "
            "(see film-continuity.json)."
        )
    review = _write_review(
        project_root, [item["review_row"] for item in segment_records], warnings,
        len(cross_take_analysis["candidates"]) + len(cross_take_analysis["uncertain_matches"]),
        continuity=continuity,
    )
    manifest = {
        "schema_version": 1, "kind": "gate1", "project_id": project_config["id"],
        "revision": int(project_config.get("editorial_revision", 1)),
        "style_version": str(project_config.get("style_version", "default-v1")),
        "provider_versions": {
            "transcription": segment_records[0]["provider_version"],
            "editorial": EDITORIAL_WORKER_VERSION, "visual_planning": VISUAL_PLANNER_VERSION,
            "broll_search": SEARCH_WORKER_VERSION,
            "cross_segment_takes": CROSS_TAKES_WORKER_VERSION,
            "film_continuity": FILM_CONTINUITY_WORKER_VERSION,
        },
        "review": artifact_record(project_root, review, kind="gate1-review"),
        "cross_segment_take_analysis": artifact_record(
            project_root, cross_take_path, kind="cross-segment-take-analysis"
        ),
        "film_continuity": artifact_record(project_root, continuity_path, kind="film-continuity"),
        "segments": [{key: value for key, value in item.items() if key not in {"review_row", "provider_version"}} for item in segment_records],
    }
    output = project_root / "03_phase1" / "gate1-manifest.json"
    atomic_write_json(output, manifest)
    return output


def run_phase1(project_root: Path, store: StateStore | None = None, *, restart_reason: str | None = None, test_hook: Callable[[str], None] | None = None) -> Path:
    project_root = project_root.resolve(strict=True)
    store = store or StateStore(project_root)
    config = read_json(project_root / "project.json")
    raw_manifest = scan_raw(project_root, allow_number_gaps=bool(config.get("allow_number_gaps", False)))
    inputs_hash = canonical_json_hash({
        "raw": [(item["path"], item["sha256"]) for item in raw_manifest["files"]],
        "config": config,
    })
    ledger = store.ensure()
    if ledger["state"] == "GATE1_REVIEW" and restart_reason:
        ledger = store.restart_phase1(inputs_hash=inputs_hash, reason=restart_reason)
    if ledger["state"] == "NEW":
        store.begin_phase("phase1", inputs_hash=inputs_hash)
    elif ledger["state"] != "PHASE1_RUNNING":
        raise ValueError(f"Phase 1 cannot run from {ledger['state']}")
    output_root = project_root / "03_phase1"
    output_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_root / "manifest.json", raw_manifest)
    store.checkpoint("ingested", evidence={"manifest_hash": canonical_json_hash(raw_manifest)})
    try:
        if test_hook:
            test_hook("phase1.ingested")
        transcriber = build_transcriber(config.get("transcription", {}))
    except Exception as exc:
        if store.read()["state"] == "PHASE1_RUNNING":
            store.fail(str(exc), retryable=True)
        raise
    rules_ledger = load_approved_rules(project_root)
    approved_rules = rules_ledger.get("approved", [])
    media = _media_by_id(raw_manifest)
    library_root = _library_root(project_root, config)
    jobs = JobLedger(project_root)
    segment_records = []
    try:
        for group in raw_manifest["segments"]:
            segment_id = f"{group['number']:02d}"
            feeds = group["feeds"]
            speech_media = media[feeds.get("camera") or feeds["screen"]]
            speech_path = resolve_project_path(project_root, speech_media["path"])
            job_fingerprint = canonical_json_hash({
                "feeds": sorted((role, media[item_id]["sha256"]) for role, item_id in feeds.items()),
                "transcription": config.get("transcription", {}),
                "visuals": config.get("visuals", {}).get(segment_id, []),
                "visual_planning": config.get("visual_planning", {
                    "enabled": True, "cadence_seconds": 30.0, "max_per_segment": 6,
                }),
                "editorial": config.get("editorial", {}),
                "broll_catalog": _catalog_fingerprint(library_root),
                "default_grade": config.get("default_grade"),
                "approved_rules": approved_rules,
            })
            job_id = f"phase1.segment.{segment_id}"
            worker_version = (
                f"phase1-bundle-v5:{transcriber.name}:{transcriber.version}:"
                f"{EDITORIAL_WORKER_VERSION}:{VISUAL_PLANNER_VERSION}:{SEARCH_WORKER_VERSION}"
            )
            reusable = jobs.reusable(job_id, worker_version=worker_version, fingerprint=job_fingerprint)
            if reusable:
                source_path = reusable.outputs["source_transcript"]
                transcript_path = reusable.outputs["transcript"]
                sync_path = reusable.outputs["sync_report"]
                grade_path = reusable.outputs["grade_manifest"]
                visual_path = reusable.outputs["visual_plan"]
                editorial_path = reusable.outputs["editorial_analysis"]
                review_row = reusable.metadata["review_row"]
                source_record = artifact_record(project_root, source_path, kind="source-transcript")
            else:
                jobs.start(job_id, worker_version=worker_version, fingerprint=job_fingerprint)
                try:
                    source_transcript = transcriber.transcribe(speech_path)
                    segment_root = output_root / "segments" / segment_id
                    segment_root.mkdir(parents=True, exist_ok=True)
                    source_path = segment_root / "source-transcript.json"
                    atomic_write_json(source_path, source_transcript)
                    source_record = artifact_record(project_root, source_path, kind="source-transcript")
                    review_source = coalesce_source_transcript(source_transcript)
                    editorial = analyze_editorial(review_source, **_editorial_analyze_kwargs(config))
                    editorial["source_transcript_sha256"] = source_record["sha256"]
                    # Паузы между словами — свой масштаб: analyze_editorial ищет провалы
                    # между высказываниями (порядка секунды), а плотность речи делается
                    # промежутками от десятых долей. План кладём кандидатом, не решением.
                    pause_plan = None
                    try:
                        pause_plan = cut_plan(
                            source_transcript,
                            audio_path=speech_path,
                            **_pause_cut_kwargs(config),
                        )
                        pause_plan["source_transcript_sha256"] = source_record["sha256"]
                        editorial["word_pause_plan"] = {
                            "cut_count": pause_plan["cut_count"],
                            "removed_s": pause_plan["removed_s"],
                            "duration_after_s": pause_plan["duration_after_s"],
                            "speech_share_after": pause_plan["speech_share_after"],
                            "thresholds": pause_plan["thresholds"],
                        }
                        atomic_write_json(segment_root / "pause-cut-plan.json", pause_plan)
                    except ValueError as exc:
                        # Расшифровка без пословных таймингов — рез пауз недоступен,
                        # но остальная редактура работать обязана.
                        editorial["word_pause_plan"] = {"unavailable": str(exc)}
                        pause_plan = None
                    editorial_path = segment_root / "editorial-analysis.json"
                    atomic_write_json(editorial_path, editorial)
                    entries = apply_editorial_proposals(_entries(review_source, approved_rules), editorial)
                    # Рез пауз — механический приём стиля, а не смысловое решение:
                    # применяем, если стиль этого требует. Смысловые KEEP/CUT по-прежнему
                    # остаются за агентом и человеком на гейте.
                    if pause_plan and _pause_cuts_enabled(config):
                        before = sum(item.end_s - item.start_s for item in entries)
                        entries = apply_cuts_to_entries(entries, pause_plan["cuts"])
                        after = sum(item.end_s - item.start_s for item in entries)
                        editorial["word_pause_plan"]["applied"] = True
                        editorial["word_pause_plan"]["entry_duration_before_s"] = round(before, 3)
                        editorial["word_pause_plan"]["entry_duration_after_s"] = round(after, 3)
                    entries, llm_editorial = run_llm_editorial(
                        segment_id,
                        entries,
                        output_dir=segment_root,
                        config=_editorial_llm_config(config),
                    )
                    llm_path = segment_root / "llm-editorial.json"
                    visual_plan, llm_visual = run_llm_visual(
                        segment_id,
                        entries,
                        output_dir=segment_root,
                        library_root=library_root,
                        project_root=project_root,
                        config=_visual_llm_config(config, segment_id),
                    )
                    visuals = [
                        VisualEntry(
                            id=scene["id"], anchor=scene["anchor"], type=scene["type"],
                            brief=scene["brief"], asset=scene.get("asset"),
                            end_s=scene.get("end_s"), start_s=scene.get("start_s"),
                        )
                        for scene in visual_plan["scenes"]
                    ]
                    transcript_path = segment_root / "transcript.md"
                    media_end_s = max((float(item.end_s) for item in entries), default=0.0)
                    transcript_path.write_text(
                        render_transcript(
                            entries,
                            visuals,
                            segment_id=segment_id,
                            media_end_s=media_end_s,
                        ),
                        encoding="utf-8",
                    )
                    transcript_record = artifact_record(project_root, transcript_path, kind="editable-transcript")
                    visual_path = segment_root / "visual-plan.json"
                    visual_plan["transcript_sha256"] = transcript_record["sha256"]
                    atomic_write_json(visual_path, visual_plan)
                    llm_visual_path = segment_root / "llm-visual.json"
                    sync_path = segment_root / "sync-report.json"
                    if feeds.get("audio"):
                        sync = analyze_sync(speech_path, resolve_project_path(project_root, media[feeds["audio"]]["path"]))
                    else:
                        sync = {"schema_version": 1, "verdict": "NOT_REQUIRED", "reason": "no external audio feed"}
                    sync["bindings"] = {
                        "source_transcript_sha256": source_record["sha256"],
                        "speech_media_sha256": speech_media["sha256"],
                        "audio_media_sha256": media[feeds["audio"]]["sha256"] if feeds.get("audio") else None,
                    }
                    atomic_write_json(sync_path, sync)
                    if sync["verdict"] == "FAIL":
                        raise ValueError(f"segment {segment_id} audio sync failed: {sync.get('reasons')}")
                    representative = entries[0].start_s if entries else 0.0
                    grade = generate_grade_samples(project_root, speech_path, segment_root / "grade-samples", representative_s=representative)
                    if config.get("default_grade"):
                        grade["selected"] = config["default_grade"]
                    grade_path = segment_root / "grade-manifest.json"
                    atomic_write_json(grade_path, grade)
                    review_row = {
                        "id": segment_id, "source": speech_media["path"], "sync": sync["verdict"],
                        "visual_count": len(visuals), "editorial_candidate_count": len(editorial["candidates"]),
                        "broll_match_count": sum(scene.get("resolution") == "LIBRARY_MATCH" for scene in visual_plan["scenes"]),
                        "motion_fallback_count": sum(scene.get("resolution") == "MOTION_FALLBACK" for scene in visual_plan["scenes"]),
                    }
                    job_outputs = {
                        "source_transcript": (source_path, "source-transcript"),
                        "editorial_analysis": (editorial_path, "editorial-analysis"),
                        "llm_editorial": (llm_path, "llm-editorial"),
                        "llm_visual": (llm_visual_path, "llm-visual"),
                        "transcript": (transcript_path, "editable-transcript"),
                        "sync_report": (sync_path, "sync-report"),
                        "grade_manifest": (grade_path, "grade-manifest"),
                        "visual_plan": (visual_path, "visual-plan"),
                    }
                    for index, sample in enumerate(grade["samples"]):
                        job_outputs[f"grade_sample_{index}"] = (resolve_project_path(project_root, sample["path"]), "grade-sample")
                    for index, record in enumerate(_broll_records(project_root, visual_plan)):
                        job_outputs[f"broll_asset_{index}"] = (resolve_project_path(project_root, record["path"]), "library-broll")
                    jobs.complete(job_id, worker_version=worker_version, fingerprint=job_fingerprint, outputs=job_outputs, metadata={"review_row": review_row})
                except Exception as exc:
                    jobs.fail(job_id, str(exc))
                    raise
            current_visual_plan = read_json(visual_path)
            segment_records.append({
                "id": segment_id,
                "source_transcript": source_record,
                "editorial_analysis": artifact_record(project_root, editorial_path, kind="editorial-analysis"),
                "transcript": artifact_record(project_root, transcript_path, kind="editable-transcript"),
                "sync_report": artifact_record(project_root, sync_path, kind="sync-report"),
                "grade_manifest": artifact_record(project_root, grade_path, kind="grade-manifest"),
                "visual_plan": artifact_record(project_root, visual_path, kind="visual-plan"),
                "broll_assets": _broll_records(project_root, current_visual_plan),
                "provider_version": f"{transcriber.name}:{transcriber.version}",
                "review_row": review_row,
            })
        cross_take_path = _cross_segment_take_artifact(project_root, config, segment_records, jobs)
        store.checkpoint("phase1-bundles", evidence={
            "segment_count": len(segment_records),
            "cross_segment_take_analysis_sha256": sha256_file(cross_take_path),
        })
        gate_manifest = assemble_gate1(project_root, config, segment_records, cross_take_path)
        store.prepare_gate("gate1", gate_manifest)
        return gate_manifest
    except Exception as exc:
        if store.read()["state"] == "PHASE1_RUNNING":
            store.fail(str(exc), retryable=True)
        raise


def refresh_gate1(project_root: Path, store: StateStore | None = None) -> Path:
    """Rebind human-edited Phase 1 artifacts without re-running media work."""
    project_root = project_root.resolve(strict=True)
    store = store or StateStore(project_root)
    if store.read()["state"] != "GATE1_REVIEW":
        raise ValueError(f"Gate 1 can be refreshed only during review, current={store.read()['state']}")
    config = read_json(project_root / "project.json")
    raw_manifest = read_json(project_root / "03_phase1" / "manifest.json")
    media = _media_by_id(raw_manifest)
    records = []
    from .transcript import load_transcript
    for group in raw_manifest["segments"]:
        segment_id = f"{group['number']:02d}"
        segment_root = project_root / "03_phase1" / "segments" / segment_id
        source_path = segment_root / "source-transcript.json"
        transcript_path = segment_root / "transcript.md"
        source = read_json(source_path)
        entries, visuals = load_transcript(transcript_path, source)
        visual_path = segment_root / "visual-plan.json"
        previous_plan = read_json(visual_path)
        previous_scenes = {scene["id"]: scene for scene in previous_plan.get("scenes", [])}
        refreshed_scenes = []
        refreshed_searches = []
        for visual in visuals:
            previous = previous_scenes.get(visual.id)
            if visual.type == "library-broll":
                requested_asset = visual.asset
                if (
                    previous and previous.get("asset") == visual.asset
                    and previous.get("resolution") == "LIBRARY_MATCH"
                ):
                    requested_asset = previous.get("catalog_asset_id")
                planned = plan_visuals(
                    segment_id, entries, [{
                        "id": visual.id, "anchor": visual.anchor, "type": visual.type,
                        "brief": visual.brief, "asset": requested_asset,
                        "origin": previous.get("origin", "USER_EDITED") if previous else "USER_EDITED",
                    }], library_root=_library_root(project_root, config), project_root=project_root,
                )
                refreshed_scenes.extend(planned["scenes"]); refreshed_searches.extend(planned["searches"])
            else:
                refreshed_scenes.append({
                    "id": visual.id, "anchor": visual.anchor, "type": visual.type,
                    "brief": visual.brief, "asset": visual.asset,
                    "resolution": previous.get("resolution", "CONFIGURED") if previous else "CONFIGURED",
                    "origin": previous.get("origin", "USER_EDITED") if previous else "USER_EDITED",
                    "status": "PROPOSED",
                })
        visual_plan = {
            "schema_version": 1, "kind": "visual-plan", "worker_version": VISUAL_PLANNER_VERSION,
            "segment_id": segment_id, "scenes": refreshed_scenes,
            "searches": refreshed_searches or previous_plan.get("searches", []),
            "status": "PROPOSED" if refreshed_scenes else "NO_VISUALS_PROPOSED",
            "transcript_sha256": artifact_record(project_root, transcript_path, kind="editable-transcript")["sha256"],
        }
        # MeVGa style recipes must survive Gate 1 refresh (Slava catch: list never rendered).
        if previous_plan.get("style_scenes"):
            visual_plan["style_scenes"] = previous_plan["style_scenes"]
        visual_plan = reconcile_style_scenes(visual_plan, segment_root=segment_root)
        atomic_write_json(visual_path, visual_plan)
        editorial_path = segment_root / "editorial-analysis.json"
        editorial = read_json(editorial_path)
        sync_path = segment_root / "sync-report.json"
        grade_path = segment_root / "grade-manifest.json"
        feeds = group["feeds"]
        speech_media = media[feeds.get("camera") or feeds["screen"]]
        records.append({
            "id": segment_id,
            "source_transcript": artifact_record(project_root, source_path, kind="source-transcript"),
            "editorial_analysis": artifact_record(project_root, editorial_path, kind="editorial-analysis"),
            "transcript": artifact_record(project_root, transcript_path, kind="editable-transcript"),
            "sync_report": artifact_record(project_root, sync_path, kind="sync-report"),
            "grade_manifest": artifact_record(project_root, grade_path, kind="grade-manifest"),
            "visual_plan": artifact_record(project_root, visual_path, kind="visual-plan"),
            "broll_assets": _broll_records(project_root, visual_plan),
            "provider_version": f"{source['provider']}:{source['provider_version']}",
            "review_row": {
                "id": segment_id, "source": speech_media["path"], "sync": read_json(sync_path)["verdict"],
                "visual_count": len(visuals), "editorial_candidate_count": len(editorial["candidates"]),
                "broll_match_count": sum(scene.get("resolution") == "LIBRARY_MATCH" for scene in visual_plan["scenes"]),
                "motion_fallback_count": sum(scene.get("resolution") == "MOTION_FALLBACK" for scene in visual_plan["scenes"]),
            },
        })
    cross_take_path = _cross_segment_take_artifact(project_root, config, records, JobLedger(project_root))
    manifest_path = assemble_gate1(project_root, config, records, cross_take_path)
    store.prepare_gate("gate1", manifest_path)
    return manifest_path
