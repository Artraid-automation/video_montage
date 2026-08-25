"""Re-apply editorial + mandatory LLM cohesion onto existing Phase 1 sources."""

from __future__ import annotations

from pathlib import Path

from pipeline.factory.artifacts import artifact_record
from pipeline.factory.editorial import analyze_editorial, apply_editorial_proposals
from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.jobs import JobLedger
from pipeline.factory.llm_editorial import run_llm_editorial
from pipeline.factory.llm_visual import run_llm_visual
from pipeline.factory.phase1 import (
    _broll_records,
    _cross_segment_take_artifact,
    _editorial_analyze_kwargs,
    _editorial_llm_config,
    _entries,
    _library_root,
    _media_by_id,
    _visual_llm_config,
    assemble_gate1,
)
from pipeline.factory.state import StateStore
from pipeline.factory.transcript import TranscriptEntry, VisualEntry, render_transcript
from pipeline.factory.utterances import coalesce_source_transcript


def _visual_entries(visual_plan: dict) -> list[VisualEntry]:
    return [
        VisualEntry(
            scene["id"],
            scene["anchor"],
            scene["type"],
            scene["brief"],
            scene.get("asset"),
            scene.get("end_s"),
            scene.get("start_s"),
        )
        for scene in visual_plan["scenes"]
    ]

def _fix_asr_text(text: str) -> str:
    return (
        text.replace("вечерна на нуле", "вечно на нуле")
        .replace("не на какой-то счет в этом банке, она", "не на какой-то счет в этом банке, а на")
    )


def main() -> None:
    root = Path("projects/tanya-reel-pilot").resolve()
    config = read_json(root / "project.json")
    raw = read_json(root / "03_phase1/manifest.json")
    media = _media_by_id(raw)
    library = _library_root(root, config)
    records = []
    for group in raw["segments"]:
        segment_id = f"{group['number']:02d}"
        segment_root = root / "03_phase1" / "segments" / segment_id
        source_path = segment_root / "source-transcript.json"
        source = read_json(source_path)
        review_source = coalesce_source_transcript(source)
        source_record = artifact_record(root, source_path, kind="source-transcript")
        editorial = analyze_editorial(review_source, **_editorial_analyze_kwargs(config))
        editorial["source_transcript_sha256"] = source_record["sha256"]
        atomic_write_json(segment_root / "editorial-analysis.json", editorial)
        entries = apply_editorial_proposals(_entries(review_source, []), editorial)
        entries = [
            TranscriptEntry(
                item.kind, item.id, item.start_s, item.end_s, item.word_ids,
                _fix_asr_text(item.text), item.reason,
            )
            for item in entries
        ]
        entries, llm_result = run_llm_editorial(
            segment_id,
            entries,
            output_dir=segment_root,
            config=_editorial_llm_config(config),
        )
        visual_plan, visual_result = run_llm_visual(
            segment_id,
            entries,
            output_dir=segment_root,
            library_root=library,
            project_root=root,
            config=_visual_llm_config(config, segment_id),
        )
        visuals = _visual_entries(visual_plan)
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
        transcript_record = artifact_record(root, transcript_path, kind="editable-transcript")
        visual_plan["transcript_sha256"] = transcript_record["sha256"]
        atomic_write_json(segment_root / "visual-plan.json", visual_plan)
        feeds = group["feeds"]
        speech = media[feeds.get("camera") or feeds["screen"]]
        sync = read_json(segment_root / "sync-report.json")
        keep = sum(1 for item in entries if item.kind == "keep")
        cut = sum(1 for item in entries if item.kind == "cut")
        print(
            f"{segment_id}: keep={keep} cut={cut} "
            f"editorial={len(editorial['candidates'])} llm={llm_result['provider']} "
            f"visuals={len(visuals)} ({visual_result['provider']})"
        )
        records.append({
            "id": segment_id,
            "source_transcript": source_record,
            "editorial_analysis": artifact_record(
                root, segment_root / "editorial-analysis.json", kind="editorial-analysis"
            ),
            "transcript": transcript_record,
            "sync_report": artifact_record(root, segment_root / "sync-report.json", kind="sync-report"),
            "grade_manifest": artifact_record(root, segment_root / "grade-manifest.json", kind="grade-manifest"),
            "visual_plan": artifact_record(root, segment_root / "visual-plan.json", kind="visual-plan"),
            "broll_assets": _broll_records(root, visual_plan),
            "provider_version": f"{source['provider']}:{source['provider_version']}",
            "review_row": {
                "id": segment_id,
                "source": speech["path"],
                "sync": sync["verdict"],
                "visual_count": len(visuals),
                "editorial_candidate_count": len(editorial["candidates"]),
                "llm_editorial_provider": llm_result["provider"],
                "broll_match_count": sum(
                    scene.get("resolution") == "LIBRARY_MATCH" for scene in visual_plan["scenes"]
                ),
                "motion_fallback_count": sum(
                    scene.get("resolution") == "MOTION_FALLBACK" for scene in visual_plan["scenes"]
                ),
            },
        })
    cross = _cross_segment_take_artifact(root, config, records, JobLedger(root))
    manifest = assemble_gate1(root, config, records, cross)
    StateStore(root).prepare_gate("gate1", manifest)
    print(manifest)


if __name__ == "__main__":
    main()
