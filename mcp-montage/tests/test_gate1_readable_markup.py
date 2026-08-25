from __future__ import annotations

import unittest

from pipeline.factory.editorial import analyze_editorial, apply_editorial_proposals
from pipeline.factory.transcript import (
    TranscriptEntry,
    VisualEntry,
    compact_entry_id,
    compact_visual_id,
    parse_transcript,
    render_transcript,
)
from pipeline.factory.utterances import coalesce_utterances


class Gate1ReadableMarkupTests(unittest.TestCase):
    def test_compact_ids_bold_speech_and_motion_span(self) -> None:
        entries = [
            TranscriptEntry("keep", "u0001", 2.32, 5.5, ("w1",), "И здесь дело не в сумме."),
            TranscriptEntry("cut", "u0014", 47.75, 62.0, ("w2",), "старый дубль", "proposed-retake-prefix"),
        ]
        visuals = [
            VisualEntry("3a", "u0001", "motion", "схема приоритета", None, end_s=5.5),
        ]
        rendered = render_transcript(entries, visuals, segment_id="03")
        self.assertIn("[0:02.320] KEEP id=3.1", rendered)
        self.assertIn("**И здесь дело не в сумме.**", rendered)
        self.assertIn("[0:02.320] MOTION 3a (оверлей-начало) @3.1", rendered)
        self.assertIn("[0:05.500] MOTION 3a (оверлей-конец)", rendered)
        self.assertIn("CUT (повтор начала дубля) id=3.14", rendered)
        self.assertNotIn("visual-03", rendered)
        self.assertNotIn("u0001", rendered)
        parsed, parsed_visuals = parse_transcript(rendered, segment_id="03")
        self.assertEqual(parsed[0].id, "u0001")
        self.assertEqual(parsed[0].text, "И здесь дело не в сумме.")
        self.assertEqual(parsed_visuals[0].id, "3a")
        self.assertEqual(parsed_visuals[0].anchor, "u0001")
        self.assertAlmostEqual(parsed_visuals[0].end_s or 0.0, 5.5)

    def test_coalesce_merges_incomplete_clause_and_prefix_without_po(self) -> None:
        utterances = [
            {"id": "u12", "start_s": 29.38, "end_s": 31.54, "text": "Если ты таким образом не откладывал, то ее бы", "word_ids": ["w1"]},
            {"id": "u13", "start_s": 31.54, "end_s": 32.24, "text": "у тебя и не было.", "word_ids": ["w2"]},
            {"id": "u14", "start_s": 47.75, "end_s": 50.33, "text": "По моим наблюдениям деньги уходят не потому, что", "word_ids": ["w3"]},
            {"id": "u15", "start_s": 50.33, "end_s": 62.17, "text": "их мало. конец.", "word_ids": ["w4"]},
            {"id": "u25", "start_s": 129.04, "end_s": 134.64, "text": "моим наблюдениям деньги уходят не потому, что их недостаточно, а потому что свою мечту,", "word_ids": ["w5"]},
            {"id": "u26", "start_s": 135.10, "end_s": 141.98, "text": "своей безопасности и свободу ты ставишь на второе место.", "word_ids": ["w6"]},
        ]
        merged = coalesce_utterances(utterances)
        ids = [item["id"] for item in merged]
        self.assertEqual(ids, ["u12", "u14", "u25"])
        self.assertIn("не было.", merged[0]["text"])
        self.assertIn("второе место.", merged[2]["text"])
        editorial = analyze_editorial({"schema_version": 1, "utterances": merged}, pause_threshold_s=0.5, repetition_similarity=0.86)
        entries = [
            TranscriptEntry("keep", item["id"], float(item["start_s"]), float(item["end_s"]), tuple(item["word_ids"]), item["text"])
            for item in merged
        ]
        proposed = {item.id: item for item in apply_editorial_proposals(entries, editorial)}
        # Latest cohesive take stays; earlier prefix attempt is cut when detected.
        self.assertEqual(proposed["u25"].kind, "keep")
        self.assertIn("второе место.", proposed["u25"].text)
        if proposed["u14"].kind == "keep":
            # Fallback acceptable only if analyzer did not form a retake cluster.
            self.assertTrue(len(editorial.get("take_candidates", [])) == 0)

    def test_compact_helpers(self) -> None:
        self.assertEqual(compact_entry_id("03", "u0005"), "3.5")
        self.assertEqual(compact_visual_id("03", 1), "3a")
        self.assertEqual(compact_visual_id("03", 2), "3b")


if __name__ == "__main__":
    unittest.main()
