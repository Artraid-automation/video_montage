"""Independent segment renderer with content-addressed cache."""

from __future__ import annotations

import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any

from .dependencies import segment_fingerprint
from .camera_move import shot_plan as camera_shot_plan
from .camera_move import zoom_filter as camera_zoom_filter
from .framing import build_segment_framing_plan, caption_layout_at_timestamp
from .grade import GRADE_FILTERS
from .io import atomic_write_json, read_json, resolve_project_path, working_output
from .media import require_tool, run, validate_video
from .motion import MOTION_WORKER_VERSION, render_motion_overlay
from .style_guard import collect_expected_recipes
from .style_overlay import render_framework_list_card, render_hook_title_card
from .transcript import (
    TranscriptEntry,
    VisualEntry,
    load_transcript,
    resolve_visual_end,
    resolve_visual_start,
)
from .verification import caption_burn_words_for_entry, caption_words_for_entry, expected_render_transcript
from .style_profile import captions as style_captions
from .style_profile import load_style, section as style_section, style_id_from
from .visual_policy import (
    CAPTION_MAX_WORDS,
    CAPTION_REQUIRED_ALIGNMENT,
    CAPTION_REQUIRED_COLOR,
    CAPTION_REQUIRED_FONT_CLASS,
    MOTION_MODE_OVERLAY,
    caption_font_size,
    caption_margin_v,
    caption_wrap_width_chars,
    hex_to_ass_colour,
    phrase_chunks,
    resolve_caption_font_ratio,
    resolve_hook_title_font_ratio,
    caption_display_text,
    wrap_caption_lines,
)


def _ffmpeg_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _subtract_suppress_windows(
    start: float,
    end: float,
    windows: list[tuple[float, float]],
    *,
    min_hold_s: float = 0.12,
) -> list[tuple[float, float]]:
    """Keep caption intervals that fall outside MOTION suppress windows."""
    if end <= start:
        return []
    segments: list[tuple[float, float]] = [(start, end)]
    for win_start, win_end in windows:
        if win_end <= win_start:
            continue
        next_segments: list[tuple[float, float]] = []
        for seg_start, seg_end in segments:
            if win_end <= seg_start or win_start >= seg_end:
                next_segments.append((seg_start, seg_end))
                continue
            if seg_start < win_start:
                next_segments.append((seg_start, min(seg_end, win_start)))
            if seg_end > win_end:
                next_segments.append((max(seg_start, win_end), seg_end))
        segments = next_segments
    return [(a, b) for a, b in segments if (b - a) >= min_hold_s]


def _caption_events_from_words(
    timed_words: list[dict[str, Any]],
    *,
    duration_s: float,
    max_words: int = CAPTION_MAX_WORDS,
) -> list[tuple[float, float, str]]:
    """Build phrase caption windows from real word timings (not even duration slices)."""
    cleaned: list[dict[str, Any]] = []
    for item in timed_words:
        token = " ".join(str(item.get("text", "")).replace("{", "(").replace("}", ")").split())
        if not token:
            continue
        start = max(0.0, float(item["start_s"]))
        end = min(float(duration_s), max(start + 0.04, float(item["end_s"])))
        cleaned.append({"text": token, "start_s": start, "end_s": end})
    if not cleaned:
        return []
    events: list[tuple[float, float, str]] = []
    for index in range(0, len(cleaned), max_words):
        chunk = cleaned[index : index + max_words]
        start = float(chunk[0]["start_s"])
        end = float(chunk[-1]["end_s"])
        if index + max_words < len(cleaned):
            next_start = float(cleaned[index + max_words]["start_s"])
            end = min(max(end, end + 0.08), max(start + 0.12, next_start - 0.04))
        else:
            end = min(float(duration_s), end + 0.18)
        phrase = " ".join(item["text"] for item in chunk)
        events.append((start, end, phrase))
    return events


def _write_caption_ass(
    path: Path,
    *,
    text: str,
    duration_s: float,
    width: int,
    height: int,
    pip_enabled: bool,
    pos_x: int | None = None,
    pos_y: int | None = None,
    max_width_px: int | None = None,
    font_ratio: float | None = None,
    suppress_windows: list[tuple[float, float]] | None = None,
    timed_words: list[dict[str, Any]] | None = None,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    caps = style_captions(style)
    font_size = caption_font_size(height, font_ratio=font_ratio, style=style)
    margin_v = caption_margin_v(height)
    right_margin = max(40, width // 4 + 48) if pip_enabled else 40
    primary = hex_to_ass_colour(str(caps["color"]))
    outline_colour = hex_to_ass_colour(str(caps.get("outline_color") or "#000000"))
    outline_px = max(1, round(font_size * float(caps.get("outline_ratio") or 0.025)))
    font_family = str(caps["font_family"])
    style_max_words = int(caps["max_words"])
    windows = list(suppress_windows or [])
    wrap_chars = caption_wrap_width_chars(font_size, max_width_px, style=style)
    if style_max_words <= 1:
        # Пословный стиль: ширина конверта роли не играет, в кадре всегда одно слово.
        phrase_words = 1
    else:
        # Fewer words per beat when the torso envelope is narrow (longform left-third).
        phrase_words = 2 if wrap_chars <= 16 else max(3, min(style_max_words, wrap_chars // 4))
    word_events = _caption_events_from_words(
        timed_words or [], duration_s=duration_s, max_words=phrase_words,
    )
    timing_mode = "source-words" if word_events else "even-slice-fallback"
    phrase_events: list[tuple[float, float, str]]
    if word_events:
        phrase_events = word_events
    else:
        chunks = phrase_chunks(
            text.replace("{", "(").replace("}", ")"), max_words=phrase_words, style=style,
        )
        if not chunks:
            chunks = [""]
        slice_s = max(duration_s / len(chunks), 0.12)
        cursor = 0.0
        phrase_events = []
        for index, chunk in enumerate(chunks):
            start = cursor
            end = duration_s if index == len(chunks) - 1 else min(duration_s, cursor + slice_s)
            cursor = end
            phrase_events.append((start, end, chunk))
    events: list[str] = []
    pos_prefix = ""
    if pos_x is not None and pos_y is not None:
        # \an8 = top-center: pos_y is the top of the block (below face/necklace).
        # Growing downward keeps text on the chest; \an5 previously put half the
        # block above pos_y and landed the first phrases on the neck.
        pos_prefix = "{\\an8\\pos(" + f"{int(pos_x)},{int(pos_y)}" + ")}"
    for start, end, chunk in phrase_events:
        display = chunk if str(caps.get("case")) == "as-spoken" else caption_display_text(chunk)
        safe = wrap_caption_lines(display, width_chars=wrap_chars, style=style)
        if not safe:
            continue
        for event_start, event_end in _subtract_suppress_windows(start, end, windows):
            events.append(
                f"Dialogue: 0,{_ass_time(event_start)},{_ass_time(event_end)},Caption,,0,0,0,,{pos_prefix}{safe}"
            )
    # Face-anchored: Style alignment must match \an8 or libass ignores \pos.
    style_alignment = 8 if pos_x is not None and pos_y is not None else int(caps["alignment"])
    body = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_family},{font_size},{primary},{primary},{outline_colour},&H80000000,{1 if int(caps.get("font_weight") or 0) >= 700 else 0},0,0,0,100,100,0,0,1,{outline_px},1,{style_alignment},40,{right_margin},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{chr(10).join(events)}
"""
    path.write_text(body, encoding="utf-8")
    return {
        "caption_font_size": font_size,
        "caption_alignment": CAPTION_REQUIRED_ALIGNMENT if pos_x is None else style_alignment,
        "caption_margin_v": margin_v,
        "caption_font_ratio": round(font_size / max(height, 1), 4),
        "caption_color": str(caps["color"]),
        "caption_font_class": str(caps["font_class"]),
        "caption_font_family": font_family,
        "caption_max_words": style_max_words,
        "caption_phrase_count": len(phrase_events),
        "caption_timing": timing_mode,
        "caption_pos_x": pos_x,
        "caption_pos_y": pos_y,
        "caption_max_width_px": max_width_px,
        "caption_wrap_chars": wrap_chars,
        "caption_placement": "face-chest" if pos_x is not None else "style-default",
        "caption_suppress_windows": [
            {"start_s": round(a, 3), "end_s": round(b, 3)} for a, b in windows
        ],
        "captions_suppressed_for_motion": bool(windows),
    }


def _filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace(":", "\\:").replace("'", "\\'")


def _render_entry(
    *,
    project_root: Path,
    segment_id: str,
    entry: TranscriptEntry,
    visual: VisualEntry | None,
    style_scene: dict[str, Any] | None,
    camera: Path | None,
    screen: Path | None,
    audio_source: Path,
    audio_offset_s: float,
    output: Path,
    profile: dict[str, Any],
    grade_name: str,
    framing_plan: dict[str, Any] | None = None,
    timed_caption_words: list[dict[str, Any]] | None = None,
    camera_move: dict[str, Any] | None = None,
) -> dict[str, Any]:
    width = int(profile["width"])
    height = int(profile["height"])
    fps = int(profile["fps"])
    style = load_style(style_id_from(profile))
    caption_ratio = resolve_caption_font_ratio(profile, style=style)
    hook_ratio = resolve_hook_title_font_ratio(profile, style=style)
    duration = entry.end_s - entry.start_s
    generated_motion: Path | None = None
    style_plate: Path | None = None
    caption_file: Path | None = None
    motion_spec = None
    loop_base = False
    talk = screen or camera
    if talk is None:
        raise ValueError(f"segment {segment_id} has no video source")
    base_start = entry.start_s
    motion_mode = None
    motion_on_screen = None
    motion_raw_brief = None
    motion_template = None
    motion_window_start_s = None
    motion_window_end_s = None
    style_recipe = None
    style_meta: dict[str, Any] = {}
    caption_pos = dict((framing_plan or {}).get("caption") or {})
    # Строка субтитра стоит НЕПОДВИЖНО весь сегмент: позиция берётся из плана
    # кадрирования (медиана лица), а не пересчитывается на каждом плане. Покадровый
    # пересчёт заставлял субтитр прыгать между склейками — это читается как брак.
    # Плашка-заголовок — другое дело: она привязана к подбородку на своём плане,
    # поэтому для неё лицо замеряется живьём.
    live_pos: dict[str, Any] = {}
    if (
        framing_plan
        and camera is not None
        and camera.is_file()
        and style_scene
        and style_scene.get("recipe") == "hook_title"
    ):
        sample_t = float(entry.start_s) + min(0.45, max(0.2, duration * 0.12))
        live = caption_layout_at_timestamp(
            camera,
            sample_t,
            framing_plan=framing_plan,
            out_w=width,
            out_h=height,
            cache_dir=output.parent / "caption-face-samples",
        )
        if live:
            live_pos = live
    layout_center_x = None
    if caption_pos.get("caption_pos_x") is not None:
        layout_center_x = int(caption_pos["caption_pos_x"])
    if visual and visual.type == "motion":
        motion_raw_brief = visual.brief
        motion_abs_start = resolve_visual_start([entry], visual)
        motion_abs_end = resolve_visual_end([entry], visual)
        local_start = max(0.0, motion_abs_start - float(entry.start_s))
        local_end = min(duration, max(local_start + 0.2, motion_abs_end - float(entry.start_s)))
        motion_window_start_s = round(local_start, 3)
        motion_window_end_s = round(local_end, 3)
        motion_window_dur = local_end - local_start
        generated_motion = output.with_suffix(".motion.mov")
        _motion_path, motion_spec = render_motion_overlay(
            generated_motion,
            brief=visual.brief,
            duration_s=motion_window_dur,
            width=width,
            height=height,
            fps=fps,
            center_x=layout_center_x,
        )
        motion_template = motion_spec.template
        motion_on_screen = motion_spec.label or None
        motion_mode = MOTION_MODE_OVERLAY
    elif visual and visual.type == "library-broll":
        if not visual.asset:
            raise ValueError(f"visual {visual.id} has no library asset")
        # B-roll still replaces picture while speech continues (faceless cutaway).
        talk = resolve_project_path(project_root, visual.asset)
        base_start = 0.0
        loop_base = True
    if style_scene and style_scene.get("recipe") == "hook_title":
        style_plate = output.with_suffix(".style.mov")
        face_bottom = None
        hook_pos = live_pos or caption_pos
        if hook_pos.get("face_bottom_max") is not None:
            face_bottom = int(hook_pos["face_bottom_max"])
        elif hook_pos.get("face"):
            face_box = hook_pos["face"]
            face_bottom = int(face_box.get("y", 0)) + int(face_box.get("h", 0))
        elif framing_plan:
            face_bottom = framing_plan.get("face_bottom_max")
            if face_bottom is None:
                face_out = framing_plan.get("face_output") or {}
                if face_out.get("h"):
                    face_bottom = int(face_out.get("y", 0)) + int(face_out["h"])
        style_meta = render_hook_title_card(
            style_plate,
            title=str(style_scene.get("title") or style_scene.get("what") or "Title"),
            duration_s=min(duration, 4.0),
            width=width,
            height=height,
            fps=fps,
            face_bottom_y=int(face_bottom) if face_bottom is not None else None,
            center_x=layout_center_x,
            font_ratio=hook_ratio,
            min_font_px=caption_font_size(height, font_ratio=caption_ratio) + 8,
        )
        style_recipe = "hook_title"
    elif style_scene and style_scene.get("recipe") == "framework_list":
        style_plate = output.with_suffix(".style.mov")
        lines = list(style_scene.get("lines") or [])
        active_from = style_scene.get("active_from")
        active_to = style_scene.get("active_to")
        render_framework_list_card(
            style_plate,
            lines=lines,
            duration_s=duration,
            width=width,
            height=height,
            fps=fps,
            active_index=int(style_scene.get("active_index") or 0),
            active_from=int(active_from) if active_from is not None else None,
            active_to=int(active_to) if active_to is not None else None,
            progressive=bool(style_scene.get("progressive", True)),
        )
        style_recipe = "framework_list"
    audio_start = entry.start_s + audio_offset_s
    audio_delay_ms = 0
    if audio_start < 0:
        audio_delay_ms = round(-audio_start * 1000)
        audio_start = 0.0
    command = [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y"]
    if loop_base:
        command.extend(["-stream_loop", "-1"])
    command.extend(["-ss", f"{base_start:.3f}", "-t", f"{duration:.3f}", "-i", str(talk)])
    command.extend(["-ss", f"{audio_start:.3f}", "-t", f"{duration:.3f}", "-i", str(audio_source)])
    use_pip = (
        screen is not None
        and camera is not None
        and not (visual and visual.type in {"motion", "library-broll"})
        and style_plate is None
    )
    input_index = 2
    if use_pip:
        command.extend(["-ss", f"{entry.start_s:.3f}", "-t", f"{duration:.3f}", "-i", str(camera)])
        input_index += 1
    motion_input = None
    motion_window_dur = 0.0
    if visual and visual.type == "motion":
        motion_window_dur = (motion_window_end_s or 0.0) - (motion_window_start_s or 0.0)
    if generated_motion is not None:
        command.extend(["-t", f"{max(motion_window_dur, 0.2):.3f}", "-i", str(generated_motion)])
        motion_input = input_index
        input_index += 1
    style_input = None
    if style_plate is not None:
        command.extend(["-t", f"{duration:.3f}", "-i", str(style_plate)])
        style_input = input_index
        input_index += 1
    if framing_plan and not loop_base and framing_plan.get("ffmpeg_vf"):
        scale = f"{framing_plan['ffmpeg_vf']},setsar=1"
    else:
        scale = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    grade = GRADE_FILTERS.get(grade_name)
    if grade is None:
        raise ValueError(f"unknown grade selection: {grade_name}")
    # Гарнитура стиля лежит в репозитории, а не в системе: без fontsdir libass молча
    # подставит первый попавшийся шрифт, и субтитры выйдут не тем, чем задумано.
    fonts_dir_arg = ""
    entry_caps = style_captions(style)
    font_file = entry_caps.get("font_file")
    if font_file:
        fonts_root = (Path(__file__).resolve().parents[2] / str(font_file)).parent
        if fonts_root.is_dir():
            fonts_dir_arg = f":fontsdir='{_filter_path(fonts_root)}'"

    # Движение кадра идёт ПОСЛЕ кадрирования по лицу: zoompan работает уже с приведённым
    # кадром, иначе наезд считался бы от исходного размера и уезжал бы мимо лица.
    if camera_move and not loop_base:
        move_chain = camera_zoom_filter(camera_move, width=width, height=height, fps=fps)
        filters = [f"[0:v]{scale},{move_chain},format=yuv420p[base]"]
    else:
        filters = [f"[0:v]{scale},fps={fps},format=yuv420p[base]"]
    current = "base"
    if use_pip:
        pip_width = max(120, width // 4)
        filters.append(f"[2:v]scale={pip_width}:-2,format=yuv420p[pip]")
        filters.append(f"[{current}][pip]overlay=W-w-24:H-h-24[with_pip]")
        current = "with_pip"
    if motion_input is not None:
        assert motion_window_start_s is not None and motion_window_end_s is not None
        filters.append(
            f"[{motion_input}:v]scale={width}:{height},format=rgba,"
            f"setpts=PTS+{motion_window_start_s}/TB[motion]"
        )
        filters.append(
            f"[{current}][motion]overlay=0:0:format=auto:"
            f"enable='between(t,{motion_window_start_s:.3f},{motion_window_end_s:.3f})'[with_motion]"
        )
        current = "with_motion"
    if style_input is not None:
        # MeVGa framework_list: blur+darken live A-roll under transparent list plate.
        if style_recipe == "framework_list":
            filters.append(
                f"[{current}]gblur=sigma=18,eq=brightness=-0.28:saturation=0.75,format=yuv420p[blurred]"
            )
            current = "blurred"
        filters.append(f"[{style_input}:v]scale={width}:{height},format=rgba[style]")
        filters.append(f"[{current}][style]overlay=0:0:format=auto[with_style]")
        current = "with_style"
    caption_meta: dict[str, Any] = {}
    suppress_windows: list[tuple[float, float]] = []
    if (
        generated_motion is not None
        and motion_spec is not None
        and motion_spec.suppress_captions
        and motion_window_start_s is not None
        and motion_window_end_s is not None
    ):
        suppress_windows = [(float(motion_window_start_s), float(motion_window_end_s))]
    captions_on = bool(profile.get("captions", True)) and style_plate is None
    if captions_on:
        caption_file = output.with_suffix(".captions.ass")
        caption_meta = _write_caption_ass(
            caption_file,
            text=entry.text,
            duration_s=duration,
            width=width,
            height=height,
            pip_enabled=use_pip,
            pos_x=caption_pos.get("caption_pos_x"),
            pos_y=caption_pos.get("caption_pos_y"),
            max_width_px=caption_pos.get("caption_max_width_px"),
            font_ratio=caption_ratio,
            style=style,
            suppress_windows=suppress_windows,
            timed_words=timed_caption_words,
        )
        filters.append(
            f"[{current}]{grade},subtitles=filename='{_filter_path(caption_file)}'"
            f"{fonts_dir_arg}[v]"
        )
    else:
        filters.append(f"[{current}]{grade}[v]")
        if bool(profile.get("captions", True)):
            caption_meta = {
                "caption_font_size": caption_font_size(height, font_ratio=caption_ratio),
                "caption_alignment": CAPTION_REQUIRED_ALIGNMENT,
                "caption_margin_v": caption_margin_v(height),
                "caption_color": CAPTION_REQUIRED_COLOR,
                "caption_font_class": CAPTION_REQUIRED_FONT_CLASS,
                "captions_suppressed_for_style": style_plate is not None,
                "captions_suppressed_for_motion": False,
            }
    camera_meta = {
        "camera_zoom_pct": float(camera_move["zoom_pct"]),
        "camera_cut_step_pct": float(camera_move["cut_step_pct"]),
        "camera_start_scale": float(camera_move["start_scale"]),
        "camera_end_scale": float(camera_move["end_scale"]),
    } if camera_move else {}
    audio_filter = "aresample=48000,asetpts=PTS-STARTPTS"
    extra_audio = str(profile.get("audio_filter") or "").strip()
    if extra_audio:
        audio_filter += f",{extra_audio}"
    if audio_delay_ms:
        audio_filter += f",adelay={audio_delay_ms}|{audio_delay_ms}"
    filters.append(f"[1:a]{audio_filter}[a]")
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
        "-t", f"{duration:.3f}",
        # Force yuv420p: rgba motion overlays / ASS leave yuv444p otherwise
        # (Telegram: black video + audio, then "unsupported format").
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-preset", str(profile.get("preset", "veryfast")),
        "-crf", str(profile.get("crf", 20)), "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output),
    ])
    try:
        run(command)
    finally:
        if generated_motion:
            generated_motion.unlink(missing_ok=True)
        if style_plate:
            style_plate.unlink(missing_ok=True)
        if caption_file:
            caption_file.unlink(missing_ok=True)
    return {
        "motion_mode": motion_mode,
        "motion_on_screen": motion_on_screen,
        "motion_raw_brief": motion_raw_brief,
        "motion_template": motion_template,
        "motion_window_start_s": motion_window_start_s,
        "motion_window_end_s": motion_window_end_s,
        "style_recipe": style_recipe,
        **caption_meta,
        **camera_meta,
        **style_meta,
    }



def _source_fps(record: dict[str, Any] | None) -> float:
    """Объявленная частота кадров исходника — по ней ограничивается рендер."""
    if not record:
        return 0.0
    for stream in record.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        for key in ("r_frame_rate", "avg_frame_rate"):
            raw = stream.get(key)
            if not raw or raw == "0/0":
                continue
            try:
                value = float(Fraction(str(raw)))
            except (ValueError, ZeroDivisionError):
                continue
            if value > 0:
                return value
    return 0.0


def concat_clips(clips: list[Path], output: Path, *, profile: dict[str, Any] | None = None) -> None:
    """Concatenate clip MP4s into one review file.

    Re-encodes (not stream-copy): copy-concat of independently encoded clips
    often produces timestamp/GOP seams that some players stop on mid-file.
    """
    if not clips:
        raise ValueError("cannot concatenate an empty segment")
    concat_file = output.with_suffix(".concat.txt")
    concat_file.write_text("".join(f"file '{_ffmpeg_path(path)}'\n" for path in clips), encoding="utf-8")
    fps = int((profile or {}).get("fps", 30))
    crf = str((profile or {}).get("crf", 20))
    preset = str((profile or {}).get("preset", "veryfast"))
    try:
        with working_output(output) as temporary:
            run([
                require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-fps_mode", "cfr", "-r", str(fps),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
                "-preset", preset, "-crf", crf,
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", str(temporary),
            ])
    finally:
        concat_file.unlink(missing_ok=True)


def render_segment(
    project_root: Path,
    *,
    segment_id: str,
    raw_manifest: dict[str, Any],
    config: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    group = next((item for item in raw_manifest["segments"] if f"{item['number']:02d}" == segment_id), None)
    if group is None:
        raise ValueError(f"raw segment is missing: {segment_id}")
    media = {item["id"]: item for item in raw_manifest["files"]}
    feeds = group["feeds"]
    camera_record = media.get(feeds.get("camera"))
    screen_record = media.get(feeds.get("screen"))
    camera = resolve_project_path(project_root, camera_record["path"]) if camera_record else None
    screen = resolve_project_path(project_root, screen_record["path"]) if screen_record else None
    audio_record = media.get(feeds.get("audio"))
    audio_source = resolve_project_path(project_root, audio_record["path"]) if audio_record else (camera or screen)
    if audio_source is None:
        raise ValueError(f"segment {segment_id} has no audio source")
    phase1_root = project_root / "03_phase1" / "segments" / segment_id
    source_transcript = read_json(phase1_root / "source-transcript.json")
    entries, visuals = load_transcript(phase1_root / "transcript.md", source_transcript)
    visual_plan = read_json(phase1_root / "visual-plan.json") if (phase1_root / "visual-plan.json").is_file() else {}
    style_by_anchor = {
        str(item.get("anchor")): item
        for item in (visual_plan.get("style_scenes") or [])
        if isinstance(item, dict) and item.get("anchor")
    }
    kept = [item for item in entries if item.kind == "keep"]
    expected = expected_render_transcript(
        entries,
        source_words=source_transcript.get("words") or [],
    )
    sync = read_json(phase1_root / "sync-report.json")
    audio_offset = float(sync.get("offset_s", 0.0)) if audio_record else 0.0
    # Исправления распознавания со стола: меняют написание в субтитре, но не звук
    # и не сверку — файла может не быть, это норма для проекта без ручных правок.
    rewrites_path = phase1_root / "caption-rewrites.json"
    caption_rewrites = (
        {str(key): str(value) for key, value in read_json(rewrites_path).items()}
        if rewrites_path.is_file() else {}
    )
    grade_manifest = read_json(phase1_root / "grade-manifest.json")
    grade_name = grade_manifest.get("selected") or config.get("default_grade", "neutral")
    profile = {
        "width": 640, "height": 360, "fps": 25, "crf": 20, "preset": "veryfast", "captions": True,
        # Имя стиля обязано ехать вместе с профилем: субтитры рисуются по нему,
        # и Gate 2 судит по нему же. Без этой строки рендер молча собирал дефолтным
        # видом, хотя проект создан под другим стилем.
        "style_version": config.get("style_version"),
        **config.get("render_profile", {}),
    }
    # Частота кадров рендера не может быть выше исходной. Апскейл 25→60 не добавляет
    # плавности — он дублирует кадры; а когда часть планов вышла в 25, часть в 60,
    # склейка в режиме CFR затыкает разрывы стоп-кадрами и растягивает картинку
    # относительно звука (замер 30.08 на pilot-live2: 61,8 с застываний на 181,6 с,
    # видеодорожка длиннее звуковой на 25,5 с).
    source_fps = _source_fps(camera_record or screen_record)
    if source_fps > 0 and float(profile.get("fps") or 0) > source_fps + 0.01:
        profile["fps"] = int(round(source_fps))
    raw_records = [media[media_id] for media_id in feeds.values()]
    fingerprint = segment_fingerprint(
        project_root,
        segment_id=segment_id,
        raw_records=raw_records,
        transcript_path=phase1_root / "transcript.md",
        visual_plan_path=phase1_root / "visual-plan.json",
        sync_report_path=phase1_root / "sync-report.json",
        grade_manifest_path=phase1_root / "grade-manifest.json",
        style_version=str(config.get("style_version", "default-v1")),
        provider_versions={
            "render": "ffmpeg-overlay-v25-brand-atomic",
            "verification": str(config.get("verification_transcription", {}).get("provider", "unconfigured")),
            "framing": "framing-face-v5-yunet",
            "motion": MOTION_WORKER_VERSION,
        },
        rule_versions=config.get("rule_versions", {}),
        render_profile=profile,
    )
    cache_dir = project_root / "04_phase2" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{fingerprint.split(':', 1)[1]}.mp4"
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "review.mp4"
    cache_hit = False
    clip_contracts: list[dict[str, Any]] = []
    if cache_path.is_file():
        validate_video(cache_path)
        shutil.copy2(cache_path, output)
        cache_hit = True
        contract_path = output_root / "render-contract.json"
        if contract_path.is_file():
            clip_contracts = [read_json(contract_path)]
    else:
        framing_plan = None
        existing_plan = output_root / "framing-plan.json"
        if camera is not None and existing_plan.is_file():
            framing_plan = read_json(existing_plan)
        elif camera is not None:
            sample_times: list[float] = []
            for keep in kept:
                start = float(keep.start_s)
                end = float(keep.end_s)
                mid = (start + end) / 2
                sample_times.extend([
                    max(0.05, start + 0.25),
                    mid,
                    max(0.05, end - 0.25),
                ])
            sample_times = sorted({round(t, 2) for t in sample_times})[:12]
            framing_plan = build_segment_framing_plan(
                project_root,
                segment_id=segment_id,
                media_path=camera,
                output_dir=output_root,
                out_w=int(profile["width"]),
                out_h=int(profile["height"]),
                sample_times_s=sample_times or [0.5, 1.5, 3.0],
            )
        clips_dir = output_root / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        visual_by_anchor = {item.anchor: item for item in visuals}
        words_by_id = {
            str(item["id"]): item
            for item in (source_transcript.get("words") or [])
            if isinstance(item, dict) and item.get("id") is not None
        }
        # Один план движения на весь сегмент: ступень крупности считается от предыдущего
        # плана, поэтому её нельзя решать внутри отдельного клипа.
        segment_style = load_style(style_id_from(profile))
        camera_settings = style_section(segment_style, "camera")
        camera_plan: dict[str, dict[str, Any]] = {}
        if camera_settings:
            shots = [
                {"id": entry.id, "duration_s": max(0.0, float(entry.end_s) - float(entry.start_s))}
                for entry in kept
            ]
            camera_plan = {
                item["shot_id"]: item
                for item in camera_shot_plan(shots, camera=camera_settings, seed=segment_id)
            }
        clips = []
        for index, entry in enumerate(kept, 1):
            clip = clips_dir / f"clip-{index:03d}-{entry.id}.mp4"
            meta = _render_entry(
                project_root=project_root,
                segment_id=segment_id,
                entry=entry,
                visual=visual_by_anchor.get(entry.id),
                style_scene=style_by_anchor.get(entry.id),
                camera=camera,
                screen=screen,
                audio_source=audio_source,
                audio_offset_s=audio_offset,
                output=clip,
                profile=profile,
                grade_name=grade_name,
                framing_plan=framing_plan,
                timed_caption_words=caption_burn_words_for_entry(entry, words_by_id, caption_rewrites),
                camera_move=camera_plan.get(entry.id),
            )
            clip_contracts.append(meta)
            clips.append(clip)
        concat_clips(clips, output, profile=profile)
        shutil.copy2(output, cache_path)
    motion_texts = [item["motion_on_screen"] for item in clip_contracts if item.get("motion_on_screen")]
    motion_raw = [item["motion_raw_brief"] for item in clip_contracts if item.get("motion_raw_brief")]
    # Prefer a clip that actually burned face-chest captions (not motion-suppressed).
    caption_meta = next(
        (
            item for item in clip_contracts
            if item.get("caption_pos_x") is not None and not item.get("captions_suppressed_for_motion")
        ),
        None,
    ) or next(
        (item for item in clip_contracts if "caption_font_size" in item and not item.get("captions_suppressed_for_motion")),
        None,
    ) or next((item for item in clip_contracts if "caption_font_size" in item), {})
    # If cache hit without contract, force FAIL-closed defaults that policies will catch
    # unless a prior contract exists — rewrite from profile policy for cache-only path.
    if cache_hit and not caption_meta:
        cache_style = load_style(style_id_from(profile))
        cache_caps = style_captions(cache_style)
        caption_meta = {
            "caption_font_size": caption_font_size(
                int(profile["height"]),
                font_ratio=resolve_caption_font_ratio(profile, style=cache_style),
                style=cache_style,
            ),
            "caption_alignment": int(cache_caps["alignment"]),
            "caption_margin_v": caption_margin_v(int(profile["height"])),
            "caption_color": str(cache_caps["color"]),
            "caption_font_class": str(cache_caps["font_class"]),
        }
    motion_modes = {item.get("motion_mode") for item in clip_contracts if item.get("motion_mode")}
    motion_mode = MOTION_MODE_OVERLAY if MOTION_MODE_OVERLAY in motion_modes or motion_texts else (
        next(iter(motion_modes), None)
    )
    if visuals and any(item.type == "motion" for item in visuals) and cache_hit and motion_mode != MOTION_MODE_OVERLAY:
        # Legacy cache without overlay contract — fail closed.
        motion_mode = "replace"
        motion_raw = [item.brief for item in visuals if item.type == "motion"]
    style_expected = collect_expected_recipes(visual_plan.get("style_scenes") if isinstance(visual_plan, dict) else None)
    style_applied = sorted({
        str(item["style_recipe"])
        for item in clip_contracts
        if item.get("style_recipe")
    })
    # Cache-hit contracts store recipes at the top level, not per-clip.
    if not style_applied:
        for item in clip_contracts:
            for recipe in item.get("style_recipes_applied") or []:
                if str(recipe):
                    style_applied.append(str(recipe))
        style_applied = sorted(set(style_applied))
    segment_style = load_style(style_id_from(profile))
    segment_caps = style_captions(segment_style)
    contract = {
        "schema_version": 1,
        "kind": "render-contract",
        "style_id": str(segment_style.get("id")),
        "worker_version": "ffmpeg-overlay-v25-brand-atomic",
        "segment_id": segment_id,
        "width": int(profile["width"]),
        "height": int(profile["height"]),
        # Частота едет в контракте: гейт обязан судить по тому, что реально собрано.
        # Профиль просит 60, но потолок ставится по исходнику уже на прогоне, и без
        # этой строки техпроверка валила сборку за «frame rate mismatch».
        "fps": int(profile["fps"]),
        # Число планов нужно гейту длительности: каждый план не может быть точнее
        # одного кадра, и на пятидесяти стыках округление копится в полсекунды.
        "clip_count": len(clip_contracts),
        "motion_mode": motion_mode,
        "motion_count": sum(1 for item in visuals if item.type == "motion"),
        "motion_on_screen_texts": motion_texts,
        "motion_raw_briefs": motion_raw,
        "caption_font_size": int(caption_meta.get(
            "caption_font_size",
            caption_font_size(
                int(profile["height"]),
                font_ratio=resolve_caption_font_ratio(profile, style=segment_style),
                style=segment_style,
            ),
        )),
        "caption_alignment": int(caption_meta.get("caption_alignment", int(segment_caps["alignment"]))),
        "caption_margin_v": int(caption_meta.get("caption_margin_v", caption_margin_v(int(profile["height"])))),
        "caption_color": str(caption_meta.get("caption_color", str(segment_caps["color"]))),
        "caption_font_class": str(caption_meta.get("caption_font_class", str(segment_caps["font_class"]))),
        "caption_pos_x": caption_meta.get("caption_pos_x"),
        "caption_pos_y": caption_meta.get("caption_pos_y"),
        "caption_placement": caption_meta.get("caption_placement"),
        "caption_timing": caption_meta.get("caption_timing"),
        "style_recipes_expected": style_expected,
        "style_recipes_applied": style_applied,
        "camera_moving_share": round(
            sum(1 for item in clip_contracts if abs(float(item.get("camera_zoom_pct") or 0.0)) > 1e-6)
            / len(clip_contracts), 3,
        ) if clip_contracts else 0.0,
        "camera_cut_steps_pct": [
            round(float(item["camera_cut_step_pct"]), 3)
            for item in clip_contracts if item.get("camera_cut_step_pct")
        ],
        "hook_title_font_size": next(
            (item.get("hook_title_font_size") for item in clip_contracts if item.get("hook_title_font_size")),
            None,
        ),
        "hook_title_y_center_ratio": next(
            (item.get("hook_title_y_center_ratio") for item in clip_contracts if item.get("hook_title_y_center_ratio") is not None),
            None,
        ),
        "hook_title_pos_y": next(
            (item.get("hook_title_pos_y") for item in clip_contracts if item.get("hook_title_pos_y") is not None),
            None,
        ),
        "cache_hit": cache_hit,
        "framing_plan": "framing-plan.json" if (output_root / "framing-plan.json").is_file() else None,
    }
    contract_path = output_root / "render-contract.json"
    atomic_write_json(contract_path, contract)
    expected_path = output_root / "expected-transcript.json"
    atomic_write_json(expected_path, expected)
    return {
        "segment_id": segment_id,
        "fingerprint": fingerprint,
        "cache_hit": cache_hit,
        "output": output,
        "expected_path": expected_path,
        "expected": expected,
        "contract_path": contract_path,
        "contract": contract,
    }
