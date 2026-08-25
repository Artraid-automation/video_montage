"""Searchable style recipe library (Dan Koe / project style packs)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json


REQUIRED_RECIPE_FIELDS = (
    "id",
    "title",
    "what_happens",
    "tags",
    "situations",
    "anti_situations",
    "look",
    "compositor",
)


def style_library_path(repo_root: Path, version: str) -> Path:
    return repo_root / "presets" / "styles" / version / "library.json"


def _search_blob(recipe: dict[str, Any]) -> str:
    parts = [
        str(recipe.get("id", "")),
        str(recipe.get("title", "")),
        str(recipe.get("what_happens", "")),
        " ".join(str(item) for item in recipe.get("tags", [])),
        " ".join(str(item) for item in recipe.get("situations", [])),
        " ".join(str(item) for item in recipe.get("anti_situations", [])),
        str(recipe.get("min_content", "")),
        str(recipe.get("source", "")),
    ]
    return " ".join(parts).casefold()


def _validate_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(recipe, dict):
        raise ValueError("style recipe must be an object")
    missing = [field for field in REQUIRED_RECIPE_FIELDS if field not in recipe]
    if missing:
        raise ValueError(f"style recipe missing fields: {missing}")
    if not isinstance(recipe["tags"], list) or not recipe["tags"]:
        raise ValueError(f"style recipe {recipe['id']} needs non-empty tags")
    if not isinstance(recipe["situations"], list) or not recipe["situations"]:
        raise ValueError(f"style recipe {recipe['id']} needs non-empty situations")
    enriched = dict(recipe)
    enriched["search_text"] = str(recipe.get("search_text") or _search_blob(recipe))
    return enriched


def load_style_library(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"style library must be an object: {path}")
    recipes_raw = raw.get("recipes")
    if not isinstance(recipes_raw, list) or not recipes_raw:
        raise ValueError(f"style library has no recipes: {path}")
    recipes = [_validate_recipe(item) for item in recipes_raw]
    ids = [item["id"] for item in recipes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate style recipe ids")
    return {
        "schema_version": int(raw.get("schema_version", 1)),
        "id": str(raw.get("id", path.parent.name)),
        "title": str(raw.get("title", "")),
        "source_url": raw.get("source_url"),
        "analysis": raw.get("analysis"),
        "path": str(path),
        "recipes": recipes,
        "by_id": {item["id"]: item for item in recipes},
    }


def get_recipe(library: dict[str, Any], recipe_id: str) -> dict[str, Any]:
    try:
        return library["by_id"][recipe_id]
    except KeyError as exc:
        raise KeyError(f"unknown style recipe: {recipe_id}") from exc


def search_recipes(library: dict[str, Any], query: str) -> list[dict[str, Any]]:
    needle = " ".join(str(query or "").casefold().split())
    if not needle:
        return list(library["recipes"])
    hits: list[dict[str, Any]] = []
    for recipe in library["recipes"]:
        blob = str(recipe.get("search_text") or _search_blob(recipe))
        tags = " ".join(str(item).casefold() for item in recipe.get("tags", []))
        if needle in blob or needle in tags:
            hits.append(recipe)
            continue
        # Multi-token: all tokens must appear somewhere in the blob.
        tokens = needle.split()
        if len(tokens) > 1 and all(token in blob for token in tokens):
            hits.append(recipe)
    return hits


def library_digest(library: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact card list for Gate 1 visual agent requests."""
    digest = []
    for recipe in library["recipes"]:
        digest.append({
            "id": recipe["id"],
            "title": recipe["title"],
            "tags": list(recipe["tags"]),
            "situations": list(recipe["situations"]),
            "anti_situations": list(recipe.get("anti_situations", [])),
            "what_happens": recipe["what_happens"],
            "inputs": list(recipe.get("inputs", [])),
        })
    return digest
