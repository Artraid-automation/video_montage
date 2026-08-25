from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.io import atomic_write_json
from pipeline.factory.profiles import apply_profile_to_config, load_profile
from pipeline.factory.senses import search_senses, sense_query_expansion


class ProfileTests(unittest.TestCase):
    def test_reels_and_longform_load(self) -> None:
        reels = load_profile("reels-9x16")
        self.assertEqual(reels["render_profile"]["width"], 720)
        self.assertEqual(reels["render_profile"]["height"], 1280)
        longform = load_profile("longform-16x9")
        self.assertEqual(longform["render_profile"]["width"], 1920)
        self.assertEqual(longform["format"], "longform")

    def test_apply_profile_sets_profile_key(self) -> None:
        cfg = apply_profile_to_config({"schema_version": 2, "id": "x"}, "reels-9x16")
        self.assertEqual(cfg["profile"], "reels-9x16")
        self.assertEqual(cfg["telegram_delivery"]["send_as"], "document")

    def test_unknown_profile_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_profile("podcast-audio")


class SenseCatalogTests(unittest.TestCase):
    def test_tanya_senses_match_money_query(self) -> None:
        result = search_senses("правило 10 процентов 60000", limit=3)
        ids = [m["id"] for m in result["matches"]]
        self.assertIn("rule-ten-percent", ids)

    def test_expansion_adds_tags(self) -> None:
        expanded = sense_query_expansion("пустой кошелёк")
        self.assertNotEqual(expanded, "пустой кошелёк")
        self.assertTrue(any(token in expanded for token in ("wallet", "zero", "pain", "empty", "ноль")))

    def test_empty_catalog_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            atomic_write_json(path, {"schema_version": 1, "kind": "sense-catalog", "senses": []})
            result = search_senses("anything tags", catalog_path=path)
            self.assertEqual(result["matches"], [])


if __name__ == "__main__":
    unittest.main()
