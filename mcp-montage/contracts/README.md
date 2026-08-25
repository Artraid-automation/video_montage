# Runtime contracts (v2)

These schemas document the durable public artifacts of Local AI Video Factory v2.
Runtime validation is implemented by `pipeline/factory/contracts.py` and
`pipeline/factory/artifacts.py`; schema and code versions must change together.

- `project-state.schema.json` — atomic state/job/gate ledger;
- `gate-manifest.schema.json` — common envelope for Gate 1, Gate 2 and Final Review;
- every artifact record is content-bound by SHA-256 and byte size;
- QC, sync, transcript verification and archive receipts additionally bind the
  evidence to the exact media/transcript hashes they prove.

Pre-v2 schemas are preserved in `lab/legacy/pre-v2-contracts/` and are not a
runtime API.
