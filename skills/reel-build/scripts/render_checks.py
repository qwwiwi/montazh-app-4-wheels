"""Pure checks on rendered frames and on the plan numbers; the driver ``postrender_check.py`` feeds them real frames.

Every function takes arrays or numbers and returns problems as strings (empty = pass), so each rule is tested with synthetic
frames. Frames are BGR uint8 arrays (full 1080x1920 unless a name says «small»).

Rules (repository docs/GOLDEN.md and the owner's hard rules):

* caption: not across the seam, not clipped by the frame edge, not in 1520..1920, not over the face (``caption_problems``);
* visual panel coverage from the first frame of a segment (``coverage_problem``): a cut must land on a card, not on an empty panel;
* a visual never shows the same picture for longer than 1.5 s (``static_problems``, canon 2 s with a margin);
* a full-screen visual has no large empty band (``empty_band_problem``): the cards fill the frame, nothing is left empty below them;
* the hook: frame 0 is sharp (no blur-in) and its first caption word is solid, not mid-fade (``hook_problems``);
* the ending shows a moving reminder of the code word (``reminder_problems``), and its code word box stays tall, inside the visual half and unobstructed
  from the moment it is typed to the last frame (``codeword_problems``);
* dark + orange is the default palette: light-background frames are at most 25 % of the visual time (``light_share``, ``palette_problem``);
* the same shot type never lasts longer than 4.5 s in a row, judged on the rendered frames (``classify``, ``run_problems``);
* nothing of the graphics in 1520..1920 of a full-screen visual (``ui_zone_problem``);
* no repeated take in the transcript (``takes.check_takes``).
"""

from __future__ import annotations

import math

import cv2
import numpy as np

import geometry as geo
from geometry import Box

INK_DELTA = 45               # a pixel differs from the local background by more than this (max channel) = ink
COVER_DELTA = 8              # card fills differ from the background by less than a text pixel does
COVERAGE_MIN = {geo.SHOT_SPLIT: 0.30, geo.SHOT_VISUAL: 0.25}
UI_INK_MAX = 0.02            # share of ink pixels allowed in 1520..1920 of a full-screen visual: nothing of ours lives in Instagram's interface zone
STATE_GAP_MAX_S = 1.5        # longest stretch without a visible state change inside a visual (canon: 2 s)
EMPTY_BAND_MAX = 0.18        # longest empty band of a full-screen visual, share of the frame height
EMPTY_ROW_INK = 6            # a row holds content when at least this many of its pixels differ from the background
HOOK_SHARP_MIN = 0.55        # sharpness of frame 0 against the settled hook frames
HOOK_SOLID_MIN = 0.85        # contrast of the first caption word at frame 0 against the settled word
REMINDER_INK_MIN = 0.04      # share of ink inside the reminder box at the last frame
REMINDER_CHANGE_MAD = 6.0    # mean difference of the reminder box between the scene start and the last frame (typed word, pressed button)
CHANGE_EPS = 0.004           # share of changed pixels of the visual area (small frames) that counts as «a new state»: about a 60x60 px block
                             # at full size (a toggle flipping, a typed line, a bar growing); a pointer move or a tick alone (0.2 %) does not
CHANGE_DELTA = 20
MATCH_MAD = 14.0             # mean absolute difference below this = the render shows the video here
ZOOM_MARGIN = 0.5            # the unzoomed cut must beat the zoomed one by this much before a planned zoom counts as missing


def background(img: np.ndarray, y0: int, y1: int, strip: int = 10) -> np.ndarray:
    """Median colour of a thin strip at the left edge of rows ``y0..y1``: the background of a scene (cards are inset)."""
    return np.median(img[y0:y1, :strip].reshape(-1, 3), axis=0)


def ink_mask(img: np.ndarray, bg: np.ndarray, delta: int = INK_DELTA) -> np.ndarray:
    """Boolean mask of pixels that differ from ``bg`` by more than ``delta`` in any channel."""
    return (np.abs(img.astype(np.int16) - bg.astype(np.int16)).max(axis=2) > delta)


def ink_fraction(img: np.ndarray, box: Box, bg: np.ndarray, delta: int = INK_DELTA) -> float:
    """Share of ink pixels inside ``box`` (clamped to the image)."""
    x0, y0 = max(0, int(box.x0)), max(0, int(box.y0))
    x1, y1 = min(img.shape[1], int(box.x1)), min(img.shape[0], int(box.y1))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(ink_mask(img[y0:y1, x0:x1], bg, delta).mean())


# ---- captions ---------------------------------------------------------------------------------

def caption_problems(cid: str, img: np.ndarray, box: Box, shot_type: str, bg: np.ndarray, face: Box | None) -> list[str]:
    """Checks of one caption on its rendered frame and measured box.

    * seam: in a split no ink of the caption band reaches the rows just above the seam, and the box does not straddle it;
    * clipped: no ink on the frame edge strips beside the caption, the box stays inside the frame margins;
    * ui: the box stays above 1520;
    * face: the box does not meet the face detected on the frame.
    """
    out: list[str] = []
    if shot_type == geo.SHOT_SPLIT:
        if box.y0 < geo.SEAM < box.y1 or box.y1 > geo.SEAM - 10 + 0.5:
            out.append(f"{cid}: caption {geo.fmt(box)} touches or crosses the seam {geo.SEAM}")
        near = Box(0, geo.SEAM - 9, geo.FRAME_W, geo.SEAM - 7)       # rows between the caption and the 6 px seam border
        if ink_fraction(img, near, bg) > 0.01:
            out.append(f"{cid}: ink on the rows just above the seam: something is drawn into the seam")
    if box.x0 < geo.SIDE_MARGIN - 0.5 or box.x1 > geo.FRAME_W - geo.SIDE_MARGIN + 0.5:
        out.append(f"{cid}: caption {geo.fmt(box)} is clipped by the frame margin {geo.SIDE_MARGIN}")
    edges = (Box(0, box.y0, 8, box.y1), Box(geo.FRAME_W - 8, box.y0, geo.FRAME_W, box.y1))
    if shot_type != geo.SHOT_SPEAKER and any(ink_fraction(img, e, bg) > 0.2 for e in edges):
        out.append(f"{cid}: ink on the frame edge beside the caption (clipped text)")
    if box.y1 > geo.UI_TOP or box.y0 < geo.HEADER_BOTTOM:
        out.append(f"{cid}: caption {geo.fmt(box)} in the interface zone (<{geo.HEADER_BOTTOM} or >{geo.UI_TOP})")
    if face is not None and box.intersects(face):
        out.append(f"{cid}: caption {geo.fmt(box)} is over the face {geo.fmt(face)}")
    return out


def caption_present(img: np.ndarray, box: Box, bg: np.ndarray) -> bool:
    """The caption really is on the frame: enough ink inside its box."""
    return ink_fraction(img, box, bg) > 0.02


# ---- visual panel -----------------------------------------------------------------------------

def panel_region(shot_type: str) -> tuple[int, int]:
    """Rows of the visual area that carry content: below the header, above the caption band."""
    return (geo.HEADER_BOTTOM, geo.SPLIT_CONTENT_BOTTOM if shot_type == geo.SHOT_SPLIT else geo.FULL_CONTENT_BOTTOM)


def coverage(img: np.ndarray, shot_type: str) -> float:
    """Share of the content area covered by something other than the scene background."""
    y0, y1 = panel_region(shot_type)
    bg = background(img, y0, y1)
    region = cv2.medianBlur(np.ascontiguousarray(img[y0:y1]), 7)      # the 2 px background grid is median-filtered away
    return float(ink_mask(region, bg, COVER_DELTA).mean())


def coverage_problem(label: str, img: np.ndarray, shot_type: str) -> str | None:
    """None when the content area holds enough graphics, else a message (an empty panel on the first frame of a segment)."""
    c = coverage(img, shot_type)
    need = COVERAGE_MIN[shot_type]
    return None if c >= need else f"{label}: visual panel covers {c * 100:.1f} % < {need * 100:.0f} % at the first frame of the {shot_type} segment"


def ui_zone_problem(label: str, img: np.ndarray) -> str | None:
    """A full-screen visual keeps everything out of 1520..1920 (``UI_INK_MAX``): no cards, no text, no decoration."""
    bg = background(img, geo.UI_TOP, geo.FRAME_H)
    f = ink_fraction(img, Box(0, geo.UI_TOP, geo.FRAME_W, geo.FRAME_H), bg)
    return None if f <= UI_INK_MAX else f"{label}: graphics in the interface zone {geo.UI_TOP}..{geo.FRAME_H} ({f * 100:.2f} % ink)"


# ---- empty bands of full-screen visuals -------------------------------------------------------

def empty_band(img: np.ndarray) -> int:
    """Longest run (pixels) of content-free rows between the header and the interface zone (115..1520).

    Below 1520 is Instagram's own interface (captions, buttons): nothing of ours lives there, so it is not part of the picture.

    A row is content when enough of its pixels differ from the scene background after a median filter (the 2 px
    background grid is filtered away). Caption rows are content, so a caption under the card splits the gap.
    """
    y0, y1 = geo.HEADER_BOTTOM, geo.UI_TOP
    bg = background(img, y0, y1)
    region = cv2.medianBlur(np.ascontiguousarray(img[y0:y1]), 7)
    rows = ink_mask(region, bg, COVER_DELTA).sum(axis=1) >= EMPTY_ROW_INK
    best = run = 0
    for has in rows:
        run = 0 if has else run + 1
        best = max(best, run)
    return best


def empty_band_problem(label: str, img: np.ndarray) -> str | None:
    """None when no empty band of a full-screen visual exceeds 18 % of the frame height, else a message."""
    band = empty_band(img)
    limit = EMPTY_BAND_MAX * geo.FRAME_H
    if band <= limit:
        return None
    return f"{label}: empty band of {band} px ({band / geo.FRAME_H * 100:.0f} % of the frame height > {EMPTY_BAND_MAX * 100:.0f} %): enlarge or centre the cards"


# ---- hook and ending ---------------------------------------------------------------------------

def sharpness(img: np.ndarray, rows: tuple[int, int] = (geo.HEADER_BOTTOM, geo.SEAM)) -> float:
    """Mean absolute Laplacian of the visual area: low for a blurred picture."""
    g = cv2.cvtColor(np.ascontiguousarray(img[rows[0]:rows[1]]), cv2.COLOR_BGR2GRAY)
    return float(np.abs(cv2.Laplacian(g, cv2.CV_32F)).mean())


def contrast_in(img: np.ndarray, box: Box) -> float:
    """Mean absolute difference from the background inside ``box`` (a faint word has little of it)."""
    x0, y0, x1, y1 = max(0, int(box.x0)), max(0, int(box.y0)), int(box.x1), int(box.y1)
    bg = background(img, y0, y1)
    return float(np.abs(img[y0:y1, x0:x1].astype(np.int16) - bg.astype(np.int16)).max(axis=2).mean())


def hook_problems(frame0: np.ndarray, settled: np.ndarray, word_box: Box,
                  first: np.ndarray | None = None, settled_caption: np.ndarray | None = None) -> list[str]:
    """Frame 0 of the reel must already be the hook: sharp graphics and a solid first caption word.

    ``frame0``/``settled`` are full frames at t=0 and at a moment when the hook has settled (sharpness reference);
    ``first``/``settled_caption`` (default: the same frames) are used for the caption word at ``word_box``.
    """
    out: list[str] = []
    ref = sharpness(settled)
    if ref > 0 and sharpness(frame0) < HOOK_SHARP_MIN * ref:
        out.append(f"hook: frame 0 is blurred (sharpness {sharpness(frame0):.2f} vs {ref:.2f} settled): no blur-in on the first frame")
    a = frame0 if first is None else first
    b = settled if settled_caption is None else settled_caption
    full = contrast_in(b, word_box)
    if full > 0 and contrast_in(a, word_box) < HOOK_SOLID_MIN * full:
        out.append(f"hook: the first caption word is faint at frame 0 (contrast {contrast_in(a, word_box):.0f} vs {full:.0f} solid)")
    return out


def reminder_problems(first: np.ndarray, last: np.ndarray, box: Box) -> list[str]:
    """The reminder of the code word is drawn in its box at the last frame and was not there when the scene started."""
    bg = background(last, int(box.y0), int(box.y1))
    shown = ink_fraction(last, box, bg)
    if shown < REMINDER_INK_MIN:
        return [f"reminder: the code word box {geo.fmt(box)} is empty at the end of the reel ({shown * 100:.1f} % ink)"]
    y0, y1, x0, x1 = int(box.y0), int(box.y1), int(box.x0), int(box.x1)
    mad = float(np.abs(first[y0:y1, x0:x1].astype(np.int16) - last[y0:y1, x0:x1].astype(np.int16)).mean())
    if mad < REMINDER_CHANGE_MAD:
        return [f"reminder: the code word box {geo.fmt(box)} does not change between the scene start and the end (mean difference {mad:.1f}): no animated action"]
    return []


LIGHT_LUMA = 192             # background gray level of a light scene (paper 240); the orange accent (145) and dark (14) are not light
LIGHT_SHARE_MAX = 0.25       # share of visual frames on a light background
CODEWORD_MIN_H = 90          # the ending's code word box is at least this tall (full-size px)
CODEWORD_STABLE_MAD = 10.0   # mean absolute difference of the code word box between the typed moment and the last frame


def sheet_times(duration: float, step: float = 0.5, tail: float = 6.0, tail_step: float = 0.25) -> list[float]:
    """Frame times of the contact sheets: every ``step`` seconds over the reel, every ``tail_step`` over the last ``tail`` seconds (the ending)."""
    first = math.ceil(max(0.0, duration - tail) / tail_step - 1e-9)
    last = math.floor(duration / tail_step + 1e-9)
    ending = [round(k * tail_step, 3) for k in range(first, last + 1)]
    head = [round(k * step, 3) for k in range(int(ending[0] / step + 1e-9) + 1) if k * step < ending[0] - 1e-9]
    return head + ending


def is_light_frame(gray_small: np.ndarray, shot_type: str) -> bool:
    """Is the visual area of a small gray frame on a light background? Median of the left edge strip of the visual rows."""
    rows = (29, 240) if shot_type == geo.SHOT_SPLIT else (29, 300)
    return float(np.median(gray_small[rows[0]:rows[1], :3])) > LIGHT_LUMA


def light_share(types: list[str], light: list[bool]) -> float:
    """Share of the split / full-screen visual frames that are on a light background (speaker frames do not count)."""
    pairs = [lt for t, lt in zip(types, light) if t != geo.SHOT_SPEAKER]
    return sum(pairs) / len(pairs) if pairs else 0.0


def palette_problem(share: float) -> str | None:
    """None when light scenes stay an accent (at most 25 % of the visual time), else a message."""
    return None if share <= LIGHT_SHARE_MAX + 1e-6 else f"palette: {share * 100:.0f} % of the visual time is on a light background, limit {LIGHT_SHARE_MAX * 100:.0f} %"


def codeword_problems(label: str, typed: np.ndarray, last: np.ndarray, box: Box) -> list[str]:
    """The ending's code word box, on a frame where it is fully typed and on the last frame.

    It must be at least 90 px tall, fully inside the visual half, drawn (inked) on both frames and identical on both:
    nothing (pointer, badge, animation) may cover or move it between the two moments.
    """
    out: list[str] = []
    if box.h < CODEWORD_MIN_H:
        out.append(f"{label}: the code word box is {box.h:.0f} px tall < {CODEWORD_MIN_H} px")
    if box.y0 < geo.HEADER_BOTTOM or box.y1 > geo.SEAM or box.x0 < 0 or box.x1 > geo.FRAME_W:
        out.append(f"{label}: the code word box {geo.fmt(box)} is not fully inside the visual half (y {geo.HEADER_BOTTOM}-{geo.SEAM})")
    for name, img in (("typed frame", typed), ("last frame", last)):
        bg = background(img, int(box.y0), int(box.y1))
        if ink_fraction(img, box, bg) < REMINDER_INK_MIN:
            out.append(f"{label}: the code word box is empty on the {name}")
    y0, y1, x0, x1 = int(box.y0), int(box.y1), int(box.x0), int(box.x1)
    mad = float(np.abs(typed[y0:y1, x0:x1].astype(np.int16) - last[y0:y1, x0:x1].astype(np.int16)).mean())
    if mad > CODEWORD_STABLE_MAD:
        out.append(f"{label}: the code word box changes between the typed moment and the last frame (mean difference {mad:.1f} > {CODEWORD_STABLE_MAD}): covered or moving")
    return out


# ---- static pictures --------------------------------------------------------------------------

def changed(prev: np.ndarray, cur: np.ndarray, rows: tuple[int, int]) -> bool:
    """Do two small gray frames differ in ``rows`` (scaled) by a visible share of pixels?"""
    a, b = prev[rows[0]:rows[1]].astype(np.int16), cur[rows[0]:rows[1]].astype(np.int16)
    return float((np.abs(a - b) > CHANGE_DELTA).mean()) > CHANGE_EPS


def static_problems(label: str, flags: list[bool], dt: float, limit: float = STATE_GAP_MAX_S) -> list[str]:
    """Stretches of unchanged picture longer than ``limit`` seconds; ``flags[i]`` = frame i+1 differs from frame i."""
    out: list[str] = []
    run = 0
    for i, f in enumerate(flags + [True]):
        if f:
            if run * dt > limit + 1e-9:
                out.append(f"{label}: the picture does not change for {run * dt:.1f} s (from {(i - run) * dt:.1f} s of the segment)")
            run = 0
        else:
            run += 1
    return out


# ---- shot types on the render ----------------------------------------------------------------

def zoom_frame(img: np.ndarray, z: float, origin: tuple[float, float]) -> np.ndarray:
    """The frame scaled by ``z`` about ``origin`` (pixels of ``img``), same size: what a punch-in zoom of the speaker shows."""
    m = np.float32([[z, 0, origin[0] * (1 - z)], [0, z, origin[1] * (1 - z)]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference of two equally sized gray images."""
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def zoom_problem(label: str, render_small: np.ndarray, cut_small: np.ndarray, zoom: tuple[float, float, float]) -> str | None:
    """A shot with a planned punch-in zoom must show the scaled cut: fail when the render matches the UNZOOMED cut clearly better."""
    plain = mean_abs_diff(render_small, cut_small)
    zoomed = mean_abs_diff(render_small, zoom_frame(cut_small, zoom[0], (zoom[1], zoom[2])))
    if plain + ZOOM_MARGIN < zoomed:
        return f"{label}: the render matches the unzoomed cut ({plain:.1f}) better than the zoomed one ({zoomed:.1f}): the planned zoom {zoom[0]} is not applied"
    return None


def classify(render_small: np.ndarray, cut_small: np.ndarray, y0_small: int, zoom: tuple[float, float, float] | None = None) -> str:
    """Which layout a rendered small gray frame shows, by comparison with the cut at the same moment.

    speaker: the whole frame is the video (scaled by ``zoom = (z, ox, oy)`` in small pixels while a punch-in is planned); split: the lower half
    is the video slice starting at ``y0_small``; else a full-screen visual.
    """
    h = render_small.shape[0]
    half = h // 2

    def mad(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())

    if mad(render_small, cut_small) < MATCH_MAD:
        return geo.SHOT_SPEAKER
    if zoom is not None and mad(render_small, zoom_frame(cut_small, zoom[0], (zoom[1], zoom[2]))) < MATCH_MAD:
        return geo.SHOT_SPEAKER
    if y0_small + half <= cut_small.shape[0] and mad(render_small[half:], cut_small[y0_small:y0_small + half]) < MATCH_MAD:
        return geo.SHOT_SPLIT
    return geo.SHOT_VISUAL


def runs_of(types: list[str], dt: float) -> list[tuple[str, float, float]]:
    """Runs of equal consecutive types: ``(type, start, end)`` in seconds."""
    out: list[tuple[str, float, float]] = []
    for i, t in enumerate(types):
        if out and out[-1][0] == t:
            out[-1] = (t, out[-1][1], (i + 1) * dt)
        else:
            out.append((t, i * dt, (i + 1) * dt))
    return out


def run_problems(runs: list[tuple[str, float, float]], limit: float = 4.5) -> list[str]:
    """Runs of one shot type longer than ``limit``."""
    return [f"same type «{t}» for {b - a:.2f} s ({a:.1f}..{b:.1f} s) > {limit} s" for t, a, b in runs if b - a > limit + 1e-9]


def type_shares(types: list[str]) -> dict[str, float]:
    """Share of frames per shot type."""
    n = max(len(types), 1)
    return {t: round(types.count(t) / n, 4) for t in geo.SHOT_TYPES}


def to_small_gray(img: np.ndarray, factor: int = 4) -> np.ndarray:
    """Gray image shrunk by ``factor`` (area average)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (g.shape[1] // factor, g.shape[0] // factor), interpolation=cv2.INTER_AREA)
