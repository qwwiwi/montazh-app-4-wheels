"""Frame geometry and caption rules of the reference canon, as pure functions.

Everything is in pixels of the 1080x1920 output frame unless a name says «source». The split is exactly 50/50:
visual y 0..960, speaker y 960..1920. Hard rules of the owner: a caption never overlaps the face, never straddles the
seam, never touches y 1520..1920 (Instagram interface) or y < 115 (header). The module has no I/O so every rule can be
tested without a browser.
"""

from __future__ import annotations

from dataclasses import dataclass

FRAME_W = 1080
FRAME_H = 1920

SEAM = 960                   # split is exactly 50/50: visual above, speaker below
HEADER_BOTTOM = 115          # top 6 % belongs to the Reels header
SAFE_LINE = 1248             # below it text may be covered by the post caption
UI_TOP = 1520                # 1520..1920 is Instagram UI, always
BUTTONS_X0 = 950             # like / comment / share column, x 950..1080
BUTTONS_Y0 = 1080
BUTTONS_Y1 = 1720
SIDE_MARGIN = 40             # captions keep this far from the left/right frame edge

SPLIT_CONTENT_TOP = 130      # card area of a split visual
SPLIT_CONTENT_BOTTOM = 760   # below it the caption band of the split starts (captions sit just above the seam)
SPLIT_CAPTION_BOTTOM = 944   # caption box bottom in a split: fully above the seam with a 16 px gap
FULL_CONTENT_BOTTOM = 1280   # card area of a full-screen visual: the cards fill y 130..1280, so no empty lower third remains
VISUAL_CAPTION_TOP = 1320    # caption box top under a full-screen visual (canon y 1320..1450)
CHEST_TOP = 1180             # canon: captions of a full-screen speaker sit at chest level, box top y 1180..1340
CHEST_BOTTOM = 1340
CHEST_BOX_H = 160            # height of a two-line caption box (60 px type + line gap), used to test the chest slot
GAP = 14                     # minimum clear space between a caption box and the face box
SPEAKER_CAPTION_GAP = 24     # clear space between a caption above the head and the hair

SHOT_SPLIT = "split"
SHOT_VISUAL = "visual"
SHOT_SPEAKER = "speaker"
SHOT_TYPES = (SHOT_SPLIT, SHOT_VISUAL, SHOT_SPEAKER)

MODE_ABOVE_SEAM = "above_seam"
MODE_UNDER_CARD = "under_card"
MODE_ABOVE_HEAD = "above_head"
MODE_PUNCH = "punch"         # a key word in a large size instead of the running caption; same anchor as the caption of the shot

PUNCH_PX_MAX, PUNCH_PX_MIN = 140, 100    # type size of a punch word (the running caption is 60 px)
PUNCH_LINE_W = 800                       # width a centred word may take: x 140..940 stays clear of the button column (x >= 950) in a full-screen visual
PUNCH_CHAR_EM = 0.82                     # width of an uppercase Cyrillic letter of Golos Text 800 in em, measured in Chrome («НАЖИМАЕШЬ»); the gate backs it up
PUNCH_MAX_CHARS = int(PUNCH_LINE_W / (PUNCH_CHAR_EM * PUNCH_PX_MIN))     # 9: a longer word would not fit the line at 100 px
MODE_CHEST = "chest"


@dataclass(frozen=True)
class Box:
    """Axis-aligned box, x0/y0 inclusive top-left, x1/y1 bottom-right."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        """Width."""
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        """Height."""
        return self.y1 - self.y0

    def intersects(self, other: Box, margin: float = 0.0) -> bool:
        """True when the boxes overlap, or come closer than ``margin`` pixels."""
        return (
            self.x0 < other.x1 + margin and other.x0 < self.x1 + margin
            and self.y0 < other.y1 + margin and other.y0 < self.y1 + margin
        )

    def union(self, other: Box) -> Box:
        """Smallest box holding both."""
        return Box(min(self.x0, other.x0), min(self.y0, other.y0),
                   max(self.x1, other.x1), max(self.y1, other.y1))

    def pad(self, dx: float, dy: float | None = None) -> Box:
        """Grow by ``dx`` on the sides and ``dy`` (default ``dx``) top and bottom."""
        dy = dx if dy is None else dy
        return Box(self.x0 - dx, self.y0 - dy, self.x1 + dx, self.y1 + dy)


@dataclass(frozen=True)
class Head:
    """Head measured on the actual take, source pixels (hair top .. chin)."""

    left: int
    top: int
    right: int
    chin: int


@dataclass(frozen=True)
class SplitLayout:
    """Speaker half of a split: source row ``y0`` lands on the seam (scale 1, the half shows a 960 px slice)."""

    y0: int

    @property
    def shift(self) -> int:
        """Vertical shift from source to screen pixels in a split."""
        return SEAM - self.y0


def split_y0(head: Head, air: int = 12) -> int:
    """First source row of the speaker half: ``air`` pixels above the typical hair top, so hair is not cut."""
    return max(0, head.top - air)


def split_box(layout: SplitLayout, box: Box) -> Box:
    """Map a source-pixel box into the speaker half of a split."""
    return Box(box.x0, box.y0 + layout.shift, box.x1, box.y1 + layout.shift)


@dataclass(frozen=True)
class CaptionSlot:
    """Where captions of one shot sit: mode and the anchor line. ``bottom`` anchors the box bottom, ``top`` its top."""

    mode: str
    anchor: str
    y: float


def band_for(shot_type: str, mode: str, head_top: float | None = None) -> tuple[float, float]:
    """Vertical band a caption box must stay inside for the shot type and mode.

    split: above the seam (y1 <= 960 - 10); visual: the free band under the card; speaker: above the head
    (``head_top`` is the highest hair position over the shot on screen).
    """
    if shot_type == SHOT_SPLIT:
        return (SPLIT_CONTENT_BOTTOM if mode == MODE_PUNCH else HEADER_BOTTOM, SEAM - 10)    # a punch word never sits on the card strip
    if shot_type == SHOT_VISUAL:
        return (SAFE_LINE, UI_TOP - 20)
    if shot_type == SHOT_SPEAKER and mode == MODE_CHEST:
        return (CHEST_TOP - 10, CHEST_BOTTOM + 20)
    if shot_type == SHOT_SPEAKER:
        return (HEADER_BOTTOM, (head_top if head_top is not None else SAFE_LINE) - GAP)
    raise ValueError(f"unknown shot type {shot_type!r}")


def punch_px(text: str) -> int:
    """Type size of a punch word: 140 px, shrinking with the length so the word keeps inside the line (never below 100 px)."""
    return max(PUNCH_PX_MIN, min(PUNCH_PX_MAX, int(PUNCH_LINE_W / (PUNCH_CHAR_EM * max(len(text), 1)))))


def caption_slot(shot_type: str, head_screen: Box | None = None, face_screen: Box | None = None, punch: bool = False) -> CaptionSlot:
    """Choose the caption position for a shot (``punch=True``: the same place, marked ``MODE_PUNCH`` for the larger key word).

    * split: bottom of the box just above the seam;
    * visual: top of the box under the card (canon y 1320..1450);
    * speaker: chest level (box top y 1180, canon 1180..1340) when the face box ends clear above it, i.e. the caption
      cannot cover the face; otherwise (a close-up whose chin reaches y 1500) above the head: box bottom = hair top - 24 px.

    Raises:
        ValueError: when a speaker shot has no head box or the head leaves no room for a caption above it.
    """
    if shot_type == SHOT_SPLIT:
        return CaptionSlot(MODE_PUNCH if punch else MODE_ABOVE_SEAM, "bottom", float(SPLIT_CAPTION_BOTTOM))
    if shot_type == SHOT_VISUAL:
        return CaptionSlot(MODE_PUNCH if punch else MODE_UNDER_CARD, "top", float(VISUAL_CAPTION_TOP))
    if shot_type != SHOT_SPEAKER:
        raise ValueError(f"unknown shot type {shot_type!r}")
    if head_screen is None:
        raise ValueError("speaker shot needs a head box")
    if not punch and face_screen is not None and face_screen.y1 + GAP <= CHEST_TOP and CHEST_TOP + CHEST_BOX_H <= CHEST_BOTTOM + 20:
        return CaptionSlot(MODE_CHEST, "top", float(CHEST_TOP))
    bottom = head_screen.y0 - SPEAKER_CAPTION_GAP
    if bottom - 190 < HEADER_BOTTOM:
        raise ValueError("no room for two caption lines above the head in this shot")
    return CaptionSlot(MODE_PUNCH if punch else MODE_ABOVE_HEAD, "bottom", bottom)


@dataclass(frozen=True)
class Violation:
    """One broken rule: which element, which rule, and the numbers."""

    caption_id: str
    rule: str
    detail: str


def check_caption(
    caption_id: str,
    box: Box,
    shot_type: str,
    mode: str,
    face: Box | None,
    *,
    head_top: float | None = None,
    face_margin: float = 0.0,
) -> list[Violation]:
    """Check one measured caption box against every hard rule.

    Rules: band for the shot type (never across the seam), nothing in 0..115 or 1520..1920, side margins, the right
    button column, no overlap with the face box (``face`` holds every position the face takes while the caption is on screen).
    """
    out: list[Violation] = []
    lo, hi = band_for(shot_type, mode, head_top)
    if box.y0 < lo - 0.5 or box.y1 > hi + 0.5:
        out.append(Violation(caption_id, "band", f"y {box.y0:.0f}..{box.y1:.0f} outside {lo:.0f}..{hi:.0f} for {shot_type}/{mode}"))
    if shot_type == SHOT_SPLIT and box.y0 < SEAM < box.y1:
        out.append(Violation(caption_id, "seam", f"caption y {box.y0:.0f}..{box.y1:.0f} straddles the seam {SEAM}"))
    if box.y0 < HEADER_BOTTOM:
        out.append(Violation(caption_id, "header", f"top {box.y0:.0f} < {HEADER_BOTTOM}"))
    if box.y1 > UI_TOP:
        out.append(Violation(caption_id, "ui-zone", f"bottom {box.y1:.0f} > {UI_TOP}"))
    if box.x0 < SIDE_MARGIN or box.x1 > FRAME_W - SIDE_MARGIN:
        out.append(Violation(caption_id, "clipped", f"x {box.x0:.0f}..{box.x1:.0f} beyond the frame margin {SIDE_MARGIN}"))
    if box.y1 > BUTTONS_Y0 and box.y0 < BUTTONS_Y1 and box.x1 > BUTTONS_X0:
        out.append(Violation(caption_id, "buttons", f"x1 {box.x1:.0f} > {BUTTONS_X0} inside y {BUTTONS_Y0}..{BUTTONS_Y1}"))
    if face is not None and box.intersects(face, margin=face_margin):
        out.append(Violation(caption_id, "face", f"box {fmt(box)} meets face {fmt(face)}"))
    return out


def zoom_origin(face: Box) -> tuple[float, float]:
    """Centre of the face box: the point a punch-in zoom grows from (it stays where it is on screen)."""
    return ((face.x0 + face.x1) / 2, (face.y0 + face.y1) / 2)


def zoom_box(box: Box, z: float, origin: tuple[float, float]) -> Box:
    """Where a box of the full-screen frame lands after the frame is scaled by ``z`` about ``origin``."""
    ox, oy = origin
    return Box(ox + (box.x0 - ox) * z, oy + (box.y0 - oy) * z, ox + (box.x1 - ox) * z, oy + (box.y1 - oy) * z)


def zoom_violations(shot_id: str, face: Box, head: Box | None) -> list[Violation]:
    """Rules of the zoomed crop (boxes already zoomed): the chin stays above the interface zone, the face stays clear of the right-hand
    buttons column, the head stays in the frame and below the header."""
    out: list[Violation] = []
    if face.y1 > UI_TOP:
        out.append(Violation(shot_id, "zoom-ui", f"zoomed chin y {face.y1:.0f} > {UI_TOP}: face {fmt(face)} reaches the interface zone"))
    if face.x1 > BUTTONS_X0 and face.x0 < FRAME_W and face.y1 > BUTTONS_Y0 and face.y0 < BUTTONS_Y1:
        out.append(Violation(shot_id, "zoom-buttons", f"zoomed face {fmt(face)} slides under the like / comment / share column (x {BUTTONS_X0}..{FRAME_W}, y {BUTTONS_Y0}..{BUTTONS_Y1})"))
    if head is not None and (head.x0 < 0 or head.x1 > FRAME_W or head.y0 < HEADER_BOTTOM):
        out.append(Violation(shot_id, "zoom-frame", f"zoomed head {fmt(head)} leaves the frame or the header band (x 0..{FRAME_W}, y >= {HEADER_BOTTOM})"))
    return out


def fmt(box: Box) -> str:
    """Compact box text for messages."""
    return f"[{box.x0:.0f},{box.y0:.0f},{box.x1:.0f},{box.y1:.0f}]"
