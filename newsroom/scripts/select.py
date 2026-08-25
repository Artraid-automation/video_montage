#!/usr/bin/env python3
"""Отобрать из кандидатов десятку для эфирного листа.

Три ступени по cost-curve:
  1. Python ($0)  — снять заведомый мусор: пресс-релизы, служебные ленты, обрубки.
  2. haiku        — грубый скоринг заголовков пачками (0-3) по правилам голоса и вкуса.
  3. sonnet       — финальный отбор десятки с балансом рубрик из лучших по скору.

Правила отбора берутся из brand/VOICE.md и feed/TASTE.md — калибровка вкуса
влияет на автоматику сразу, без правки кода.

Использование: python3 select.py [дата] [--take 10]
"""
import argparse, json, pathlib, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from llm import ask_json, FAST, STRONG

ROOT = pathlib.Path(__file__).resolve().parent.parent
MSK = timezone(timedelta(hours=3))

# Пресс-релизные ленты и корпоративный шум: отсекаются без модели
JUNK = re.compile(r'подвел[аи]? (финансовые )?итоги|подвёл итоги|запустил[аи]? 4G|'
                  r'стали чаще (искать|покупать)|партнерск\w+ фулфилмент|вебинар|'
                  r'назначен\w* (на пост|директором)|открыл[аи]? офис|'
                  r'приглашает|стартовал приём заявок|дарит|скидк', re.I)
JUNK_URL = re.compile(r'cnews\.ru/news/line/|/promo/|/reklama/')


def prefilter(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        if len(it['title']) < 25:
            continue
        if JUNK.search(it['title']) or JUNK_URL.search(it['url']):
            continue
        out.append(it)
    return out


def rules() -> str:
    voice = (ROOT / 'brand/VOICE.md').read_text(encoding='utf-8')
    taste = (ROOT / 'feed/TASTE.md').read_text(encoding='utf-8')
    return f'--- ГОЛОС ---\n{voice}\n--- КАЛИБРОВКА ВКУСА ---\n{taste}'


def score(items: list[dict], batch: int = 50, workers: int = 5) -> list[dict]:
    """Пачки идут параллельно: последовательно 12 пачек — это минуты ожидания на пустом месте."""
    rl = rules()
    chunks = [items[i:i + batch] for i in range(0, len(items), batch)]

    def one(pair):
        i, chunk = pair
        lines = '\n'.join(f'{n}. [{it["category"]}] {it["title"]}' for n, it in enumerate(chunk))
        prompt = (
            f'{rl}\n\n'
            'Ниже заголовки новостей. Оцени КАЖДЫЙ по пригодности для утреннего видеоролика, '
            'где ведущий рассказывает новость широкой русскоязычной аудитории и высказывает мнение.\n'
            '3 — внутри новости видна механика: кто, что именно сделал, как работает; есть конкретный факт или цифра.\n'
            '2 — значимое событие, о котором есть что сказать.\n'
            '1 — понятно, но говорить особо не о чем.\n'
            '0 — мусор: статистика продаж без события, корпоративные новости, узкотехническое, '
            'обновление версии, локальная сводка.\n\n'
            f'{lines}\n\n'
            'Верни JSON-массив вида [{"n":0,"s":2,"case":true},...] по одному объекту на каждый '
            'заголовок. case=true только если это живой кейс применения ИИ на конкретном '
            'предприятии или у конкретного человека (видно, кто и что именно внедрил).')
        try:
            for r in ask_json(prompt, model=FAST, timeout=240):
                k = int(r['n'])
                if 0 <= k < len(chunk):
                    chunk[k]['score'] = int(r['s'])
                    chunk[k]['case'] = bool(r.get('case'))
        except Exception as e:
            print(f'  скоринг пачки {i}: {e}', file=sys.stderr)
        return chunk

    scored = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in pool.map(one, enumerate(chunks)):
            scored.extend(chunk)
    return scored


def finalize(top: list[dict], take: int) -> list[dict]:
    lines = '\n'.join(
        f'{n}. [{it["category"]} | {it["feed"]}] {it["title"]}\n   {it.get("summary","")[:220]}'
        for n, it in enumerate(top))
    prompt = (
        f'{rules()}\n\n'
        f'Ниже {len(top)} лучших новостей дня. Выбери {take} штук: первые — основной выпуск, '
        'последние идут в запас на случай, если публикация не откроется.\n'
        'Требования к подборке:\n'
        f'- ГЛАВНОЕ: не меньше {max(3, take // 3)} новостей должны быть ЖИВЫМИ КЕЙСАМИ применения ИИ — '
        'названо конкретное предприятие или человек, названо, что именно внедрили, видно, как это '
        'работает и что изменилось. Анонсы моделей, раунды инвестиций и рассуждения о будущем ИИ '
        'кейсами НЕ являются. Если подходящих кейсов в списке меньше — добери столько, сколько есть, '
        'и не подменяй их обычными новостями про ИИ.\n'
        f'- ПОТОЛОК: не больше {take // 2 + 1} новостей про ИИ во всём выпуске, считая кейсы. '
        'Лист целиком про ИИ — это провал выпуска, зрителю нужен воздух.\n'
        '- Остальное обязательно: наука, общество, деньги, что-то человеческое или культурное.\n'
        '- Каждая должна объясняться одним предложением и давать повод высказаться.\n'
        '- Никаких дублей одного события.\n'
        '- Первой ставь самую живую и конкретную, последней — ту, что оставляет хорошее послевкусие.\n\n'
        f'{lines}\n\n'
        'Верни JSON-массив в порядке выпуска: [{"n":12,"topic":"ИИ · Китай"},...]. '
        'topic — рубрика ИМЕННО ЭТОЙ новости под её номером n, из двух-трёх слов, '
        'в формате "Тема · Место" или просто "Тема", кириллицей. Сверь каждую рубрику '
        'с заголовком под тем же номером: рубрика от чужой новости ломает выпуск.')
    picked = ask_json(prompt, model=STRONG, timeout=300)
    out = []
    for r in picked[:take]:
        it = dict(top[int(r['n'])])
        it['topic'] = r.get('topic', it['category'])
        out.append(it)
    return out


AI_WORDS = re.compile(r'\bии\b|\bai\b|нейросет|искусственн\w+ интеллект|llm|gpt|chatgpt|'
                      r'claude|нейронн\w+ сет|машинн\w+ обучен|ml[- ]', re.I)


def is_ai(item: dict) -> bool:
    return bool(item.get('case')) or bool(AI_WORDS.search(item['title'] + ' ' + item.get('topic', '')))


def balance(picked: list[dict], take: int, ceiling: int) -> list[dict]:
    """Развести выпуск по темам.

    Модель соблюдает потолок доли ИИ нестрого, а лист целиком про ИИ — провал выпуска:
    зрителю нужен воздух. Поэтому лишние ИИ-новости уходят в хвост, их места занимают
    другие темы, а сам порядок внутри групп сохраняется.
    """
    main, tail, ai = [], [], 0
    for it in picked:
        if is_ai(it):
            if ai < ceiling and len(main) < take:
                main.append(it); ai += 1
            else:
                tail.append(it)
        elif len(main) < take:
            main.append(it)
        else:
            tail.append(it)
    # недобор (в потоке просто не было других тем) закрываем отложенными
    while len(main) < take and tail:
        main.append(tail.pop(0))
    return main + tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('date', nargs='?', default=datetime.now(MSK).strftime('%Y-%m-%d'))
    ap.add_argument('--take', type=int, default=10)
    ap.add_argument('--reserve', type=int, default=6,
                    help='запас на добор: платные стены и антиботы съедают часть публикаций')
    ap.add_argument('--pool', type=int, default=40, help='сколько лучших уходит на финальный отбор')
    args = ap.parse_args()

    src = ROOT / 'feed/cache' / f'candidates-{args.date}.json'
    items = json.loads(src.read_text(encoding='utf-8'))['items']
    kept = prefilter(items)
    print(f'{len(items)} кандидатов -> {len(kept)} после фильтра мусора')

    scored = score(kept)
    # Пул собирается ДВУМЯ корзинами. Если просто поднять кейсы наверх, финал состоит
    # из одних кейсов, и разнообразию взяться неоткуда — выпуск выходит целиком про ИИ.
    rank = lambda x: (-x.get('score', 0), x.get('published') or '')
    cases = sorted([i for i in scored if i.get('case')], key=rank)
    rest = sorted([i for i in scored if not i.get('case')], key=rank)
    quota = args.pool * 3 // 5
    top = cases[:quota] + rest[:args.pool - quota]
    print(f'скоринг: {sum(1 for i in scored if i.get("score",0)>=3)} по 3 балла, '
          f'{sum(1 for i in scored if i.get("score",0)==2)} по 2, '
          f'{sum(1 for i in scored if i.get("case"))} живых кейсов ИИ; на финал ушло {len(top)} '
          f'({sum(1 for i in top if i.get("case"))} кейсов + '
          f'{sum(1 for i in top if not i.get("case"))} прочих)')

    picked = balance(finalize(top, args.take + args.reserve), args.take,
                     args.take // 2 + 1)
    out = ROOT / 'feed/cache' / f'selected-{args.date}.json'
    out.write_text(json.dumps({'date': args.date, 'take': args.take, 'items': picked},
                              ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'в выпуске про ИИ: {sum(1 for i in picked[:args.take] if is_ai(i))} из {args.take}')
    for n, it in enumerate(picked, 1):
        mark = f'{n:02d}' if n <= args.take else ' r'
        print(f'{mark} [{it["topic"]}] {it["title"][:80]}')
    print('->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
