#!/usr/bin/env python3
"""Взять из каждой отобранной публикации ключевой абзац и подготовить его к листу.

Железное правило (brand/VOICE.md): абзац — фрагмент САМОЙ публикации, переведённый близко
к тексту. Ничего не добавлять по смыслу: детали, которой нет в источнике, не существует.
Поэтому модель получает текст статьи и работает только с ним, а не с заголовком.

Вход:  feed/cache/selected-<дата>.json
Выход: feed/digest/<дата>.json — готовые данные для render.py

Использование: python3 extract.py [дата]
"""
import argparse, html, json, pathlib, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from llm import ask_json, STRONG
from unwrap import unwrap
from net import fetch as net_fetch

ROOT = pathlib.Path(__file__).resolve().parent.parent
MSK = timezone(timedelta(hours=3))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'


def article_text(url: str, limit: int = 9000) -> str:
    raw = net_fetch(url, timeout=30)[0].decode('utf-8', 'ignore')
    raw = re.sub(r'<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>', ' ', raw, flags=re.S | re.I)
    paras = []
    for m in re.findall(r'<p[^>]*>(.*?)</p>', raw, re.S):
        s = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', m))).strip()
        if len(s) >= 90 and s.count('  ') < 4:
            paras.append(s)
    if not paras:  # страницы, где текст не в <p> (vc.ru и подобные)
        s = re.sub(r'<[^>]+>', '\n', raw)
        paras = [l.strip() for l in html.unescape(s).split('\n') if len(l.strip()) >= 90]
    return '\n\n'.join(paras)[:limit]


def key_paragraph(item: dict) -> dict | None:
    text = item.get('fulltext', '')
    if len(text) < 400:
        try:
            text = article_text(item['url'])
        except Exception as e:
            print(f'  не скачалось {item["url"]}: {e}', file=sys.stderr)
            return None
    if len(text) < 200:
        print(f'  пустой текст: {item["url"]}', file=sys.stderr)
        return None
    prompt = (
        'Ниже текст публикации. Твоя задача — подготовить карточку новости для ведущего, '
        'который прочитает её перед камерой.\n\n'
        'ЖЁСТКОЕ ПРАВИЛО: абзац составляется ТОЛЬКО из фактов, которые есть в этом тексте. '
        'Ничего не добавляй по смыслу, не обобщай, не делай выводов, не пиши, что это значит. '
        'Если факта нет в тексте — его нет вообще.\n\n'
        'Верни JSON: {"title": "...", "text": "...", "topic": "..."}\n'
        '- title: заголовок новости по-русски, до 70 знаков, без кликбейта.\n'
        '- topic: рубрика этой новости, два-три слова кириллицей, формат "Тема · Место" '
        'или просто "Тема". Только по этому тексту, не по чужим новостям.\n'
        '- text: 2-4 предложения по-русски — ключевой фрагмент публикации, переведённый близко '
        'к тексту. Внутри должна быть механика события: кто, что именно сделал, как это работает, '
        'конкретные числа и названия из текста.\n\n'
        f'Заголовок источника: {item["title"]}\n\nТЕКСТ ПУБЛИКАЦИИ:\n{text}')
    try:
        r = ask_json(prompt, model=STRONG, timeout=240)
    except Exception as e:
        print(f'  модель не справилась {item["url"]}: {e}', file=sys.stderr)
        return None
    host = re.sub(r'^www\.', '', urllib.request.urlparse(item['url']).netloc)
    if 'bbc.com' in host and '/russian/' in item['url']:
        host = 'bbc.com/russian'
    return {'topic': (r.get('topic') or item.get('topic') or item['category']).strip(),
            'title': r['title'].strip(),
            'text': r['text'].strip(), 'url': item['url'], 'source': host}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('date', nargs='?', default=datetime.now(MSK).strftime('%Y-%m-%d'))
    ap.add_argument('--tag', default='', help='суффикс имени файла, чтобы не затирать готовый лист дня')
    args = ap.parse_args()

    src = ROOT / 'feed/cache' / f'selected-{args.date}.json'
    data = json.loads(src.read_text(encoding='utf-8'))
    picked, take = data['items'], data.get('take', 10)

    # ссылки агрегатора ведут на страницу-переходник, статьи по ним не существует
    real = unwrap([it['url'] for it in picked])
    for it in picked:
        if it['url'] in real:
            it['url'] = real[it['url']]
    if real:
        print(f'развёрнуто ссылок агрегатора: {len(real)}')

    # Идём волнами: часть публикаций закрыта платной стеной или антиботом, поэтому недостачу
    # добираем из резерва, а не выпускаем короткий лист.
    cards, queue = [], list(picked)
    with ThreadPoolExecutor(max_workers=4) as pool:
        while queue and len(cards) < take:
            wave, queue = queue[:take - len(cards)], queue[take - len(cards):]
            cards.extend(c for c in pool.map(key_paragraph, wave) if c)
    cards = cards[:take]

    out = ROOT / 'feed/digest' / f'{args.date}{args.tag}.json'
    out.write_text(json.dumps({'date': args.date, 'items': cards}, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    print(f'{len(cards)} карточек из {take} нужных (в запасе было {len(picked) - take}) -> {out}')
    if len(cards) < take:
        print('часть публикаций не открылась или не разобралась — лист выйдет короче', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
