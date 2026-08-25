#!/usr/bin/env python3
"""Забор страниц через два выхода в интернет: этот сервер и российский `crm`.

Издания режут доступ по географии в обе стороны: РБК и Forbes.ru не отвечают отсюда,
Reddit отдаёт 403 отсюда, но 200 с `crm`. Поэтому адрес пробуется по обоим маршрутам,
начиная с того, который для его домена вероятнее. Если закрыто с обоих (Bloomberg —
антибот, а не гео), поднимается последняя ошибка.
"""
import re, subprocess, urllib.error, urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120 Safari/537.36')
RU_ZONES = ('.ru', '.рф', '.su', '.by', '.kz', '.xn--p1ai')
LOCAL, CRM = 'local', 'crm'


def routes(url: str, prefer: str | None = None) -> list[str]:
    """Порядок маршрутов: сначала тот, где адрес вероятнее откроется."""
    if prefer:
        return [prefer, CRM if prefer == LOCAL else LOCAL]
    host = (urllib.request.urlparse(url).netloc or '').lower().split(':')[0]
    return [CRM, LOCAL] if host.endswith(RU_ZONES) else [LOCAL, CRM]


def _local(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def _crm(url: str, timeout: int) -> bytes:
    # -n обязателен: без него ssh съедает stdin вызывающего цикла
    r = subprocess.run(['ssh', '-n', 'crm',
                        f"curl -sL --max-time {timeout} -A '{UA}' -w '\\n%{{http_code}}' '{url}'"],
                       capture_output=True, timeout=timeout + 25)
    body = r.stdout
    code = body.rsplit(b'\n', 1)[-1].decode(errors='ignore').strip()
    if code != '200':
        raise urllib.error.HTTPError(url, int(code or 0), f'crm вернул {code}', None, None)
    return body.rsplit(b'\n', 1)[0]


def fetch(url: str, *, timeout: int = 25, prefer: str | None = None) -> tuple[bytes, str]:
    """Вернуть (содержимое, маршрут). Пробует оба выхода, прежде чем сдаться."""
    last = None
    for route in routes(url, prefer):
        try:
            body = (_local if route == LOCAL else _crm)(url, timeout)
            if body and len(body) > 200:
                return body, route
            last = ValueError(f'{route}: пустой ответ')
        except Exception as e:
            last = e
    raise last if last else RuntimeError('маршруты не отработали')
