#!/usr/bin/env python3
import sys, json, pathlib
from faster_whisper import WhisperModel
model = WhisperModel(sys.argv[3], device="cpu", compute_type="int8", cpu_threads=4)
segs, _ = model.transcribe(sys.argv[1], language="ru", word_timestamps=True, vad_filter=False, beam_size=5)
words=[{"w":w.word.strip(),"s":round(w.start,3),"e":round(w.end,3)} for s in segs for w in (s.words or [])]
pathlib.Path(sys.argv[2]).write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
print(f"{sys.argv[3]}: {len(words)} слов")
