"""Transcription provider boundary with deterministic sidecar and local Whisper implementations."""

from __future__ import annotations

import re
import json
import subprocess
from pathlib import Path
from typing import Any, Protocol

from .io import read_json
from .media import duration_s, probe


class Transcriber(Protocol):
    name: str
    version: str

    def transcribe(self, media_path: Path) -> dict[str, Any]: ...


def _tokens(text: str) -> list[str]:
    return [item for item in re.findall(r"\S+", text.strip()) if item]


def normalize_transcript(payload: dict[str, Any], *, media_path: Path, provider: str, version: str) -> dict[str, Any]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("transcription payload must contain non-empty segments")
    words: list[dict[str, Any]] = []
    utterances: list[dict[str, Any]] = []
    last_end = 0.0
    for segment_index, segment in enumerate(raw_segments, 1):
        start = float(segment.get("start", segment.get("start_s", 0.0)))
        end = float(segment.get("end", segment.get("end_s", start)))
        text = str(segment.get("text", "")).strip()
        if start < last_end - 1e-6 or end <= start or not text:
            raise ValueError(f"invalid transcript segment {segment_index}")
        last_end = end
        raw_words = segment.get("words") or []
        if not raw_words:
            tokens = _tokens(text)
            step = (end - start) / max(len(tokens), 1)
            raw_words = [
                {"word": token, "start": start + index * step, "end": start + (index + 1) * step, "confidence": 1.0}
                for index, token in enumerate(tokens)
            ]
        word_ids = []
        for raw_word in raw_words:
            word_start = float(raw_word.get("start", raw_word.get("start_s", start)))
            word_end = float(raw_word.get("end", raw_word.get("end_s", word_start)))
            word_text = str(raw_word.get("word", raw_word.get("text", ""))).strip()
            if not __import__("math").isfinite(word_start) or not __import__("math").isfinite(word_end) or word_end < word_start - 0.1 or word_start < start - 0.75 or word_end > end + 0.75 or not word_text:
                raise ValueError(f"invalid word timing in transcript segment {segment_index}")
            word_start = max(start, min(word_start, end - 0.0001))
            word_end = min(end, max(word_end, word_start + 0.0001))
            word_id = f"w{len(words) + 1:06d}"
            word_ids.append(word_id)
            words.append({
                "id": word_id, "start_s": round(word_start, 6), "end_s": round(word_end, 6),
                "text": word_text, "confidence": float(raw_word.get("confidence", raw_word.get("probability", 1.0))),
            })
        utterances.append({
            "id": str(segment.get("id") or f"u{segment_index:04d}"),
            "start_s": start, "end_s": end, "text": text, "word_ids": word_ids,
            "decision": str(segment.get("decision", "keep")),
            "reason": segment.get("reason"), "take_group": segment.get("take_group"),
        })
    media_duration = payload.get("duration_s")
    if media_duration is None:
        media_duration = duration_s(probe(media_path))
    return {
        "schema_version": 1, "provider": provider, "provider_version": version,
        "language": payload.get("language", "unknown"), "media_path": str(media_path),
        "duration_s": float(media_duration), "words": words, "utterances": utterances,
    }


class SidecarTranscriber:
    name = "sidecar"
    version = "1"

    def sidecar_path(self, media_path: Path) -> Path:
        candidates = [
            media_path.with_suffix(media_path.suffix + ".transcript.json"),
            media_path.with_suffix(".transcript.json"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ValueError(f"transcript sidecar is missing for {media_path.name}")

    def transcribe(self, media_path: Path) -> dict[str, Any]:
        return normalize_transcript(
            read_json(self.sidecar_path(media_path)), media_path=media_path,
            provider=self.name, version=self.version,
        )


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(self, model: str = "small", language: str | None = None):
        self.model = model
        self.language = language
        self.version = model
        self._loaded_model = None

    def transcribe(self, media_path: Path) -> dict[str, Any]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper provider selected but the package is not installed") from exc
        if self._loaded_model is None:
            self._loaded_model = WhisperModel(self.model, device="cpu", compute_type="int8")
        segments, info = self._loaded_model.transcribe(str(media_path), language=self.language, word_timestamps=True, vad_filter=True)
        payload_segments = []
        for segment in segments:
            payload_segments.append({
                "start": segment.start, "end": segment.end, "text": segment.text,
                "words": [
                    {"start": word.start, "end": word.end, "word": word.word, "probability": word.probability}
                    for word in (segment.words or [])
                ],
            })
        return normalize_transcript(
            {"segments": payload_segments, "language": info.language, "duration_s": info.duration},
            media_path=media_path, provider=self.name, version=self.version,
        )



class CommandTranscriber:
    """Adapter for a configured local ASR executable that emits JSON to stdout."""
    name = "external-command"

    def __init__(self, command: list[str], version: str):
        if not command or not version:
            raise ValueError("external-command provider requires command and version")
        self.command = list(command)
        self.version = version

    def transcribe(self, media_path: Path) -> dict[str, Any]:
        result = subprocess.run([*self.command, str(media_path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise RuntimeError(f"external ASR failed ({result.returncode}): {result.stderr[-2000:]}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("external ASR returned invalid JSON") from exc
        return normalize_transcript(payload, media_path=media_path, provider=self.name, version=self.version)

def build_transcriber(config: dict[str, Any]) -> Transcriber:
    provider = config.get("provider", "sidecar")
    if provider == "sidecar":
        return SidecarTranscriber()
    if provider == "faster-whisper":
        return FasterWhisperTranscriber(config.get("model", "small"), config.get("language"))
    if provider == "external-command":
        return CommandTranscriber(config.get("command", []), str(config.get("version", "")))
    raise ValueError(f"unknown transcription provider: {provider}")
