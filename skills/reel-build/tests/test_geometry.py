"""Frame geometry: the exact 50/50 split, caption slots per shot type and the hard caption rules."""

import pytest

import geometry as geo
from geometry import Box


def test_split_is_exactly_fifty_fifty() -> None:
    assert geo.SEAM * 2 == geo.FRAME_H
    layout = geo.SplitLayout(geo.split_y0(geo.Head(100, 590, 800, 1470), air=12))
    assert layout.y0 == 578 and layout.shift == 960 - 578
    assert geo.split_box(layout, Box(0, 578, 10, 600)).y0 == 960


def test_slots_follow_the_shot_type() -> None:
    assert geo.caption_slot(geo.SHOT_SPLIT) == geo.CaptionSlot(geo.MODE_ABOVE_SEAM, "bottom", float(geo.SPLIT_CAPTION_BOTTOM))
    assert geo.SPLIT_CAPTION_BOTTOM < geo.SEAM
    visual = geo.caption_slot(geo.SHOT_VISUAL)
    assert visual.mode == geo.MODE_UNDER_CARD and 1250 < visual.y < 1450
    speaker = geo.caption_slot(geo.SHOT_SPEAKER, Box(100, 560, 900, 1480))
    assert speaker.mode == geo.MODE_ABOVE_HEAD and speaker.y < 560


def test_speaker_slot_needs_a_head_and_room_above_it() -> None:
    with pytest.raises(ValueError):
        geo.caption_slot(geo.SHOT_SPEAKER)
    with pytest.raises(ValueError):
        geo.caption_slot(geo.SHOT_SPEAKER, Box(100, 250, 900, 1480))


def rules(box: Box, shot: str, mode: str, face: Box | None = None, head_top: float | None = None) -> set[str]:
    return {v.rule for v in geo.check_caption("c", box, shot, mode, face, head_top=head_top)}


def test_caption_straddling_the_seam_is_a_violation() -> None:
    assert "seam" in rules(Box(200, 880, 880, 1010), geo.SHOT_SPLIT, geo.MODE_ABOVE_SEAM)
    assert rules(Box(200, 770, 880, 944), geo.SHOT_SPLIT, geo.MODE_ABOVE_SEAM) == set()


def test_caption_touching_the_frame_margin_is_clipped() -> None:
    assert "clipped" in rules(Box(10, 770, 800, 944), geo.SHOT_SPLIT, geo.MODE_ABOVE_SEAM)
    assert "clipped" in rules(Box(300, 770, 1075, 944), geo.SHOT_SPLIT, geo.MODE_ABOVE_SEAM)


def test_caption_in_the_interface_zones_is_a_violation() -> None:
    assert "ui-zone" in rules(Box(200, 1400, 880, 1560), geo.SHOT_VISUAL, geo.MODE_UNDER_CARD)
    assert "header" in rules(Box(200, 60, 880, 200), geo.SHOT_SPEAKER, geo.MODE_ABOVE_HEAD, head_top=600)
    assert rules(Box(200, 1300, 880, 1474), geo.SHOT_VISUAL, geo.MODE_UNDER_CARD) == set()


def test_caption_over_the_face_is_a_violation() -> None:
    face = Box(190, 760, 820, 1450)
    assert "face" in rules(Box(200, 1000, 880, 1170), geo.SHOT_SPEAKER, geo.MODE_ABOVE_HEAD, face, head_top=600)
    assert rules(Box(200, 350, 880, 524), geo.SHOT_SPEAKER, geo.MODE_ABOVE_HEAD, face, head_top=600) == set()


def test_button_column_is_kept_free() -> None:
    assert "buttons" in rules(Box(300, 1300, 1000, 1474), geo.SHOT_VISUAL, geo.MODE_UNDER_CARD)


def test_speaker_caption_sits_at_chest_level_when_the_face_is_above_it() -> None:
    face = Box(340, 300, 740, 900)
    slot = geo.caption_slot(geo.SHOT_SPEAKER, Box(300, 150, 780, 900), face)
    assert slot.mode == geo.MODE_CHEST and 1180 <= slot.y <= 1340
    assert rules(Box(200, slot.y, 880, slot.y + 150), geo.SHOT_SPEAKER, geo.MODE_CHEST, face=face) == set()


def test_speaker_caption_goes_above_the_head_when_the_face_reaches_the_chest() -> None:
    close_up = Box(190, 780, 820, 1500)           # chin at y 1500: chest level would be the face
    slot = geo.caption_slot(geo.SHOT_SPEAKER, Box(136, 587, 858, 1500), close_up)
    assert slot.mode == geo.MODE_ABOVE_HEAD and slot.y < 587
    assert "face" in rules(Box(200, 1180, 880, 1330), geo.SHOT_SPEAKER, geo.MODE_CHEST, face=close_up)


def test_chest_caption_outside_its_band_is_a_violation() -> None:
    assert "band" in rules(Box(200, 700, 880, 850), geo.SHOT_SPEAKER, geo.MODE_CHEST, face=Box(340, 100, 740, 400))
