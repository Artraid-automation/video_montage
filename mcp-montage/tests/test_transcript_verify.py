from __future__ import annotations

import unittest

from pipeline.factory.verification import verify_transcript


def transcript(text: str) -> dict:
    tokens = text.split()
    return {"words": [{"text": token, "start_s": index * 0.4, "end_s": index * 0.4 + 0.3} for index, token in enumerate(tokens)]}


class TranscriptVerificationTests(unittest.TestCase):
    def test_exact_and_punctuation_only_pass(self) -> None:
        self.assertEqual(verify_transcript(transcript("Hello world"), transcript("hello world"))["verdict"], "PASS")
        self.assertEqual(verify_transcript(transcript("Привет мир"), transcript("Привет, мир!"))["verdict"], "PASS")

    def test_deletion_duplication_and_reorder_fail(self) -> None:
        expected = transcript("one two three four five six")
        for actual in (
            transcript("one two five six"),
            transcript("one two three three four five six"),
            transcript("one five six two three four"),
        ):
            self.assertEqual(verify_transcript(expected, actual, max_wer=0.1, min_order_ratio=0.95)["verdict"], "FAIL")

    def test_long_silence_fails_even_when_words_match(self) -> None:
        expected = transcript("one two")
        actual = transcript("one two")
        actual["words"][1]["start_s"] = 4.0
        actual["words"][1]["end_s"] = 4.3
        result = verify_transcript(expected, actual)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("unexpected long silence", result["reasons"])

    def test_adjacent_phrase_echo_fails(self) -> None:
        expected = transcript("ежедневная работа руками работа руками и упорство")
        actual = transcript("ежедневная работа руками работа руками и упорство")
        result = verify_transcript(expected, actual, max_wer=0.2, min_order_ratio=0.8)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("adjacent phrase echo in expected keep", result["reasons"])

    def test_repeated_opener_in_actual_fails_even_if_expected_clean(self) -> None:
        expected = transcript("переходят следующее вместо того чтобы добежать до результата")
        actual = transcript(
            "переходят следующее вместо того чтобы вместо твердой постоянной работы вместо того чтобы добежать"
        )
        result = verify_transcript(
            expected,
            actual,
            max_wer=0.5,
            min_order_ratio=0.5,
            reject_adjacent_echoes=False,
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("repeated clause opener retake in rendered speech", result["reasons"])

    def test_leading_silence_in_keep_fails(self) -> None:
        expected = {
            "words": [
                {"text": "hello", "start_s": 2.5, "end_s": 2.8},
                {"text": "world", "start_s": 2.9, "end_s": 3.2},
            ],
            "utterances": [
                {
                    "source_entry_id": "u1",
                    "start_s": 0.0,
                    "end_s": 4.0,
                    "text": "hello world",
                    "word_ids": [],
                }
            ],
        }
        actual = transcript("hello world")
        result = verify_transcript(
            expected,
            actual,
            max_wer=0.2,
            min_order_ratio=0.8,
            max_lead_in_silence_s=0.8,
            reject_repeated_openers=False,
            reject_adjacent_echoes=False,
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("leading silence inside keep clip", result["reasons"])

    def test_timing_drift_fails_when_words_match_but_shifted(self) -> None:
        expected = transcript("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima")
        actual = transcript("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima")
        for word in actual["words"]:
            word["start_s"] = float(word["start_s"]) + 1.2
            word["end_s"] = float(word["end_s"]) + 1.2
        result = verify_transcript(
            expected,
            actual,
            max_wer=0.2,
            min_order_ratio=0.8,
            max_timing_drift_s=0.5,
            max_timing_drift_ratio=0.2,
            reject_repeated_openers=False,
            reject_adjacent_echoes=False,
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("speech timing drift exceeds threshold", result["reasons"])


if __name__ == "__main__":
    unittest.main()
