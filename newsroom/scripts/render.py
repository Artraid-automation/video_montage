#!/usr/bin/env python3
"""Собрать эфирный лист (HTML + самодостаточную версию для телефона) из данных дня.

Вход:  feed/digest/<дата>.json  {"date":"YYYY-MM-DD","items":[{topic,title,text,url,source}]}
Выход: feed/digest/<дата>.html            — фрагмент под публикацию артефактом
       feed/digest/<дата>-эфирный-лист.html — самодостаточный файл (doctype/charset/viewport)

Использование: python3 render.py 2026-08-23   (или без аргумента — сегодня по МСК)
"""
import json, pathlib, sys, html
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
MSK = timezone(timedelta(hours=3))
DAYS = ['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье']
MONTHS = ['января','февраля','марта','апреля','мая','июня','июля','августа',
          'сентября','октября','ноября','декабря']

ITEM = """    <article>
      <div class="meta"><button class="num" aria-label="Свернуть или развернуть новость">{num}</button><span class="topic">{topic}</span></div>
      <h2>{title}</h2>
      <p class="body">{text}</p>
      <a class="src" href="{url}" target="_blank" rel="noopener noreferrer">{source}</a>
    </article>"""


def build(date_iso: str, tag: str = '') -> tuple[pathlib.Path, pathlib.Path]:
    data = json.loads((ROOT / 'feed/digest' / f'{date_iso}{tag}.json').read_text(encoding='utf-8'))
    items = data['items']
    d = datetime.strptime(date_iso, '%Y-%m-%d')
    blocks = '\n\n'.join(
        ITEM.format(num=f'{i:02d}', topic=html.escape(it['topic']), title=html.escape(it['title']),
                    text=it['text'], url=html.escape(it['url'], quote=True),
                    source=html.escape(it['source']))
        for i, it in enumerate(items, 1))
    page = (ROOT / 'scripts/template.html').read_text(encoding='utf-8')
    for k, v in {
        '{{DATE_TITLE}}': f'{d.day} {MONTHS[d.month - 1]}',
        '{{DATE_HUMAN}}': f'{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}',
        '{{DATE_SHORT}}': d.strftime('%d.%m.%Y'),
        '{{DATE_ISO}}': date_iso,
        '{{COUNT}}': str(len(items)),
        '{{ITEMS}}': blocks,
    }.items():
        page = page.replace(k, v)

    frag = ROOT / 'feed/digest' / f'{date_iso}{tag}.html'
    frag.write_text(page, encoding='utf-8')

    i = page.index('<div class="wrap">')
    standalone = ('<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
                  '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                  '<meta name="color-scheme" content="light dark">\n'
                  f'{page[:i]}</head>\n<body>\n{page[i:]}</body>\n</html>\n')
    phone = ROOT / 'feed/digest' / f'{date_iso}{tag}-эфирный-лист.html'
    phone.write_text(standalone, encoding='utf-8')
    return frag, phone


if __name__ == '__main__':
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(MSK).strftime('%Y-%m-%d')
    tag = sys.argv[2] if len(sys.argv) > 2 else ''
    for p in build(date, tag):
        print(p)
