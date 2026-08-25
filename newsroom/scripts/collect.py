#!/usr/bin/env python3
"""Обойти реестр источников и собрать кандидатов за последние сутки.

Читает feed/feeds.txt (категория|название|url[|crm]); строки с полем crm тянутся через
российский сервер (ssh -n crm curl), иначе издание не отдаёт фид с нашего IP.
Пишет feed/cache/candidates-<дата>.json — сырой список без отбора.

Использование: python3 collect.py [--hours 30] [--out путь]
"""
import argparse, json, pathlib, re, sys, html, time
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from net import fetch as net_fetch, CRM, LOCAL
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
MSK = timezone(timedelta(hours=3))
UA = 'Mozilla/5.0 (compatible; brand-feed/1.0)'


def fetch(url: str, via: str | None) -> bytes:
    """Реестр задаёт предпочтительный выход, маршрутизатор пробует и второй."""
    body, _ = net_fetch(url, timeout=25, prefer=CRM if via == 'crm' else LOCAL)
    return body


# Часть изданий кладёт полный текст прямо в фид. Это ценнее веба: РБК, например,
# отдаёт на curl пустую страницу даже с российского адреса, а в фиде текст есть.
FULLTEXT_TAGS = ('encoded', 'full-text', 'fulltext', 'content')


def clean(s: str) -> str:
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))
    return re.sub(r'\s+', ' ', s).strip()


def when(node) -> datetime | None:
    for tag in ('pubDate', 'published', 'updated', 'date'):
        for c in node:
            if c.tag.split('}')[-1] == tag and c.text:
                try:
                    return parsedate_to_datetime(c.text.strip())
                except Exception:
                    try:
                        return datetime.fromisoformat(c.text.strip().replace('Z', '+00:00'))
                    except Exception:
                        pass
    return None


def parse(raw: bytes, cat: str, name: str, cutoff: datetime) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    items = []
    for node in root.iter():
        if node.tag.split('}')[-1] not in ('item', 'entry'):
            continue
        title = link = desc = full = ''
        for c in node:
            t = c.tag.split('}')[-1]
            if t == 'title' and not title:
                title = clean(c.text or '')
            elif t == 'link' and not link:
                link = (c.get('href') or c.text or '').strip()
            elif t in ('description', 'summary', 'content') and not desc:
                desc = clean(c.text or '')
            if t in FULLTEXT_TAGS and c.text and len(c.text) > len(full):
                full = clean(c.text)
        if not title or not link:
            continue
        ts = when(node)
        if ts and ts.astimezone(timezone.utc) < cutoff:
            continue
        # Google News клеит источник в хвост заголовка
        title = re.sub(r'\s+-\s+[^-]{2,40}$', '', title) if 'news.google.com' in link else title
        item = {'category': cat, 'feed': name, 'title': title,
                'url': link, 'summary': desc[:600],
                'published': ts.astimezone(MSK).isoformat() if ts else None}
        if len(full) > 400:
            item['fulltext'] = full[:5000]
        items.append(item)
    return items


def norm(t: str) -> str:
    return re.sub(r'[^a-zа-я0-9 ]', '', t.lower())[:70]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=30)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    feeds = []
    for line in (ROOT / 'feed/feeds.txt').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('|')
        feeds.append((parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else None))

    def one(f):
        cat, name, url, via = f
        try:
            time.sleep(0.2)
            return parse(fetch(url, via), cat, name, cutoff), name, None
        except Exception as e:
            return [], name, str(e)[:80]

    got, failed = [], []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for items, name, err in pool.map(one, feeds):
            if err:
                failed.append(f'{name}: {err}')
            got.extend(items)

    seen, uniq = set(), []
    for it in sorted(got, key=lambda x: x['published'] or '', reverse=True):
        key = norm(it['title'])
        if key in seen or it['url'] in seen:
            continue
        seen.add(key); seen.add(it['url'])
        uniq.append(it)

    date = datetime.now(MSK).strftime('%Y-%m-%d')
    out = pathlib.Path(args.out) if args.out else ROOT / 'feed/cache' / f'candidates-{date}.json'
    out.write_text(json.dumps({'date': date, 'hours': args.hours, 'failed': failed,
                               'items': uniq}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{len(uniq)} кандидатов из {len(feeds)} источников -> {out}')
    if failed:
        print('не ответили:', '; '.join(failed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
