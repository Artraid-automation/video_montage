"""Сценарий на утверждение — читаемая страница вместо служебного transcript.md.

Заказчик утверждает текст ДО монтажа: читает сплошную речь, разворачивает то, что
редактор предложил вырезать, и возвращает нужное обратно. Поэтому страница — не
отчёт о работе машины, а рабочий документ: сверху то, что останется в ролике,
рядом причина каждого реза, внизу — список правок, который можно скопировать и
прислать одним сообщением.
"""

from __future__ import annotations

import html
from typing import Any

from .transcript import TranscriptEntry, format_timecode

CUT_REASON_LABELS = {
    "оговорка": "сбился и переговорил заново",
    "дубль": "та же мысль сказана ещё раз",
    "команда": "команда себе или монтажёру",
    "обрубок": "фраза оборвана",
    "не по теме": "выпадает из рассказа",
}


def _stats(entries: list[TranscriptEntry]) -> dict[str, Any]:
    keeps = [item for item in entries if item.kind == "keep"]
    cuts = [item for item in entries if item.kind == "cut"]
    kept_s = sum(float(item.end_s) - float(item.start_s) for item in keeps)
    cut_s = sum(float(item.end_s) - float(item.start_s) for item in cuts)
    return {
        "keep_count": len(keeps),
        "cut_count": len(cuts),
        "kept_s": kept_s,
        "cut_s": cut_s,
        "words": sum(len(item.text.split()) for item in keeps),
    }


def _duration(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _blocks_html(entries: list[TranscriptEntry]) -> str:
    parts: list[str] = []
    for entry in entries:
        timecode = format_timecode(float(entry.start_s))
        text = html.escape(entry.text)
        anchor = html.escape(entry.id)
        if entry.kind == "keep":
            parts.append(
                f'<article class="block" data-id="{anchor}" data-kind="keep">'
                f'<span class="tc">{timecode}</span>'
                f'<p class="speech">{text}</p>'
                f'<button class="flip" type="button">вырезать</button>'
                f"</article>"
            )
            continue
        reason = str(entry.reason or "мусор")
        explain = CUT_REASON_LABELS.get(reason, reason)
        parts.append(
            f'<article class="block" data-id="{anchor}" data-kind="cut">'
            f'<span class="tc">{timecode}</span>'
            f'<div class="cutbody">'
            f'<button class="reveal" type="button" aria-expanded="false">'
            f'<span class="tag">{html.escape(reason)}</span>'
            f'<span class="hint">{html.escape(explain)}</span>'
            f"</button>"
            f'<p class="speech struck" hidden>{text}</p>'
            f"</div>"
            f'<button class="flip" type="button">вернуть</button>'
            f"</article>"
        )
    return "\n".join(parts)


def build_script_page(
    entries: list[TranscriptEntry],
    *,
    title: str,
    summary: str | None = None,
    risks: list[str] | None = None,
    source_duration_s: float | None = None,
) -> str:
    stats = _stats(entries)
    # «Снято» — длина исходника, а не сумма реплик: между репликами есть тишина,
    # которая ни в один блок не попала, и сумма блоков занижает хронометраж.
    source_s = float(source_duration_s) if source_duration_s else stats["kept_s"] + stats["cut_s"]
    risk_items = "".join(f"<li>{html.escape(item)}</li>" for item in (risks or []))
    risk_block = (
        '<section class="aside"><h2>Редактор просит перепроверить</h2>'
        f"<ul>{risk_items}</ul></section>" if risk_items else ""
    )
    summary_block = (
        '<section class="aside"><h2>О чём получился рассказ</h2>'
        f"<p>{html.escape(summary)}</p></section>" if summary else ""
    )
    return PAGE_TEMPLATE.format(
        title=html.escape(title),
        kept=_duration(stats["kept_s"]),
        source=_duration(source_s),
        cut_count=stats["cut_count"],
        keep_count=stats["keep_count"],
        words=stats["words"],
        summary_block=summary_block,
        risk_block=risk_block,
        blocks=_blocks_html(entries),
    )


# Страница уходит человеку файлом, а не ссылкой, поэтому документ обязан быть
# самодостаточным: со своей кодировкой и обнулением полей. Без явного charset
# кириллица при открытии файла с диска зависит от догадки браузера.
PAGE_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Literata:opsz,wght@7..72,400;7..72,600&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  * {{ box-sizing: border-box; }}
  html {{ color-scheme: light dark; }}
  body {{ margin: 0; }}
  img {{ max-width: 100%; }}
  [hidden] {{ display: none !important; }}
  :root {{
    --paper: #FAFAF7;
    --card: #FFFFFF;
    --ink: #16191D;
    --ink-soft: #5C6470;
    --rule: #E3E4DF;
    --keep: #1F6F5C;
    --cut: #A34A34;
    --cut-soft: #F3EAE6;
    --shadow: 0 1px 2px rgba(22, 25, 29, .06);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --paper: #14161A;
      --card: #1B1E23;
      --ink: #E7E8E4;
      --ink-soft: #99A0AB;
      --rule: #2A2E35;
      --keep: #5FBFA5;
      --cut: #E08D72;
      --cut-soft: #24211F;
      --shadow: 0 1px 2px rgba(0, 0, 0, .45);
    }}
  }}
  :root[data-theme="dark"] {{
    --paper: #14161A;
    --card: #1B1E23;
    --ink: #E7E8E4;
    --ink-soft: #99A0AB;
    --rule: #2A2E35;
    --keep: #5FBFA5;
    --cut: #E08D72;
    --cut-soft: #24211F;
    --shadow: 0 1px 2px rgba(0, 0, 0, .45);
  }}

  body {{
    background: var(--paper);
    color: var(--ink);
    font-family: "IBM Plex Sans", system-ui, sans-serif;
    line-height: 1.5;
  }}
  .wrap {{
    max-width: 60rem;
    margin: 0 auto;
    padding: 3rem 1.5rem 8rem;
    display: flex;
    flex-direction: column;
    gap: 2.5rem;
  }}
  header h1 {{
    font-family: Literata, Georgia, serif;
    font-size: clamp(1.6rem, 1.2rem + 1.6vw, 2.3rem);
    font-weight: 600;
    margin: 0 0 .5rem;
    text-wrap: balance;
  }}
  header p {{
    margin: 0;
    color: var(--ink-soft);
    max-width: 48ch;
  }}
  .facts {{
    display: flex;
    flex-wrap: wrap;
    gap: 2rem;
    padding: 1.25rem 1.5rem;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 6px;
    box-shadow: var(--shadow);
  }}
  .fact {{ display: flex; flex-direction: column; gap: .15rem; }}
  .fact b {{
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 1.35rem;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }}
  .fact span {{
    font-size: .78rem;
    letter-spacing: .07em;
    text-transform: uppercase;
    color: var(--ink-soft);
  }}
  .aside {{
    border-left: 2px solid var(--rule);
    padding-left: 1.25rem;
  }}
  .aside h2 {{
    font-size: .78rem;
    letter-spacing: .07em;
    text-transform: uppercase;
    color: var(--ink-soft);
    font-weight: 600;
    margin: 0 0 .5rem;
  }}
  .aside p, .aside li {{ margin: 0 0 .4rem; max-width: 68ch; }}
  .aside ul {{ margin: 0; padding-left: 1.1rem; }}

  .script {{ display: flex; flex-direction: column; gap: .35rem; }}
  .block {{
    display: grid;
    grid-template-columns: 4.5rem 1fr auto;
    align-items: baseline;
    gap: 1rem;
    padding: .55rem .75rem;
    border-radius: 5px;
  }}
  .block:hover {{ background: var(--card); }}
  .tc {{
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: .8rem;
    color: var(--ink-soft);
    font-variant-numeric: tabular-nums;
  }}
  .speech {{
    font-family: Literata, Georgia, serif;
    font-size: 1.06rem;
    margin: 0;
    max-width: 68ch;
  }}
  .struck {{ text-decoration: line-through; color: var(--ink-soft); }}
  .cutbody {{ display: flex; flex-direction: column; gap: .35rem; }}
  .reveal {{
    display: inline-flex;
    align-items: center;
    gap: .5rem;
    background: none;
    border: 0;
    padding: 0;
    cursor: pointer;
    color: var(--ink-soft);
    font: inherit;
    font-size: .9rem;
    text-align: left;
  }}
  .tag {{
    color: var(--cut);
    background: var(--cut-soft);
    border-radius: 3px;
    padding: .05rem .4rem;
    font-size: .8rem;
    font-weight: 500;
  }}
  .hint {{ font-size: .85rem; }}
  .reveal[aria-expanded="true"] .hint::after {{ content: " ▴"; }}
  .reveal[aria-expanded="false"] .hint::after {{ content: " ▾"; }}
  .flip {{
    font: inherit;
    font-size: .8rem;
    color: var(--ink-soft);
    background: none;
    border: 1px solid var(--rule);
    border-radius: 4px;
    padding: .15rem .55rem;
    cursor: pointer;
    opacity: 0;
    transition: opacity .12s ease;
  }}
  .block:hover .flip, .flip:focus-visible {{ opacity: 1; }}
  .block[data-changed="true"] {{ background: var(--card); box-shadow: inset 3px 0 0 var(--keep); }}
  .block[data-changed="true"] .flip {{ opacity: 1; color: var(--keep); border-color: var(--keep); }}
  .block[data-kind="cut"] .speech {{ text-decoration: line-through; color: var(--ink-soft); }}

  .tray {{
    position: sticky;
    bottom: 0;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 6px;
    padding: .9rem 1.2rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
    box-shadow: var(--shadow);
  }}
  .tray p {{ margin: 0; color: var(--ink-soft); flex: 1 1 16rem; }}
  .tray button {{
    font: inherit;
    font-weight: 500;
    background: var(--ink);
    color: var(--paper);
    border: 0;
    border-radius: 4px;
    padding: .5rem 1rem;
    cursor: pointer;
  }}
  .tray button.ghost {{ background: none; color: var(--ink-soft); border: 1px solid var(--rule); }}
  :focus-visible {{ outline: 2px solid var(--keep); outline-offset: 2px; }}
  @media (max-width: 40rem) {{
    .block {{ grid-template-columns: 3.5rem 1fr; }}
    .flip {{ grid-column: 2; justify-self: start; opacity: 1; }}
  }}
</style>
</head>
<body>

<div class="wrap">
  <header>
    <h1>{title}</h1>
    <p>Читайте подряд — это то, что прозвучит в ролике. Вырезанное свёрнуто: разверните, чтобы увидеть текст и причину. Нужное верните кнопкой, а список правок скопируйте внизу.</p>
  </header>

  <div class="facts">
    <div class="fact"><b>{kept}</b><span>останется</span></div>
    <div class="fact"><b>{source}</b><span>снято</span></div>
    <div class="fact"><b>{keep_count}</b><span>реплик в сценарии</span></div>
    <div class="fact"><b>{cut_count}</b><span>предложено вырезать</span></div>
    <div class="fact"><b>{words}</b><span>слов</span></div>
  </div>

  {summary_block}

  <section class="script">
    {blocks}
  </section>

  {risk_block}

  <div class="tray">
    <p id="trayText">Правок нет — сценарий принимается как есть.</p>
    <button type="button" id="copy">Скопировать правки</button>
    <button type="button" class="ghost" id="reset">Сбросить</button>
  </div>
</div>

<script>
  const STORE = "script-edits";
  const blocks = [...document.querySelectorAll(".block")];
  const trayText = document.getElementById("trayText");

  const load = () => {{
    try {{ return JSON.parse(localStorage.getItem(STORE) || "{{}}"); }}
    catch (error) {{ return {{}}; }}
  }};
  const save = (state) => {{
    try {{ localStorage.setItem(STORE, JSON.stringify(state)); }} catch (error) {{ /* приватный режим */ }}
  }};
  let state = load();

  function label(block) {{
    const kind = block.dataset.kind;
    const changed = state[block.dataset.id];
    const button = block.querySelector(".flip");
    if (kind === "keep") button.textContent = changed ? "оставлено вырезать" : "вырезать";
    else button.textContent = changed ? "возвращено" : "вернуть";
    block.dataset.changed = changed ? "true" : "false";
  }}

  function edits() {{
    return blocks
      .filter((block) => state[block.dataset.id])
      .map((block) => {{
        const time = block.querySelector(".tc").textContent;
        const text = block.querySelector(".speech").textContent.trim();
        const verb = block.dataset.kind === "cut" ? "вернуть" : "вырезать";
        return `${{verb}} ${{time}} — ${{text.slice(0, 90)}}`;
      }});
  }}

  function refresh() {{
    const list = edits();
    trayText.textContent = list.length
      ? `Правок: ${{list.length}}. Скопируйте список и пришлите — соберу монтаж по нему.`
      : "Правок нет — сценарий принимается как есть.";
  }}

  blocks.forEach((block) => {{
    label(block);
    block.querySelector(".flip").addEventListener("click", () => {{
      const id = block.dataset.id;
      if (state[id]) delete state[id]; else state[id] = true;
      save(state);
      label(block);
      refresh();
    }});
    const reveal = block.querySelector(".reveal");
    if (reveal) {{
      const speech = block.querySelector(".speech");
      reveal.addEventListener("click", () => {{
        const open = reveal.getAttribute("aria-expanded") === "true";
        reveal.setAttribute("aria-expanded", String(!open));
        speech.hidden = open;
      }});
    }}
  }});

  document.getElementById("copy").addEventListener("click", async () => {{
    const list = edits();
    const text = list.length ? list.join("\\n") : "Сценарий принят без правок.";
    try {{
      await navigator.clipboard.writeText(text);
      trayText.textContent = "Скопировано.";
      setTimeout(refresh, 1600);
    }} catch (error) {{
      trayText.textContent = text;
    }}
  }});

  document.getElementById("reset").addEventListener("click", () => {{
    state = {{}};
    save(state);
    blocks.forEach(label);
    refresh();
  }});

  refresh();
</script>
</body>
</html>
"""
