"""Монтажный стол — страница, где сценарий правят пословно и заказывают пересборку.

Живёт на сервере рядом с Artraid AI и отдаётся по адресу /montage/<id>. Формы входа
нет намеренно: секрет — сам адрес, поэтому идентификатор длинный и случайный.

Служба держит только две вещи: сценарии (что показать) и правки (что человек решил).
Пересборку она не запускает — задание забирает сторож на машине фабрики. Так сервер
с сайтом не знает ни про ключи, ни про монтаж, и падение фабрики не роняет страницу.
"""

from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
EDITS_DIR = ROOT / "edits"
TEMPLATE_PATH = ROOT / "page.html"
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{6,80}$")
MAX_BODY_BYTES = 2 * 1024 * 1024


def _load_script(desk_id: str) -> dict[str, Any] | None:
    path = SCRIPTS_DIR / f"{desk_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _render_page(payload: dict[str, Any]) -> bytes:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    # Данные уезжают в страницу одним JSON-блоком: разметку рисует браузер, иначе
    # двести слов пришлось бы клеить строками на сервере при каждом открытии.
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("__DESK_DATA__", data).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "MontageDesk"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 — подпись из stdlib
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Страница со сценарием не должна попадать в поиск: секрет — сам адрес.
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 — подпись из stdlib
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in {"/montage/health", "/health"}:
            self._json(200, {"status": "ok", "scripts": len(list(SCRIPTS_DIR.glob("*.json")))})
            return
        match = re.fullmatch(r"/montage/([^/]+)", path)
        if not match:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        desk_id = match.group(1)
        if not ID_RE.fullmatch(desk_id):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        payload = _load_script(desk_id)
        if payload is None:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        saved = EDITS_DIR / f"{desk_id}.draft.json"
        if saved.is_file():
            # Черновик правок живёт на сервере, а не только в браузере: человек
            # начинает на телефоне и дочитывает с компьютера.
            payload = {**payload, "draft": json.loads(saved.read_text(encoding="utf-8"))}
        self._send(200, _render_page(payload), "text/html; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802 — подпись из stdlib
        path = self.path.split("?", 1)[0].rstrip("/")
        match = re.fullmatch(r"/montage/([^/]+)/(draft|submit)", path)
        if not match:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        desk_id, action = match.group(1), match.group(2)
        if not ID_RE.fullmatch(desk_id) or _load_script(desk_id) is None:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(400, {"error": "bad length"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "bad json"})
            return
        record = {
            "desk_id": desk_id,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "cut_words": [int(index) for index in body.get("cut_words") or [] if str(index).lstrip("-").isdigit()],
            # Исправления распознанных слов: слово остаётся в ролике, меняется только
            # его написание в субтитре. Поэтому это отдельный словарь, а не рез.
            "rewrites": {
                str(int(index)): str(value)[:120]
                for index, value in (body.get("rewrites") or {}).items()
                if str(index).lstrip("-").isdigit() and str(value).strip()
            },
            "note": str(body.get("note") or "")[:8000],
        }
        EDITS_DIR.mkdir(parents=True, exist_ok=True)
        if action == "draft":
            (EDITS_DIR / f"{desk_id}.draft.json").write_text(
                json.dumps(record, ensure_ascii=False), encoding="utf-8",
            )
            self._json(200, {"status": "saved"})
            return
        # Задание для фабрики: имя со временем, чтобы сторож забирал по одному и
        # ничего не терял, если правок пришло несколько подряд.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (EDITS_DIR / f"{desk_id}.{stamp}.submit.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        self._json(200, {"status": "accepted", "cut_words": len(record["cut_words"])})


def main() -> None:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    EDITS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 3320), Handler)
    print("montage desk on 127.0.0.1:3320", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
