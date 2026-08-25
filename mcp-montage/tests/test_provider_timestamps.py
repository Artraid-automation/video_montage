from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.providers import normalize_transcript
from tests.helpers import make_video


class ProviderTimestampTests(unittest.TestCase):
    def test_small_provider_boundary_drift_is_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            media = make_video(Path(temp) / "speech.mp4")
            result = normalize_transcript({"segments": [{
                "start": 0.1, "end": 0.5, "text": "hello",
                "words": [{"start": 0.08, "end": 0.56, "word": "hello"}],
            }]}, media_path=media, provider="fixture", version="1")
            self.assertEqual(result["words"][0]["start_s"], 0.1)
            self.assertEqual(result["words"][0]["end_s"], 0.5)

    def test_zero_duration_provider_word_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            media = make_video(Path(temp) / "speech.mp4")
            result = normalize_transcript({"segments": [{"start": 0.1, "end": 0.5, "text": "hello", "words": [{"start": 0.3, "end": 0.3, "word": "hello"}]}]}, media_path=media, provider="fixture", version="1")
            self.assertGreater(result["words"][0]["end_s"], result["words"][0]["start_s"])

    def test_gross_provider_boundary_error_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            media = make_video(Path(temp) / "speech.mp4")
            with self.assertRaisesRegex(ValueError, "invalid word timing"):
                normalize_transcript({"segments": [{
                    "start": 0.1, "end": 0.5, "text": "hello",
                    "words": [{"start": 0.1, "end": 2.0, "word": "hello"}],
                }]}, media_path=media, provider="fixture", version="1")


if __name__ == "__main__":
    unittest.main()
