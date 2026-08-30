"""Применить правки с монтажного стола к сценарию проекта.

Стол возвращает список номеров вычеркнутых слов. Разметка проекта живёт репликами,
поэтому реплика режется по границам оставленного: слова, вычеркнутые в середине,
разрывают её на части, а сплошь вычеркнутая уходит целиком.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from factory.io import read_json  # noqa: E402
from factory.transcript import TranscriptEntry, load_transcript, render_transcript  # noqa: E402


def _spans(flags: list[bool]) -> list[tuple[int, int, bool]]:
    """Свернуть пометки в отрезки: (начало, конец, оставлено)."""
    spans: list[tuple[int, int, bool]] = []
    start = 0
    for index in range(1, len(flags) + 1):
        if index == len(flags) or flags[index] != flags[start]:
            spans.append((start, index - 1, flags[start]))
            start = index
    return spans


def apply_edits(
    entries: list[TranscriptEntry],
    desk: dict,
    cut_words: set[int],
) -> list[TranscriptEntry]:
    words = desk["words"]
    by_entry: dict[str, list[dict]] = {}
    for word in words:
        by_entry.setdefault(str(word["entry_id"]), []).append(word)

    updated: list[TranscriptEntry] = []
    for entry in entries:
        local = by_entry.get(entry.id)
        if not local:
            updated.append(entry)
            continue
        keep_flags = [word["i"] not in cut_words for word in local]
        if all(keep_flags):
            updated.append(TranscriptEntry(
                kind="keep", id=entry.id, start_s=entry.start_s, end_s=entry.end_s,
                word_ids=entry.word_ids, text=entry.text, reason=None,
            ))
            continue
        if not any(keep_flags):
            updated.append(TranscriptEntry(
                kind="cut", id=entry.id, start_s=entry.start_s, end_s=entry.end_s,
                word_ids=entry.word_ids, text=entry.text, reason="решение заказчика",
            ))
            continue
        for part, (first, last, kept) in enumerate(_spans(keep_flags), 1):
            chunk = local[first:last + 1]
            # Слова реплики и её word_ids идут в одном порядке, поэтому кусок
            # берёт свой срез идентификаторов по тому же смещению.
            updated.append(TranscriptEntry(
                kind="keep" if kept else "cut",
                # Суффикс `x` — принятый в системе признак части реплики: по нему
                # разметка проходит проверку id и печатает границы куска, без чего
                # обратное чтение transcript.md теряет времена. Идентификаторы слов
                # берём из выгрузки стола: у склеенной реплики свой список неполон.
                id=f"{entry.id}x{part}",
                start_s=float(chunk[0]["start_s"]),
                end_s=float(chunk[-1]["end_s"]),
                word_ids=tuple(str(item.get("wid")) for item in chunk if item.get("wid")),
                text=" ".join(str(item["text"]) for item in chunk),
                reason=None if kept else "решение заказчика",
            ))
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="применить правки монтажного стола")
    parser.add_argument("project_root")
    parser.add_argument("submit_json")
    parser.add_argument("--segment", default="01")
    args = parser.parse_args()

    root = Path(args.project_root).resolve(strict=True)
    phase1 = root / "03_phase1" / "segments" / args.segment
    desk = read_json(phase1 / "desk.json") if (phase1 / "desk.json").is_file() else read_json(
        root / "03_phase1" / "desk.json"
    )
    submit = json.loads(Path(args.submit_json).read_text(encoding="utf-8"))
    cut_words = {int(index) for index in submit.get("cut_words") or []}

    source = read_json(phase1 / "source-transcript.json")
    entries, visuals = load_transcript(phase1 / "transcript.md", source)
    updated = apply_edits(entries, desk, cut_words)

    media_end = max((float(item.end_s) for item in updated), default=0.0)
    # Разметка переписывается на месте, поэтому прежняя версия сохраняется рядом:
    # ошибка в правках иначе стоила бы повторной расшифровки всего исходника.
    target = phase1 / "transcript.md"
    backup = phase1 / f"transcript.before-{time.strftime('%Y%m%d-%H%M%S')}.md"
    backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.write_text(
        render_transcript(updated, visuals, segment_id=args.segment, media_end_s=media_end),
        encoding="utf-8",
    )
    # Исправления распознавания живут отдельным файлом: они не меняют разметку речи,
    # только надпись на экране, и переживают любую пересборку сценария.
    rewrites = {}
    by_index = {int(word["i"]): word for word in desk["words"]}
    for index, value in (submit.get("rewrites") or {}).items():
        word = by_index.get(int(index))
        if word and word.get("wid") and str(value).strip():
            rewrites[str(word["wid"])] = str(value).strip()
    rewrites_path = phase1 / "caption-rewrites.json"
    if rewrites:
        existing = json.loads(rewrites_path.read_text(encoding="utf-8")) if rewrites_path.is_file() else {}
        existing.update(rewrites)
        rewrites_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    kept = sum(1 for item in updated if item.kind == "keep")
    print(
        f"применено: реплик оставлено {kept} из {len(updated)}, "
        f"вычеркнуто слов {len(cut_words)}, исправлено написаний {len(rewrites)}"
    )
    if submit.get("note"):
        print(f"пожелание: {submit['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
