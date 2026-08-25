#!/usr/bin/env python3
"""Пословная транскрибация референса: нужны не слова, а ПАУЗЫ между ними."""
import sys, json, pathlib
from faster_whisper import WhisperModel
model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=2)
segs, info = model.transcribe(sys.argv[1], language="ru", word_timestamps=True,
                              vad_filter=False, beam_size=1)
words = []
for s in segs:
    for w in (s.words or []):
        words.append({"w": w.word.strip(), "s": round(w.start,3), "e": round(w.end,3)})
pathlib.Path(sys.argv[2]).write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
print(f"{pathlib.Path(sys.argv[1]).name}: {len(words)} слов")
