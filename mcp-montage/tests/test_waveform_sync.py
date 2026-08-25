from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from pipeline.factory.sync import analyze_sync


def pulse_wav(path: Path, *, delay_s: float, duration_s: float = 5.0, rate: int = 8000) -> None:
    events = [1.0 + delay_s, 2.2 + delay_s, 3.7 + delay_s]
    values = []
    for index in range(int(duration_s * rate)):
        t = index / rate
        value = 0.0
        for event in events:
            if event <= t < event + 0.08:
                value += 0.8 * math.sin(2 * math.pi * 700 * (t - event))
        values.append(max(-32767, min(32767, int(value * 32767))))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(struct.pack("<h", value) for value in values))


class WaveformSyncTests(unittest.TestCase):
    def test_known_external_delay_is_measured(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reference = root / "reference.wav"
            external = root / "external.wav"
            pulse_wav(reference, delay_s=0.0)
            pulse_wav(external, delay_s=0.35)
            result = analyze_sync(reference, external, max_offset_s=1.0, correlation_threshold=0.5)
            self.assertEqual(result["verdict"], "PASS")
            self.assertAlmostEqual(result["offset_s"], 0.35, delta=0.03)


if __name__ == "__main__":
    unittest.main()
