"""Agent visual proposals for Gate 1 (producer judgment, not cadence)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_json
from .planning import plan_visuals
from .style_guard import reconcile_style_scenes
from .style_library import library_digest, load_style_library, style_library_path
from .transcript import (
    MOTION_DEFAULT_DURATION_S,
    MOTION_MAX_DURATION_S,
    MOTION_MIN_DURATION_S,
    TranscriptEntry,
    VisualEntry,
    compact_visual_id,
    resolve_visual_end,
    resolve_visual_start,
)


PROMPT_VERSION = "gate1-visual-producer.v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / f"{PROMPT_VERSION}.md"
LLM_VISUAL_WORKER_VERSION = "llm-visual-v1"


def load_visual_prompt() -> str:
    if not PROMPT_PATH.is_file():
        raise ValueError(f"missing visual producer prompt: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_llm_visual_request(
    segment_id: str,
    entries: list[TranscriptEntry],
    *,
    prompt_version: str = PROMPT_VERSION,
    style_library_digest: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    keeps = [item for item in entries if item.kind == "keep"]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "llm-visual-request",
        "worker_version": LLM_VISUAL_WORKER_VERSION,
        "prompt_version": prompt_version,
        "segment_id": str(segment_id),
        "keep_blocks": [
            {
                "id": item.id,
                "start_s": item.start_s,
                "end_s": item.end_s,
                "text": item.text,
            }
            for item in keeps
        ],
    }
    if style_library_digest is not None:
        payload["style_library_digest"] = style_library_digest
    return payload


def validate_style_scenes(
    scenes_raw: Any,
    *,
    keep_ids: set[str],
    recipe_ids: set[str],
) -> list[dict[str, Any]]:
    if scenes_raw is None:
        return []
    if not isinstance(scenes_raw, list):
        raise ValueError("llm visual style_scenes must be a list")
    scenes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in scenes_raw:
        if not isinstance(item, dict):
            raise ValueError("style_scene must be an object")
        scene_id = str(item.get("id", "")).strip()
        recipe = str(item.get("recipe", "")).strip()
        anchor = str(item.get("anchor", "")).strip()
        what = str(item.get("what", "")).strip()
        why = str(item.get("why", "")).strip()
        if not scene_id:
            raise ValueError("style_scene requires id")
        if scene_id in seen:
            raise ValueError(f"duplicate style_scene id: {scene_id}")
        if recipe not in recipe_ids:
            raise ValueError(f"style_scene recipe not in library: {recipe}")
        if recipe == "captions_body":
            raise ValueError("captions_body is default compositor look — do not propose as style_scene")
        if recipe == "grade_talking_head":
            raise ValueError("grade_talking_head is selected at Gate 1 grade — not a style_scene")
        if anchor not in keep_ids:
            raise ValueError(f"style_scene anchor must be KEEP id: {anchor}")
        if not what or not why:
            raise ValueError(f"style_scene {scene_id} requires what and why")
        scene: dict[str, Any] = {
            "id": scene_id,
            "recipe": recipe,
            "anchor": anchor,
            "what": what,
            "why": why,
            "origin": "AGENT",
            "status": "PROPOSED",
        }
        if recipe == "hook_title":
            title = str(item.get("title") or what).strip()
            if not title:
                raise ValueError(f"style_scene {scene_id} hook_title requires title")
            scene["title"] = title
        if recipe == "framework_list":
            lines = item.get("lines")
            if not isinstance(lines, list) or len(lines) < 3:
                raise ValueError(f"style_scene {scene_id} framework_list requires lines[] with >= 3 items")
            cleaned = [str(line).strip() for line in lines if str(line).strip()]
            if len(cleaned) < 3:
                raise ValueError(f"style_scene {scene_id} framework_list needs >= 3 non-empty lines")
            scene["lines"] = cleaned
        seen.add(scene_id)
        scenes.append(scene)
    return scenes


def validate_llm_visual_response(
    response: dict[str, Any],
    request: dict[str, Any],
    *,
    keep_ids: set[str],
    recipe_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ValueError("llm visual response must be an object")
    if int(response.get("schema_version", -1)) != 1:
        raise ValueError("llm visual response schema_version must be 1")
    if str(response.get("prompt_version", "")) != str(request["prompt_version"]):
        raise ValueError("llm visual prompt_version mismatch")
    if str(response.get("segment_id", "")) != str(request["segment_id"]):
        raise ValueError("llm visual segment_id mismatch")
    proposals_raw = response.get("proposals")
    if not isinstance(proposals_raw, list):
        raise ValueError("llm visual proposals must be a list")
    seen_ids: set[str] = set()
    proposals: list[dict[str, Any]] = []
    for item in proposals_raw:
        if not isinstance(item, dict):
            raise ValueError("llm visual proposal must be an object")
        visual_id = str(item.get("id", "")).strip()
        anchor = str(item.get("anchor", "")).strip()
        visual_type = str(item.get("type", "motion")).strip()
        what = str(item.get("what", "")).strip()
        why = str(item.get("why", "")).strip()
        if not visual_id:
            raise ValueError("llm visual proposal requires id")
        if visual_id in seen_ids:
            raise ValueError(f"duplicate llm visual id: {visual_id}")
        if anchor not in keep_ids:
            raise ValueError(f"llm visual anchor must be KEEP id: {anchor}")
        if visual_type not in {"motion", "library-broll", "screen", "none"}:
            raise ValueError(f"unsupported llm visual type: {visual_type}")
        if not what or not why:
            raise ValueError(f"llm visual {visual_id} requires what and why")
        start_offset_s = float(item.get("start_offset_s", 0.0) or 0.0)
        if start_offset_s < 0:
            raise ValueError(f"llm visual {visual_id} start_offset_s must be >= 0")
        if "duration_s" in item and item.get("duration_s") is not None:
            duration_s = float(item["duration_s"])
            if duration_s < MOTION_MIN_DURATION_S or duration_s > MOTION_MAX_DURATION_S:
                raise ValueError(
                    f"llm visual {visual_id} duration_s must be in "
                    f"[{MOTION_MIN_DURATION_S}, {MOTION_MAX_DURATION_S}]"
                )
        else:
            duration_s = MOTION_DEFAULT_DURATION_S
        brief = str(item.get("brief", "")).strip() or f"{what}. Зачем: {why}"
        proposal = {
            "id": visual_id,
            "anchor": anchor,
            "type": visual_type,
            "what": what,
            "why": why,
            "brief": brief,
            "start_offset_s": start_offset_s,
            "duration_s": duration_s,
            "origin": "AGENT",
            "status": "PROPOSED",
        }
        if visual_type == "library-broll":
            proposal["query"] = str(item.get("query") or what).strip()
        if item.get("asset"):
            proposal["asset"] = item.get("asset")
        seen_ids.add(visual_id)
        proposals.append(proposal)
    summary = str(response.get("narrative_summary", "")).strip()
    if not summary:
        raise ValueError("llm visual narrative_summary is required")
    risks = response.get("risks", [])
    if not isinstance(risks, list) or any(not isinstance(item, str) for item in risks):
        raise ValueError("llm visual risks must be a list of strings")
    allowed = recipe_ids or {
        str(item.get("id"))
        for item in (request.get("style_library_digest") or [])
        if isinstance(item, dict) and item.get("id")
    }
    style_scenes = validate_style_scenes(
        response.get("style_scenes"),
        keep_ids=keep_ids,
        recipe_ids=allowed or {"hook_title", "framework_list", "captions_body", "grade_talking_head"},
    )
    return {
        "schema_version": 1,
        "kind": "llm-visual-result",
        "worker_version": LLM_VISUAL_WORKER_VERSION,
        "prompt_version": str(request["prompt_version"]),
        "segment_id": str(request["segment_id"]),
        "proposals": proposals,
        "style_scenes": style_scenes,
        "narrative_summary": summary,
        "risks": [str(item) for item in risks],
    }


def _fixture_response(
    request: dict[str, Any],
    *,
    configured: list[dict[str, Any]],
    auto_config: dict[str, Any] | None,
    entries: list[TranscriptEntry],
) -> dict[str, Any]:
    proposals: list[dict[str, Any]] = []
    if configured:
        for index, item in enumerate(configured, 1):
            brief = str(item.get("brief", "")).strip() or "fixture visual"
            proposals.append({
                "id": str(item.get("id") or compact_visual_id(request["segment_id"], index)),
                "anchor": str(item["anchor"]),
                "type": str(item.get("type", "motion")),
                "what": brief,
                "why": "fixture / test configured visual",
                "brief": brief,
                "query": item.get("query"),
                "asset": item.get("asset"),
            })
    elif auto_config and bool(auto_config.get("enabled", False)):
        plan = plan_visuals(
            request["segment_id"],
            entries,
            [],
            auto_config=auto_config,
        )
        for scene in plan["scenes"]:
            proposals.append({
                "id": scene["id"],
                "anchor": scene["anchor"],
                "type": scene["type"],
                "what": scene["brief"],
                "why": "fixture cadence proposal for tests only",
                "brief": scene["brief"],
                "query": scene.get("query"),
            })
    return {
        "schema_version": 1,
        "prompt_version": request["prompt_version"],
        "segment_id": request["segment_id"],
        "proposals": proposals,
        "style_scenes": [],
        "narrative_summary": "Fixture visual provider (tests only).",
        "risks": ["fixture provider — not for production Gate 1"],
    }


def _resolve_style_digest(settings: dict[str, Any], project_root: Path | None) -> list[dict[str, Any]]:
    if settings.get("style_library_digest") is not None:
        return list(settings["style_library_digest"])
    version = str(settings.get("style_version") or "dankoe-mevga-v1")
    roots: list[Path] = []
    if project_root is not None:
        roots.append(project_root)
        if project_root.parent.name == "projects":
            roots.append(project_root.parent.parent)
    roots.append(Path(__file__).resolve().parents[2])
    for root in roots:
        path = style_library_path(root, version)
        if path.is_file():
            return library_digest(load_style_library(path))
    return library_digest(
        load_style_library(style_library_path(Path(__file__).resolve().parents[2], "dankoe-mevga-v1"))
    )


def run_llm_visual(
    segment_id: str,
    entries: list[TranscriptEntry],
    *,
    output_dir: Path,
    library_root: Path | None = None,
    project_root: Path | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Visual pass after KEEP/CUT. Production: agent proposes what+why. No silent empty skip."""
    settings = dict(config or {})
    provider = str(settings.get("provider", "agent"))
    if provider not in {"agent", "file", "fixture"}:
        raise ValueError(f"unknown llm visual provider: {provider}")
    prompt_version = str(settings.get("prompt_version", PROMPT_VERSION))
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = _resolve_style_digest(settings, project_root)
    request = build_llm_visual_request(
        segment_id,
        entries,
        prompt_version=prompt_version,
        style_library_digest=digest,
    )
    atomic_write_json(output_dir / "llm-visual-request.json", request)
    response_path = Path(str(settings.get("response_path", output_dir / "llm-visual-response.json")))
    if provider == "fixture":
        raw = (
            read_json(response_path)
            if response_path.is_file()
            else _fixture_response(
                request,
                configured=list(settings.get("configured") or []),
                auto_config=settings.get("auto_config"),
                entries=entries,
            )
        )
    else:
        if not response_path.is_file():
            raise ValueError(
                f"llm visual missing response: {response_path}. "
                "Agent must propose MOTION/BROLL with what + why after editorial."
            )
        raw = read_json(response_path)
    keep_ids = {item.id for item in entries if item.kind == "keep"}
    recipe_ids = {str(item["id"]) for item in digest}
    result = validate_llm_visual_response(raw, request, keep_ids=keep_ids, recipe_ids=recipe_ids)
    if provider == "fixture":
        for item in result["proposals"]:
            item["origin"] = "AUTO" if "fixture cadence" in item["why"] else item.get("origin", "CONFIGURED")
            if item["origin"] == "AGENT" and "fixture" in item["why"]:
                item["origin"] = "CONFIGURED"
    result["provider"] = provider
    atomic_write_json(output_dir / "llm-visual.json", result)
    if result.get("style_scenes"):
        atomic_write_json(output_dir / "style-scenes.json", {"scenes": result["style_scenes"]})
    configured = []
    for item in result["proposals"]:
        row = {
            "id": item["id"],
            "anchor": item["anchor"],
            "type": item["type"],
            "brief": item["brief"],
            "origin": item.get("origin", "AGENT"),
            "status": "PROPOSED",
        }
        if item.get("query"):
            row["query"] = item["query"]
        if item.get("asset"):
            row["asset"] = item["asset"]
        configured.append(row)
    visual_plan = plan_visuals(
        segment_id,
        entries,
        configured,
        library_root=library_root,
        project_root=project_root,
        auto_config={"enabled": False},
    )
    visual_plan["style_scenes"] = list(result.get("style_scenes") or [])
    visual_plan = reconcile_style_scenes(
        visual_plan,
        style_scenes=list(result.get("style_scenes") or []) or None,
    )
    # Preserve agent origin/what/why on scenes when plan_visuals normalizes.
    by_id = {item["id"]: item for item in result["proposals"]}
    for scene in visual_plan["scenes"]:
        source = by_id.get(scene["id"])
        if source:
            scene["origin"] = source.get("origin", scene.get("origin", "AGENT"))
            scene["what"] = source.get("what")
            scene["why"] = source.get("why")
            scene["start_offset_s"] = source.get("start_offset_s", 0.0)
            scene["duration_s"] = source.get("duration_s", MOTION_DEFAULT_DURATION_S)
            scene["status"] = "PROPOSED"
            temp = VisualEntry(
                id=scene["id"],
                anchor=scene["anchor"],
                type=scene["type"],
                brief=scene["brief"],
                asset=scene.get("asset"),
            )
            start_s = resolve_visual_start(
                entries, temp, start_offset_s=float(scene["start_offset_s"]),
            )
            end_s = resolve_visual_end(
                entries,
                temp,
                default_duration_s=float(scene["duration_s"]),
                start_offset_s=float(scene["start_offset_s"]),
            )
            # resolve_visual_end uses visual.start_s if set; bake absolute window on scene
            scene["start_s"] = start_s
            scene["end_s"] = end_s
            hold = end_s - start_s
            if hold + 1e-6 < MOTION_MIN_DURATION_S and provider != "fixture":
                raise ValueError(
                    f"overlay {scene['id']} hold {hold:.2f}s < {MOTION_MIN_DURATION_S}s "
                    f"(anchor too short or bad offset — pick a longer KEEP clause)"
                )
            scene["hold_s"] = hold
    visual_plan["llm_visual"] = {
        "prompt_version": result["prompt_version"],
        "narrative_summary": result["narrative_summary"],
        "risks": result["risks"],
        "proposals": result["proposals"],
        "style_scenes": result.get("style_scenes") or [],
    }
    return visual_plan, result
