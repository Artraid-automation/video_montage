# Engineering invariants

- Treat `docs/product/IMPLEMENTATION_PLAN.md` as the versioned product plan and `docs/product/ACCEPTANCE.md` as the final acceptance contract.
- Never mark a phase complete from file existence alone. Validate typed manifests, hashes, media probes, QC verdicts, approvals, and dependency versions.
- Separate orchestration from media workers. Workers are idempotent and communicate through versioned artifacts; the orchestrator owns transitions, leases, checkpoints, and retries.
- Before implementing a block, state a falsifiable claim and add a test that fails for the missing behavior. Preserve raw test evidence.
- After implementation, run two independent audits: functional/safety and architecture/maintainability. Resolve every blocking finding before writing `audit/Pn-verdict.json` with `PASS`.
- Do not use a human as a debugger. Request real media only after P0–P4 synthetic E2E and all phase audits pass.
- Heavy media never enters Git. Destructive cleanup requires a verified archive receipt, explicit approval, exact allowlisted paths, symlink/junction rejection, and recoverable quarantine.
- A repeated human correction becomes a rule only through proposed → approved promotion with provenance, scope, rollback, and a failing-then-passing regression fixture.
- **Learning loop (always):** log every error, nuance, and rework with symptom → wrong assumption → root cause → fix → guardrail. Canon: `docs/product/LEARNING_LOOP.md`. Rule: `.cursor/rules/learning-loop.mdc`.
- Keep rules short. Put detailed workflows in skills or canonical documentation and link to them.
- Numbered segments are parts of **one** final video. Cross-segment KEEP duplicates block Gate 1 approve / Gate 2 / Phase 3 concat (`docs/product/FILM_CONTINUITY.md`).
- **Style Bible (author):** after Tanya, defaults live in `docs/product/STYLE_BIBLE.md`. Formats: Reels or long-form only. Semantic media briefs use `library/senses/` (agent cards), not embedding APIs.

## Required verification verdict

For every claimed block completion, emit exactly one machine-readable status: `VERIFIED`, `NOT_VERIFIED`, or `INCONCLUSIVE`, with the claim, thresholds, commands, raw evidence paths, commit SHA, and reviewer identifiers.
