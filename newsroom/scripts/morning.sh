#!/usr/bin/env bash
# Утренний прогон: собрать источники -> отобрать десятку -> вытащить абзацы -> сверстать -> прислать в Telegram.
# Использование: bash ~/brand/scripts/morning.sh [--force] [--no-send]
set -uo pipefail
# Крон даёт голый PATH — без этой строки не находится ни claude, ни node под ним
export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/$(ls -1 "$HOME/.nvm/versions/node" 2>/dev/null | tail -1)/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")/.." || exit 1
DATE=$(TZ=Europe/Moscow date +%F)
LOG="feed/cache/log-$DATE.txt"
FORCE=0; SEND=1
for a in "$@"; do
  [ "$a" = "--force" ] && FORCE=1
  [ "$a" = "--no-send" ] && SEND=0
done

say(){ echo "[$(TZ=Europe/Moscow date +%H:%M:%S)] $*" | tee -a "$LOG"; }
# Молчаливый сбой хуже отсутствия автоматики: два утра подряд лист не приходил и никто не знал.
fail(){ say "СБОЙ: $1"; python3 "$HOME/scripts/tg.py" --no-ito \
  "Эфирный лист сегодня не собрался: $1. Лог: brand/feed/cache/$(basename "$LOG")" >/dev/null 2>&1; exit 1; }

if [ -s "feed/digest/$DATE.json" ] && [ "$FORCE" = "0" ]; then
  say "лист за $DATE уже собран, повтор не нужен (--force чтобы пересобрать)"
  exit 0
fi

say "1/4 сбор источников"
python3 -u scripts/collect.py --hours 30 2>&1 | tee -a "$LOG" || fail "сбор источников"

say "2/4 отбор десятки"
python3 -u scripts/select.py "$DATE" 2>&1 | tee -a "$LOG" || fail "отбор десятки"

say "3/4 ключевые абзацы"
python3 -u scripts/extract.py "$DATE" 2>&1 | tee -a "$LOG" || fail "ключевые абзацы"

say "4/4 вёрстка"
python3 -u scripts/render.py "$DATE" 2>&1 | tee -a "$LOG" || fail "вёрстка"

N=$(python3 -c "import json;print(len(json.load(open('feed/digest/$DATE.json'))['items']))")
FILE="feed/digest/$DATE-эфирный-лист.html"

if [ "$SEND" = "1" ]; then
  python3 ~/scripts/tg.py --no-ito -f "$FILE" \
    -c "Эфирный лист на сегодня — $N новостей. Скачай и открой в браузере: тап по номеру сворачивает отработанную." \
    2>&1 | tee -a "$LOG"
  say "отправлено в Telegram"
else
  say "готово без отправки: $FILE"
fi
