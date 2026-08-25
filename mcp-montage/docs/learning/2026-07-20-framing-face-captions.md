# 2026-07-20 — Framing + face-aware captions (Tanya pilot)

Author feedback: субтитры должны быть на середине груди, а на экране оказывались на лице; нельзя смотреть только на координаты — всегда проверять факт картинки; после кропа положение меняется; кадр выставлять автоматически по правилам.

## Loop entries

### 1. Fixed ASS mid-center ≠ mid-chest on a person

- **Symptom:** Gold captions sat on mouth/chin while policy said “chest / alignment 5”.
- **Wrong assumption:** ASS `Alignment=5` (geometric mid-frame) equals mid-chest relative to the speaker.
- **Root cause:** Mid-frame is a screen coordinate. The speaker’s chest moves with crop/scale and pose.
- **Fix:** Caption `\pos(x,y)` from **detected face after crop**; Y = below face box + gap, with a 9:16 chest band floor (~68% height).
- **Guardrail:** `verify_frame_face_caption` on Gate2 probe JPGs; FAIL on face∩caption overlap. Style alignment 8 when face-pos is used.
- **Evidence:** `docs/product/FRAMING.md`; `pipeline/factory/framing.py`; Tanya `render-contract.json` `caption_pos_y` ≈ 870.

### 2. Coordinates / plans without pixel proof

- **Symptom:** Contract claimed chest Y; author (and vision captions of JPGs) still reported “on the face”.
- **Wrong assumption:** Matching planned `caption_pos_y` is enough to declare PASS.
- **Root cause:** Plan Y can be right while (a) framing never applied, (b) face detector used a wrong box, (c) multi-line ASS extends through the face, (d) image-description models mis-locate text vs chin.
- **Fix:** Always measure on burned frames: yellow-pixel Y band + Haar face bbox overlap. Prefer pixels over LLM image captions when they conflict.
- **Guardrail:** `gate2-visual-audit` + face_check on random/MOTION JPGs; learning-loop rule forbids “coords only” claims.
- **Evidence:** Pixel checks showed yellow median ≈ 900 with `caption_pos_y=870` while some vision descriptions still said “on chin” — detector overlap was False.

### 3. Identity crop — Haar torso false positive

- **Symptom:** `ffmpeg_vf` was `scale=720:1280,crop=720:1280:0:0` (no zoom); huge empty headroom remained.
- **Wrong assumption:** “Largest detected face” is the talking-head face.
- **Root cause:** Haar often returns a **torso-sized** box (e.g. 586×586) plus a real face (~280–430). Largest-wins selected the FP → face already “fills” the frame → scale stayed 1.0 → crop_y clamped to 0.
- **Fix:** `filter_talking_head_faces` (height 10–40% of frame, aspect, upper-half); score typical faces; scale from scored face, not raw largest.
- **Guardrail:** Framing samples logged in `framing-plan.json`; reject FP size band at plan time.
- **Evidence:** `framing-samples/sample-02-6.96.jpg` had faces `[(68,55,586,586), (139,303,436,436)]`.

### 4. Eye-line 32% + face 33% implies ~19% headroom

- **Symptom:** Audit FAIL `excessive headroom ~0.19` while “targets” claimed eye-line 0.32.
- **Wrong assumption:** Eye-line 32% and headroom 8–12% are independent knobs.
- **Root cause:** Geometry: crown ≈ eyes − 0.38×face_h. With face_h≈33% of frame, headroom ≈ 0.32 − 0.125 ≈ **0.20**. Targets fought each other.
- **Fix:** Drive crop from **crown / HEADROOM_TARGET (~10%)**; eye-line becomes derived (~22–28%).
- **Guardrail:** Updated `FRAMING.md` metrics; unit test on `compute_framing_plan` headroom band.
- **Evidence:** Early `predicted.headroom_ratio` ≈ 0.196 with eye-line-first crop.

### 5. Face already ~26% of 9:16 → no room to crop sky

- **Symptom:** After filtering FPs, face size was on target but headroom still ~25%; crop still 0:0.
- **Wrong assumption:** `scale = max(cover, face_fill_scale)` is enough to reframe.
- **Root cause:** If the face already fills ~26% and sits low, you must **zoom past cover** so `crop_y` can remove empty sky. Without `headroom_scale`, crop_y clamps to 0.
- **Fix:** `headroom_scale = out_h*(1−HEADROOM_TARGET)/(src_h−crown_y)`; `scale = max(cover, face_scale, headroom_scale)`, capped so face does not exceed ~34% after zoom.
- **Guardrail:** Non-identity `ffmpeg_vf` on Tanya (e.g. `scale=814:1448,crop=720:1280:18:126`).
- **Evidence:** Dry-run before headroom_scale vs after.

### 6. Static caption Y from one sample vs moving speaker

- **Symptom:** Overlap FAIL on some MOTION/random probes; headroom swung 0.01–0.33 across frames.
- **Wrong assumption:** One sample face → one caption Y safe for the whole segment.
- **Root cause:** Pose changes; lean-in enlarges face; MOTION overlays can hide faces.
- **Fix:** Multi-sample plan: median center/crown for crop; **max face_bottom** across samples for caption Y; chest-band floor 68%; audit hard-fail only on overlap / extreme headroom (>40%); soft notes for mild headroom drift; MOTION probes `require_face=False`.
- **Guardrail:** `sample_strategy` in `framing-plan.json`; visual_audit v2 face_check.
- **Evidence:** Pre-fix QC reasons listing per-probe headroom and overlap.

### 7. Director MOTION brief burned as “0 ₽”

- **Symptom:** Junk on-card text `0 ₽` from salvage of director brief.
- **Wrong assumption:** Quoting numbers/currency from briefs is safe audience punch.
- **Root cause:** Salvage pulled fragments from producer notes (`Индикатор… «0 ₽»… Зачем:`).
- **Fix:** Do not salvage director-shaped briefs into on-screen text; empty punch if unclean.
- **Guardrail:** `motion_on_screen_text` + visual_policy tests; Gate2 rejects director copy on card.
- **Evidence:** Author rejection; contract `motion_on_screen_texts` emptied on rebuild.

### 8. OpenCV 5 removed CascadeClassifier

- **Symptom:** `AttributeError: module 'cv2' has no attribute 'CascadeClassifier'`.
- **Wrong assumption:** Any current `opencv-python-headless` exposes Haar API.
- **Root cause:** OpenCV 5 moved Haar to contrib; default 5.x wheel lacked it.
- **Fix:** Pin `opencv-python-headless>=4.8,<5` (`requirements-framing.txt`).
- **Guardrail:** Dependency pin; framing tests import cascade path.
- **Evidence:** Local `cv2.__version__` 5.0.0 → 4.10.0.

### 9. Audit `require_face` too strict after aggressive zoom

- **Symptom:** QC FAIL `face not detected on probe frame` after successful reframe (face ~38–45% of frame).
- **Wrong assumption:** Same size filter for planning and for post-render audit.
- **Root cause:** Plan filter max height 40%; zoomed render faces often >40% → audit saw “no face”.
- **Fix:** Audit detection allows `max_height_ratio=0.55`; plan-time filter stays stricter.
- **Guardrail:** `verify_frame_face_caption(..., max_height_ratio=0.55)`.
- **Evidence:** Seg01 QC reasons before/after loosen.

### 10. Vision-model JPG descriptions vs pixels

- **Symptom:** Assistants repeatedly “saw” captions on the face after Y was already ~870–900.
- **Wrong assumption:** Read-tool image descriptions are ground truth for layout QC.
- **Root cause:** Caption models blur chin vs upper chest; yellow text draws attention to the face region.
- **Fix:** Learning rule: when vision ≠ pixels/detector, **pixels win**; log the disagreement.
- **Guardrail:** This file + learning-loop rule.
- **Evidence:** `yellow y median ~906` with face_bottom ~711 and overlap False on Tanya seg01.

## Outcome (Tanya Gate2, framing-face-v4)

- Auto crop applied (non-identity `ffmpeg_vf` on 01/02/03).
- `caption_pos_y` ≈ 870; yellow band ~900; face overlap False on sampled frames.
- Segment QC PASS; ledger `GATE2_REVIEW`.
- Canon: `docs/product/FRAMING.md`, `.cursor/rules/gate2-visual-policy.mdc`, `.cursor/rules/learning-loop.mdc`.
