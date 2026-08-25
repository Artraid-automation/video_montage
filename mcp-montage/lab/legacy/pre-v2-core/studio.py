#!/usr/bin/env python3
"""Small deterministic front door for the local video factory."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from m1 import analyze_transcript as build_transcript_analysis
from m1 import normalize_whisper, read_json, render_rough_cut, write_json
from m2 import (
    captions_from_plan,
    index_broll,
    plan_visuals,
    render_cached_preview,
    render_caption_preview,
    search_broll,
)
from orchestrator import (
    accept_final,
    approve as approve_gate,
    ensure_state,
    finalize as start_finalization,
    load_state,
    request_revision,
    resume as resume_pipeline,
    start as start_pipeline,
)


MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".mxf", ".avi", ".webm",
    ".wav", ".mp3", ".m4a", ".aac", ".flac",
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
}

PROJECT_DIRS = (
    "01_raw",
    "02_inputs/broll",
    "02_inputs/audio",
    "03_phase1/segments",
    "04_phase2/segments",
    "05_final/publishing-package",
    "06_state/checkpoints",
)


def configure_console() -> None:
    """Keep Unicode media paths printable in the Windows console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def stable_id(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix().encode("utf-8")
    return "media_" + hashlib.sha1(relative).hexdigest()[:12]


def role_for(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        return "image"
    if parts & {"a_roll", "01_footage", "footage"}:
        return "a_roll"
    if parts & {"screen", "02_screen", "screencast"}:
        return "screen"
    if parts & {"audio", "03_audio"} or suffix in {".wav", ".mp3", ".m4a", ".aac", ".flac"}:
        return "audio"
    if parts & {"b_roll", "broll", "04_broll", "03_project_broll"}:
        return "b_roll"
    return "unknown"


def run_version(executable: str, args: list[str]) -> str | None:
    resolved = shutil.which(executable)
    if not resolved:
        return None
    result = subprocess.run(
        [resolved, *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    line = (result.stdout or result.stderr).splitlines()
    return line[0].strip() if line else resolved


def doctor(_: argparse.Namespace) -> int:
    checks = {
        "python": sys.version.split()[0],
        "ffmpeg": run_version("ffmpeg", ["-version"]),
        "ffprobe": run_version("ffprobe", ["-version"]),
        "git": run_version("git", ["--version"]),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    missing = [name for name in ("ffmpeg", "ffprobe") if checks[name] is None]
    if missing:
        print(f"ERROR: missing required tools: {', '.join(missing)}", file=sys.stderr)
        return 1
    print("OK: core media toolchain is available")
    return 0


def safe_slug(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    slug = value.strip().lower().replace(" ", "-")
    if not slug or any(char not in allowed for char in slug):
        raise ValueError("slug must contain only a-z, 0-9, hyphen and underscore")
    return slug


def new_project(args: argparse.Namespace) -> int:
    slug = safe_slug(args.slug)
    root = Path(args.projects_dir).resolve() / slug
    if root.exists():
        print(f"ERROR: project already exists: {root}", file=sys.stderr)
        return 1
    for directory in PROJECT_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema_version": 1,
        "id": slug,
        "title": args.title or slug,
        "created_at": utc_now(),
        "status": "NEW",
        "current_phase": "phase1",
    }
    (root / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "02_inputs" / "brief.md").write_text(
        "# Brief\n\n## Цель видео\n\n## Аудитория\n\n## Главная мысль\n\n"
        "## Формат и площадка\n\n## Ограничения\n\n## Референсы\n\n",
        encoding="utf-8",
    )
    (root / "02_inputs" / "style.md").write_text(
        "# Style notes\n\n## Ритм\n\n## Кадрирование\n\n## Текст и графика\n\n"
        "## Цвет\n\n## Звук и музыка\n\n## Не делать\n\n",
        encoding="utf-8",
    )
    ensure_state(root)
    print(root)
    return 0


def probe_file(path: Path) -> tuple[bool, dict[str, Any] | None, str | None]:
    command = [
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        return False, None, result.stderr.strip() or f"ffprobe exit {result.returncode}"
    try:
        return True, json.loads(result.stdout), None
    except json.JSONDecodeError as exc:
        return False, None, f"invalid ffprobe JSON: {exc}"


def scan(args: argparse.Namespace) -> int:
    root = Path(args.project_root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1
    files = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS),
        key=lambda path: path.as_posix().lower(),
    )
    records: list[dict[str, Any]] = []
    for path in files:
        ok, probe, error = probe_file(path)
        duration = None
        streams: list[dict[str, Any]] = []
        if probe:
            raw_duration = probe.get("format", {}).get("duration")
            if raw_duration is not None:
                try:
                    duration = round(float(raw_duration), 6)
                except (TypeError, ValueError):
                    duration = None
            for stream in probe.get("streams", []):
                streams.append({
                    key: stream.get(key)
                    for key in (
                        "index", "codec_type", "codec_name", "width", "height",
                        "r_frame_rate", "avg_frame_rate", "sample_rate", "channels",
                        "channel_layout", "pix_fmt", "color_space", "color_transfer",
                        "color_primaries",
                    )
                    if stream.get(key) is not None
                })
        records.append({
            "id": stable_id(path, root),
            "path": str(path),
            "relative_path": path.relative_to(root).as_posix(),
            "role": role_for(path.relative_to(root)),
            "size_bytes": path.stat().st_size,
            "probe_ok": ok,
            "duration_s": duration,
            "streams": streams,
            "error": error,
        })
        print(f"{'OK' if ok else 'FAIL':4} {path.relative_to(root)}")
    manifest = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "project_root": str(root),
        "files": records,
    }
    output = Path(args.output).resolve() if args.output else root / "04_work" / "manifests" / "media_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest: {output}")
    print(f"Files: {len(records)}; probe failures: {sum(not item['probe_ok'] for item in records)}")
    return 0 if all(item["probe_ok"] for item in records) else 2


def transcribe(args: argparse.Namespace) -> int:
    python = Path(args.python).resolve() if args.python else Path(sys.executable)
    worker = Path(__file__).with_name("transcribe_worker.py")
    command = [str(python), str(worker), args.media, args.output, "--model", args.model]
    if args.language:
        command.extend(["--language", args.language])
    result = subprocess.run(command)
    return int(result.returncode)


def normalize_transcript_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    transcript = normalize_whisper(
        read_json(input_path),
        source_id=args.source_id,
        media_path=str(Path(args.media).resolve()) if args.media else None,
        engine=args.engine,
    )
    write_json(output_path, transcript)
    print(output_path)
    print(f"Words: {len(transcript['words'])}; segments: {len(transcript['segments'])}")
    return 0


def analyze_transcript_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    analysis = build_transcript_analysis(read_json(input_path), gap_s=args.utterance_gap)
    write_json(output_path, analysis)
    print(output_path)
    print(json.dumps(analysis["summary"], ensure_ascii=False, indent=2))
    return 0


def render_rough_command(args: argparse.Namespace) -> int:
    plan = Path(args.plan).resolve()
    output = Path(args.output).resolve()
    report = Path(args.report).resolve() if args.report else output.with_suffix(".build-report.json")
    result = render_rough_cut(plan, output, report)
    duration = result["probe"].get("format", {}).get("duration")
    print(output)
    print(f"Rendered duration: {duration}s")
    print(f"Build report: {report}")
    return 0



def broll_index_command(args: argparse.Namespace) -> int:
    root = Path(args.library_root).resolve()
    catalog_path = Path(args.catalog).resolve() if args.catalog else root / "catalog.json"
    catalog = index_broll(root, catalog_path)
    print(catalog_path)
    print(json.dumps(catalog["summary"], ensure_ascii=False, indent=2))
    return 0 if catalog["summary"]["probe_failures"] == 0 else 2


def broll_search_command(args: argparse.Namespace) -> int:
    catalog_path = Path(args.catalog).resolve()
    matches = search_broll(read_json(catalog_path), args.query, limit=args.limit)
    print(json.dumps({"query": args.query, "matches": matches}, ensure_ascii=False, indent=2))
    return 0


def plan_visuals_command(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    result = plan_visuals(
        read_json(Path(args.plan).resolve()),
        read_json(Path(args.catalog).resolve()),
        match_limit=args.match_limit,
    )
    write_json(output, result)
    print(output)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


def build_captions_command(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    ass, report = captions_from_plan(
        read_json(Path(args.plan).resolve()),
        read_json(Path(args.transcript).resolve()),
        width=args.width,
        height=args.height,
        font=args.font,
        font_size=args.font_size,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(ass, encoding="utf-8-sig")
    report_path = Path(args.report).resolve() if args.report else output.with_suffix(".report.json")
    write_json(report_path, report)
    print(output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["uncovered_segments"] else 2


def render_captions_command(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    report_path = Path(args.report).resolve() if args.report else output.with_suffix(".build-report.json")
    report = render_caption_preview(
        Path(args.input),
        Path(args.captions),
        output,
        report_path,
    )
    print(output)
    print(f"Build report: {report_path}")
    duration = report["probe"].get("format", {}).get("duration")
    print(f"Rendered duration: {duration}s")
    return 0



def render_cached_command(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    cache = Path(args.cache).resolve()
    report_path = Path(args.report).resolve() if args.report else output.with_suffix(".build-report.json")
    report = render_cached_preview(
        Path(args.plan),
        output,
        cache,
        report_path,
        fps=args.fps,
        crf=args.crf,
    )
    print(output)
    print(f"Cache hits: {report['cache_hits']}; misses: {report['cache_misses']}")
    print(f"Build report: {report_path}")
    return 0


def _print_product_state(state: dict[str, Any]) -> None:
    print(json.dumps(state, ensure_ascii=False, indent=2))


def start_command(args: argparse.Namespace) -> int:
    state = start_pipeline(Path(args.project_root))
    _print_product_state(state)
    print("Phase 1 state created. The Phase 1 worker is not wired yet; no gate was fabricated.")
    return 0


def status_command(args: argparse.Namespace) -> int:
    root = Path(args.project_root)
    state_file = root / "06_state" / "project-state.json"
    state = load_state(root) if state_file.is_file() else ensure_state(root)
    _print_product_state(state)
    return 0


def approve_command(args: argparse.Namespace) -> int:
    _print_product_state(approve_gate(Path(args.project_root), args.gate, reviewer=args.reviewer))
    return 0


def revise_command(args: argparse.Namespace) -> int:
    _print_product_state(request_revision(Path(args.project_root)))
    return 0


def finalize_command(args: argparse.Namespace) -> int:
    _print_product_state(start_finalization(Path(args.project_root)))
    return 0


def resume_command(args: argparse.Namespace) -> int:
    _print_product_state(resume_pipeline(Path(args.project_root)))
    return 0


def accept_final_command(args: argparse.Namespace) -> int:
    _print_product_state(accept_final(Path(args.project_root), reviewer=args.reviewer))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="check local toolchain")
    doctor_parser.set_defaults(func=doctor)

    start_parser = subparsers.add_parser("start", help="start the three-phase product pipeline")
    start_parser.add_argument("project_root")
    start_parser.set_defaults(func=start_command)

    status_parser = subparsers.add_parser("status", help="show durable product state")
    status_parser.add_argument("project_root")
    status_parser.set_defaults(func=status_command)

    approve_parser = subparsers.add_parser("approve", help="approve a prepared human gate")
    approve_parser.add_argument("project_root")
    approve_parser.add_argument("gate", choices=("gate1", "gate2"))
    approve_parser.add_argument("--reviewer", default="user")
    approve_parser.set_defaults(func=approve_command)

    revise_parser = subparsers.add_parser("revise", help="request revisions after Gate 2/final review")
    revise_parser.add_argument("project_root")
    revise_parser.set_defaults(func=revise_command)

    finalize_parser = subparsers.add_parser("finalize", help="start Phase 3 after Gate 2 approval")
    finalize_parser.add_argument("project_root")
    finalize_parser.set_defaults(func=finalize_command)

    resume_parser = subparsers.add_parser("resume", help="resume the last recoverable running phase")
    resume_parser.add_argument("project_root")
    resume_parser.set_defaults(func=resume_command)

    accept_parser = subparsers.add_parser("accept-final", help="accept hash-bound final artifacts")
    accept_parser.add_argument("project_root")
    accept_parser.add_argument("--reviewer", default="user")
    accept_parser.set_defaults(func=accept_final_command)

    new_parser = subparsers.add_parser("new-project", help="create canonical project folders")
    new_parser.add_argument("slug")
    new_parser.add_argument("--title")
    new_parser.add_argument("--projects-dir", default="projects")
    new_parser.set_defaults(func=new_project)

    scan_parser = subparsers.add_parser("scan", help="probe media and write a manifest")
    scan_parser.add_argument("project_root")
    scan_parser.add_argument("--output")
    scan_parser.set_defaults(func=scan)

    transcribe_parser = subparsers.add_parser("transcribe", help="create a word-level raw transcript")
    transcribe_parser.add_argument("media")
    transcribe_parser.add_argument("output")
    transcribe_parser.add_argument("--model", default="small")
    transcribe_parser.add_argument("--language")
    transcribe_parser.add_argument("--python", help="Python executable containing faster-whisper")
    transcribe_parser.set_defaults(func=transcribe)

    normalize_parser = subparsers.add_parser("normalize-transcript", help="normalize Whisper JSON")
    normalize_parser.add_argument("input")
    normalize_parser.add_argument("output")
    normalize_parser.add_argument("--source-id", required=True)
    normalize_parser.add_argument("--media")
    normalize_parser.add_argument("--engine", default="faster-whisper")
    normalize_parser.set_defaults(func=normalize_transcript_command)

    analyze_parser = subparsers.add_parser("analyze-transcript", help="detect pauses and repeated takes")
    analyze_parser.add_argument("input")
    analyze_parser.add_argument("output")
    analyze_parser.add_argument("--utterance-gap", type=float, default=1.2)
    analyze_parser.set_defaults(func=analyze_transcript_command)

    rough_parser = subparsers.add_parser("render-rough", help="render approved semantic edit plan")
    rough_parser.add_argument("plan")
    rough_parser.add_argument("output")
    rough_parser.add_argument("--report")
    rough_parser.set_defaults(func=render_rough_command)

    broll_index_parser = subparsers.add_parser("broll-index", help="index the local B-roll library")
    broll_index_parser.add_argument("library_root", nargs="?", default="library/broll")
    broll_index_parser.add_argument("--catalog")
    broll_index_parser.set_defaults(func=broll_index_command)

    broll_search_parser = subparsers.add_parser("broll-search", help="search indexed B-roll")
    broll_search_parser.add_argument("query")
    broll_search_parser.add_argument("--catalog", default="library/broll/catalog.json")
    broll_search_parser.add_argument("--limit", type=int, default=5)
    broll_search_parser.set_defaults(func=broll_search_command)

    visuals_parser = subparsers.add_parser("plan-visuals", help="resolve edit-plan visual cues")
    visuals_parser.add_argument("plan")
    visuals_parser.add_argument("catalog")
    visuals_parser.add_argument("output")
    visuals_parser.add_argument("--match-limit", type=int, default=3)
    visuals_parser.set_defaults(func=plan_visuals_command)

    captions_parser = subparsers.add_parser("build-captions", help="build timed ASS captions")
    captions_parser.add_argument("plan")
    captions_parser.add_argument("transcript")
    captions_parser.add_argument("output")
    captions_parser.add_argument("--report")
    captions_parser.add_argument("--width", type=int, default=1080)
    captions_parser.add_argument("--height", type=int, default=1920)
    captions_parser.add_argument("--font", default="Arial")
    captions_parser.add_argument("--font-size", type=int, default=64)
    captions_parser.set_defaults(func=build_captions_command)

    render_captions_parser = subparsers.add_parser("render-captions", help="burn ASS captions into a preview")
    render_captions_parser.add_argument("input")
    render_captions_parser.add_argument("captions")
    render_captions_parser.add_argument("output")
    render_captions_parser.add_argument("--report")
    render_captions_parser.set_defaults(func=render_captions_command)

    cached_parser = subparsers.add_parser("render-cached", help="render a preview with segment cache")
    cached_parser.add_argument("plan")
    cached_parser.add_argument("output")
    cached_parser.add_argument("--cache", required=True)
    cached_parser.add_argument("--report")
    cached_parser.add_argument("--fps", type=int, default=25)
    cached_parser.add_argument("--crf", type=int, default=20)
    cached_parser.set_defaults(func=render_cached_command)
    return parser


def main() -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

