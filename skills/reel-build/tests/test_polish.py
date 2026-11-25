""" no decorative filler, large readable text, the ending code word, the dark palette (generator, gate, plan, frames)."""

import json
from pathlib import Path

import numpy as np
import pytest

import build_composition as bc
import geometry as geo
import prerender_gate as pg
import reel_plan as rp
import render_checks as rc
import scenes
from geometry import Box
from reel_config import load_config

EX = Path(__file__).resolve().parent.parent / "examples"
SKILL = Path(__file__).resolve().parent.parent

needs_assets = pytest.mark.skipif(not bc.NODE_MODULES.exists(), reason="npm install in skills/reel-build first (fonts, GSAP)")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> bc.BuildInfo:
    tmp = tmp_path_factory.mktemp("proj")
    cut = tmp / "cut.mp4"
    cut.write_bytes(b"x")
    head = tmp / "head.json"
    samples = [{"t": i * 0.25, "box": [140, 590, 860, 1476], "face": [190, 780, 820, 1450]} for i in range(180)]
    head.write_text(json.dumps({"step": 0.25, "samples": samples}), encoding="utf-8")
    words = rp.load_words(EX / "words-test-reel.json")
    duration = json.loads((EX / "words-test-reel.json").read_text(encoding="utf-8"))["duration"]
    plan = rp.load_plan(EX / "plan-test-reel.json", words, duration)
    return bc.build_project(cut, words, plan, load_config(EX / "reel_config-test-reel.json"), head, tmp / "reel")


# --- 1. no decorative filler ---------------------------------------------------------------------

@needs_assets
def test_page_has_no_decorative_filler_blocks(built: bc.BuildInfo) -> None:
    page = (built.project / "index.html").read_text(encoding="utf-8")
    assert 'data-deco' not in page and 'class="deco"' not in page
    assert scenes.decor_problems(page) == []
    assert not hasattr(scenes.SB, "deco")


def test_decor_check_fails_on_a_filler_or_a_decor_reused_in_two_scenes() -> None:
    page = ('<div id="s0" class="clip scene full"><div data-decor="blocks"></div></div>'
            '<div id="s1" class="clip scene full"><div data-decor="blocks"></div></div>')
    assert any("blocks" in p for p in scenes.decor_problems(page))
    assert scenes.decor_problems('<div id="s0" class="clip scene"><div data-decor="a"></div></div><div id="s1" class="clip scene"><div data-decor="b"></div></div>') == []
    assert scenes.decor_problems('<div id="s0" class="clip scene"><div class="deco" data-deco="1"></div></div>')


# --- 2. text size and contrast -------------------------------------------------------------------

def test_label_threshold_is_32_px_and_code_is_40_px() -> None:
    assert scenes.MIN_TEXT_PX >= 32 and scenes.MIN_MONO_PX >= 40
    assert scenes.lint_fonts(".lbl { font-size:30px; }")
    assert scenes.lint_fonts(".lbl { font-size:32px; }") == []


@needs_assets
def test_generated_page_has_no_text_below_32_px(built: bc.BuildInfo) -> None:
    assert scenes.lint_fonts((built.project / "index.html").read_text(encoding="utf-8")) == []


def _scene_with(part: dict) -> dict:
    card = {"id": "c", "x0": 80.0, "y0": 200.0, "x1": 1000.0, "y1": 900.0, "w": 920.0, "h": 700.0}
    base = {"tag": "div", "text": "code", "x0": 100.0, "y0": 300.0, "x1": 300.0, "y1": 340.0, "card": "c", "font": 44.0, "mono": False,
            "fg": [244, 239, 233], "bg": [28, 25, 22], "opacity": 1.0}
    return {"id": "s0", "kind": "x", "zone": "full", "start": 0, "dur": 1, "cards": [card], "loose": [], "parts": [{**base, **part}]}


def test_gate_fails_code_text_under_40_px_and_low_contrast() -> None:
    assert pg.zone_violations(_scene_with({})) == []
    assert "font-size" in {v.rule for v in pg.zone_violations(_scene_with({"mono": True, "font": 34.0}))}
    assert "font-size" not in {v.rule for v in pg.zone_violations(_scene_with({"mono": True, "font": 44.0}))}
    dim = _scene_with({"fg": [138, 129, 122], "bg": [255, 253, 249]})          # the old muted grey on a light card: 3.7:1
    assert "contrast" in {v.rule for v in pg.zone_violations(dim)}
    assert "contrast" not in {v.rule for v in pg.zone_violations(_scene_with({"fg": [92, 84, 77], "bg": [255, 253, 249]}))}
    assert "contrast" not in {v.rule for v in pg.zone_violations(_scene_with({"fg": [20, 17, 15], "bg": [255, 253, 249], "opacity": 0.0}))}


def test_contrast_ratio_matches_wcag() -> None:
    assert pg.contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=0.01)
    assert pg.contrast_ratio((138, 129, 122), (255, 253, 249)) < 4.5


# --- 3. the ending: the code word is the biggest thing and stays readable -------------------------

def _frame() -> np.ndarray:
    img = np.empty((geo.FRAME_H, geo.FRAME_W, 3), dtype=np.uint8)
    img[:] = (14, 13, 12)
    return img


def test_codeword_check_wants_a_tall_stable_box_inside_the_visual_half() -> None:
    box = Box(100, 420, 900, 580)
    a, b = _frame(), _frame()
    for img in (a, b):
        img[430:570, 110:890] = (252, 253, 255)
        img[450:550, 200:800] = (15, 17, 20)
    assert rc.codeword_problems("end", a, b, box) == []
    assert any("empty" in p for p in rc.codeword_problems("end", _frame(), b, box))
    c = b.copy()
    c[450:550, 200:800] = (252, 253, 255)                              # a pointer or an overlay hides the word at the last frame
    assert any("changes" in p or "covered" in p for p in rc.codeword_problems("end", a, c, box))
    assert any("half" in p for p in rc.codeword_problems("end", a, b, Box(100, 900, 900, 1060)))
    assert any("90" in p for p in rc.codeword_problems("end", a, b, Box(100, 420, 900, 480)))


@needs_assets
def test_ending_has_the_codeword_role_and_a_comment_label(built: bc.BuildInfo) -> None:
    page = (built.project / "index.html").read_text(encoding="utf-8")
    assert 'data-role="codeword"' in page
    assert "Комментарий" in page.split('data-role="reminder"')[1][:2500]


def test_no_misspelled_comment_in_sources_or_screen_text() -> None:
    bad = "комент"
    for path in list(SKILL.glob("scripts/*.py")) + list(SKILL.glob("examples/*.json")) + [SKILL / "SKILL.md"]:
        assert bad not in path.read_text(encoding="utf-8").lower(), path
    assert scenes.spelling_problems("<div>КОМЕНТАРИЙ</div>") and scenes.spelling_problems("<div>КОММЕНТАРИЙ</div>") == []


# --- 4. palette ----------------------------------------------------------------------------------

@needs_assets
def test_example_plan_is_dark_by_default(built: bc.BuildInfo) -> None:
    assert rp.light_share(built.plan) <= rp.LIGHT_SHARE_MAX
    assert rp.palette_problems(built.plan) == []


def test_rendered_light_share_is_measured_on_the_frames() -> None:
    gray_light, gray_dark, gray_orange = (np.full((480, 270), v, np.uint8) for v in (238, 14, 145))
    assert rc.is_light_frame(gray_light, "split") and not rc.is_light_frame(gray_dark, "split") and not rc.is_light_frame(gray_orange, "visual")
    types = ["split", "split", "speaker", "visual"]
    assert rc.light_share(types, [True, False, True, True]) == pytest.approx(2 / 3)     # the speaker frame is not a visual
    assert rc.palette_problem(0.40) and rc.palette_problem(0.2) is None


def test_contact_sheet_times_are_dense_in_the_last_six_seconds() -> None:
    """The brief: a frame every 0.5 s, every 0.25 s for the last 6 s."""
    t = rc.sheet_times(41.83)
    assert t[0] == 0.0 and t[1] == 0.5 and t == sorted(set(t))
    tail = [x for x in t if x >= 41.83 - 6.0]
    assert len(tail) >= 23 and all(abs(b - a - 0.25) < 1e-6 for a, b in zip(tail, tail[1:]))
    assert max(t) > 41.5 and all(abs(b - a - 0.5) < 1e-6 for a, b in zip(t[:70], t[1:70]) if b < 35.0)
