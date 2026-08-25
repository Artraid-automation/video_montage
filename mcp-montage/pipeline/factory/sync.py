"""Waveform offset analysis without third-party numeric dependencies."""

from __future__ import annotations

import array
import math
import subprocess
from pathlib import Path
from typing import Any

from .media import require_tool


def extract_envelope(path: Path, *, sample_rate: int = 2000, envelope_rate: int = 100) -> list[float]:
    block = sample_rate // envelope_rate
    if block <= 0 or sample_rate % envelope_rate:
        raise ValueError("sample_rate must be divisible by envelope_rate")
    command = [
        require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-map", "0:a:0", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", "replace")[-2000:]
        raise RuntimeError(f"cannot extract audio waveform from {path}: {error}")
    samples = array.array("h")
    samples.frombytes(result.stdout[: len(result.stdout) - len(result.stdout) % 2])
    if not samples:
        raise ValueError(f"audio stream is empty: {path}")
    return [
        sum(abs(value) for value in samples[start:start + block]) / (block * 32768.0)
        for start in range(0, len(samples) - block + 1, block)
    ]


def _correlation(left: list[float], right: list[float], lag: int, min_overlap: int) -> float:
    left_start = max(0, -lag)
    right_start = max(0, lag)
    length = min(len(left) - left_start, len(right) - right_start)
    if length < min_overlap:
        return -1.0
    a = left[left_start:left_start + length]
    b = right[right_start:right_start + length]
    mean_a = sum(a) / length
    mean_b = sum(b) / length
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    denominator = math.sqrt(
        sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)
    )
    return numerator / denominator if denominator > 1e-12 else -1.0


def estimate_offset(
    reference: list[float], external: list[float], *, rate: int = 100, max_offset_s: float = 30.0,
) -> dict[str, float]:
    if min(len(reference), len(external)) < rate * 2:
        raise ValueError("waveforms are too short for reliable synchronization")
    max_lag = min(int(max_offset_s * rate), max(len(reference), len(external)) - rate * 2)
    min_overlap = max(rate * 2, min(rate * 20, min(len(reference), len(external)) - max_lag))
    scores = [(lag, _correlation(reference, external, lag, min_overlap)) for lag in range(-max_lag, max_lag + 1)]
    best_lag, best_score = max(scores, key=lambda item: item[1])
    exclusion = max(2, rate // 20)
    alternatives = [score for lag, score in scores if abs(lag - best_lag) > exclusion]
    second = max(alternatives) if alternatives else -1.0
    return {
        "offset_s": best_lag / rate,
        "correlation": round(best_score, 6),
        "prominence": round(best_score - second, 6),
    }


def analyze_sync(
    reference_path: Path,
    external_path: Path,
    *,
    max_offset_s: float = 30.0,
    correlation_threshold: float = 0.55,
    max_drift_ppm: float = 1500.0,
) -> dict[str, Any]:
    rate = 100
    reference = extract_envelope(reference_path, envelope_rate=rate)
    external = extract_envelope(external_path, envelope_rate=rate)
    result = estimate_offset(reference, external, rate=rate, max_offset_s=max_offset_s)
    duration_s = min(len(reference), len(external)) / rate
    drift_ppm = 0.0
    early_offset = result["offset_s"]
    late_offset = result["offset_s"]
    if duration_s >= 40:
        window = min(int(rate * 30), len(reference) // 3, len(external) // 3)
        padding = int(max_offset_s * rate)
        early = estimate_offset(reference[:window], external[:window + padding], rate=rate, max_offset_s=max_offset_s)
        late = estimate_offset(reference[-window:], external[-(window + padding):], rate=rate, max_offset_s=max_offset_s)
        early_offset = early["offset_s"]
        late_offset = late["offset_s"]
        drift_ppm = (late_offset - early_offset) / max(duration_s - window / rate, 1.0) * 1_000_000
    reasons: list[str] = []
    if result["correlation"] < correlation_threshold:
        reasons.append("correlation below threshold")
    if abs(drift_ppm) > max_drift_ppm:
        reasons.append("drift exceeds threshold")
    return {
        "schema_version": 1, "verdict": "FAIL" if reasons else "PASS",
        "reference": str(reference_path), "external": str(external_path),
        "offset_s": result["offset_s"], "correlation": result["correlation"],
        "prominence": result["prominence"], "early_offset_s": early_offset,
        "late_offset_s": late_offset, "drift_ppm": round(drift_ppm, 3),
        "thresholds": {"correlation_min": correlation_threshold, "drift_ppm_max": max_drift_ppm},
        "reasons": reasons,
    }
