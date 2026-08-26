# Local AI Video Factory v2

Локальный трёхфазный pipeline: от пронумерованных camera/screen/WAV-исходников до проверенного master, архива и publishing package. Монтаж управляется через текстовые артефакты и три human-in-the-loop gate; открывать таймлайн для чернового постпродакшена не требуется.

## Что уже реализовано

- безопасный ingest только из `01_raw`, feed grouping, SHA-256 и ffprobe manifest;
- первичная ASR-транскрибация, анализ пауз/повторов/дублей, waveform sync;
- локальный B-roll catalog/search с rights, provenance и checksum validation;
- редактируемый `transcript.md`, visual plan, три grade sample и Gate 1;
- независимые segment jobs, PiP/B-roll/motion, ASS captions, audio offset и grade;
- повторная ASR-транскрибация готового MP4, WER/order/silence verification;
- frame/audio/layout/technical QC, Gate 2 и исполняемые scoped revisions;
- selective rebuild по fingerprint, настоящий resume по job ledger;
- final master, chapters, publishing package, verified archive и recoverable cleanup;
- rule promotion только после исполняемого failing-before/passing-after regression.

## Быстрый старт

```powershell
python pipeline/studio.py doctor
python pipeline/studio.py new-project my-video
# положить 01_camera.mp4, 01_screen.mp4, 01_audio.wav и т. п. в projects/my-video/01_raw
python pipeline/studio.py start projects/my-video
python pipeline/studio.py approve projects/my-video gate1 --reviewer owner
python pipeline/studio.py approve projects/my-video gate2 --reviewer owner
python pipeline/studio.py finalize projects/my-video
python pipeline/studio.py accept-final projects/my-video --reviewer owner
```

Реальный запуск требует `ffmpeg`, `ffprobe`, Pillow и ASR provider. Локальный `faster-whisper` поддерживается напрямую; внешний локальный ASR можно подключить через `external-command` adapter. `doctor` показывает фактическую готовность окружения.

## Контур продукта

```text
01_raw
  → Phase 1: ingest / ASR / editorial / sync / B-roll plan / grade samples
  → Gate 1: текстовое утверждение монтажного решения
  → Phase 2: segment render / rendered-media ASR / verification / QC
  → Gate 2: просмотр сегментов и адресные исполняемые fixes
  → Phase 3: master / full QC / publishing package / verified archive
  → Final Review → explicit acceptance → optional recoverable cleanup
```

Стиль задаётся данными, а не кодом: `presets/styles/<id>/style.json` (гарнитура, кегль, ритм,
камера, звук) плюс `presets/profiles/<id>.json` (кадр, частота, кодек). Измеренный по референсам
стиль — `strokov-measured-v1`, профиль под него — `reels-9x16-measured`.

Основные документы:

- [`agent.md`](agent.md) — устройство: границы модулей, стык стиля и механики, грабли;

- [`docs/product/REFERENCE_SYSTEM.md`](docs/product/REFERENCE_SYSTEM.md) — подробный разбор референсной системы Brian Casel;
- [`docs/product/PRODUCT_SPEC.md`](docs/product/PRODUCT_SPEC.md) — границы и требования продукта;
- [`docs/product/PIPELINE.md`](docs/product/PIPELINE.md) — фазы, gates и структура проекта;
- [`docs/product/ARTIFACTS.md`](docs/product/ARTIFACTS.md) — форматы текстового управления;
- [`docs/product/ACCEPTANCE.md`](docs/product/ACCEPTANCE.md) — доказательства готовности;
- [`docs/product/IMPLEMENTATION_PLAN.md`](docs/product/IMPLEMENTATION_PLAN.md) — P0–P4;
- [`docs/product/ENGINEERING_METHOD.md`](docs/product/ENGINEERING_METHOD.md) — planner/worker/verifier/critic workflow.

`lab/legacy/` содержит сохранённые pre-v2 эксперименты и не является runtime API. Папка `projects/tanya-reel-pilot/` — пользовательские исходники и системой не изменялась.