#!/usr/bin/env python3
"""Обернуть артефактный фрагмент дайджеста в самодостаточный HTML для телефона.
Использование: python3 standalone.py feed/digest/2026-08-23.html
Без doctype/charset/viewport файл, открытый напрямую с телефона, даёт мелкий текст и кракозябры."""
import sys, pathlib, re
src = pathlib.Path(sys.argv[1])
t = src.read_text(encoding='utf-8')
i = t.index('<div class="wrap">')
title = re.search(r'<title>(.*?)</title>', t)
out = ('<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
       '<meta name="color-scheme" content="light dark">\n'
       f'{t[:i]}</head>\n<body>\n{t[i:]}</body>\n</html>\n')
name = (title.group(1) if title else src.stem).replace(' ', '-').lower()
dst = src.with_name(f'{src.stem}-{name}.html')
dst.write_text(out, encoding='utf-8')
print(dst)
