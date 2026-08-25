#!/usr/bin/env bash
# Проверка живости RSS-источников. Живой = HTTP 200 + в теле есть <item или <entry.
# Формат строки: категория|название|url[|crm]   (crm = тянуть через российский сервер, ssh crm)
# Использование: bash ~/brand/scripts/check_feeds.sh [файл-списка]
LIST="${1:-$HOME/brand/feed/feeds.txt}"
UA='Mozilla/5.0 (compatible; brand-feed-check/1.0)'
while IFS='|' read -r cat name url via; do
  case "$cat" in \#*|'') continue;; esac
  [ -z "$url" ] && continue
  if [ "$via" = "crm" ]; then
    body=$(timeout 40 ssh -n crm "curl -sL --max-time 20 -A '$UA' -w '\n%{http_code}' '$url'" 2>/dev/null)
  else
    body=$(curl -sL --max-time 20 -A "$UA" -w '\n%{http_code}' "$url" 2>/dev/null)
  fi
  code=$(printf '%s' "$body" | tail -1)
  items=$(printf '%s' "$body" | grep -o -E '<item|<entry' | wc -l)
  if [ "$code" = "200" ] && [ "$items" -gt 0 ]; then st="OK  "; else st="FAIL"; fi
  printf '%s | %-4s | %-4s | %-28s | %s%s\n' "$st" "$code" "$items" "$name" "$cat" "${via:+ (via $via)}"
done < "$LIST"
