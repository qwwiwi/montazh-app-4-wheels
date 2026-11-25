"""Punch-in zoom of the speaker (move 9): plan limits, geometry of the zoomed crop, analysis and gates recomputed, generator, render checks."""

import json
from pathlib import Path

import numpy as np
import pytest

import analysis as an_mod
import geometry as geo
import prerender_gate as pg
import reel_plan as rp
import render_checks as rcx
from conftest import EXAMPLES, build_example, make_words
from faces import FaceTrack
from geometry import Box
from reel_config import load_config

# 40 words, 0.4 s apart: слово{i} starts at 0.4 i; «слово4.» ends a sentence, «слово19» is followed by a long pause
LONG = make_words(" ".join(f"слово{i}" + ("." if i in (4, 10, 24) else "") for i in range(40)), gap_after={19: 0.5})


def long_plan(*zooms: tuple[int, str, float | None]) -> dict:
    """Split / speaker shots; each ``(word index, type, zoom)`` starts a shot at that word."""
    shots = [{"from": 0, "type": "split"}]
    for idx, kind, zoom in zooms:
        shots.append({"from": {"word": f"слово{idx}"}, "type": kind, **({"zoom": zoom} if zoom is not None else {})})
    return {"shots": shots, "scenes": [{"shot": i, "kind": "x10"} for i, s in enumerate(shots) if s["type"] != "speaker"]}


def build(*zooms: tuple[int, str, float | None]) -> rp.Plan:
    return rp.build_plan(long_plan(*zooms), LONG, 16.5)


# ---- plan --------------------------------------------------------------------------------------

def test_zoom_defaults_to_none_and_is_read_from_the_shot() -> None:
    plan = build((5, "speaker", None), (9, "split", None))
    assert [s.zoom for s in plan.shots] == [1.0, 1.0, 1.0]
    plan = build((5, "speaker", 1.12), (9, "split", None))
    assert [s.zoom for s in plan.shots] == [1.0, 1.12, 1.0] and rp.zoom_problems(plan.shots, LONG) == []


def test_zoom_only_on_a_full_screen_speaker_shot() -> None:
    with pytest.raises(rp.PlanError, match="speaker"):
        build((5, "split", 1.12))                         # the split shows a 960 px slice: no visible effect
    with pytest.raises(rp.PlanError, match="speaker"):
        raw = long_plan((5, "speaker", None), (9, "visual", 1.12))
        rp.build_plan(raw, LONG, 16.5)


@pytest.mark.parametrize("zoom", [1.02, 1.3, 0.9])
def test_zoom_stays_in_the_dosed_range(zoom: float) -> None:
    with pytest.raises(rp.PlanError, match="range"):
        build((5, "speaker", zoom))


def test_zoom_is_a_number() -> None:
    with pytest.raises(rp.PlanError, match="number"):
        build((5, "speaker", True))                       # type: ignore[arg-type]


def test_zoom_starts_on_a_sentence_boundary() -> None:
    build((5, "speaker", 1.12))                           # after «слово4.»
    build((20, "speaker", 1.12))                          # after a 0.5 s pause
    with pytest.raises(rp.PlanError, match="sentence"):
        build((7, "speaker", 1.12))                       # mid-sentence, no pause


def test_zoom_never_switches_in_the_middle_of_a_spoken_word() -> None:
    words = rp.load_words(EXAMPLES / "words-test-reel.json")
    duration = json.loads((EXAMPLES / "words-test-reel.json").read_text(encoding="utf-8"))["duration"]
    raw = json.loads((EXAMPLES / "plan-test-reel.json").read_text(encoding="utf-8"))
    raw["shots"][2].update({"from": 6.3, "zoom": 1.12})       # «командами.» sounds 6.06-6.54: the cut would slice it
    with pytest.raises(rp.PlanError, match="middle of the spoken word «командами»"):
        rp.build_plan(raw, words, duration)
    # the same shot at its word, with the usual lead before it, is accepted
    raw["shots"][2].update({"from": {"word": "И", "after": 6.0, "before": 7.0}, "zoom": 1.12})
    assert rp.build_plan(raw, words, duration).shots[2].zoom == 1.12


def test_sentence_boundary_is_checked_against_the_end_of_the_previous_word() -> None:
    ws = [rp.Word("конец.", 1.0, 1.5), rp.Word("новое", 1.52, 1.9), rp.Word("слово", 2.0, 2.4)]
    assert rp.at_sentence_boundary(ws, 1.52 - rp.LEAD)         # the usual cut: LEAD before the next word, 0.04 s inside the previous one
    assert rp.at_sentence_boundary(ws, 1.5)                    # right at the end of the sentence
    assert not rp.at_sentence_boundary(ws, 1.3)                # mid-word although the word ends a sentence
    assert not rp.at_sentence_boundary(ws, 2.2)                # inside the last word
    assert not rp.at_sentence_boundary(ws, 1.2)
    assert rp.at_sentence_boundary(ws, 2.4) and rp.at_sentence_boundary(ws, 5.0)    # after the last word
    assert rp.at_sentence_boundary(ws, 0.0)


def test_zoom_count_and_spacing_are_dosed() -> None:
    ok = build((5, "speaker", 1.12), (9, "split", None), (25, "speaker", 1.15))
    assert rp.zoom_problems(ok.shots, LONG) == []
    with pytest.raises(rp.PlanError, match="at most 2"):
        build((5, "speaker", 1.12), (11, "speaker", 1.12), (20, "speaker", 1.12), (25, "speaker", 1.12))
    with pytest.raises(rp.PlanError, match="6"):
        build((5, "speaker", 1.12), (11, "speaker", 1.12))      # 2.4 s apart: a zoom more often than every 6 s is a tic


def test_zoom_pure_check_lists_every_problem() -> None:
    shots = [rp.Shot(0, 2, "split", "", 1.12), rp.Shot(2, 4, "speaker", "", 1.5)]
    problems = rp.zoom_problems(shots, LONG)
    assert any("speaker" in p for p in problems) and any("range" in p for p in problems)


# ---- geometry ----------------------------------------------------------------------------------

def test_zoom_box_scales_about_the_origin() -> None:
    box = Box(100, 200, 300, 400)
    assert geo.zoom_box(box, 1.0, (200, 300)) == box
    z = geo.zoom_box(box, 1.2, (200, 300))
    assert (z.x0, z.y0, z.x1, z.y1) == pytest.approx((80, 180, 320, 420))        # the origin stays put, the box grows 20 %
    assert geo.zoom_origin(Box(100, 200, 300, 400)) == (200.0, 300.0)


def test_zoomed_face_must_stay_out_of_the_interface_zone_and_the_frame() -> None:
    face, head = Box(180, 770, 830, 1460), Box(140, 590, 860, 1476)
    origin = geo.zoom_origin(face)
    ok = geo.zoom_violations("shot1", geo.zoom_box(face, 1.12, origin), geo.zoom_box(head, 1.12, origin))
    assert ok == []
    low = geo.zoom_violations("shot1", geo.zoom_box(face, 1.18, origin), geo.zoom_box(head, 1.18, origin))
    assert {v.rule for v in low} == {"zoom-ui"}                                  # the chin crosses y 1520
    wide = geo.zoom_violations("shot1", Box(0, 800, 900, 1200), Box(-5, 700, 1090, 1300))
    assert {v.rule for v in wide} == {"zoom-frame"}


def test_zoomed_face_must_not_slide_under_the_right_hand_buttons() -> None:
    face, head = Box(460, 800, 940, 1450), Box(400, 600, 950, 1470)           # clear of the buttons column (x >= 950, y 1080..1720) before the zoom
    origin = geo.zoom_origin(face)
    assert geo.zoom_violations("shot1", face, head) == []
    zf, zh = geo.zoom_box(face, 1.12, origin), geo.zoom_box(head, 1.12, origin)
    assert (zf.x0, zf.y0, zf.x1, zf.y1) == pytest.approx((431.2, 761, 968.8, 1489))
    found = geo.zoom_violations("shot1", zf, zh)
    assert {v.rule for v in found} == {"zoom-buttons"} and "950" in found[0].detail
    # a face that is high enough (y1 above the column) or left of it is fine
    assert geo.zoom_violations("s", Box(700, 700, 1000, 1070), None) == []
    assert geo.zoom_violations("s", Box(500, 900, 949, 1400), None) == []
    assert {v.rule for v in geo.zoom_violations("s", Box(800, 1000, 960, 1100), None)} == {"zoom-buttons"}


# ---- analysis: boxes, caption slot and problems recomputed for the zoomed crop ------------------

def track(face: tuple[int, int, int, int] = (190, 780, 820, 1450)) -> FaceTrack:
    n = 80
    return FaceTrack(0.25, tuple(i * 0.25 for i in range(n)), tuple(Box(*face) for _ in range(n)), tuple(Box(140, 590, 860, 1476) for _ in range(n)))


def analyse(zoom: float, face: tuple[int, int, int, int] = (190, 780, 820, 1450)):  # noqa: ANN202
    import reel_captions as rc

    plan = build((5, "speaker", zoom if zoom != 1.0 else None))
    cfg = load_config(EXAMPLES / "reel_config-test-reel.json")
    return plan, an_mod.analyse(plan, rc.build_groups(LONG, plan), track(face), cfg)


def test_zoomed_shot_has_zoomed_face_head_and_a_higher_caption_slot() -> None:
    plan_a, plain = analyse(1.0)
    plan_b, zoomed = analyse(1.12)
    a, b = plain.info(plan_a.shots[1]), zoomed.info(plan_b.shots[1])
    assert b.zoom == 1.12 and b.origin is not None and a.origin is None
    assert b.face_screen.y0 < a.face_screen.y0 and b.face_screen.y1 > a.face_screen.y1           # grows about its centre
    assert b.head_screen.y0 < a.head_screen.y0
    assert b.slot.y < a.slot.y                                                                    # the caption keeps clear of the zoomed hair
    assert zoomed.problems == () and plain.problems == ()


def test_too_much_zoom_on_a_low_chin_is_a_problem_of_the_shot() -> None:
    _, zoomed = analyse(1.18)
    assert any(v.rule == "zoom-ui" for v in zoomed.problems)


# ---- generator and gate on the example reel -----------------------------------------------------

ZOOM_EXAMPLE = {"from": {"word": "И", "after": 6.0, "before": 7.0}, "type": "speaker", "note": "breath: «это не для меня»", "zoom": 1.12}


def zoom_edit(raw: dict) -> None:
    raw["shots"][2] = ZOOM_EXAMPLE


@pytest.fixture(scope="module")
def built_zoom(tmp_path_factory: pytest.TempPathFactory):  # noqa: ANN201
    return build_example(tmp_path_factory.mktemp("zoom"), edit_plan=zoom_edit)


def test_page_zooms_only_the_marked_shot_and_resets_after_it(built_zoom) -> None:  # noqa: ANN001
    page = (built_zoom.project / "index.html").read_text(encoding="utf-8")
    sets = [ln for ln in page.splitlines() if ln.startswith('tl.set("#vbase"')]
    assert len(sets) == len(built_zoom.plan.shots)
    assert sum("scale:1.12" in ln and "transformOrigin" in ln for ln in sets) == 1
    assert all("scale:1," in ln or "scale:1}" in ln for ln in sets if "scale:1.12" not in ln)       # every other shot resets the scale
    info = built_zoom.analysis.info(built_zoom.plan.shots[2])
    assert f'transformOrigin:"{info.origin[0]:.1f}px {info.origin[1]:.1f}px"' in page


def test_old_plan_page_has_no_zoom_transform(tmp_path: Path) -> None:
    info = build_example(tmp_path)
    page = (info.project / "index.html").read_text(encoding="utf-8")
    assert "transformOrigin" not in "".join(ln for ln in page.splitlines() if ln.startswith('tl.set("#vbase"'))
    assert all(s.zoom == 1.0 for s in info.plan.shots)


def _boxes(info, mutate: dict | None = None):  # noqa: ANN001, ANN202
    mutate = mutate or {}
    caps = []
    for g in info.groups:
        slot = info.analysis.slots[g.id]
        y1 = slot.y if slot.anchor == "bottom" else slot.y + 174
        box = {"x0": 200.0, "y0": y1 - 174, "x1": 880.0, "y1": y1}
        box.update(mutate.get(g.id, {}))
        caps.append({"id": g.id, "mode": slot.mode, "shot": g.shot_type, "start": g.start, "duration": g.end - g.start, "text": g.text, "w": 680.0, "h": 174.0, **box,
                     "words": [{"text": w.w, "x0": 200.0, "y0": box["y0"], "x1": 300.0, "y1": box["y1"]} for w in g.words]})
    return {"fontsOk": True, "captions": caps, "scenes": [], "roles": {"codeword": {"x0": 100.0, "y0": 420.0, "x1": 900.0, "y1": 600.0, "font": 124.0, "text": "ВЫХОДНЫЕ"}}}


def test_gate_is_recomputed_for_the_zoomed_crop(built_zoom, tmp_path: Path) -> None:  # noqa: ANN001
    cfg = load_config(EXAMPLES / "reel_config-test-reel.json")
    assert pg.run_gate(built_zoom, _boxes(built_zoom), cfg) == []
    speaker = next(g for g in built_zoom.groups if g.shot == 2)
    plain = build_example(tmp_path)                                  # the same reel without the zoom: its speaker caption sits lower
    old_slot = plain.analysis.slots[next(g.id for g in plain.groups if g.shot == 2)]
    new_slot = built_zoom.analysis.slots[speaker.id]
    assert new_slot.y < old_slot.y
    stale = {speaker.id: {"y0": old_slot.y - 174, "y1": old_slot.y}}      # the caption box of the UNZOOMED layout
    rules = {v.rule for v in pg.run_gate(built_zoom, _boxes(built_zoom, stale), cfg)}
    assert "band" in rules                                           # now the hair is higher: the old box would sit on it


def test_gate_reports_a_zoom_that_pushes_the_chin_into_the_interface_zone(tmp_path: Path) -> None:
    cfg = load_config(EXAMPLES / "reel_config-test-reel.json")
    info = build_example(tmp_path, edit_plan=lambda raw: raw["shots"].__setitem__(2, {**ZOOM_EXAMPLE, "zoom": 1.18}))
    assert any(v.rule == "zoom-ui" for v in pg.run_gate(info, _boxes(info), cfg))


def test_meta_carries_the_zoom_for_the_post_render_check(built_zoom, tmp_path: Path) -> None:  # noqa: ANN001
    import reel

    out = tmp_path / "meta.json"
    reel.write_meta(built_zoom, out, 60)
    shots = json.loads(out.read_text(encoding="utf-8"))["shots"]
    assert shots[2]["zoom"] == 1.12 and len(shots[2]["origin"]) == 2 and "zoom" not in shots[1]


# ---- render checks ------------------------------------------------------------------------------

def pattern(h: int = 480, w: int = 270) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w]
    return (127 + 100 * np.sin(x * 0.9) * np.sin(y * 0.9)).astype(np.uint8)


def test_zoom_frame_keeps_the_origin_and_scales_around_it() -> None:
    img = pattern()
    assert np.array_equal(rcx.zoom_frame(img, 1.0, (135, 300)), img)
    big = np.zeros((480, 270), dtype=np.uint8)
    big[290:310, 125:145] = 255                                                      # a block around the origin (135, 300)
    zoomed = rcx.zoom_frame(big, 2.0, (135, 300))
    assert zoomed[300, 135] == 255 and zoomed[300 + 15, 135] == 255 and big[300 + 15, 135] == 0       # grows from the centre


def test_classify_knows_a_zoomed_speaker_frame_only_with_the_zoom() -> None:
    cut = pattern()
    render = rcx.zoom_frame(cut, 1.15, (135, 300))
    assert rcx.classify(render, cut, 100) == geo.SHOT_VISUAL                          # without the zoom it looks like a card
    assert rcx.classify(render, cut, 100, zoom=(1.15, 135.0, 300.0)) == geo.SHOT_SPEAKER
    assert rcx.classify(cut, cut, 100, zoom=(1.15, 135.0, 300.0)) == geo.SHOT_SPEAKER      # an unzoomed frame near the cut is still the speaker


def test_post_render_check_looks_up_the_planned_zoom_of_the_shot_on_screen() -> None:
    import postrender_check as pc

    shots = [{"start": 0.0, "end": 2.0, "type": "split"}, {"start": 2.0, "end": 4.0, "type": "speaker", "zoom": 1.12, "origin": [505.0, 1115.0]},
             {"start": 4.0, "end": 6.0, "type": "speaker"}]
    assert pc.zoom_at(shots, 1.0) is None and pc.zoom_at(shots, 5.0) is None
    assert pc.zoom_at(shots, 3.0) == (1.12, 505.0, 1115.0)
    assert pc.zoom_at(shots, 3.0, 4) == (1.12, 126.25, 278.75)              # small frames are 4 times smaller


def test_a_planned_zoom_that_the_render_does_not_show_is_a_failure() -> None:
    cut = pattern()
    zoom = (1.15, 135.0, 300.0)
    assert rcx.zoom_problem("shot 2", rcx.zoom_frame(cut, 1.15, (135, 300)), cut, zoom) is None
    msg = rcx.zoom_problem("shot 2", cut, cut, zoom)                                  # the render shows the plain frame
    assert msg is not None and "not applied" in msg
    flat = np.full((480, 270), 90, dtype=np.uint8)
    assert rcx.zoom_problem("shot 2", flat, flat, zoom) is None                      # nothing to tell apart: no false alarm
