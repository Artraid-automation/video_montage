# Future: semantic segments from raw multi-takes

**Status:** deferred — idea only. Do not implement until A/V timing and sync contracts are proven end-to-end on real multi-file inputs.

## Problem today

Input may be **1, 3, 5, or N** numbered raw videos. They are **source takes**, not meaning units. The product currently often treats each file as a “segment,” but a real film needs **semantic segments** (intro, body chunks, outro). Without that, Gate continuity and Phase 3 concat operate on file boundaries, not story boundaries.

## Proposed term

**Segment** = a **semantic** piece of the final film, not “one input file.”

Typical structure:

- introduction
- main body — split into **1–3** large meaning blocks
- closing / CTA

N raw files → still one story; M segments where M is chosen by meaning, not by file count.

## Future pipeline sketch

1. Ingest and transcribe **each raw input** (existing ASR / word timestamps).
2. Author or agent proposes **semantic cut points** across the glued narrative (intro / body×1–3 / outro).
3. **Glue + re-cut** media into true segment work units for Gate 1 → Phase 2 → Phase 3.
4. Existing film-continuity (`KEEP` across segments) then applies to real chapters of one film.

## Hard constraint (why deferred)

Re-cutting across file boundaries must preserve:

- word-aligned timing
- camera / screen / WAV sync
- no drift at seam points

Until glue+slice is proven fail-closed (hashes, probes, sync reports), keep current file→segment mapping for production.

## Out of scope for this note

- Implementation, schemas, workers, or Tanya migration.
- Auto-segmentation without author Gate.
