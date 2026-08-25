from __future__ import annotations

import unittest

from pipeline.factory.transcript import TranscriptEntry, VisualEntry, parse_fixes, parse_transcript, render_transcript


class TranscriptMarkdownTests(unittest.TestCase):
    def test_unicode_roundtrip_preserves_ids_ranges_cuts_and_visuals(self) -> None:
        entries = [
            TranscriptEntry("cut", "u1", 0.0, 1.0, ("w1", "w2"), "Неудачный <дубль>", "false-start"),
            TranscriptEntry("keep", "u2", 1.2, 2.5, ("w3", "w4"), "Готовый дубль & смысл"),
        ]
        visuals = [VisualEntry("v1", "u2", "motion", "Показать «три фазы»")]
        rendered = render_transcript(entries, visuals)
        self.assertIn("[0:00.000] CUT (фальстарт) id=u1", rendered)
        self.assertIn("[0:01.200] KEEP id=u2", rendered)
        self.assertIn("**Готовый дубль & смысл**", rendered)
        self.assertIn("[0:01.200] MOTION v1 (оверлей-начало) @u2", rendered)
        self.assertNotIn("words=", rendered)
        actual_entries, actual_visuals = parse_transcript(rendered, valid_word_ids=None)
        enriched = [
            type(entries[0])(item.kind, item.id, entries[i].start_s, entries[i].end_s, entries[i].word_ids, item.text, item.reason)
            for i, item in enumerate(actual_entries)
        ]
        # Round-trip human fields; timing/words rebound from original entries for assertion equality.
        self.assertEqual([(e.kind, e.id, e.text, e.reason) for e in actual_entries], [(e.kind, e.id, e.text, e.reason) for e in entries])
        self.assertEqual(
            [(v.id, v.anchor, v.type, v.brief) for v in actual_visuals],
            [(v.id, v.anchor, v.type, v.brief) for v in visuals],
        )

    def test_invalid_nested_or_unknown_word_markup_is_blocked(self) -> None:
        nested = '<keep id="u1" start="0" end="1" words="w1"><cut>bad</cut></keep>'
        with self.assertRaisesRegex(ValueError, "invalid transcript markup"):
            parse_transcript(nested, valid_word_ids={"w1"})
        unknown = '[0:00.000] KEEP id=u1\ntext\n'
        parsed, _ = parse_transcript(unknown, valid_word_ids=None)
        with self.assertRaisesRegex(ValueError, "unknown word|no stable word"):
            validate = __import__("pipeline.factory.transcript", fromlist=["validate_entries"]).validate_entries
            validate(parsed, valid_word_ids={"w1"})
        # Prefer enrich path: missing id in source
        from pipeline.factory.transcript import enrich_entries_from_source
        with self.assertRaisesRegex(ValueError, "not found in source"):
            enrich_entries_from_source(parsed, {"utterances": [{"id": "other", "start_s": 0, "end_s": 1, "text": "x", "word_ids": ["w1"]}]})


    def test_overlap_is_blocked(self) -> None:
        text = "\n".join([
            "[0:00.000] KEEP id=u1",
            "one",
            "",
            "[0:01.000] KEEP id=u2",
            "two",
            "",
        ])
        entries, _ = parse_transcript(text, valid_word_ids=None)
        from pipeline.factory.transcript import TranscriptEntry, validate_entries
        with self.assertRaisesRegex(ValueError, "overlapping"):
            validate_entries([
                TranscriptEntry("keep", "u1", 0.0, 2.0, ("w1",), "one"),
                TranscriptEntry("keep", "u2", 1.0, 3.0, ("w2",), "two"),
            ], valid_word_ids={"w1", "w2"})


    def test_fixes_and_rule_candidates_are_typed(self) -> None:
        result = parse_fixes(
            '- [fix blocking] segment=01 range=00:01.2-00:02.4 remove duplicate phrase\n'
            '- [fix visual] segment=02 move PiP away from Export\n'
            '- [rule candidate] scope=profile sample PiP at least every two seconds\n'
        )
        self.assertTrue(result["fixes"][0]["blocking"])
        self.assertAlmostEqual(result["fixes"][0]["start_s"], 1.2)
        self.assertEqual(result["rule_candidates"][0]["status"], "PROPOSED")


if __name__ == "__main__":
    unittest.main()
