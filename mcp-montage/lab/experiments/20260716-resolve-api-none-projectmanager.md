# Experiment: Resolve GetProjectManager NoneType

Date: 2026-07-16
Verdict: retry

## Гипотеза

Bridge HTTP up ⇒ можно create_project / import.

## Результат

`get_resolve_status.connected=true`, но любые project calls: `TypeError: 'NoneType' object is not callable` на `r.GetProjectManager()`.

## Почему retry

Нужен рестарт: открыть проект в Resolve → Workspace → Scripts → CursorBridge заново.

## Следующий шаг

Перед следующим билдом — проверить `get_project_info` успех, иначе снова ffmpeg path.
