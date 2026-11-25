#!/usr/bin/env python3
"""Post-render check: look at the rendered MP4, not at the plan.

* duration of video and audio against the frozen cut (±1 frame / ±40 ms);
* every frame at 10 fps is classified (split / full-screen speaker / full-screen visual) by comparison with the cut: shot types
  and their shares are measured on the render, no type may last longer than 4.5 s in a row, and the render must show the shot type the plan says;
* first frame of every split / visual segment: the visual panel must already be covered by a card (no empty panel after a cut);
* a split or visual segment never shows the same picture for longer than 1.5 s (frame differences inside the content area, 10 fps);
* a full-screen visual has no empty band taller than 18 % of the frame height (three frames per segment);
* the hook: frame 0 of the render is sharp (no blur-in) and the first caption word is solid; the ending shows the moving code-word reminder, and its
  code word box (>= 90 px tall, inside the visual half) is readable and unchanged from 2.5 s before the end to the last frame;
* palette: the share of visual time on a light background (measured on the frames) is at most 25 %;
* graphics never enter 1520..1920 (measured boxes, plus the pixels of every full-screen visual);
* every caption on its real frame: present, not across the seam, not clipped, not in the interface zone, not over the face
  detected ON THE RENDERED FRAME (Haar cascade, median of three nearby frames);
* no repeated take in the transcript;
* sync of the full-screen speaker clips: SSIM of the face area of the render against the cut at the same moment and at ±0.5 s (a clip with a planned
  punch-in zoom is compared with the cut scaled the same way about the same point);
* contact sheets for a human: a frame every 0.5 s with its timestamp, and one frame per caption group with the caption box (red) and
  the detected face (green) drawn.

The exit code is 1 when any of these fail.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

import geometry as geo
import measure_head as mh
import render_checks as rcx
import takes
import reel_plan as rp
from geometry import Box

LOG = logging.getLogger("postrender_check")
FPS = 30
SMALL_FPS = 10
SMALL_W, SMALL_H = 270, 480
SYNC_FACE = (200, 700, 880, 1400)   # source-pixel area used for the SSIM sync check
JITTER_OFFSETS = (-0.2, 0.0, 0.2)
TYPE_TOLERANCE_S = 0.25             # frames this close to a cut are not held against the plan's shot type


@dataclass
class Report:
    """Collected numbers and failures."""

    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)


def probe(path: Path) -> dict[str, float]:
    """Video and audio stream durations plus format duration, seconds."""
    raw = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout
    data = json.loads(raw)
    out = {"format": float(data["format"]["duration"])}
    for s in data["streams"]:
        if "duration" in s:
            out[s["codec_type"]] = float(s["duration"])
    return out


def frame_at(path: Path, t: float) -> np.ndarray:
    """Decode the frame at ``t`` (BGR)."""
    img = mh.extract_frame(path, max(0.0, t))
    if img is None and t > 0:
        # a seek exactly onto the last frame can return nothing (ffmpeg -ss at the EOF edge): take the frame half a frame earlier
        img = mh.extract_frame(path, max(0.0, t - 0.5 / FPS))
    if img is None:
        raise RuntimeError(f"cannot decode {path} at {t:.3f}")
    return img


def small_frames(path: Path, fps: int = SMALL_FPS) -> np.ndarray:
    """All frames at ``fps`` as small gray arrays, shape (N, 480, 270), in one ffmpeg pass."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={SMALL_W}:{SMALL_H}:flags=area", "-pix_fmt", "gray",
         "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, SMALL_H, SMALL_W)


def luma(img: np.ndarray, x: int, y: int) -> float:
    """Luminance (0-255) of one pixel."""
    b, g, r = (float(v) for v in img[int(y), int(x)])
    return 0.114 * b + 0.587 * g + 0.299 * r


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Mean SSIM of two equally sized grayscale images (Gaussian window, standard constants)."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = cv2.GaussianBlur(a, (11, 11), 1.5), cv2.GaussianBlur(b, (11, 11), 1.5)
    s_aa = cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a ** 2
    s_bb = cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b ** 2
    s_ab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + c1) * (2 * s_ab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (s_aa + s_bb + c2))
    return float(m.mean())


def detect_face_screen(render: Path, t: float, top: int, cascade: cv2.CascadeClassifier, pad: int) -> Box | None:
    """Face box on the rendered frame at ``t`` (median of three nearby frames), padded; ``top`` = first row of the speaker area."""
    found: list[tuple[int, int, int, int]] = []
    for dt in JITTER_OFFSETS:
        img = frame_at(render, t + dt)
        crop = img[top:, :] if top > 0 else img
        face = mh.detect_face(crop, cascade)
        if face:
            x, y, w, h = face
            found.append(mh.face_from_haar((x, y + top, w, h)))
    if not found:
        return None
    med = [sorted(f[i] for f in found)[len(found) // 2] for i in range(4)]
    return Box(*med).pad(pad)


def expected_type(shots: list[dict[str, Any]], t: float) -> str | None:
    """Shot type the plan puts at ``t``, None within ``TYPE_TOLERANCE_S`` of a cut."""
    for s in shots:
        if s["start"] - 1e-6 <= t < s["end"] - 1e-6:
            return None if min(t - s["start"], s["end"] - t) < TYPE_TOLERANCE_S else s["type"]
    return None


def zoom_at(shots: list[dict[str, Any]], t: float, factor: int = 1) -> tuple[float, float, float] | None:
    """``(z, ox, oy)`` of the punch-in zoom planned for the shot on screen at ``t``, origin divided by ``factor`` (small frames), else None."""
    for s in shots:
        if s["start"] - 1e-6 <= t < s["end"] - 1e-6:
            if s.get("zoom") and s.get("origin"):
                return (float(s["zoom"]), s["origin"][0] / factor, s["origin"][1] / factor)
            return None
    return None


def check_render(
    render: Path, cut: Path, meta: dict[str, Any], boxes: dict[str, Any], out_dir: Path, face_pad: int,
) -> Report:
    """Run every post-render check; write the contact sheets and the report into ``out_dir``."""
    rep = Report()
    cascade = mh.make_cascade()
    shots, groups = meta["shots"], meta["groups"]
    y0 = int(meta["layout"]["y0"])

    # 1. duration
    pr, pc = probe(render), probe(cut)
    rep.numbers["duration"] = {"render": pr, "cut": pc}
    if abs(pr.get("video", pr["format"]) - pc["video"]) > 1.5 / FPS:
        rep.failures.append(f"video duration {pr.get('video')} vs cut {pc['video']} (more than one frame)")
    if "audio" in pr and abs(pr["audio"] - pc["audio"]) > 0.04:
        rep.failures.append(f"audio duration {pr['audio']} vs cut {pc['audio']} (more than 40 ms)")
    if "audio" not in pr:
        rep.failures.append("render has no audio stream")

    # 2. shot types measured on the render
    rs, cs = small_frames(render), small_frames(cut)
    n = min(len(rs), len(cs))
    dt = 1.0 / SMALL_FPS
    types = [rcx.classify(rs[i], cs[i], y0 // 4, zoom_at(shots, i * dt, 4)) for i in range(n)]
    runs = rcx.runs_of(types, dt)
    shares = rcx.type_shares(types)
    mismatch = [f"{i * dt:.1f}s: render shows {t}, plan {e}" for i, t in enumerate(types)
                if (e := expected_type(shots, i * dt)) is not None and e != t]
    light = [rcx.is_light_frame(rs[i], types[i]) for i in range(n)]
    share_light = rcx.light_share(types, light)
    rep.numbers["palette"] = {"light_share_render": round(share_light, 4), "light_share_plan": rp.light_share_of(meta["scenes"]), "limit": rcx.LIGHT_SHARE_MAX,
                              "light_seconds": [round(i * dt, 1) for i in range(n) if light[i] and types[i] != geo.SHOT_SPEAKER][::5]}
    msg = rcx.palette_problem(share_light)
    if msg:
        rep.failures.append(msg)
    rep.numbers["shot_types"] = {"shares_render": shares, "shares_plan": rp.shares([rp.Shot(s["start"], s["end"], s["type"]) for s in shots]),
                                 "longest_run_s": round(max(b - a for _, a, b in runs), 2), "runs": [[t, round(a, 2), round(b, 2)] for t, a, b in runs],
                                 "frames_disagreeing_with_plan": len(mismatch)}
    zoom_rows: list[dict[str, Any]] = []
    for i_shot, s in enumerate(shots):              # a planned punch-in zoom must be visible on the render, not only assumed by the gates
        if not s.get("zoom"):
            continue
        k = min(n - 1, int((s["start"] + s["end"]) / 2 * SMALL_FPS))
        zoom = zoom_at(shots, (s["start"] + s["end"]) / 2, 4)
        msg = rcx.zoom_problem(f"shot {i_shot} zoom", rs[k], cs[k], zoom) if zoom else None
        zoom_rows.append({"shot": i_shot, "zoom": s["zoom"], "applied": msg is None})
        if msg:
            rep.failures.append(msg)
    rep.numbers["zoom"] = zoom_rows
    rep.failures += rcx.run_problems(runs)
    if len(mismatch) > 0.04 * n:
        rep.failures.append(f"{len(mismatch)} of {n} frames show another layout than the plan: {mismatch[:4]}")

    # 3. per segment: first-frame coverage, static pictures, interface zone
    seg_rows: list[dict[str, Any]] = []
    for i, s in enumerate(shots):
        if s["type"] == geo.SHOT_SPEAKER:
            continue
        label = f"shot {i} {s['type']} {s['start']:.1f}-{s['end']:.1f}"
        first = frame_at(render, s["start"] + 1 / 60)
        cov = rcx.coverage(first, s["type"])
        msg = rcx.coverage_problem(label, first, s["type"])
        if msg:
            rep.failures.append(msg)
        r0, r1 = (v // 4 for v in rcx.panel_region(s["type"]))
        a, b = int(round(s["start"] * SMALL_FPS)) + 1, min(int(round(s["end"] * SMALL_FPS)) - 1, n - 1)
        flags = [rcx.changed(rs[k], rs[k + 1], (r0, r1)) for k in range(a, b)]
        rep.failures += rcx.static_problems(label, flags, dt)
        longest = 0
        run = 0
        for f in flags:
            run = 0 if f else run + 1
            longest = max(longest, run)
        row: dict[str, Any] = {"shot": i, "type": s["type"], "start": s["start"], "end": s["end"], "first_frame_coverage": round(cov, 3),
                               "longest_static_s": round(longest * dt, 2),
                               "state_changes_per_s": round(sum(flags) / max(len(flags) * dt, dt), 2)}
        if s["type"] == geo.SHOT_VISUAL:
            ui = rcx.ui_zone_problem(label, frame_at(render, (s["start"] + s["end"]) / 2))
            row["interface_zone_clean"] = ui is None
            if ui:
                rep.failures.append(ui)
            bands = []
            for frac in (0.3, 0.55, 0.85):
                t_s = s["start"] + frac * (s["end"] - s["start"])
                img_s = frame_at(render, t_s)
                bands.append(rcx.empty_band(img_s))
                msg = rcx.empty_band_problem(f"{label} at {t_s:.1f} s", img_s)
                if msg:
                    rep.failures.append(msg)
            row["longest_empty_band_px"] = max(bands)
        seg_rows.append(row)
    rep.numbers["segments"] = seg_rows

    # 3b. hook: frame 0 is sharp, the first caption word is solid
    if groups and groups[0]["start"] <= 0.0:
        c0 = by_group_boxes(boxes, groups[0]["id"])
        first_word = Box(c0["words"][0]["x0"], c0["words"][0]["y0"], c0["words"][0]["x1"], c0["words"][0]["y1"]) if c0 and c0["words"] else None
        f0, f_settled = frame_at(render, 0.0), frame_at(render, 0.7)
        rep.numbers["hook"] = {"sharpness_frame0": round(rcx.sharpness(f0), 2), "sharpness_settled": round(rcx.sharpness(f_settled), 2)}
        if first_word is not None:
            rep.numbers["hook"]["first_word_contrast"] = [round(rcx.contrast_in(f0, first_word), 1), round(rcx.contrast_in(f_settled, first_word), 1)]
            rep.failures += rcx.hook_problems(f0, f_settled, first_word)
        else:
            rep.failures += rcx.hook_problems(f0, f_settled, Box(0, 0, 1, 1))

    # 3c. ending: the code word is shown again, with an animated action
    role = boxes.get("roles", {}).get("reminder")
    if meta.get("cta") is not None:
        if role is None:
            rep.failures.append("reminder: no element with data-role=\"reminder\" in the composition")
        else:
            last_scene = meta["scenes"][-1]
            rbox = Box(role["x0"], role["y0"], role["x1"], role["y1"])
            first_img, last_img = frame_at(render, last_scene["start"] + 0.1), frame_at(render, pc["video"] - 0.1)
            probs = rcx.reminder_problems(first_img, last_img, rbox)
            rep.numbers["reminder"] = {"box": [round(v) for v in (rbox.x0, rbox.y0, rbox.x1, rbox.y1)], "problems": probs}
            rep.failures += probs
            word = boxes.get("roles", {}).get("codeword")
            if word is None:
                rep.failures.append('ending: no element with data-role="codeword" in the composition')
            else:
                wbox = Box(word["x0"], word["y0"], word["x1"], word["y1"])
                t_end = pc["video"] - 1 / FPS
                t_typed = t_end - rp.REMINDER_HOLD_MIN_S
                wprobs = rcx.codeword_problems("ending", frame_at(render, t_typed), frame_at(render, t_end), wbox)
                rep.numbers["codeword"] = {"box": [round(v) for v in (wbox.x0, wbox.y0, wbox.x1, wbox.y1)], "height_px": round(wbox.h),
                                           "font_px": word.get("font"), "checked_at_s": [round(t_typed, 2), round(t_end, 2)], "problems": wprobs}
                rep.failures += wprobs

    # 4. boxes: nothing of the page may reach the interface zone
    lowest = 0.0
    for c in boxes["captions"]:
        lowest = max(lowest, c["y1"])
    for sc in boxes["scenes"]:
        for blk in sc["cards"] + sc["loose"] + sc["parts"]:
            lowest = max(lowest, blk["y1"])
    rep.numbers["lowest_graphic_y"] = round(lowest, 1)
    if lowest > geo.UI_TOP:
        rep.failures.append(f"a caption or card reaches y {lowest:.0f} > {geo.UI_TOP} (interface zone)")

    # 5. captions on their frames
    by_id = {c["id"]: c for c in boxes["captions"]}
    cap_rows: list[dict[str, Any]] = []
    sheet_caps: list[tuple[str, Image.Image]] = []
    face_hits = no_face = 0
    min_gap = float("inf")
    scene_bg = {sc["shot"]: sc["bg"] for sc in meta["scenes"]}
    for g in groups:
        c = by_id[g["id"]]
        box = Box(c["x0"], c["y0"], c["x1"], c["y1"])
        shot = shots[g["shot"]]
        t = round(min(g["end"] - 0.05, g["words"][-1]["start"] + 0.35), 3)
        img = frame_at(render, t)
        bg = rcx.background(img, int(box.y0), int(box.y1))
        row: dict[str, Any] = {"id": g["id"], "t": t, "shot": shot["type"], "mode": c["mode"], "text": g["text"],
                               "box": [round(v) for v in (box.x0, box.y0, box.x1, box.y1)], "words": len(g["words"]),
                               "lines": g["lines"]}
        face: Box | None = None
        if shot["type"] != geo.SHOT_VISUAL:
            top = geo.SEAM if shot["type"] == geo.SHOT_SPLIT else 0
            face = detect_face_screen(render, t, top, cascade, face_pad)
            if face is None:
                no_face += 1
            else:
                row["face"] = [round(v) for v in (face.x0, face.y0, face.x1, face.y1)]
                gap = max(face.y0 - box.y1, box.y0 - face.y1, face.x0 - box.x1, box.x0 - face.x1)
                row["gap_to_face_px"] = round(gap, 1)
                min_gap = min(min_gap, gap)
                face_hits += int(box.intersects(face))
        if shot["type"] == geo.SHOT_SPEAKER:
            present = float((cv2.cvtColor(img[int(box.y0):int(box.y1), int(box.x0):int(box.x1)], cv2.COLOR_BGR2GRAY) < 60).mean()) > 0.03
        else:
            present = rcx.caption_present(img, box, bg)
        row["present"] = bool(present)
        if not present:
            rep.failures.append(f"{g['id']}: caption not found on the rendered frame at {t}")
        probs = rcx.caption_problems(g["id"], img, box, shot["type"], bg, face)
        rep.failures += probs
        row["problems"] = probs
        cap_rows.append(row)
        sheet_caps.append((f"{g['id']} {shot['type']} {t:.1f}s", annotate(img, box, face)))
    rep.numbers["captions"] = {
        "groups": len(groups), "face_intersections": face_hits, "no_face_detected": no_face,
        "min_gap_to_face_px": None if min_gap == float("inf") else round(min_gap, 1),
        "font_px": meta.get("font_px"),
        "max_lines": max(len(g["lines"]) for g in groups), "max_words_per_line": max(max(g["lines"]) for g in groups),
    }
    face_expected = sum(1 for r in cap_rows if r["shot"] != geo.SHOT_VISUAL)
    if face_expected and no_face / face_expected > 0.10:
        rep.failures.append(f"face not detected on {no_face} of {face_expected} caption frames: the intersection test is not trustworthy")

    # 6. repeated takes in the transcript
    words = [rp.Word(w["w"], w["start"], w["end"]) for w in meta["words"]]
    rep_msgs = takes.check_takes(words, meta.get("repeats_ok", []))
    rep.numbers["repeated_takes"] = len(rep_msgs)
    rep.failures += rep_msgs

    # 7. sync of full-screen speaker shots
    sync_rows = [sync_check(render, cut, s["start"] + 0.1, zoom_at(shots, s["start"] + 0.1)) for s in shots if s["type"] == geo.SHOT_SPEAKER]
    rep.numbers["sync"] = sync_rows
    for r in sync_rows:
        if not (r["same"] > r["minus"] and r["same"] > r["plus"]):
            rep.failures.append(f"speaker clip at {r['t']} is out of sync: same {r['same']:.2f}, -0.5 s {r['minus']:.2f}, +0.5 s {r['plus']:.2f}")

    # contact sheets: a frame every 0.5 s with its time; one frame per caption group
    out_dir.mkdir(parents=True, exist_ok=True)
    times = rcx.sheet_times(pc["video"])
    frames = timeline_frames(render, times)
    save_sheet(frames, out_dir / "contact-sheet-shots.jpg", cols=12, thumb=(144, 256))
    tail_from = pc["video"] - 6.0
    save_sheet([f for t, f in zip(times, frames) if t >= tail_from - 1e-6], out_dir / "contact-sheet-ending.jpg", cols=8, thumb=(216, 384))
    save_sheet(sheet_caps, out_dir / "contact-sheet-captions.jpg", cols=9, thumb=(200, 356))
    (out_dir / "postcheck.json").write_text(json.dumps({"numbers": rep.numbers, "failures": rep.failures, "captions": cap_rows,
                                                        "frame_types_10fps": types}, indent=1, ensure_ascii=False), encoding="utf-8")
    return rep


def by_group_boxes(boxes: dict[str, Any], gid: str) -> dict[str, Any] | None:
    """Measured box record of one caption group."""
    return next((c for c in boxes["captions"] if c["id"] == gid), None)


def timeline_frames(render: Path, times: list[float]) -> list[tuple[str, Image.Image]]:
    """The frames at ``times`` (seconds), labelled with their time; one ffmpeg pass at 4 fps (every time is a multiple of 0.25 s)."""
    w, h = 270, 480
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(render), "-vf", f"fps=4,scale={w}:{h}:flags=area", "-pix_fmt", "rgb24",
                          "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w, 3)
    return [(f"{t:g}s", Image.fromarray(arr[min(int(round(t * 4)), len(arr) - 1)])) for t in times]


def sync_check(render: Path, cut: Path, t: float, zoom: tuple[float, float, float] | None = None) -> dict[str, Any]:
    """SSIM of the face area: render vs cut at the same moment and at ±0.5 s (the cut is scaled like the render when a punch-in zoom is planned)."""
    x0, y0, x1, y1 = SYNC_FACE
    a = cv2.cvtColor(frame_at(render, t), cv2.COLOR_BGR2GRAY)[y0:y1, x0:x1]
    out: dict[str, Any] = {"t": round(t, 3)}
    for key, dt in (("same", 0.0), ("minus", -0.5), ("plus", 0.5)):
        gray = cv2.cvtColor(frame_at(cut, max(0.0, t + dt)), cv2.COLOR_BGR2GRAY)
        if zoom is not None:
            gray = rcx.zoom_frame(gray, zoom[0], (zoom[1], zoom[2]))
        b = gray[y0:y1, x0:x1]
        out[key] = round(ssim(a, b), 3)
    return out


def annotate(img: np.ndarray, caption: Box | None, face: Box | None) -> Image.Image:
    """Draw the caption box (red), the face box (green) and the zone lines (yellow)."""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    for y in (geo.HEADER_BOTTOM, geo.SEAM, geo.UI_TOP):
        d.line([(0, y), (geo.FRAME_W, y)], fill=(255, 215, 0), width=3)
    if face:
        d.rectangle([face.x0, face.y0, face.x1, face.y1], outline=(0, 255, 0), width=5)
    if caption:
        d.rectangle([caption.x0, caption.y0, caption.x1, caption.y1], outline=(255, 0, 0), width=5)
    return pil


def save_sheet(items: list[tuple[str, Image.Image]], path: Path, cols: int, thumb: tuple[int, int]) -> None:
    """Tile labelled thumbnails into one JPEG."""
    rows = (len(items) + cols - 1) // cols
    label_h = 22
    sheet = Image.new("RGB", (cols * thumb[0], rows * (thumb[1] + label_h)), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for i, (label, im) in enumerate(items):
        x, y = (i % cols) * thumb[0], (i // cols) * (thumb[1] + label_h)
        sheet.paste(im.resize(thumb), (x, y + label_h))
        d.text((x + 4, y + 4), label, fill=(255, 255, 255))
    sheet.save(path, quality=88)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("render", type=Path)
    ap.add_argument("--cut", type=Path, required=True)
    ap.add_argument("--project", type=Path, required=True, help="folder with reel-meta.json and boxes.json")
    ap.add_argument("--out", type=Path, required=True, help="folder for contact sheets and postcheck.json")
    ap.add_argument("--face-pad", type=int, default=10)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    meta = json.loads((args.project / "reel-meta.json").read_text(encoding="utf-8"))
    boxes = json.loads((args.project / "boxes.json").read_text(encoding="utf-8"))
    rep = check_render(args.render, args.cut, meta, boxes, args.out, args.face_pad)
    LOG.info(json.dumps(rep.numbers, ensure_ascii=False, indent=1))
    if rep.failures:
        LOG.error("POST-RENDER CHECK FAILED:\n  " + "\n  ".join(rep.failures))
        return 1
    LOG.info("POST-RENDER CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
