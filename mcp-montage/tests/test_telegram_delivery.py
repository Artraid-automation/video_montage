from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.factory.media import duration_s, probe, streams
from pipeline.factory.telegram_delivery import (
    build_telegram_filters,
    encode_telegram_delivery,
    resolve_telegram_delivery_config,
)
from tests.helpers import make_video


class TelegramDeliveryFilterTests(unittest.TestCase):
    def test_filters_default_no_speed(self) -> None:
        vf, af = build_telegram_filters(width=1080, height=1920, speed_factor=1.0)
        self.assertIn("scale=1080:1920", vf)
        self.assertIn("setsar=1", vf)
        self.assertIn("format=yuv420p", vf)
        self.assertNotIn("setpts", vf)
        self.assertIsNone(af)

    def test_filters_speed_1_15(self) -> None:
        vf, af = build_telegram_filters(width=1080, height=1920, speed_factor=1.15)
        self.assertIn("setpts=PTS/1.15", vf)
        self.assertEqual(af, "atempo=1.15")

    def test_rejects_bad_speed(self) -> None:
        with self.assertRaises(ValueError):
            build_telegram_filters(width=1080, height=1920, speed_factor=0.4)


class TelegramDeliveryEncodeTests(unittest.TestCase):
    def test_encode_1080x1920_yuv420p_and_optional_speed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_video(root / "src.mp4", duration=2.0, color="green")
            out = root / "tg.mp4"
            encode_telegram_delivery(
                source, out, width=1080, height=1920, speed_factor=1.15, crf=28, preset="ultrafast",
            )
            report = probe(out)
            video = streams(report, "video")[0]
            self.assertEqual(int(video["width"]), 1080)
            self.assertEqual(int(video["height"]), 1920)
            self.assertEqual(video["pix_fmt"], "yuv420p")
            sar = video.get("sample_aspect_ratio") or "1:1"
            self.assertIn(sar, {"1:1", "N/A"})
            # 2.0s / 1.15 ≈ 1.74s
            self.assertAlmostEqual(duration_s(report), 2.0 / 1.15, delta=0.15)


class TelegramDeliveryConfigTests(unittest.TestCase):
    def test_resolve_defaults_and_optional_speed(self) -> None:
        cfg = resolve_telegram_delivery_config({
            "default_grade": "warm",
            "telegram_delivery": {"speed_factor": 1.15},
        })
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["width"], 1080)
        self.assertEqual(cfg["height"], 1920)
        self.assertEqual(cfg["speed_factor"], 1.15)
        self.assertEqual(cfg["grade"], "warm")
        self.assertEqual(cfg["send_as"], "document")

    def test_can_disable(self) -> None:
        cfg = resolve_telegram_delivery_config({"telegram_delivery": {"enabled": False}})
        self.assertFalse(cfg["enabled"])


class TelegramSendDocumentTests(unittest.TestCase):
    def test_send_document_posts_multipart(self) -> None:
        from pipeline.factory.telegram_delivery import send_telegram_document

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "clip.mp4"
            path.write_bytes(b"fake")
            with patch("urllib.request.urlopen") as urlopen:
                class _Resp:
                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return False

                    def read(self):
                        return b'{"ok":true,"result":{"message_id":42}}'

                urlopen.return_value = _Resp()
                result = send_telegram_document(
                    path,
                    bot_token="123:ABC",
                    chat_id="999",
                    caption="hello",
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["message_id"], 42)
                self.assertTrue(urlopen.called)


if __name__ == "__main__":
    unittest.main()
