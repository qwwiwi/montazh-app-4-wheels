"""Post-render checks on synthetic frames: each rule fails on a bad frame and passes on a good one."""

import numpy as np

import geometry as geo
import render_checks as rc
from geometry import Box

PAPER = (230, 238, 243)     # BGR of the light background
INK = (15, 17, 20)


def blank(colour: tuple[int, int, int] = PAPER) -> np.ndarray:
    img = np.empty((geo.FRAME_H, geo.FRAME_W, 3), dtype=np.uint8)
    img[:] = colour
    return img


def fill(img: np.ndarray, box: Box, colour: tuple[int, int, int] = INK) -> None:
    img[int(box.y0):int(box.y1), int(box.x0):int(box.x1)] = colour


def bg_of(img: np.ndarray, box: Box) -> np.ndarray:
    return rc.background(img, int(box.y0), int(box.y1))


# --- caption: seam, clipped, interface zone, face ----------------------------------------------

def test_caption_across_the_seam_fails_on_the_frame() -> None:
    img, box = blank(), Box(200, 880, 880, 1010)
    fill(img, Box(300, 900, 700, 990))
    assert any("seam" in p for p in rc.caption_problems("c1", img, box, geo.SHOT_SPLIT, bg_of(img, box), None))


def test_caption_fully_above_the_seam_passes() -> None:
    img, box = blank(), Box(200, 770, 880, 944)
    fill(img, Box(300, 800, 700, 930))
    assert rc.caption_problems("c1", img, box, geo.SHOT_SPLIT, bg_of(img, box), None) == []


def test_ink_in_the_rows_just_above_the_seam_fails() -> None:
    img, box = blank(), Box(200, 770, 880, 944)
    fill(img, Box(0, 945, geo.FRAME_W, 952))
    assert any("just above the seam" in p for p in rc.caption_problems("c1", img, box, geo.SHOT_SPLIT, bg_of(img, box), None))


def test_clipped_caption_fails_by_box_and_by_pixels() -> None:
    img, box = blank(), Box(10, 770, 700, 944)
    assert any("clipped" in p for p in rc.caption_problems("c1", img, box, geo.SHOT_SPLIT, bg_of(img, box), None))
    img2, box2 = blank(), Box(100, 770, 900, 944)
    fill(img2, Box(0, 780, 8, 930))
    assert any("frame edge" in p for p in rc.caption_problems("c2", img2, box2, geo.SHOT_SPLIT, bg_of(img2, box2), None))


def test_caption_over_the_face_fails() -> None:
    img, box = blank(), Box(200, 1000, 880, 1170)
    face = Box(300, 800, 800, 1450)
    assert any("over the face" in p for p in rc.caption_problems("c1", img, box, geo.SHOT_SPEAKER, bg_of(img, box), face))
    above = Box(200, 350, 880, 524)
    assert rc.caption_problems("c2", img, above, geo.SHOT_SPEAKER, bg_of(img, above), face) == []


def test_caption_in_the_interface_zone_fails() -> None:
    img, box = blank(), Box(200, 1450, 880, 1620)
    assert any("interface zone" in p for p in rc.caption_problems("c1", img, box, geo.SHOT_VISUAL, bg_of(img, box), None))


def test_caption_presence_needs_ink() -> None:
    img, box = blank(), Box(200, 770, 880, 944)
    assert not rc.caption_present(img, box, bg_of(img, box))
    fill(img, Box(300, 800, 700, 930))
    assert rc.caption_present(img, box, bg_of(img, box))


# --- visual panel coverage from the first frame ----------------------------------------------

def test_empty_panel_on_the_first_frame_fails() -> None:
    for shot in (geo.SHOT_SPLIT, geo.SHOT_VISUAL):
        msg = rc.coverage_problem("shot", blank(), shot)
        assert msg and "covers" in msg


def test_card_on_the_first_frame_passes_even_with_a_background_grid() -> None:
    img = blank()
    img[::54] = (222, 230, 236)                # thin grid lines must not count as content
    assert rc.coverage(img, geo.SHOT_SPLIT) < 0.01
    fill(img, Box(60, 150, 1020, 750), (252, 253, 255))
    assert rc.coverage_problem("shot", img, geo.SHOT_SPLIT) is None


def test_dark_card_on_dark_background_counts() -> None:
    img = blank((12, 13, 14))
    fill(img, Box(60, 150, 1020, 750), (22, 25, 28))
    assert rc.coverage(img, geo.SHOT_SPLIT) > 0.5


# --- static pictures ---------------------------------------------------------------------------

def test_static_visual_longer_than_two_seconds_fails() -> None:
    assert rc.static_problems("seg", [True, False, False, False, True], 0.1) == []
    flags = [True] + [False] * 25 + [True]
    problems = rc.static_problems("seg", flags, 0.1)
    assert len(problems) == 1 and "2.5 s" in problems[0]
    assert rc.static_problems("seg", [True] + [False] * 30, 0.1)      # a static tail counts too


def test_changed_sees_a_tick_but_not_noise() -> None:
    a = np.full((480, 270), 200, np.uint8)
    b = a.copy()
    b[100:114, 100:114] = 40                    # a tick-sized mark
    assert rc.changed(a, b, (29, 190))
    noisy = a.copy()
    noisy[::7, ::5] += 6
    assert not rc.changed(a, noisy, (29, 190))


# --- shot types on the render ----------------------------------------------------------------

def test_same_type_longer_than_4_5_seconds_fails() -> None:
    runs = rc.runs_of(["split"] * 50 + ["visual"] * 20, 0.1)
    assert rc.run_problems(runs) and "split" in rc.run_problems(runs)[0]
    assert rc.run_problems(rc.runs_of(["split"] * 45 + ["speaker"] * 15, 0.1)) == []


def test_classify_tells_speaker_split_and_visual_apart() -> None:
    rng = np.random.default_rng(3)
    cut = rng.integers(0, 255, (480, 270), dtype=np.uint8)
    assert rc.classify(cut.copy(), cut, 100) == geo.SHOT_SPEAKER
    split = rng.integers(0, 255, (480, 270), dtype=np.uint8)
    split[240:] = cut[100:340]
    assert rc.classify(split, cut, 100) == geo.SHOT_SPLIT
    assert rc.classify(rng.integers(0, 255, (480, 270), dtype=np.uint8), cut, 100) == geo.SHOT_VISUAL


# --- interface zone of full-screen visuals ---------------------------------------------------

def test_anything_in_1520_1920_of_a_visual_fails_even_a_few_filler_blocks() -> None:
    """the decorative blocks are gone; the interface zone stays free of graphics."""
    img = blank()
    assert rc.ui_zone_problem("v", img) is None
    assert rc.ui_zone_problem("v", _filled()) is None
    fill(img, Box(60, 1560, 1020, 1860))                        # a dark card
    assert "interface zone" in (rc.ui_zone_problem("v", img) or "")
    blocks = _filled()
    for x, y in ((60, 1548), (330, 1560), (600, 1548), (110, 1730), (470, 1744), (800, 1722)):
        fill(blocks, Box(x, y, x + 110, y + 110), (60, 100, 200))
    assert "interface zone" in (rc.ui_zone_problem("v", blocks) or "")


# --- empty band in a full-screen visual  --------------------------------------------

def test_card_in_the_top_65_percent_with_an_empty_lower_third_fails() -> None:
    img = blank()
    fill(img, Box(60, 200, 1020, 840), (252, 253, 255))          # the v2 card: nothing below it except the caption
    fill(img, Box(200, 1320, 880, 1450))
    msg = rc.empty_band_problem("v", img)
    assert msg and "empty band" in msg


def _filled() -> np.ndarray:
    """Card y 150..1250 and the caption 1320..1450; below the caption is Instagram's interface zone, left empty."""
    img = blank()
    fill(img, Box(60, 150, 1020, 1250), (252, 253, 255))
    fill(img, Box(200, 1320, 880, 1450))
    return img


def test_card_that_fills_the_frame_needs_no_decoration_and_the_caption_splits_the_gap() -> None:
    img = _filled()
    assert rc.empty_band_problem("v", img) is None
    assert rc.empty_band(img) < 0.18 * geo.FRAME_H
    img2 = blank()                                               # card 150..700, the caption alone under a 620 px gap
    fill(img2, Box(60, 150, 1020, 700), (252, 253, 255))
    fill(img2, Box(200, 1320, 880, 1450))
    assert rc.empty_band(img2) >= 600


def test_background_grid_does_not_fill_an_empty_band() -> None:
    img = blank()
    img[::54] = (222, 230, 236)
    img[:, ::54] = (222, 230, 236)
    fill(img, Box(60, 150, 1020, 700), (252, 253, 255))
    assert rc.empty_band(img) > 700


# --- hook: frame 0 is sharp and its caption is solid  --------------------------------

def _texty() -> np.ndarray:
    img = blank()
    for k in range(12):                                          # stripes of «text»: high local contrast
        fill(img, Box(100, 200 + k * 40, 900, 214 + k * 40))
    return img


def test_blurred_first_frame_fails_the_hook_check() -> None:
    import cv2
    sharp = _texty()
    blurred = cv2.GaussianBlur(sharp, (0, 0), 9)
    box = Box(300, 800, 700, 900)
    assert rc.hook_problems(sharp, sharp, box) == []
    assert any("blur" in p for p in rc.hook_problems(blurred, sharp, box))


def test_faint_first_caption_word_fails_the_hook_check() -> None:
    settled = blank()
    fill(settled, Box(320, 820, 600, 880))
    faint = blank()
    fill(faint, Box(320, 820, 600, 880), (200, 210, 218))        # 30 % opacity ink: barely darker than the paper
    problems = rc.hook_problems(_texty(), _texty(), Box(300, 800, 700, 900), first=faint, settled_caption=settled)
    assert any("caption" in p for p in problems)
    assert rc.hook_problems(_texty(), _texty(), Box(300, 800, 700, 900), first=settled, settled_caption=settled) == []


# --- state changes: tighter than 2 s  -------------------------------------------------

def test_a_picture_that_holds_for_1_7_seconds_already_fails() -> None:
    assert rc.STATE_GAP_MAX_S <= 2.0
    flags = [True] + [False] * 17 + [True]
    problems = rc.static_problems("seg", flags, 0.1)
    assert len(problems) == 1 and "1.7 s" in problems[0]
    assert rc.static_problems("seg", [True] + [False] * 14 + [True], 0.1) == []


# --- reminder of the code word in the last seconds  ---------------------------------

def test_reminder_box_must_show_ink_that_changes_at_the_end() -> None:
    early, last = blank(), blank()
    box = Box(100, 600, 900, 740)
    assert any("reminder" in p for p in rc.reminder_problems(early, last, box))      # nothing drawn
    fill(last, Box(120, 620, 880, 720), (252, 253, 255))
    fill(last, Box(200, 650, 600, 690))
    assert rc.reminder_problems(early, last, box) == []


def test_a_pointer_move_alone_is_not_a_visible_state_change() -> None:
    """v2 passed the old detector (any tiny change counted) while the reviewer saw a static card."""
    a = np.full((480, 270), 200, np.uint8)
    pointer = a.copy()
    pointer[100:114, 100:114] = 40                  # a 56 px pointer at full size = 14 px small
    block = a.copy()
    block[100:130, 60:150] = 40                     # a typed line / a flipped toggle row
    rows = (29, 291)                                # the visual area of a full-screen shot, small rows
    assert not rc.changed(a, pointer, rows)
    assert rc.changed(a, block, rows)
