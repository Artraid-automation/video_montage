from __future__ import annotations

import json
import subprocess
import shutil
from pathlib import Path
from typing import Any

from pipeline.factory.artifacts import artifact_record
from pipeline.factory.io import atomic_write_json


def make_project(root: Path, project_id: str = "fixture") -> Path:
    project = root / project_id
    for directory in (
        "01_raw", "02_inputs", "03_phase1/segments/01/grade-samples", "04_phase2/segments/01",
        "05_final/publishing-package", "06_state/checkpoints",
    ):
        (project / directory).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project / "project.json", {"schema_version": 2, "id": project_id, "title": "Fixture"})
    return project


def write_json(path: Path, value: Any) -> Path:
    atomic_write_json(path, value)
    return path


def write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def make_video(path: Path, duration: float = 0.6, color: str = "blue", *, with_face: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if with_face:
        face = Path(__file__).resolve().parent / "fixtures" / "frontal-face.jpg"
        if not face.is_file():
            raise FileNotFoundError(f"missing face fixture: {face}")
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-i", str(face),
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-t", str(duration), "-s", "720x1280", "-r", "25",
            # Метка цветом в углу: без неё несколько сегментов с одним лицом дают одинаковый
            # SHA-256, и ingest справедливо отвергает их как дубликат содержимого.
            "-vf", f"drawbox=x=0:y=0:w=48:h=48:color={color}:t=fill",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
        ]
    else:
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=25:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
        ]
    subprocess.run(command, check=True, capture_output=True)
    return path


def gate1_manifest(project: Path) -> Path:
    segment = project / "03_phase1" / "segments" / "01"
    source = write_json(segment / "source-transcript.json", {"schema_version": 1, "utterances": [{"id": "w1", "start_s": 0.0, "end_s": 0.5, "text": "hello", "word_ids": ["w1"]}], "words": [{"id": "w1", "start_s": 0.0, "end_s": 0.5, "text": "hello"}]})
    transcript = write_text(segment / "transcript.md", '<keep id="w1" start="0.000" end="0.500">hello</keep>\n')
    source_hash = artifact_record(project, source, kind="source-transcript")["sha256"]
    editorial = write_json(segment / "editorial-analysis.json", {"schema_version": 1, "kind": "editorial-analysis", "worker_version": "fixture-v1", "source_transcript_sha256": source_hash, "thresholds": {"pause_s": 0.8, "repetition_similarity": 0.88}, "verdict": "NO_CANDIDATES", "pause_candidates": [], "repetition_candidates": [], "take_candidates": [], "candidates": []})
    sync = write_json(segment / "sync-report.json", {"schema_version": 1, "verdict": "NOT_REQUIRED", "bindings": {"source_transcript_sha256": artifact_record(project, source, kind="source-transcript")["sha256"]}})
    visual = write_json(segment / "visual-plan.json", {"schema_version": 1, "kind": "visual-plan", "worker_version": "fixture-v1", "segment_id": "01", "status": "NO_VISUALS_PROPOSED", "scenes": [], "searches": [], "transcript_sha256": artifact_record(project, transcript, kind="editable-transcript")["sha256"]})
    samples = []
    for name in ("neutral", "warm", "punchy"):
        sample = write_text(segment / "grade-samples" / f"{name}.png", name)
        samples.append(artifact_record(project, sample, kind="grade-sample"))
    grade = write_json(segment / "grade-manifest.json", {"schema_version": 1, "verdict": "PASS", "selected": "neutral", "filters": {"neutral": "null", "warm": "warm", "punchy": "punchy"}, "samples": samples})
    cross_takes = write_json(project / "03_phase1" / "cross-segment-take-analysis.json", {
        "schema_version": 1, "kind": "cross-segment-take-analysis", "worker_version": "fixture-v1",
        "input_bindings": [{"segment_id": "01", "source_transcript_sha256": source_hash, "utterance_ids": ["w1"]}],
        "thresholds": {"similarity": 0.84, "recommendation": 0.92, "min_tokens": 5, "metric": "fixture"},
        "verdict": "NO_CANDIDATES", "groups": [], "uncertain_matches": [], "candidates": [],
        "auto_apply": False,
    })
    transcript_hash = artifact_record(project, transcript, kind="editable-transcript")["sha256"]
    continuity = write_json(project / "03_phase1" / "film-continuity.json", {
        "schema_version": 1, "kind": "film-continuity", "worker_version": "fixture-v1",
        "input_bindings": [{"segment_id": "01", "transcript_sha256": transcript_hash, "keep_ids": ["w1"]}],
        "thresholds": {"similarity": 0.84, "recommendation": 0.92, "min_tokens": 5, "metric": "fixture"},
        "verdict": "PASS", "blocking_groups": [], "uncertain_matches": [],
    })
    review = write_text(project / "03_phase1" / "review.md", "# Gate 1\n\nReview every transcript.\n")
    manifest = {
        "schema_version": 1, "kind": "gate1", "project_id": project.name, "revision": 1,
        "style_version": "fixture-style-v1", "provider_versions": {"transcript": "fake-v1"},
        "review": artifact_record(project, review, kind="gate1-review"),
        "cross_segment_take_analysis": artifact_record(project, cross_takes, kind="cross-segment-take-analysis"),
        "film_continuity": artifact_record(project, continuity, kind="film-continuity"),
        "segments": [{
            "id": "01",
            "source_transcript": artifact_record(project, source, kind="source-transcript"),
            "editorial_analysis": artifact_record(project, editorial, kind="editorial-analysis"),
            "transcript": artifact_record(project, transcript, kind="editable-transcript"),
            "sync_report": artifact_record(project, sync, kind="sync-report"),
            "grade_manifest": artifact_record(project, grade, kind="grade-manifest"),
            "visual_plan": artifact_record(project, visual, kind="visual-plan"),
            "broll_assets": [],
        }],
    }
    return write_json(project / "03_phase1" / "gate1-manifest.json", manifest)


def gate2_manifest(project: Path, gate1_approval: dict[str, Any], *, real_video: bool = True) -> Path:
    segment = project / "04_phase2" / "segments" / "01"
    render = segment / "review.mp4"
    if real_video:
        make_video(render)
    else:
        render.write_bytes(b"not a video")
    expected_transcript = write_json(segment / "expected-transcript.json", {"schema_version": 1, "words": [{"text": "hello", "start_s": 0.0, "end_s": 0.5}]})
    rendered_transcript = write_json(segment / "rendered-transcript.json", {"schema_version": 1, "words": [{"text": "hello", "start_s": 0.0, "end_s": 0.5}]})
    render_hash = artifact_record(project, render, kind="segment-render")["sha256"]
    expected_hash = artifact_record(project, expected_transcript, kind="expected-transcript")["sha256"]
    actual_hash = artifact_record(project, rendered_transcript, kind="rendered-transcript")["sha256"]
    verification = write_json(segment / "verification.json", {"schema_version": 1, "verdict": "PASS", "provider": "fixture-asr", "provider_version": "1", "thresholds": {"wer_max": 0.12}, "metrics": {"wer": 0.0}, "bindings": {"render_sha256": render_hash, "expected_transcript_sha256": expected_hash, "actual_transcript_sha256": actual_hash}})
    qc = write_json(segment / "qc.json", {"schema_version": 2, "verdict": "PASS", "bindings": {"render_sha256": render_hash}, "technical": {"verdict": "PASS"}, "frame_integrity": {"verdict": "PASS"}, "layout_policy": {"verdict": "PASS"}})
    fixes = write_text(segment / "fixes.md", "# Fixes\n")
    review = write_text(project / "04_phase2" / "review.md", "# Gate 2\n")
    continuity = write_json(project / "04_phase2" / "film-continuity.json", {
        "schema_version": 1, "kind": "film-continuity", "worker_version": "fixture-v1",
        "input_bindings": [{"segment_id": "01", "transcript_sha256": expected_hash, "keep_ids": ["hello"]}],
        "thresholds": {"similarity": 0.84, "recommendation": 0.92, "min_tokens": 5, "metric": "fixture"},
        "verdict": "PASS", "blocking_groups": [], "uncertain_matches": [],
    })
    manifest = {
        "schema_version": 1, "kind": "gate2", "project_id": project.name, "revision": 1,
        "gate1_approval": gate1_approval,
        "review": artifact_record(project, review, kind="gate2-review"),
        "film_continuity": artifact_record(project, continuity, kind="film-continuity"),
        "segments": [{
            "id": "01", "render": artifact_record(project, render, kind="segment-render"),
            "expected_transcript": artifact_record(project, expected_transcript, kind="expected-transcript"),
            "rendered_transcript": artifact_record(project, rendered_transcript, kind="rendered-transcript"),
            "verification": artifact_record(project, verification, kind="transcript-verification"),
            "qc": artifact_record(project, qc, kind="segment-qc"),
            "fixes": artifact_record(project, fixes, kind="fixes"),
        }],
    }
    return write_json(project / "04_phase2" / "gate2-manifest.json", manifest)


def final_manifest(project: Path, gate2_approval: dict[str, Any], segment_hash: str) -> Path:
    final = project / "05_final"
    master = make_video(final / "master.mp4", duration=0.8, color="green")
    master_hash = artifact_record(project, master, kind="master")["sha256"]
    qc = write_json(final / "qc.json", {"schema_version": 2, "verdict": "PASS", "bindings": {"master_sha256": master_hash}, "technical": {"verdict": "PASS"}, "frame_integrity": {"verdict": "PASS"}, "layout_policy": {"verdict": "PASS"}})
    archive_root = project / "test-archive"
    destination = archive_root / "final" / master.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(master, destination)
    receipt = write_json(final / "archive-receipt.json", {
        "schema_version": 1, "verdict": "VERIFIED", "source_sha256": master_hash, "archive_root": str(archive_root),
        "destination_sha256": master_hash, "entries": [{"role": "master", "destination": str(destination), "sha256": master_hash, "size_bytes": destination.stat().st_size}],
    })
    package_dir = final / "publishing-package"
    title = write_text(package_dir / "title.txt", "Fixture title\n")
    description = write_text(package_dir / "description.md", "Fixture description\n")
    chapters = write_text(package_dir / "chapters.txt", "00:00 Intro\n")
    package_manifest = write_json(package_dir / "manifest.json", {"schema_version": 1})
    manifest = {
        "schema_version": 1, "kind": "final", "project_id": project.name, "revision": 1,
        "gate2_approval": gate2_approval,
        "master": artifact_record(project, master, kind="master"),
        "qc": artifact_record(project, qc, kind="final-qc"),
        "archive_receipt": artifact_record(project, receipt, kind="archive-receipt"),
        "publishing_package": {
            "title": artifact_record(project, title, kind="publishing-title"),
            "description": artifact_record(project, description, kind="publishing-description"),
            "chapters": artifact_record(project, chapters, kind="publishing-chapters"),
            "manifest": artifact_record(project, package_manifest, kind="publishing-manifest"),
        },
        "segment_hashes": [segment_hash],
    }
    return write_json(final / "final-manifest.json", manifest)
