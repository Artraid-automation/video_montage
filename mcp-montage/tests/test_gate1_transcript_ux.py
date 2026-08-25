from __future__ import annotations

import unittest

from pipeline.factory.editorial import (
    analyze_editorial,
    apply_editorial_proposals,
    coalesce_utterances,
)
from pipeline.factory.transcript import (
    TranscriptEntry,
    VisualEntry,
    enrich_entries_from_source,
    parse_transcript,
    render_transcript,
)


class Gate1TranscriptUxTests(unittest.TestCase):
    def test_human_render_is_start_only_without_word_lists(self) -> None:
        entries = [
            TranscriptEntry("keep", "u1", 19.32, 21.44, ("w1", "w2", "w3"), "полный текст"),
            TranscriptEntry("cut", "u2", 47.75, 50.33, ("w4",), "дубль", "proposed-repetition"),
        ]
        rendered = render_transcript(entries, [VisualEntry("v1", "u1", "motion", "brief")])
        self.assertIn("[0:19.320] KEEP id=u1", rendered)
        self.assertIn("**полный текст**", rendered)
        self.assertIn("[0:47.750] CUT (повтор фразы) id=u2", rendered)
        self.assertIn("[0:19.320] MOTION v1 (оверлей-начало) @u1", rendered)
        self.assertIn("КОНЕЦ СЕГМЕНТА", rendered)
        self.assertNotIn(" -> ", rendered)
        self.assertNotIn("words=", rendered)
        parsed, visuals = parse_transcript(rendered)
        self.assertEqual(parsed[0].id, "u1")
        self.assertEqual(parsed[0].kind, "keep")
        self.assertEqual(parsed[1].reason, "proposed-repetition")
        self.assertEqual(visuals[0].id, "v1")
        source = {
            "utterances": [
                {"id": "u1", "start_s": 19.32, "end_s": 21.44, "text": "полный текст", "word_ids": ["w1", "w2", "w3"]},
                {"id": "u2", "start_s": 47.75, "end_s": 50.33, "text": "дубль", "word_ids": ["w4"]},
            ]
        }
        enriched = enrich_entries_from_source(parsed, source)
        self.assertEqual(enriched[0].word_ids, ("w1", "w2", "w3"))
        self.assertAlmostEqual(enriched[0].end_s, 21.44)

    def test_coalesce_merges_orphan_trailing_word(self) -> None:
        utterances = [
            {"id": "u5", "start_s": 15.28, "end_s": 18.60, "text": "Откладывай на отдельный счет, а лучше на счет в другом", "word_ids": ["w1", "w2"]},
            {"id": "u6", "start_s": 18.60, "end_s": 19.00, "text": "банке.", "word_ids": ["w3"]},
            {"id": "u7", "start_s": 19.32, "end_s": 21.44, "text": "Пока ты будешь переводить деньги", "word_ids": ["w4", "w5"]},
        ]
        merged = coalesce_utterances(utterances)
        self.assertEqual([item["id"] for item in merged], ["u5", "u7"])
        self.assertIn("банке.", merged[0]["text"])
        self.assertEqual(merged[0]["word_ids"], ["w1", "w2", "w3"])

    def test_coalesce_keeps_retake_attempts_intact_so_cuts_are_whole_clauses(self) -> None:
        utterances = [
            {"id": "u14", "start_s": 47.75, "end_s": 50.33, "text": "По моим наблюдениям деньги уходят не потому, что", "word_ids": ["w1"]},
            {"id": "u15", "start_s": 50.33, "end_s": 53.45, "text": "их мало или недостаточно, а потому, что свои мечты,", "word_ids": ["w2"]},
            {"id": "u16", "start_s": 53.63, "end_s": 56.95, "text": "свое спокойствие, свою безопасность, мы откладываем.", "word_ids": ["w3"]},
            {"id": "u19", "start_s": 70.92, "end_s": 73.46, "text": "По моим наблюдениям деньги уходят не потому, что", "word_ids": ["w4"]},
            {"id": "u20", "start_s": 73.46, "end_s": 76.78, "text": "их недостаточно, а потому, что свои спокойствия.", "word_ids": ["w5"]},
        ]
        merged = coalesce_utterances(utterances)
        self.assertEqual([item["id"] for item in merged], ["u14", "u19"])
        self.assertIn("мы откладываем.", merged[0]["text"])
        editorial = analyze_editorial({"schema_version": 1, "utterances": merged}, pause_threshold_s=0.5, repetition_similarity=0.86)
        entries = [
            TranscriptEntry("keep", item["id"], float(item["start_s"]), float(item["end_s"]), tuple(item["word_ids"]), item["text"])
            for item in merged
        ]
        proposed = {item.id: item for item in apply_editorial_proposals(entries, editorial)}
        self.assertEqual(proposed["u14"].kind, "cut")
        self.assertEqual(proposed["u19"].kind, "keep")


if __name__ == "__main__":
    unittest.main()
