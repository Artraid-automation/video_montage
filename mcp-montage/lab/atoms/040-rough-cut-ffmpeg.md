# ATOM: rough-cut via ffmpeg

Status: proven
Last run: 2026-07-16

## Цель

Собрать keep-ranges в один ролик без Resolve API.

## Вход

- cutlist keeps[{start_s,end_s}]
- source mp4

## Шаги

1. `ffmpeg -ss START -i SRC -t DUR -c:v libx264 -c:a aac seg_N.mp4`
2. concat demuxer list
3. `ffmpeg -f concat -safe 0 -i list.txt -c copy rough.mp4`

## Когда использовать

Fallback если CursorBridge/Resolve scripting сломан или trim API слаб.
