"""Build llm-editorial-request.json for each segment (no provider call)."""

from __future__ import annotations

from pathlib import Path

from pipeline.factory.editorial import analyze_editorial, apply_editorial_proposals
from pipeline.factory.io import atomic_write_json, read_json
from pipeline.factory.llm_editorial import build_llm_editorial_request
from pipeline.factory.phase1 import _editorial_analyze_kwargs, _entries
from pipeline.factory.utterances import coalesce_source_transcript


def main() -> None:
    root = Path("projects/tanya-reel-pilot").resolve()
    config = read_json(root / "project.json")
    raw = read_json(root / "03_phase1/manifest.json")
    prompt_version = config.get("editorial", {}).get("llm", {}).get(
        "prompt_version", "gate1-editorial-cohesion.v2"
    )
    for group in raw["segments"]:
        segment_id = f"{group['number']:02d}"
        segment_root = root / "03_phase1" / "segments" / segment_id
        source = read_json(segment_root / "source-transcript.json")
        review = coalesce_source_transcript(source)
        editorial = analyze_editorial(review, **_editorial_analyze_kwargs(config))
        entries = apply_editorial_proposals(_entries(review, []), editorial)
        request = build_llm_editorial_request(
            segment_id, entries, prompt_version=str(prompt_version)
        )
        path = segment_root / "llm-editorial-request.json"
        atomic_write_json(path, request)
        false_n = sum(1 for item in request["blocks"] if item["false_cohesion"])
        print(
            f"{segment_id}: blocks={len(request['blocks'])} "
            f"false_cohesion={false_n} media_end={request['media_end_timecode']}"
        )


if __name__ == "__main__":
    main()
