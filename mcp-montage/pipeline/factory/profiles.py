"""Named project profiles: reels-9x16 and longform-16x9 only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json

ALLOWED_PROFILES = frozenset({"reels-9x16", "reels-9x16-measured", "longform-16x9"})
PROFILE_KEYS = (
    "style_version",
    "default_grade",
    "render_profile",
    "transcript_verification",
    "visual_planning",
    "visual_probe_interval_s",
    "telegram_delivery",
)


def profiles_root(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / "presets" / "profiles"


def load_profile(profile_id: str, *, repo_root: Path | None = None) -> dict[str, Any]:
    if profile_id not in ALLOWED_PROFILES:
        raise ValueError(f"unknown profile {profile_id!r}; allowed: {sorted(ALLOWED_PROFILES)}")
    path = profiles_root(repo_root) / f"{profile_id}.json"
    data = read_json(path)
    if data.get("id") != profile_id:
        raise ValueError(f"profile id mismatch in {path}")
    return data


def apply_profile_to_config(
    config: dict[str, Any],
    profile_id: str,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Return a new project config with profile fields merged (profile wins on listed keys)."""
    profile = load_profile(profile_id, repo_root=repo_root)
    merged = dict(config)
    merged["profile"] = profile_id
    merged["format"] = profile.get("format")
    for key in PROFILE_KEYS:
        if key in profile:
            merged[key] = profile[key]
    return merged
