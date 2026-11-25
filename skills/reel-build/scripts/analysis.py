"""Join plan, face track and geometry: per-shot face boxes and caption slots.

Used by the generator (to place captions) and by the pre-render gate (to check them).
"""

from __future__ import annotations

from dataclasses import dataclass

import geometry as geo
from faces import FaceTrack
from geometry import Box, CaptionSlot, SplitLayout, Violation
from reel_captions import Group
from reel_config import ReelConfig
from reel_plan import Plan, Shot


@dataclass(frozen=True)
class ShotInfo:
    """Where the face is during one shot (screen pixels) and where its captions sit."""

    shot: Shot
    face_screen: Box | None     # worst case over the whole shot
    head_screen: Box | None
    slot: CaptionSlot | None    # None for a shot without captions
    zoom: float = 1.0           # punch-in of a full-screen speaker shot; the boxes above are already zoomed
    origin: tuple[float, float] | None = None     # the point the zoom grows from (centre of the face), screen pixels


@dataclass(frozen=True)
class Analysis:
    """Everything derived from head, plan and groups."""

    layout: SplitLayout
    shots: tuple[ShotInfo, ...]
    slots: dict[str, CaptionSlot]       # group id -> slot
    problems: tuple[Violation, ...]     # shot-level problems (no face, no room for a caption)

    def info(self, shot: Shot) -> ShotInfo:
        """ShotInfo of a shot."""
        return next(i for i in self.shots if i.shot is shot)


def _screen_boxes(shot: Shot, layout: SplitLayout, track: FaceTrack, cfg: ReelConfig) -> tuple[Box | None, Box | None]:
    face = track.face(shot.start, shot.end, cfg.face_pad)
    head = track.head(shot.start, shot.end)
    if shot.type == geo.SHOT_SPLIT:
        return (geo.split_box(layout, face) if face else None, geo.split_box(layout, head) if head else None)
    if shot.type == geo.SHOT_SPEAKER:
        return face, head                      # full screen at scale 1: screen pixels = source pixels
    return None, None


def analyse(plan: Plan, groups: list[Group], track: FaceTrack, cfg: ReelConfig) -> Analysis:
    """Compute the face boxes per shot and the caption slot of every group."""
    layout = cfg.layout
    infos: list[ShotInfo] = []
    problems: list[Violation] = []
    slot_by_shot: dict[int, CaptionSlot | None] = {}
    for n, shot in enumerate(plan.shots):
        face, head = _screen_boxes(shot, layout, track, cfg)
        origin: tuple[float, float] | None = None
        if shot.zoom != 1.0 and shot.type == geo.SHOT_SPEAKER and face is not None:
            # the whole frame is scaled about the face centre: every box, the caption slot and the zone rules are recomputed for the zoomed crop
            origin = geo.zoom_origin(face)
            face = geo.zoom_box(face, shot.zoom, origin)
            head = geo.zoom_box(head, shot.zoom, origin) if head else None
            problems += geo.zoom_violations(f"shot{n}", face, head)
        slot: CaptionSlot | None = None
        needs = any(g.shot == n for g in groups)
        if shot.type != geo.SHOT_VISUAL and face is None:
            problems.append(Violation(f"shot{n}", "no-face", f"no face detected in {shot.type} shot {shot.start}..{shot.end}"))
        elif needs:
            try:
                slot = geo.caption_slot(shot.type, head, face)
            except ValueError as err:
                problems.append(Violation(f"shot{n}", "no-slot", f"{shot.start}..{shot.end}: {err}"))
        infos.append(ShotInfo(shot, face, head, slot, shot.zoom if origin else 1.0, origin))
        slot_by_shot[n] = slot
    slots = {g.id: slot_by_shot[g.shot] for g in groups if slot_by_shot.get(g.shot) is not None}
    for g in groups:                       # a punch word sits where the caption of its shot sits, marked as a punch (its own band)
        if g.punch and g.id in slots:
            try:
                slots[g.id] = geo.caption_slot(plan.shots[g.shot].type, infos[g.shot].head_screen, punch=True)
            except ValueError as err:      # the punch needs the room above the head even where chest-level running captions fit
                del slots[g.id]
                shot = plan.shots[g.shot]
                problems.append(Violation(f"shot{g.shot}", "no-slot", f"{shot.start}..{shot.end}: punch word «{g.text}»: {err}"))
    return Analysis(layout, tuple(infos), slots, tuple(problems))
