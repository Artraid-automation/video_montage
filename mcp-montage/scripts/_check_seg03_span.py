from pathlib import Path

from pipeline.factory.io import read_json
from pipeline.factory.utterances import coalesce_source_transcript

src = read_json(Path("projects/tanya-reel-pilot/03_phase1/segments/03/source-transcript.json"))
raw = src["utterances"]
print("raw count", len(raw), "span", raw[0]["start_s"], "->", raw[-1]["end_s"])
co = coalesce_source_transcript(src)["utterances"]
print("coalesced", len(co), "span", co[0]["start_s"], "->", co[-1]["end_s"])
for u in co[-8:]:
    print(f"{u['id']} {u['start_s']:.1f}-{u['end_s']:.1f} {u['text'][:60]!r}")
