"""Движение кадра: план должен воспроизводить измеренные доли, а не «оживлять» наугад."""

from __future__ import annotations

import unittest

from pipeline.factory.camera_move import DEFAULTS, describe, shot_plan, zoom_filter
from pipeline.factory.style_profile import load_style, section

SHOTS = [
    {"id": f"s{index:02d}", "duration_s": duration}
    for index, duration in enumerate(
        [2.6, 1.2, 3.4, 0.8, 2.9, 4.1, 1.7, 2.2, 3.0, 1.4, 2.5, 2.8,
         3.3, 0.9, 2.1, 3.7, 1.6, 2.4, 2.0, 3.1], 1
    )
]


class ShotPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.camera = section(load_style("strokov-measured-v1"), "camera")
        self.plan = shot_plan(SHOTS, camera=self.camera, seed="test")

    def test_moving_share_matches_the_reference_band(self) -> None:
        """В референсах движение есть в 62–80% планов."""
        share = describe(self.plan)["moving_share"]
        self.assertGreaterEqual(share, 0.55)
        self.assertLessEqual(share, 0.90)

    def test_pushes_in_dominate_pull_outs(self) -> None:
        """Наездов в 4–7 раз больше отъездов: отъезд читается как сброс на новую мысль."""
        self.assertGreaterEqual(describe(self.plan)["zoom_in_share"], 0.6)

    def test_cut_step_stays_inside_the_measured_band(self) -> None:
        """Ступень крупности на склейке — 11–20%: она и маскирует jump cut."""
        steps = [item["cut_step_pct"] for item in self.plan[1:]]
        self.assertTrue(steps)
        for step in steps:
            self.assertGreaterEqual(step, self.camera["cut_scale_step_min_pct"])
            self.assertLessEqual(step, self.camera["cut_scale_step_max_pct"])

    def test_zoom_speed_never_exceeds_the_style_rate(self) -> None:
        rate = float(self.camera["zoom_rate_pct_per_s"])
        for item in self.plan:
            if item["moves"]:
                speed = abs(item["zoom_pct"]) / max(item["duration_s"], 1e-6)
                self.assertLessEqual(round(speed, 6), rate + 1e-6)
                self.assertLessEqual(abs(item["zoom_pct"]), self.camera["zoom_max_pct"] + 1e-9)

    def test_scale_never_drops_below_the_source_frame(self) -> None:
        """Меньше единицы означало бы кадр шире исходника — брать неоткуда."""
        for item in self.plan:
            self.assertGreaterEqual(item["start_scale"], 1.0)
            self.assertGreaterEqual(item["end_scale"], 1.0)

    def test_plan_is_deterministic(self) -> None:
        """Иначе повторный рендер после resume соберёт другой кадр и сломает переиспользование."""
        again = shot_plan(SHOTS, camera=self.camera, seed="test")
        self.assertEqual(self.plan, again)
        other = shot_plan(SHOTS, camera=self.camera, seed="another")
        self.assertNotEqual(self.plan, other)

    def test_first_shot_has_no_cut_step(self) -> None:
        self.assertEqual(self.plan[0]["cut_step_pct"], 0.0)
        self.assertEqual(self.plan[0]["start_scale"], 1.0)

    def test_defaults_apply_when_style_says_nothing(self) -> None:
        plan = shot_plan(SHOTS, camera=None, seed="test")
        self.assertEqual(plan, shot_plan(SHOTS, camera=dict(DEFAULTS), seed="test"))


class ZoomFilterTests(unittest.TestCase):
    def test_moving_shot_uses_supersampled_zoompan(self) -> None:
        entry = {"shot_id": "s01", "duration_s": 3.0, "start_scale": 1.0, "end_scale": 1.075, "zoom_pct": 7.5, "moves": True}
        chain = zoom_filter(entry, width=1080, height=1920, fps=60)
        self.assertIn("scale=2160:3840", chain)  # запас перед покадровым позиционированием
        self.assertIn("zoompan=", chain)
        self.assertIn("s=1080x1920", chain)
        self.assertIn("fps=60", chain)

    def test_static_shot_avoids_per_frame_work(self) -> None:
        entry = {"shot_id": "s02", "duration_s": 2.0, "start_scale": 1.12, "end_scale": 1.12, "zoom_pct": 0.0, "moves": False}
        chain = zoom_filter(entry, width=1080, height=1920, fps=60)
        self.assertNotIn("zoompan", chain)
        self.assertIn("crop=w=iw/1.12", chain)

    def test_untouched_shot_is_a_plain_scale(self) -> None:
        entry = {"shot_id": "s03", "duration_s": 2.0, "start_scale": 1.0, "end_scale": 1.0, "zoom_pct": 0.0, "moves": False}
        # Частота приводится и на неподвижном плане: иначе часть планов уходит в
        # частоте исходника, часть — в частоте профиля, и склейка затыкает стыки
        # стоп-кадрами (замер 30.08 на pilot-live2).
        self.assertEqual(zoom_filter(entry, width=1080, height=1920, fps=60), "scale=1080:1920,fps=60")

    def test_invalid_frame_fails_closed(self) -> None:
        entry = {"shot_id": "s04", "duration_s": 1.0, "start_scale": 1.0, "end_scale": 1.05, "moves": True}
        with self.assertRaises(ValueError):
            zoom_filter(entry, width=0, height=1920, fps=60)


if __name__ == "__main__":
    unittest.main()


class RenderedZoomTests(unittest.TestCase):
    """Строка фильтра ничего не доказывает — проверяем на отрендеренном кадре.

    Источник обязан быть статичным: на живом отрезке собственное движение человека
    и склейки полностью забивают наезд в 7% (первая проверка так и ошиблась — намерила
    +35% там, где фильтр давал 7.5%).
    """

    def test_rendered_zoom_matches_the_plan(self) -> None:
        import subprocess
        import tempfile

        import cv2
        import numpy as np

        from pipeline.factory.camera_move import zoom_filter

        with tempfile.TemporaryDirectory() as temp:
            root = __import__("pathlib").Path(temp)
            still = root / "still.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=2",
                "-pix_fmt", "yuv420p", str(still),
            ], check=True, capture_output=True)
            entry = {"shot_id": "s01", "duration_s": 2.0,
                     "start_scale": 1.0, "end_scale": 1.10, "zoom_pct": 10.0, "moves": True}
            chain = zoom_filter(entry, width=360, height=640, fps=30)
            out = root / "zoomed.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(still), "-vf", chain, "-an", str(out),
            ], check=True, capture_output=True)

            cap = cv2.VideoCapture(str(out))
            frames = []
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            cap.release()
            self.assertGreaterEqual(len(frames), 30)

            first, last = frames[0], frames[-1]
            points = cv2.goodFeaturesToTrack(first, 600, 0.01, 6)
            tracked, status, _ = cv2.calcOpticalFlowPyrLK(
                first, last, points, None, winSize=(31, 31), maxLevel=4
            )
            matrix, inliers = cv2.estimateAffinePartial2D(
                points[status == 1], tracked[status == 1],
                method=cv2.RANSAC, ransacReprojThreshold=3.0,
            )
            self.assertIsNotNone(matrix)
            self.assertGreaterEqual(int(inliers.sum()), 20)
            measured = float(np.sqrt(matrix[0, 0] ** 2 + matrix[0, 1] ** 2))
            self.assertAlmostEqual(measured, 1.10, delta=0.02)
