"""Executable fixture for CLI tests of the external ASR adapter."""
from __future__ import annotations

import json
import sys
from pathlib import Path


media = Path(sys.argv[1])
expected = json.loads((media.parent / "expected-transcript.json").read_text(encoding="utf-8"))
segments = []
words = {item["id"]: item for item in expected["words"]}
for utterance in expected["utterances"]:
    segments.append({
        "id": utterance["source_entry_id"],
        "start": utterance["start_s"],
        "end": utterance["end_s"],
        "text": utterance["text"],
        "words": [
            {"word": words[word_id]["text"], "start": words[word_id]["start_s"], "end": words[word_id]["end_s"], "confidence": 1.0}
            for word_id in utterance["word_ids"]
        ],
    })
sys.stdout.write(json.dumps({"language": "fixture", "duration_s": expected["duration_s"], "segments": segments}))
