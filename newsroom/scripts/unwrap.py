#!/usr/bin/env python3
"""Развернуть ссылку Google News в адрес оригинальной публикации.

Google отдаёт не редирект, а страницу с JS-переходом, и адрес внутри зашифрован — ни curl,
ни декодирование base64 его не достают. Единственный надёжный способ — открыть браузером
и посмотреть, куда он ушёл. Разворачиваются только отобранные ссылки (десяток за прогон),
а не весь поток.
"""
import sys


def unwrap(urls: list[str], timeout_ms: int = 20000) -> dict[str, str]:
    google = [u for u in urls if 'news.google.com' in u]
    if not google:
        return {}
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        for u in google:
            try:
                pg.goto(u, wait_until='domcontentloaded', timeout=timeout_ms)
                for _ in range(20):
                    if 'news.google.com' not in pg.url:
                        break
                    pg.wait_for_timeout(400)
                if 'news.google.com' not in pg.url and pg.url.startswith('http'):
                    out[u] = pg.url
                else:
                    print(f'  не развернулась: {u[:60]}...', file=sys.stderr)
            except Exception as e:
                print(f'  ошибка разворота: {str(e)[:80]}', file=sys.stderr)
        b.close()
    return out


if __name__ == '__main__':
    for src, dst in unwrap(sys.argv[1:]).items():
        print(dst)
