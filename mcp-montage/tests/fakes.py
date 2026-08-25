from __future__ import annotations

import copy
from pathlib import Path

from pipeline.factory.io import read_json


class RenderedTranscriptFake:
    """Test-only ASR double; production code never imports this module."""

    name = "test-double"
    version = "1"

    def __init__(self, fault: str | None = None):
        self.fault = fault

    def transcribe(self, media_path: Path) -> dict:
        actual = copy.deepcopy(read_json(media_path.parent / "expected-transcript.json"))
        words = actual["words"]
        if self.fault == "delete" and len(words) > 1:
            del words[len(words) // 2]
        elif self.fault == "duplicate" and words:
            words.insert(len(words) // 2, dict(words[len(words) // 2]))
        elif self.fault == "reorder" and len(words) > 3:
            words[:] = words[len(words) // 2:] + words[:len(words) // 2]
        actual.update({"provider": self.name, "provider_version": self.version})
        return actual
