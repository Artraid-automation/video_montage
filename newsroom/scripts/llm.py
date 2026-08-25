#!/usr/bin/env python3
"""Единая точка вызова модели для тракта дайджеста.

Изоляция обязательна: без --setting-sources '' вызов наследует CLAUDE.md, хуки и скиллы
штаба — это чужой контекст и лишний расход. Модель выбирается по cost-curve:
FAST (haiku) — массовая сортировка заголовков, STRONG (sonnet) — отбор и перевод абзацев.
"""
import json, os, re, shutil, subprocess, pathlib

# Крон запускает скрипт не через login-shell: в его PATH нет ~/.local/bin, где лежит claude.
# Без абсолютного пути утренний прогон падал бы на отборе каждый день, молча.
CLAUDE = (os.environ.get('CLAUDE_BIN') or shutil.which('claude')
          or str(pathlib.Path.home() / '.local/bin/claude'))

FAST = 'claude-haiku-4-5-20251001'
STRONG = 'claude-sonnet-5'
NEUTRAL = pathlib.Path('/tmp/brand-llm')


def ask(prompt: str, *, model: str = FAST, timeout: int = 180, system: str = '') -> str:
    NEUTRAL.mkdir(parents=True, exist_ok=True)
    argv = [CLAUDE, '--print', '--setting-sources', '', '--strict-mcp-config',
            '--allowedTools', '', '--permission-mode', 'manual', '--model', model]
    if system:
        argv += ['--append-system-prompt', system]
    r = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                       timeout=timeout, cwd=NEUTRAL)
    if r.returncode != 0:
        raise RuntimeError(f'claude rc={r.returncode}: {r.stderr[:300]}')
    return r.stdout.strip()


SCHEMA_GUARD = ('Отвечай ТОЛЬКО валидным JSON по запрошенной схеме, без пояснений. '
                'Внутри строк не используй переводы строк и неэкранированные кавычки.')


def ask_json(prompt: str, *, tries: int = 2, **kw):
    """Тот же вызов, но ответ разбирается как JSON.

    Ретрай не роскошь: длинный ответ модель иногда обрывает на середине строки, и одна
    сорванная карточка выкидывает новость из листа целиком.
    """
    last = None
    for n in range(tries):
        raw = ask(prompt, system=SCHEMA_GUARD, **kw)
        m = re.search(r'```(?:json)?\s*(.*?)```', raw, re.S)
        if m:
            raw = m.group(1).strip()
        start = min([i for i in (raw.find('['), raw.find('{')) if i != -1], default=0)
        body = raw[start:]
        for candidate in (body, _mend(body)):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                last = e
    raise last


def _mend(s: str) -> str:
    """Склеить переводы строк внутри значений: модель их вставляет, JSON их не допускает."""
    out, in_str, esc = [], False, False
    for ch in s:
        if esc:
            out.append(ch); esc = False; continue
        if ch == '\\':
            out.append(ch); esc = True; continue
        if ch == '"':
            in_str = not in_str
        if in_str and ch in '\n\r':
            out.append(' '); continue
        out.append(ch)
    return ''.join(out)
