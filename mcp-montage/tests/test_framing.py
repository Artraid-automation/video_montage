from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from pipeline.factory.framing import (
    caption_pos_from_face,
    compute_framing_plan,
    face_caption_overlap,
    verify_frame_face_caption,
)


class FramingGeometryTests(unittest.TestCase):
    def test_crop_targets_eye_line_and_face_fill(self) -> None:
        # Face in upper-left of a 1920x1080 source — crop must center it.
        plan = compute_framing_plan(
            src_w=1920, src_h=1080, out_w=720, out_h=1280,
            face=(200, 80, 180, 220),
        )
        self.assertIn("scale=", plan["ffmpeg_vf"])
        self.assertIn("crop=720:1280:", plan["ffmpeg_vf"])
        predicted = plan["predicted"]
        self.assertLessEqual(predicted["face_height_ratio"], 0.40)
        self.assertLessEqual(predicted["headroom_ratio"], 0.20)
        self.assertGreaterEqual(predicted["headroom_ratio"], 0.02)

    def test_caption_below_face_not_on_face(self) -> None:
        face = (260, 200, 200, 240)
        pos = caption_pos_from_face(face, width=720, height=1280)
        self.assertEqual(pos["placement"], "below-face-chest")
        self.assertGreaterEqual(pos["caption_pos_y"], face[1] + face[3] + 8)
        self.assertIn("caption_max_width_px", pos)
        # Ширину держат поля кадра, а не плечи: прежний конверт 42% ужимал кегль на
        # длинных словах, хотя в эталоне такое слово идёт одной строкой во всю грудь.
        self.assertLessEqual(pos["caption_max_width_px"], int(720 * 0.86) + 8)
        # Строка стоит по вертикальной оси кадра, а не по телу говорящего.
        self.assertEqual(pos["caption_pos_x"], 360)
        self.assertFalse(
            face_caption_overlap(
                face,
                caption_top_y=pos["caption_pos_y"],
                caption_height_px=96,
            )
        )
        self.assertTrue(
            face_caption_overlap(
                face,
                caption_top_y=face[1] + face[3] // 2,
                caption_height_px=96,
            )
        )

    def test_map_source_face_preserve_source_scale(self) -> None:
        from pipeline.factory.framing import map_source_face_to_output

        plan = {
            "source": {"width": 1280, "height": 720},
            "scaled_w": 1920,
            "scaled_h": 1080,
            "crop_x": 0,
            "crop_y": 0,
        }
        out = map_source_face_to_output((462, 98, 133, 190), plan)
        self.assertEqual(out[:2], (693, 147))
        self.assertEqual(out[3], 285)
        self.assertIn(out[2], (199, 200))

        face = (693, 147, 199, 285)
        pos = caption_pos_from_face(face, width=1920, height=1080)
        # Must stay inside shoulder envelope (~1.55 * face_w), not frame half-width.
        self.assertLessEqual(pos["caption_max_width_px"], 450)
        self.assertGreaterEqual(pos["caption_pos_y"], 471 + int(1080 * 0.14))

    def test_verify_require_face_flag_softens_haar_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "blank.jpg"
            img = np.zeros((1280, 720, 3), dtype=np.uint8)
            img[:] = (40, 40, 40)
            cv2.imwrite(str(path), img)
            with patch("pipeline.factory.framing.detect_largest_face", return_value=None):
                soft = verify_frame_face_caption(
                    path, caption_top_y=500, caption_height_px=80, require_face=False,
                )
                hard = verify_frame_face_caption(
                    path, caption_top_y=500, caption_height_px=80, require_face=True,
                )
            self.assertIsNone(soft["face"])
            self.assertEqual(soft["verdict"], "PASS")
            self.assertEqual(hard["verdict"], "PASS")
            self.assertTrue(any("face not detected" in r for r in hard["soft_reasons"]))

    def test_verify_fails_when_face_touches_frame_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "edge.jpg"
            img = np.zeros((1280, 720, 3), dtype=np.uint8)
            img[:] = (120, 120, 120)
            cv2.imwrite(str(path), img)
            with patch("pipeline.factory.framing.detect_largest_face", return_value=(8, 120, 180, 220)):
                report = verify_frame_face_caption(
                    path, caption_top_y=900, caption_height_px=80, require_face=True,
                )
            self.assertEqual(report["verdict"], "FAIL")
            self.assertTrue(any("frame edge" in r for r in report["reasons"]))

    def test_verify_fails_when_headroom_too_small(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tight-top.jpg"
            img = np.zeros((1280, 720, 3), dtype=np.uint8)
            img[:] = (120, 120, 120)
            cv2.imwrite(str(path), img)
            with patch("pipeline.factory.framing.detect_largest_face", return_value=(220, 12, 180, 220)):
                report = verify_frame_face_caption(
                    path, caption_top_y=900, caption_height_px=80, require_face=True,
                )
            self.assertEqual(report["verdict"], "FAIL")
            self.assertTrue(any("headroom ratio" in r for r in report["reasons"]))


if __name__ == "__main__":
    unittest.main()
