from __future__ import annotations

import unittest

from pipeline.factory.transcript import TranscriptEntry, VisualEntry, parse_transcript, render_transcript


class BrianStyleTranscriptTests(unittest.TestCase):
    def test_render_shows_timestamps_cut_and_motion_in_preview_safe_markup(self) -> None:
        entries = [
            TranscriptEntry("keep", "u1", 2.45, 11.47, ("w1", "w2"), "Keep this line"),
            TranscriptEntry("cut", "u2", 12.0, 13.5, ("w3",), "Bad take", "retake-marker"),
        ]
        visuals = [
            VisualEntry("v1", "u1", "motion", "60k -> отложи 6k"),
            VisualEntry("v2", "u1", "library-broll", "bank app screen", "asset-1"),
        ]
        rendered = render_transcript(entries, visuals)
        self.assertIn("KEEP id=u1", rendered)
        self.assertIn("**Keep this line**", rendered)
        self.assertIn("[0:12.000] CUT (маркер пересъёма) id=u2", rendered)
        self.assertIn("[0:02.450] MOTION v1 (оверлей-начало) @u1", rendered)
        self.assertIn("MOTION v1 (оверлей-конец)", rendered)
        self.assertIn("[0:02.450] BROLL v2 (оверлей-начало) @u1 asset=asset-1", rendered)
        self.assertIn("60k -> отложи 6k", rendered)
        self.assertIn("(поверх речи", rendered)
        self.assertNotIn("words=", rendered)
        self.assertNotIn("<keep", rendered)
        self.assertNotIn("<visual", rendered)
        parsed_entries, parsed_visuals = parse_transcript(rendered, valid_word_ids=None)
        self.assertEqual(
            [(e.kind, e.id, e.text, e.reason) for e in parsed_entries],
            [(e.kind, e.id, e.text, e.reason) for e in entries],
        )
        self.assertEqual(parsed_visuals[0].id, "v1")
        self.assertEqual(parsed_visuals[1].id, "v2")

    def test_legacy_html_markup_still_parses(self) -> None:
        legacy = (
            '<keep id="u1" start="0.0" end="1.0" words="w1">Hello</keep>\n'
            '<cut id="u2" start="1.2" end="2.0" words="w2" reason="false-start">Nope</cut>\n'
            '<visual id="v1" anchor="u1" type="motion">Brief</visual>\n'
        )
        entries, visuals = parse_transcript(legacy, valid_word_ids={"w1", "w2"})
        self.assertEqual(entries[0].kind, "keep")
        self.assertEqual(entries[1].reason, "false-start")
        self.assertEqual(visuals[0].type, "motion")


if __name__ == "__main__":
    unittest.main()
