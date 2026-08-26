"""Рез пауз между словами: плотность речи должна выходить на референсную."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline.factory.pauses import (
    apply_cuts_to_words,
    confirm_with_audio,
    cut_plan,
    silence_windows,
    word_gap_cuts,
)


def _transcript(pairs):
    return {"words": [
        {"id": f"w{index + 1:06d}", "start_s": start, "end_s": end}
        for index, (start, end) in enumerate(pairs)
    ]}


class WordGapCutTests(unittest.TestCase):
    def test_only_gaps_above_threshold_are_cut(self) -> None:
        transcript = _transcript([(0.0, 0.40), (0.45, 0.90), (1.80, 2.20), (2.26, 2.70)])
        cuts = word_gap_cuts(transcript, threshold_s=0.15, keep_s=0.06)
        self.assertEqual([item["after_word_id"] for item in cuts], ["w000002"])
        self.assertAlmostEqual(cuts[0]["gap_s"], 0.90, places=6)

    def test_a_breath_is_left_on_the_seam(self) -> None:
        """Срез в ноль склеивает слова в кашу; в референсах p90 паузы 0.04–0.10 с."""
        transcript = _transcript([(0.0, 0.4), (1.4, 1.8)])
        cut = word_gap_cuts(transcript, threshold_s=0.15, keep_s=0.06)[0]
        self.assertAlmostEqual(cut["removed_s"], 1.0 - 0.06, places=6)
        remaining = apply_cuts_to_words(transcript, [cut])
        self.assertAlmostEqual(remaining[1]["start_s"] - remaining[0]["end_s"], 0.06, places=6)

    def test_keep_longer_than_threshold_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            word_gap_cuts(_transcript([(0.0, 0.4), (1.0, 1.4)]), threshold_s=0.10, keep_s=0.20)

    def test_transcript_without_words_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            word_gap_cuts({"segments": [{"start_s": 0, "end_s": 1}]})

    def test_plan_reports_density_before_and_after(self) -> None:
        transcript = _transcript([(0.0, 0.40), (0.45, 0.90), (1.80, 2.20), (2.26, 2.70)])
        plan = cut_plan(transcript, threshold_s=0.15, keep_s=0.06)
        self.assertEqual(plan["cut_count"], 1)
        self.assertLess(plan["duration_after_s"], plan["source_duration_s"])
        self.assertLess(plan["speech_share_before"], 0.70)
        self.assertGreater(plan["speech_share_after"], 0.90)  # референс: 0.92–0.97

    def test_word_timings_shift_by_what_was_removed(self) -> None:
        transcript = _transcript([(0.0, 0.4), (1.4, 1.8), (1.9, 2.3)])
        cuts = word_gap_cuts(transcript, threshold_s=0.15, keep_s=0.06)
        shifted = apply_cuts_to_words(transcript, cuts)
        self.assertAlmostEqual(shifted[0]["start_s"], 0.0, places=6)
        self.assertAlmostEqual(shifted[1]["start_s"], 0.46, places=6)
        self.assertAlmostEqual(shifted[2]["start_s"], 0.96, places=6)


class AudioConfirmationTests(unittest.TestCase):
    def test_silence_in_the_signal_confirms_the_cut(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "speech.wav"
            # тон 0.4 с, тишина 1.0 с, тон 0.4 с
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=300:duration=0.4",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1.0",
                "-f", "lavfi", "-i", "sine=frequency=300:duration=0.4",
                "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
                str(audio),
            ], check=True, capture_output=True)
            windows = silence_windows(audio, noise_db=-40.0, min_s=0.10)
            self.assertTrue(windows, "тишина между тонами не найдена")
            transcript = _transcript([(0.0, 0.4), (1.4, 1.8)])
            cuts = confirm_with_audio(word_gap_cuts(transcript, threshold_s=0.15, keep_s=0.06), windows)
            self.assertTrue(cuts[0]["audio_confirmed"])
            self.assertGreater(cuts[0]["audio_silence_share"], 0.8)

    def test_cut_over_speech_is_not_confirmed(self) -> None:
        transcript = _transcript([(0.0, 0.4), (1.4, 1.8)])
        cuts = confirm_with_audio(
            word_gap_cuts(transcript, threshold_s=0.15, keep_s=0.06),
            [(5.0, 6.0)],  # тишина есть, но не там
        )
        self.assertFalse(cuts[0]["audio_confirmed"])
        self.assertEqual(cuts[0]["audio_silence_share"], 0.0)


if __name__ == "__main__":
    unittest.main()
