# ATOM: transcribe-file (faster-whisper)

Status: proven
Last run: 2026-07-16

## Цель

Получить сегменты речи с таймкодами из audio/video файла.

## Вход

- Абсолютный путь к m4a/mp4
- model: small (CPU int8)

## Шаги

1. `pip install faster-whisper` в tooling venv
2. `WhisperModel('small', device='cpu', compute_type='int8')`
3. `transcribe(path, vad_filter=True, word_timestamps=True)`
4. Сохранить JSON+TXT в `05_project/transcripts/`

## MCP

`transcribe_file` — когда Resolve bridge здоров и deps в MCP venv. В run 0003 вызывали напрямую Python (надёжнее).

## Проверка

- [x] language определён
- [x] сегменты покрывают речь
