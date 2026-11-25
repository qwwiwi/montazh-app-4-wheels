"""Pre-render gate: real Chrome boxes and the plan against the canon. The build FAILS on any hit.

Inputs are the ``boxes.json`` written by ``measure_boxes.mjs`` and the ``BuildInfo`` of the generator. Rules (canon of the
reference reels plus the owner's hard rules):

* every caption box stays in the band of its shot type, never straddles the seam, is never clipped by the frame margins, never
  touches y < 115 or 1520..1920 and never meets the face box of its shot;
* scene content stays inside its strip (split: y 115..790, full screen: y 115..1236), text stays inside its card;
* a caption never overlaps scene content on screen at the same time;
* montage rhythm: no shot type longer than 4.5 s in a row, speaker «breath» 1.3-3 s, shares of the three types, call to action 5-8 s;
* a scene never shows the same picture for longer than 1.5 s (state times declared by the scene builders);
* text inside a scene is at least 32 px, code and terminal text at least 40 px, contrast at least 4.5:1 (computed in Chrome, plus a lint of the generated CSS/markup);
* the code word of the ending is the biggest text of the last scene, at least 90 px tall and inside the visual half;
* no decorative filler, no misspelled on-screen words, light scenes at most 25 % of the visual time;
* the ending carries a reminder of the code word;
* no unexplained repeated take in the transcript.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geometry as geo
import reel_plan as rp
import scene_base
import takes
from build_composition import BuildInfo
from geometry import Box, Violation
from reel_config import ReelConfig

ZONE_SIDE = 20
TEXT_TOLERANCE = 2.0
MIN_TEXT_PX = scene_base.MIN_TEXT_PX     # labels and body text of a mock-up on a 1080 px wide frame (readable on a phone)
MIN_MONO_PX = scene_base.MIN_MONO_PX     # code and terminal text
MIN_CONTRAST = 4.5                       # WCAG ratio of a text colour to its background
CODEWORD_MIN_H = 90                      # the ending's code word: box at least this tall


def _linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def contrast_ratio(fg: tuple[float, ...] | list[float], bg: tuple[float, ...] | list[float]) -> float:
    """WCAG contrast ratio of two RGB colours (1..21)."""
    def lum(c: tuple[float, ...] | list[float]) -> float:
        return 0.2126 * _linear(c[0]) + 0.7152 * _linear(c[1]) + 0.0722 * _linear(c[2])
    a, b = lum(fg), lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _box(d: dict[str, Any]) -> Box:
    return Box(d["x0"], d["y0"], d["x1"], d["y1"])


def load_boxes(path: Path) -> dict[str, Any]:
    """Read ``boxes.json``."""
    return json.loads(path.read_text(encoding="utf-8"))


def strip_for(zone: str) -> Box:
    """Allowed area of scene content: split cards end above the caption band, full-screen cards above the free band."""
    bottom = geo.SPLIT_CONTENT_BOTTOM if zone == "split" else geo.FULL_CONTENT_BOTTOM
    return Box(ZONE_SIDE, geo.HEADER_BOTTOM, geo.FRAME_W - ZONE_SIDE, bottom)


def zone_violations(scene: dict[str, Any]) -> list[Violation]:
    """Cards, loose items and text parts of one measured scene against its strip; text against its card."""
    out: list[Violation] = []
    strip = strip_for(scene["zone"])
    blocks = [(f"card {c['id']}", _box(c)) for c in scene["cards"]] + [(f"item {p['text']}", _box(p)) for p in scene["loose"]]
    blocks += [(f"text «{p['text'][:20]}»", _box(p)) for p in scene["parts"]]
    for label, b in blocks:
        if b.x0 < strip.x0 - 0.5 or b.x1 > strip.x1 + 0.5 or b.y0 < strip.y0 - 0.5 or b.y1 > strip.y1 + 0.5:
            out.append(Violation(f"{scene['id']}:{label}", "zone",
                                 f"{geo.fmt(b)} outside strip {geo.fmt(strip)} ({scene['zone']})"))
    cards = {c["id"]: _box(c) for c in scene["cards"]}
    for p in scene["parts"]:
        b = _box(p)
        card = cards.get(p["card"]) if p.get("card") else None
        if card is not None and (b.x0 < card.x0 - TEXT_TOLERANCE or b.x1 > card.x1 + TEXT_TOLERANCE
                                 or b.y0 < card.y0 - TEXT_TOLERANCE or b.y1 > card.y1 + TEXT_TOLERANCE):
            out.append(Violation(f"{scene['id']}:text «{p['text'][:20]}»", "overflow", f"{geo.fmt(b)} sticks out of its card {geo.fmt(card)}"))
        font = p.get("font")
        need = MIN_MONO_PX if p.get("mono") else MIN_TEXT_PX
        if font is not None and font < need - 0.01 and p["tag"] != "svg":
            out.append(Violation(f"{scene['id']}:text «{p['text'][:20]}»", "font-size", f"{font:.0f} px < {need} px ({'code/terminal' if p.get('mono') else 'text'})"))
        fg, bgc = p.get("fg"), p.get("bg")
        if fg and bgc and p.get("opacity", 1.0) >= 0.5 and p["tag"] != "svg" and contrast_ratio(fg, bgc) < MIN_CONTRAST:
            out.append(Violation(f"{scene['id']}:text «{p['text'][:20]}»", "contrast", f"{contrast_ratio(fg, bgc):.1f}:1 < {MIN_CONTRAST}:1 (dim text on its card)"))
        if b.y1 > geo.BUTTONS_Y0 and b.y0 < geo.BUTTONS_Y1 and b.x1 > geo.BUTTONS_X0 and p["tag"] != "svg":
            out.append(Violation(f"{scene['id']}:text «{p['text'][:20]}»", "buttons", f"x1 {b.x1:.0f} meets the button column"))
    return out


def plan_violations(info: BuildInfo) -> list[Violation]:
    """Rhythm, call-to-action window, static scenes and repeated takes (no browser needed)."""
    plan = info.plan
    out = [Violation("rhythm", "rhythm", p) for p in rp.rhythm_problems(plan.shots, plan.cta)]
    for sc in plan.scenes:
        for a, b in rp.static_gaps(info.scene_states.get(sc.n, []), sc.start, sc.end):
            out.append(Violation(f"scene{sc.n}:{sc.kind}", "static", f"no new state between {a:.2f} s and {b:.2f} s ({b - a:.2f} s > {rp.MAX_STATIC_S} s)"))
    for msg in takes.check_takes(list(info.words), plan.repeats_ok):
        out.append(Violation("transcript", "repeat", msg))
    for msg in rp.reminder_problems(plan):
        out.append(Violation("ending", "reminder", msg))
    for msg in rp.palette_problems(plan):
        out.append(Violation("palette", "palette", msg))
    return out


def ending_violations(boxes: dict[str, Any], plan: rp.Plan) -> list[Violation]:
    """The code word of the ending (``data-role="codeword"``): inside the visual half, at least 90 px tall, the biggest text of its scene."""
    if plan.cta is None:
        return []
    word = boxes.get("roles", {}).get("codeword")
    if word is None:
        return [Violation("ending", "codeword", 'no element with data-role="codeword" in the composition')]
    out: list[Violation] = []
    b = _box(word)
    if b.h < CODEWORD_MIN_H:
        out.append(Violation("ending", "codeword", f"the code word box is {b.h:.0f} px tall < {CODEWORD_MIN_H} px"))
    if b.y0 < geo.HEADER_BOTTOM or b.y1 > geo.SEAM or b.x0 < 0 or b.x1 > geo.FRAME_W:
        out.append(Violation("ending", "codeword", f"the code word box {geo.fmt(b)} is not inside the visual half (y {geo.HEADER_BOTTOM}..{geo.SEAM})"))
    last = boxes["scenes"][-1] if boxes.get("scenes") else None
    if last is not None:
        biggest = max((p.get("font") or 0.0 for p in last["parts"] if p["tag"] != "svg" and p.get("text", "").strip() != word.get("text")), default=0.0)
        if word.get("font") is not None and word["font"] < biggest + 0.01:
            out.append(Violation("ending", "codeword", f"the code word ({word['font']:.0f} px) is not the largest text of the last scene ({biggest:.0f} px)"))
    return out


def run_gate(info: BuildInfo, boxes: dict[str, Any], cfg: ReelConfig) -> list[Violation]:
    """Return every violation found (an empty list means the build may be rendered)."""
    out: list[Violation] = list(info.analysis.problems) + plan_violations(info)
    if not boxes.get("fontsOk"):
        out.append(Violation("fonts", "font", f"{boxes.get('family', 'Golos Text')} / JetBrains Mono did not load; Chrome would substitute its own"))

    plan = info.plan
    by_id = {c["id"]: c for c in boxes["captions"]}
    for gid in sorted({g.id for g in info.groups if g.id in info.analysis.slots} - set(by_id)):
        out.append(Violation(gid, "missing", "caption group not found in the measured page"))

    cap_boxes: list[tuple[str, float, float, Box]] = []
    for g in info.groups:
        c = by_id.get(g.id)
        if c is None:
            continue
        shot = plan.shots[g.shot]
        slot = info.analysis.slots[g.id]
        shot_info = info.analysis.info(shot)
        face = shot_info.face_screen if shot.type != geo.SHOT_VISUAL else None
        head_top = shot_info.head_screen.y0 if shot_info.head_screen else None
        box = _box(c)
        out += geo.check_caption(g.id, box, shot.type, slot.mode, face, head_top=head_top, face_margin=cfg.face_margin)
        for w in c["words"]:
            wb = _box(w)
            if wb.x0 < box.x0 - 0.5 or wb.x1 > box.x1 + 0.5 or wb.y0 < box.y0 - 0.5 or wb.y1 > box.y1 + 0.5:
                out.append(Violation(g.id, "clipped", f"word «{w['text']}» {geo.fmt(wb)} outside its caption {geo.fmt(box)}"))
        if len(c["words"]) != len(g.words):
            out.append(Violation(g.id, "words", f"{len(c['words'])} words on the page, {len(g.words)} in the group"))
        cap_boxes.append((g.id, g.start, g.end, box))

    out += ending_violations(boxes, plan)
    for sc in boxes["scenes"]:
        out += zone_violations(sc)
        z0, z1 = sc["start"], sc["start"] + sc["dur"]
        blocks = [_box(c) for c in sc["cards"]] + [_box(p) for p in sc["loose"]]
        for gid, g0, g1, cb in cap_boxes:
            if g0 < z1 - 0.02 and z0 < g1 - 0.02 and any(cb.intersects(b) for b in blocks):
                out.append(Violation(gid, "overlap", f"caption meets content of {sc['id']} ({sc['kind']})"))
    return out


def format_violations(violations: list[Violation]) -> str:
    """Human-readable report, one line per violation."""
    return "\n".join(f"  [{v.rule}] {v.caption_id}: {v.detail}" for v in violations)
