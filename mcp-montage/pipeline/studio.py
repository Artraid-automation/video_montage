#!/usr/bin/env python3
"""Single product CLI for the local three-phase video factory."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from factory.cleanup import cleanup_dry_run, execute_cleanup
from factory.io import atomic_write_json, canonical_json_hash, read_json
from factory.phase1 import refresh_gate1, run_phase1
from factory.phase2 import run_phase2
from factory.phase3 import run_phase3
from factory.revisions import run_revisions
from factory.rules import promote_rule
from factory.state import StateStore


PROJECT_DIRS = (
    "01_raw", "02_inputs/audio", "02_inputs/broll/approved", "02_inputs/rules/fixtures",
    "03_phase1/segments", "04_phase2/segments", "04_phase2/cache",
    "05_final/publishing-package", "06_state/checkpoints", "07_quarantine",
)


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def safe_slug(value: str) -> str:
    slug = value.strip().lower().replace(" ", "-")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if not slug or any(char not in allowed for char in slug):
        raise ValueError("slug must contain only a-z, 0-9, hyphen and underscore")
    return slug


def new_project(args: argparse.Namespace) -> int:
    from factory.profiles import ALLOWED_PROFILES, apply_profile_to_config

    slug = safe_slug(args.slug)
    root = Path(args.projects_dir).resolve() / slug
    if root.exists():
        raise ValueError(f"project already exists: {root}")
    for directory in PROJECT_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    profile_id = str(getattr(args, "profile", None) or "reels-9x16")
    if profile_id not in ALLOWED_PROFILES:
        raise ValueError(f"profile must be one of {sorted(ALLOWED_PROFILES)}")
    config = apply_profile_to_config(
        {
            "schema_version": 2,
            "id": slug,
            "title": args.title or slug,
            "transcription": {"provider": "faster-whisper", "model": "small", "language": None},
            "verification_transcription": {"provider": "faster-whisper", "model": "small", "language": None},
            "publishing": {"title": args.title or slug, "description": "", "chapter_titles": {}},
        },
        profile_id,
    )
    atomic_write_json(root / "project.json", config)
    (root / "02_inputs" / "brief.md").write_text("# Brief\n\n## Goal\n\n## Audience\n\n## Promise\n\n## Constraints\n", encoding="utf-8")
    (root / "02_inputs" / "style.md").write_text(
        "# Style\n\nSee `docs/product/STYLE_BIBLE.md` and profile "
        f"`{profile_id}`.\n\n## Editing\n\n## Visuals\n\n## Color\n\n## Audio\n\n## Never\n",
        encoding="utf-8",
    )
    StateStore(root).ensure()
    print(root)
    return 0


def doctor(_: argparse.Namespace) -> int:
    checks = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "git")}
    try:
        import PIL
        checks["pillow"] = getattr(PIL, "__version__", "installed")
    except ImportError:
        checks["pillow"] = None
    try:
        import faster_whisper
        checks["faster_whisper"] = getattr(faster_whisper, "__version__", "installed")
    except ImportError:
        checks["faster_whisper"] = None
    print_json(checks)
    return 0 if checks["ffmpeg"] and checks["ffprobe"] and checks["pillow"] else 2


def start(args: argparse.Namespace) -> int:
    manifest = run_phase1(Path(args.project_root))
    print(f"GATE1_REVIEW: {manifest}")
    return 0




def rerun_phase1(args: argparse.Namespace) -> int:
    manifest = run_phase1(Path(args.project_root), restart_reason=args.reason)
    print(manifest)
    return 0

def status(args: argparse.Namespace) -> int:
    ledger = StateStore(Path(args.project_root)).read()
    next_actions = {
        "NEW": "start", "PHASE1_RUNNING": "resume", "GATE1_REVIEW": "edit transcript/grade, then approve gate1",
        "PHASE2_PENDING": "approve gate1 already triggers Phase 2; run resume if interrupted",
        "PHASE2_RUNNING": "resume", "GATE2_REVIEW": "watch all segments; approve gate2 or add fixes and revise",
        "REVISIONS_RUNNING": "resume", "PHASE3_READY": "finalize", "PHASE3_RUNNING": "resume",
        "FINAL_REVIEW": "watch master, then accept-final", "COMPLETED": "cleanup-plan (optional)",
        "FAILED_RECOVERABLE": "resume",
    }
    print_json({**ledger, "next_action": next_actions.get(ledger["state"])})
    return 0


def approve(args: argparse.Namespace) -> int:
    root = Path(args.project_root)
    store = StateStore(root)
    if args.gate == "gate1":
        refresh_gate1(root, store)
        store.approve("gate1", reviewer=args.reviewer)
        manifest = run_phase2(root, store)
        print(f"GATE2_REVIEW: {manifest}")
    else:
        print_json(store.approve("gate2", reviewer=args.reviewer, accepted_exceptions=[]))
    return 0


def revise(args: argparse.Namespace) -> int:
    manifest = run_revisions(Path(args.project_root))
    print(f"GATE2_REVIEW: {manifest}")
    return 0


def finalize(args: argparse.Namespace) -> int:
    manifest = run_phase3(Path(args.project_root))
    print(f"FINAL_REVIEW: {manifest}")
    return 0


def accept_final(args: argparse.Namespace) -> int:
    print_json(StateStore(Path(args.project_root)).approve("final", reviewer=args.reviewer))
    return 0


def telegram_deliver(args: argparse.Namespace) -> int:
    """Encode TG document (1080x1920, optional speed) from a clean grade master and send."""
    from factory.telegram_delivery import (
        deliver_telegram_master,
        resolve_telegram_delivery_config,
        write_telegram_delivery_report,
    )

    root = Path(args.project_root).resolve(strict=True)
    config = read_json(root / "project.json")
    tg_cfg = resolve_telegram_delivery_config(config)
    if args.grade:
        config = {
            **config,
            "telegram_delivery": {**(config.get("telegram_delivery") or {}), "grade": args.grade},
        }
        tg_cfg = resolve_telegram_delivery_config(config)
    if args.speed_factor is not None:
        config = {
            **config,
            "telegram_delivery": {
                **(config.get("telegram_delivery") or {}),
                "speed_factor": float(args.speed_factor),
                "grade": tg_cfg["grade"],
            },
        }
        tg_cfg = resolve_telegram_delivery_config(config)
    source = root / "05_final" / "grades" / f"master-{tg_cfg['grade']}.mp4"
    if not source.is_file():
        raise FileNotFoundError(f"grade master missing: {source}")
    report = deliver_telegram_master(
        root, source_master=source, config=config, grade_name=str(tg_cfg["grade"]),
    )
    path = write_telegram_delivery_report(root, report)
    print_json({"report_path": str(path), **{k: report[k] for k in report if k != "raw"}})
    return 0 if report.get("verdict") in {"SENT", "ENCODED", "SKIPPED"} else 1


def resume(args: argparse.Namespace) -> int:
    root = Path(args.project_root); store = StateStore(root)
    ledger = store.read()
    if ledger["state"] == "FAILED_RECOVERABLE":
        ledger = store.resume()
    phase = (ledger.get("run") or {}).get("phase")
    if phase == "phase1":
        print(run_phase1(root, store))
    elif phase == "phase2":
        print(run_phase2(root, store))
    elif phase == "phase3":
        print(run_phase3(root, store))
    elif phase == "revision":
        scope = set((ledger.get("revision_request") or {}).get("scope", []))
        print(run_phase2(root, store, segment_scope=scope))
    else:
        raise ValueError(f"state contains no resumable worker: {ledger['state']}")
    return 0


def cleanup_plan(args: argparse.Namespace) -> int:
    path, plan = cleanup_dry_run(Path(args.project_root))
    print(path); print_json(plan)
    return 0


def cleanup_execute(args: argparse.Namespace) -> int:
    print(execute_cleanup(Path(args.project_root), args.confirmation_hash))
    return 0


def promote_rule_command(args: argparse.Namespace) -> int:
    result = promote_rule(
        Path(args.project_root), proposal_id=args.proposal_id, reviewer=args.reviewer,
        regression_fixture=Path(args.regression_fixture).resolve(),
    )
    print_json(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    item = commands.add_parser("doctor"); item.set_defaults(func=doctor)
    item = commands.add_parser("new-project")
    item.add_argument("slug")
    item.add_argument("--title")
    item.add_argument("--projects-dir", default="projects")
    item.add_argument(
        "--profile",
        default="reels-9x16",
        choices=("reels-9x16", "longform-16x9"),
        help="reels vertical or long-form horizontal (Style Bible)",
    )
    item.set_defaults(func=new_project)
    for name, function in (("start", start), ("status", status), ("revise", revise), ("finalize", finalize), ("resume", resume), ("cleanup-plan", cleanup_plan)):
        item = commands.add_parser(name); item.add_argument("project_root"); item.set_defaults(func=function)
    item = commands.add_parser("rerun-phase1"); item.add_argument("project_root"); item.add_argument("--reason", required=True); item.set_defaults(func=rerun_phase1)
    item = commands.add_parser("approve"); item.add_argument("project_root"); item.add_argument("gate", choices=("gate1", "gate2")); item.add_argument("--reviewer", default="user"); item.set_defaults(func=approve)
    item = commands.add_parser("accept-final"); item.add_argument("project_root"); item.add_argument("--reviewer", default="user"); item.set_defaults(func=accept_final)
    item = commands.add_parser("telegram-deliver")
    item.add_argument("project_root")
    item.add_argument("--grade", default=None, help="grade master to wrap (default: project default_grade)")
    item.add_argument("--speed-factor", type=float, default=None, help="optional speed, e.g. 1.15 (TG file only)")
    item.set_defaults(func=telegram_deliver)
    item = commands.add_parser("cleanup"); item.add_argument("project_root"); item.add_argument("--confirmation-hash", required=True); item.set_defaults(func=cleanup_execute)
    item = commands.add_parser("promote-rule"); item.add_argument("project_root"); item.add_argument("proposal_id"); item.add_argument("regression_fixture"); item.add_argument("--reviewer", default="user"); item.set_defaults(func=promote_rule_command)
    return parser


def main() -> int:
    configure_console()
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
