from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from pipeline.factory.io import sha256_file
from pipeline.factory.visual_audit import (
    build_gate2_visual_audit,
    caption_gap_timestamps,
    count_gold_caption_pixels,
)
from tests.helpers import make_video


class Gate2VisualAuditTests(unittest.TestCase):
    def test_requires_random_frames_and_per_motion_probes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = make_video(root / "review.mp4", duration=4.0, color="green")
            motions = [
                {
                    "id": "1a",
                    "render_start_s": 0.2,
                    "render_end_s": 1.8,
                    "on_screen": "0 ₽",
                    "raw_brief": "Индикатор. Зачем: x",
                },
                {
                    "id": "1b",
                    "render_start_s": 2.0,
                    "render_end_s": 3.5,
                    "on_screen": "",
                    "raw_brief": "Иконки паники поверх речи: x. Зачем: y",
                },
            ]
            report = build_gate2_visual_audit(
                root,
                media,
                root / "probes" / "gate2-audit",
                render_sha256=sha256_file(media),
                motions=motions,
                random_count=3,
            )
            self.assertEqual(report["kind"], "gate2-visual-audit")
            self.assertEqual(report["verdict"], "PASS")
            self.assertEqual(len(report["random_frames"]), 3)
            self.assertEqual(len(report["motion_checks"]), 2)
            for motion in report["motion_checks"]:
                self.assertEqual(motion["verdict"], "PASS")
                self.assertGreaterEqual(len(motion["frames"]), 2)
                for frame in motion["frames"]:
                    self.assertTrue((root / frame["path"]).is_file())
            for frame in report["random_frames"]:
                self.assertTrue((root / frame["path"]).is_file())
            # Same seed → same timestamps
            again = build_gate2_visual_audit(
                root,
                media,
                root / "probes" / "gate2-audit-b",
                render_sha256=sha256_file(media),
                motions=motions,
                random_count=3,
            )
            self.assertEqual(
                [item["timestamp_s"] for item in report["random_frames"]],
                [item["timestamp_s"] for item in again["random_frames"]],
            )

    def test_missing_motion_window_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = make_video(root / "review.mp4", duration=1.2, color="blue")
            report = build_gate2_visual_audit(
                root,
                media,
                root / "probes" / "gate2-audit",
                render_sha256=sha256_file(media),
                motions=[
                    {
                        "id": "bad",
                        "render_start_s": 9.0,
                        "render_end_s": 10.0,
                        "on_screen": "x",
                        "raw_brief": "x",
                    }
                ],
                random_count=2,
            )
            self.assertEqual(report["verdict"], "FAIL")
            self.assertTrue(any("motion" in reason for reason in report["reasons"]))

    def test_caption_gap_timestamps_between_motions(self) -> None:
        stamps = caption_gap_timestamps(
            10.0,
            [
                {"render_start_s": 2.0, "render_end_s": 4.0},
                {"render_start_s": 6.0, "render_end_s": 8.0},
            ],
        )
        self.assertEqual(len(stamps), 3)
        self.assertAlmostEqual(stamps[0], 1.0, places=2)
        self.assertAlmostEqual(stamps[1], 5.0, places=2)
        self.assertAlmostEqual(stamps[2], 9.0, places=2)

    def test_missing_captions_in_gap_fails_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Solid green — no gold captions.
            media = make_video(root / "review.mp4", duration=4.0, color="green")
            motions = [
                {
                    "id": "1a",
                    "render_start_s": 1.0,
                    "render_end_s": 2.5,
                    "on_screen": "0 ₽",
                    "raw_brief": "x",
                }
            ]
            report = build_gate2_visual_audit(
                root,
                media,
                root / "probes" / "gate2-audit",
                render_sha256=sha256_file(media),
                motions=motions,
                random_count=2,
                caption_pos_y=200,
                require_caption_gaps=True,
            )
            self.assertEqual(report["verdict"], "FAIL")
            self.assertTrue(report["caption_gap_checks"])
            self.assertTrue(any("missing body captions" in r for r in report["reasons"]))

            still = root / "gold.jpg"
            img = Image.new("RGB", (360, 640), (20, 20, 20))
            draw = ImageDraw.Draw(img)
            draw.rectangle((40, 400, 320, 460), fill=(225, 196, 69))
            img.save(still)
            self.assertGreater(count_gold_caption_pixels(still, caption_pos_y=400), 250)


if __name__ == "__main__":
    unittest.main()
