"""Rev.ai как провайдер расшифровки: облачный ASR вместо локального Whisper.

Зачем. Весь монтаж стоит на словах и их временах: по ним режутся паузы, по ним
рисуются субтитры, по ним же самопроверка сверяет смонтированное с задуманным.
Ошибка распознавания здесь стоит дороже, чем в обычной расшифровке — она уезжает
в картинку. Rev.ai в рабочем контуре уже принят как самый точный (память
`reference_revai_access`), поэтому он же становится провайдером здесь.

Ключ берётся из окружения (`REVAI_TOKEN` / `REVAI_API_KEY`) или из `~/.env` —
отдельного секрета для этого проекта не заводим: ключ на сервер один.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .media import require_tool
from .providers import normalize_transcript

API_ROOT = "https://api.rev.ai/speechtotext/v1"
# Пауза между опросами: задание на трёхминутный ролик обычно готово за ~40 с,
# частый опрос смысла не имеет и только жжёт лимит запросов.
POLL_INTERVAL_S = 10.0
POLL_TIMEOUT_S = 1800.0
# Границы реплики: по паузе и по длине. Слишком длинная реплика делает редактуру
# грубой, слишком короткая рвёт фразу на стыке слов.
UTTERANCE_GAP_S = 0.6
UTTERANCE_MAX_S = 15.0


def load_token(env: dict[str, str] | None = None) -> str | None:
    source = dict(os.environ if env is None else env)
    for key in ("REVAI_TOKEN", "REVAI_API_KEY"):
        value = str(source.get(key) or "").strip()
        if value:
            return value
    dotenv = Path.home() / ".env"
    if not dotenv.is_file():
        return None
    for line in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
        name, _, raw = line.partition("=")
        if name.strip() in {"REVAI_TOKEN", "REVAI_API_KEY"}:
            value = raw.strip().strip("'\"")
            if value:
                return value
    return None


def _request(url: str, *, token: str, method: str = "GET", accept: str | None = None,
             body: bytes | None = None, content_type: str | None = None) -> bytes:
    request = urllib.request.Request(url, method=method, data=body)
    request.add_header("Authorization", f"Bearer {token}")
    if accept:
        request.add_header("Accept", accept)
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"rev.ai {method} {url} failed ({exc.code}): {detail}") from exc


def _extract_audio(media_path: Path, target: Path) -> Path:
    """Гнать в облако видео целиком незачем: наверх уходит только звук."""
    subprocess.run(
        [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(media_path),
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(target)],
        check=True,
    )
    return target


def _multipart(audio_path: Path, options: dict[str, Any]) -> tuple[bytes, str]:
    boundary = f"----revai{uuid.uuid4().hex}"
    parts: list[bytes] = []
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"options\"\r\n"
        f"Content-Type: application/json\r\n\r\n{json.dumps(options)}\r\n".encode("utf-8")
    )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"{audio_path.name}\"\r\n"
        f"Content-Type: audio/flac\r\n\r\n".encode("utf-8")
    )
    parts.append(audio_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _segments_from_monologues(monologues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for monologue in monologues:
        previous_end: float | None = None
        for element in monologue.get("elements") or []:
            if element.get("type") != "text":
                continue
            word = str(element.get("value") or "").strip()
            start = float(element.get("ts", 0.0))
            end = float(element.get("end_ts", start))
            if not word or end <= start:
                continue
            gap = start - previous_end if previous_end is not None else 0.0
            too_long = current is not None and end - float(current["start"]) > UTTERANCE_MAX_S
            if current is None or gap >= UTTERANCE_GAP_S or too_long:
                current = {"start": start, "end": end, "words": []}
                segments.append(current)
            current["end"] = end
            current["words"].append({"word": word, "start": start, "end": end,
                                     "confidence": float(element.get("confidence", 1.0))})
            previous_end = end
    prepared: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, 1):
        if not segment["words"]:
            continue
        prepared.append({
            "id": f"u{index:04d}",
            "start": segment["start"],
            "end": segment["end"],
            "text": " ".join(item["word"] for item in segment["words"]),
            "words": segment["words"],
        })
    if not prepared:
        raise ValueError("rev.ai returned no words")
    return prepared


class RevAiTranscriber:
    name = "rev.ai"

    def __init__(self, language: str | None = None, token: str | None = None,
                 poll_interval_s: float = POLL_INTERVAL_S, timeout_s: float = POLL_TIMEOUT_S):
        self.language = language
        self.version = "v1"
        self._token = token
        self.poll_interval_s = float(poll_interval_s)
        self.timeout_s = float(timeout_s)

    def _resolve_token(self) -> str:
        token = self._token or load_token()
        if not token:
            raise RuntimeError(
                "rev.ai provider selected but no key found: set REVAI_TOKEN in the environment or ~/.env"
            )
        return token

    def transcribe(self, media_path: Path) -> dict[str, Any]:
        token = self._resolve_token()
        with tempfile.TemporaryDirectory() as workspace:
            audio = _extract_audio(media_path, Path(workspace) / "audio.flac")
            options: dict[str, Any] = {"metadata": media_path.name, "skip_diarization": True}
            if self.language:
                options["language"] = self.language
            body, content_type = _multipart(audio, options)
            created = json.loads(_request(f"{API_ROOT}/jobs", token=token, method="POST",
                                          body=body, content_type=content_type))
        job_id = str(created["id"])
        deadline = time.monotonic() + self.timeout_s
        while True:
            status_payload = json.loads(_request(f"{API_ROOT}/jobs/{job_id}", token=token))
            status = str(status_payload.get("status"))
            if status == "transcribed":
                break
            if status == "failed":
                raise RuntimeError(f"rev.ai job {job_id} failed: {status_payload.get('failure_detail')}")
            if time.monotonic() > deadline:
                raise RuntimeError(f"rev.ai job {job_id} did not finish in {self.timeout_s:.0f}s")
            time.sleep(self.poll_interval_s)
        transcript = json.loads(_request(
            f"{API_ROOT}/jobs/{job_id}/transcript", token=token,
            accept="application/vnd.rev.transcript.v1.0+json",
        ))
        payload = {
            "segments": _segments_from_monologues(list(transcript.get("monologues") or [])),
            "language": self.language or "unknown",
        }
        return normalize_transcript(payload, media_path=media_path, provider=self.name, version=self.version)
