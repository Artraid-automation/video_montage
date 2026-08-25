from __future__ import annotations

import unittest
from pathlib import Path

from pipeline.factory.style_library import (
    get_recipe,
    load_style_library,
    search_recipes,
    style_library_path,
)


ROOT = Path(__file__).resolve().parents[1]


class StyleLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.library = load_style_library(style_library_path(ROOT, "dankoe-mevga-v1"))

    def test_loads_four_seed_recipes(self) -> None:
        ids = {item["id"] for item in self.library["recipes"]}
        self.assertEqual(ids, {"captions_body", "hook_title", "framework_list", "grade_talking_head"})
        for recipe in self.library["recipes"]:
            self.assertTrue(recipe["what_happens"])
            self.assertTrue(recipe["tags"])
            self.assertTrue(recipe["situations"])
            self.assertIn("search_text", recipe)

    def test_search_by_tag_hook(self) -> None:
        hits = search_recipes(self.library, "#hook")
        self.assertEqual([item["id"] for item in hits], ["hook_title"])

    def test_search_by_situation_phrase(self) -> None:
        hits = search_recipes(self.library, "обещание темы")
        self.assertTrue(any(item["id"] == "hook_title" for item in hits))

    def test_search_list_framework(self) -> None:
        hits = search_recipes(self.library, "#framework")
        self.assertEqual(hits[0]["id"], "framework_list")

    def test_get_recipe_unknown_raises(self) -> None:
        with self.assertRaises(KeyError):
            get_recipe(self.library, "nope")


if __name__ == "__main__":
    unittest.main()
