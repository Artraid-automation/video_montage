from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.render import _subtract_suppress_windows, _write_caption_ass


class CaptionGapTests(unittest.TestCase):
    def test_subtract_motion_window_keeps_gaps(self) -> None:
        parts = _subtract_suppress_windows(0.0, 10.0, [(2.0, 5.0)])
        self.assertEqual(parts, [(0.0, 2.0), (5.0, 10.0)])

    def test_subtract_full_cover_drops_event(self) -> None:
        parts = _subtract_suppress_windows(2.0, 4.0, [(1.0, 5.0)])
        self.assertEqual(parts, [])

    def test_ass_skips_motion_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "c.ass"
            meta = _write_caption_ass(
                path,
                text="один два три четыре пять шесть семь восемь",
                duration_s=8.0,
                width=720,
                height=1280,
                pip_enabled=False,
                pos_x=360,
                pos_y=870,
                suppress_windows=[(1.5, 4.0)],
            )
            body = path.read_text(encoding="utf-8")
            self.assertIn("Dialogue:", body)
            self.assertTrue(meta["captions_suppressed_for_motion"])
            self.assertEqual(meta["caption_suppress_windows"][0]["start_s"], 1.5)
            # No event should start inside the suppress window.
            for line in body.splitlines():
                if not line.startswith("Dialogue:"):
                    continue
                # Dialogue: 0,H:MM:SS.cc,H:MM:SS.cc,...
                start_token = line.split(",")[1]
                h, m, rest = start_token.split(":")
                s, cs = rest.split(".")
                start_s = int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
                self.assertFalse(1.5 <= start_s < 4.0, line)

    def test_ass_uses_word_timings_not_even_slices(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "timed.ass"
            meta = _write_caption_ass(
                path,
                text="alpha bravo charlie delta echo foxtrot golf",
                duration_s=10.0,
                width=720,
                height=1280,
                pip_enabled=False,
                timed_words=[
                    {"text": "alpha", "start_s": 0.2, "end_s": 0.5},
                    {"text": "bravo", "start_s": 0.5, "end_s": 0.8},
                    {"text": "charlie", "start_s": 0.8, "end_s": 1.1},
                    {"text": "delta", "start_s": 1.1, "end_s": 1.4},
                    {"text": "echo", "start_s": 1.4, "end_s": 1.7},
                    {"text": "foxtrot", "start_s": 1.7, "end_s": 2.0},
                    {"text": "golf", "start_s": 7.0, "end_s": 7.4},
                ],
            )
            self.assertEqual(meta["caption_timing"], "source-words")
            body = path.read_text(encoding="utf-8")
            starts = []
            for line in body.splitlines():
                if not line.startswith("Dialogue:"):
                    continue
                start_token = line.split(",")[1]
                h, m, rest = start_token.split(":")
                s, cs = rest.split(".")
                starts.append(int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100)
            self.assertGreaterEqual(len(starts), 2)
            self.assertLess(starts[0], 1.0)
            self.assertGreaterEqual(starts[1], 6.5)

if __name__ == "__main__":
    unittest.main()
