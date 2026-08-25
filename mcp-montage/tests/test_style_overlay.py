from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.factory.media import validate_video
from pipeline.factory.style_overlay import render_framework_list_card, render_hook_title_card


class StyleOverlayTests(unittest.TestCase):
    def test_hook_title_renders_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "title.mov"
            meta = render_hook_title_card(
                out,
                title="How To Achieve Anything",
                duration_s=1.0,
                width=320,
                height=640,
                fps=25,
                face_bottom_y=280,
            )
            validate_video(out)
            self.assertGreater(out.stat().st_size, 1000)
            self.assertGreater(meta["hook_title_font_size"], 40)
            self.assertGreaterEqual(meta["hook_title_y_center_ratio"], 0.48)
            # Hook must be larger than body-caption target (~0.045*h).
            self.assertGreater(meta["hook_title_font_ratio"], 0.045)

    def test_framework_list_renders_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "list.mov"
            render_framework_list_card(
                out,
                lines=["Vision", "Learning", "Building", "Persistence"],
                duration_s=1.0,
                width=320,
                height=180,
                fps=25,
                active_index=1,
            )
            validate_video(out)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
