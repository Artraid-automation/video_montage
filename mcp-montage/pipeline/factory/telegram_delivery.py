"""Telegram delivery: separate 1080x1920 document file; clean masters untouched."""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any
from urllib import error, request

from .artifacts import artifact_record
from .io import atomic_write_json, working_output
from .media import require_tool, run


DEFAULT_TG_WIDTH = 1080
DEFAULT_TG_HEIGHT = 1920
# Bot API hard limit ~50MB; keep headroom for upload overhead.
MAX_TG_UPLOAD_BYTES = 48 * 1024 * 1024


def build_telegram_filters(
    *,
    width: int = DEFAULT_TG_WIDTH,
    height: int = DEFAULT_TG_HEIGHT,
    speed_factor: float = 1.0,
) -> tuple[str, str | None]:
    """Return (video_filter, audio_filter_or_None) for TG delivery encode."""
    if width < 16 or height < 16:
        raise ValueError("telegram delivery size too small")
    if not 0.5 <= float(speed_factor) <= 2.0:
        raise ValueError(f"speed_factor out of range (0.5–2.0): {speed_factor}")
    parts = [
        f"scale={int(width)}:{int(height)}:flags=lanczos",
        "setsar=1",
        f"setdar={int(width)}/{int(height)}",
        "format=yuv420p",
    ]
    factor = float(speed_factor)
    af: str | None = None
    if abs(factor - 1.0) > 1e-6:
        # PTS/factor shortens timeline; atempo speeds audio to match.
        parts.append(f"setpts=PTS/{factor:.6g}")
        af = f"atempo={factor:.6g}"
    return ",".join(parts), af


def resolve_telegram_delivery_config(project_config: dict[str, Any]) -> dict[str, Any]:
    raw = dict(project_config.get("telegram_delivery") or {})
    grade = raw.get("grade") or project_config.get("default_grade") or "dankoe"
    enabled = bool(raw.get("enabled", True))
    return {
        "enabled": enabled,
        "width": int(raw.get("width", DEFAULT_TG_WIDTH)),
        "height": int(raw.get("height", DEFAULT_TG_HEIGHT)),
        "speed_factor": float(raw.get("speed_factor", 1.0)),
        "grade": str(grade),
        "send_as": str(raw.get("send_as", "document")),
        "crf": int(raw.get("crf", 23)),
        "preset": str(raw.get("preset", "veryfast")),
        "caption": raw.get("caption"),
    }


def load_telegram_credentials(env: dict[str, str] | None = None) -> dict[str, str] | None:
    source = env if env is not None else os.environ
    token = (source.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (source.get("TELEGRAM_ADMIN_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return None
    return {"bot_token": token, "chat_id": chat_id}


def load_dotenv_credentials(project_root: Path) -> dict[str, str] | None:
    """Load bot credentials from repo `.env` without printing secrets."""
    candidates = [
        project_root / ".env",
        project_root.parent / ".env",
        project_root.parent.parent / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        parsed: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            parsed[key.strip()] = value.strip().strip('"').strip("'")
        creds = load_telegram_credentials(parsed)
        if creds:
            return creds
    return load_telegram_credentials()


def encode_telegram_delivery(
    source: Path,
    output: Path,
    *,
    width: int = DEFAULT_TG_WIDTH,
    height: int = DEFAULT_TG_HEIGHT,
    speed_factor: float = 1.0,
    crf: int = 23,
    preset: str = "veryfast",
) -> Path:
    """Encode a TG-only derivative; does not modify `source`."""
    vf, af = build_telegram_filters(width=width, height=height, speed_factor=speed_factor)
    output.parent.mkdir(parents=True, exist_ok=True)
    with working_output(output) as temporary:
        command = [
            require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-preset", preset, "-crf", str(crf),
        ]
        if af:
            command.extend(["-af", af, "-c:a", "aac", "-b:a", "160k"])
        else:
            command.extend(["-c:a", "aac", "-b:a", "160k"])
        command.extend(["-movflags", "+faststart", str(temporary)])
        run(command)
        # If still over Bot API limit, one tighter CRF pass into the same temp.
        if temporary.stat().st_size > MAX_TG_UPLOAD_BYTES:
            tighter = temporary.with_suffix(".tight.mp4")
            run([
                require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(temporary),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
                "-preset", preset, "-crf", str(min(crf + 4, 28)),
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(tighter),
            ])
            temporary.unlink(missing_ok=True)
            tighter.replace(temporary)
    return output


def _multipart_body(
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
) -> tuple[bytes, str]:
    boundary = f"----cursorbot{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        chunks.append(f"{value}\r\n".encode())
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
    )
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def send_telegram_document(
    path: Path,
    *,
    bot_token: str,
    chat_id: str,
    caption: str | None = None,
) -> dict[str, Any]:
    """Upload as document so Telegram does not recompress (iPhone-safe)."""
    if not path.is_file():
        raise FileNotFoundError(path)
    fields = {"chat_id": str(chat_id)}
    if caption:
        fields["caption"] = caption[:1024]
    body, content_type = _multipart_body(fields, "document", path)
    req = request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendDocument",
        data=body,
        method="POST",
        headers={"Content-Type": content_type},
    )
    try:
        with request.urlopen(req, timeout=600) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"telegram sendDocument failed ({exc.code}): {detail}") from exc
    if not payload.get("ok"):
        raise RuntimeError(f"telegram sendDocument rejected: {payload}")
    return {
        "ok": True,
        "message_id": payload.get("result", {}).get("message_id"),
        "raw": payload,
    }


def deliver_telegram_master(
    project_root: Path,
    *,
    source_master: Path,
    config: dict[str, Any],
    grade_name: str,
    credentials: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build TG-only 1080x1920 file (optional speed) from a clean grade master.
    Clean masters stay untouched. Send as document when credentials exist.
    """
    cfg = resolve_telegram_delivery_config(config)
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "telegram-delivery",
        "worker_version": "telegram-delivery-v1",
        "enabled": cfg["enabled"],
        "grade": grade_name,
        "width": cfg["width"],
        "height": cfg["height"],
        "speed_factor": cfg["speed_factor"],
        "send_as": cfg["send_as"],
        "source_path": str(source_master.relative_to(project_root)).replace("\\", "/"),
    }
    if not cfg["enabled"]:
        report["verdict"] = "SKIPPED"
        report["reason"] = "telegram_delivery.enabled=false"
        return report

    delivery_root = project_root / "05_final" / "delivery"
    speed_tag = (
        f"-x{cfg['speed_factor']:g}".replace(".", "p")
        if abs(cfg["speed_factor"] - 1.0) > 1e-6
        else ""
    )
    out_name = f"tg-{grade_name}-{cfg['width']}x{cfg['height']}{speed_tag}.mp4"
    output = delivery_root / out_name
    encode_telegram_delivery(
        source_master,
        output,
        width=cfg["width"],
        height=cfg["height"],
        speed_factor=cfg["speed_factor"],
        crf=cfg["crf"],
        preset=cfg["preset"],
    )
    record = artifact_record(project_root, output, kind="telegram-delivery")
    report["artifact"] = record
    report["size_bytes"] = record["size_bytes"]

    creds = credentials if credentials is not None else load_dotenv_credentials(project_root)
    if not creds:
        report["verdict"] = "ENCODED"
        report["send"] = {"status": "SKIPPED", "reason": "no TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID"}
        return report

    if cfg["send_as"] != "document":
        report["verdict"] = "ENCODED"
        report["send"] = {"status": "SKIPPED", "reason": f"unsupported send_as={cfg['send_as']}"}
        return report

    caption = cfg.get("caption") or (
        f"{config.get('title', project_root.name)} · {grade_name} · "
        f"{cfg['width']}x{cfg['height']}"
        + (f" · ×{cfg['speed_factor']:g}" if abs(cfg["speed_factor"] - 1.0) > 1e-6 else "")
        + " · document"
    )
    try:
        sent = send_telegram_document(
            output,
            bot_token=creds["bot_token"],
            chat_id=creds["chat_id"],
            caption=caption,
        )
        report["verdict"] = "SENT"
        report["send"] = {"status": "OK", "message_id": sent.get("message_id")}
    except Exception as exc:  # noqa: BLE001 — soft-fail delivery; Final Review still valid
        report["verdict"] = "ENCODED"
        report["send"] = {"status": "FAILED", "error": str(exc)[:500]}
    return report


def write_telegram_delivery_report(project_root: Path, report: dict[str, Any]) -> Path:
    path = project_root / "05_final" / "delivery" / "telegram-delivery.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, report)
    return path
