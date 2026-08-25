# Gate 2 — visual render policies (system QC)

Blocking Gate 2 QC — not optional author eyeballing.

## Hard rules

| Rule | Check |
|------|--------|
| MOTION overlay on A-roll | `motion_mode == overlay` when motions exist |
| On-card text = audience punch only | no `Зачем:`; no director notes (`поверх речи`, `иконки`, …); ≤6 words |
| Captions stay on under MOTION | gold speech captions are primary; Y from **face detect after crop** (chest), not fixed mid-frame |
| Framing auto | `framing-plan.json` from face samples; scale+crop before burn-in; fail-closed if no face |
| Font size | ≤ ~5.5% of frame height |
| Key composition probes | Deterministic start / mid / end JPGs in `probes/gate2-audit/` |
| Random frame probes | Seeded from render SHA — ≥5 JPGs in `probes/gate2-audit/` |
| Face on real pixels | On probes: detect face; FAIL if face is too close to frame edges, horizontally off-center, caption band overlaps face bbox, or headroom is too small / excessive |
| Per-MOTION probes | Separate start/mid/(end) grabs for **each** MOTION; each motion has its own verdict |
| Fail closed | missing `render-contract` or missing `visual_audit` (QC schema 4) → FAIL |

Author Gate 2 review lists every random + MOTION probe path — open the JPGs, do not rely on MP4 scrub alone.

See also: `docs/product/FRAMING.md`, `docs/product/LEARNING_LOOP.md` (log every visual miss with cause).

Style recipes (`hook_title`, `framework_list`) come from `docs/product/STYLE_LIBRARY.md` and are applied only when proposed+approved.

| Rule | Check |
|------|--------|
| Style scenes wired | Gate 1: if `style-scenes.json` / `llm-visual.json` proposes recipes, `visual-plan.json` **must** carry the same `style_scenes` (refresh must not drop them) |
| Style recipes burned | Gate 2 `render-contract`: `style_recipes_expected` ⊆ `style_recipes_applied` — missing `framework_list` / `hook_title` is **FAIL** |
| Hook ≠ body captions | `hook_title` font_size > body caption font_size; italic gold `#EAC225`; Y on chest below eyes (`hook_title_y_center_ratio` ≥ 0.48) |
| Hook clearance probe | When `hook_title` expected: `key-start` JPG must not have gold title over upper face |
| Caption timing | Phrase ASS windows follow **source word timestamps** inside each KEEP clip — not even `duration/n` slices |
| KEEP echo / sync verify | Re-ASR vs expected: FAIL on adjacent phrase echoes, speech timing drift, **and** repeated clause openers (`вместо…вместо`) in **expected or actual** — WER alone is not enough |
| Dead air in KEEP | FAIL if re-ASR gap > **1.2s**, or KEEP clip lead-in before first timed word > **0.8s** (Slava: 5s sigh before «большинство») |

See also: `docs/superpowers/specs/2026-07-20-dankoe-style-pack-design.md`, `docs/learning/2026-07-21-slava-list-and-dupes.md`
