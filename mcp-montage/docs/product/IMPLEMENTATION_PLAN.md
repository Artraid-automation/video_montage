# План реализации продукта

Статусы: `[x]` реализовано и подтверждено тестом или боевым артефактом; `[ ]` отложено за границы локального P0–P4.

## P0 — контракт и управление состоянием

- [x] Референсный процесс разобран по полному транскрипту и оформлен в продуктовые документы.
- [x] Реализованы project-state, append-only events, checkpoints и recoverable failures.
- [x] Единый CLI: `start/status/approve/revise/finalize/resume/accept-final`.
- [x] Hash-bound approvals, manifest validation и запреты обхода gates.
- [x] Версионированный content-addressed JobLedger с проверкой output SHA при resume.

Приёмка P0: state-machine и fault matrix проходят; устаревший или изменённый артефакт нельзя переиспользовать/утвердить.

## P1 — полноценная Phase 1

- [x] ffprobe manifest и реальная ASR-транскрибация через faster-whisper.
- [x] Анализ пауз, повторов, cut/take candidates и межфайловых дублей.
- [x] **Обязательный LLM cohesion-pass** по `prompts/gate1-editorial-cohesion.v2.md` (agent в Cursor / openai) с артефактом `llm-editorial.json`. См. `docs/product/GATE1_AGENT_PRODUCER.md`.
- [x] Локальный B-roll catalog/search с лицензиями, provenance и checksum.
- [x] Нумерация и связывание camera/screen/mic feeds; неоднозначности fail closed.
- [x] Per-segment editable transcript с parser/round-trip и word-ID validation.
- [x] Waveform sync report и grade samples.
- [x] Gate 1 visuals: agent-placed MOTION/BROLL (auto cadence off by default); единый Gate 1 review.

Приёмка P1: три реальных Tanya-исходника дошли до `GATE1_REVIEW`; система остановилась до авторского approval.

## P2 — полноценная Phase 2

- [x] Rough cut и selective segment cache.
- [x] ASS captions и runtime visual-scene contracts.
- [x] Compositor для camera/screen PiP, B-roll, motion, audio и grade.
- [x] Локальный motion provider выполняется внутри resumable segment jobs.
- [x] Независимая повторная ASR-транскрибация каждого render.
- [x] Expected-vs-actual transcript verification с hash bindings.
- [x] Frame probes, layout/audio policy и technical QC сегмента.
- [x] Gate 2 review и исполняемые fixes.

Приёмка P2: реальный Tanya render прошёл речь (`WER 0.15`, order ratio `0.85`); ложная проверка FPS была обнаружена боевым прогоном, исправлена и повторно пройдена через `resume`.

## P3 — ревизии и обучение правил

- [x] Инвалидация только изменённого сегмента.
- [x] Dependency fingerprints для cuts/assets/style/provider/worker versions.
- [x] Blocking fixes с обязательной повторной verification.
- [x] Promotion rule candidate в style/QC rules только после baseline/treatment regression.
- [x] Regression ledger и fixtures принятых правил.
- [x] Final metadata revisions пересобирают package/master lineage безопасно.

Приёмка P3: тесты доказывают selective rebuild, executable fixes, final revision и отклонение правила без проходящей регрессии.

## P4 — Phase 3 и доставка

- [x] Merge только verified segments и master profile.
- [x] Full-file QC и chapters по финальному таймингу.
- [x] Local publishing package.
- [x] Archive copy с destination readback checksum и path safety.
- [x] Ingestion одобренных B-roll/motion assets в локальную библиотеку.
- [x] Явный cleanup dry-run, confirmation hash, TOCTOU recheck, quarantine и receipt.

Приёмка P4: технический прогон на реальном Tanya-клипе завершён в `COMPLETED`; master QC — `PASS`, архив — `VERIFIED`, cleanup выполнен в recoverable quarantine.

## P5 — после первого авторски принятого ролика

- [x] Авторский Style Bible из решений по Gate 1/2/Final (`docs/product/STYLE_BIBLE.md`, `.cursor/rules/style-bible.mdc`) — из Tanya `COMPLETED`.
- [x] Профили **Reels 9:16** и **long-form 16:9** (`presets/profiles/`, `pipeline/factory/profiles.py`). Podcast / прочие форматы — вне scope.
- [ ] ElevenLabs/Hyperframes/Resolve adapters.
- [x] **Sense catalog (агентская разметка, не embeddings):** `library/senses/catalog.json` + лексический поиск; B-roll query expansion. Без OpenAI / локальных NN.
- [ ] Опциональная publishing integration.
- [ ] **Semantic segments from raw multi-takes** — идея: `docs/product/FUTURE_SEMANTIC_SEGMENTS.md`.

Resolve и внешние SaaS не блокируют локальный P0–P4: они подключаются как providers после принятия первого ролика и фиксации авторского стиля.