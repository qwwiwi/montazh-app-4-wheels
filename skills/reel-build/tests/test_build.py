"""Generator and pre-render gate on the synthetic test reel (words, plan and config of the examples; no browser, no media)."""

import dataclasses
import json
from pathlib import Path

import pytest

import build_composition as bc
import geometry as geo
import prerender_gate as pg
import reel_plan as rp
from reel_config import load_config

EX = Path(__file__).resolve().parent.parent / "examples"

pytestmark = pytest.mark.skipif(not bc.NODE_MODULES.exists(), reason="npm install in skills/reel-build first (fonts, GSAP)")


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
    cfg = load_config(EX / "reel_config-test-reel.json")
    return bc.build_project(cut, words, plan, cfg, head, tmp / "reel")


def test_example_plan_obeys_the_canon_rhythm(built: bc.BuildInfo) -> None:
    assert rp.rhythm_problems(built.plan.shots, built.plan.cta) == []
    types = {s.type for s in built.plan.shots}
    assert types == set(geo.SHOT_TYPES)


def test_every_scene_changes_state_at_least_every_two_seconds(built: bc.BuildInfo) -> None:
    for sc in built.plan.scenes:
        assert rp.static_gaps(built.scene_states[sc.n], sc.start, sc.end) == [], sc.kind


def test_page_has_a_scene_per_visual_shot_and_the_split_slice(built: bc.BuildInfo) -> None:
    page = (built.project / "index.html").read_text(encoding="utf-8")
    assert page.count('class="clip scene ') == 12
    assert page.count('data-cap="1"') == len(built.groups)
    assert f'y:{960 - built.analysis.layout.y0}' in page and f"inset({built.analysis.layout.y0}px" in page
    assert "<audio" in page and "tl.seek(0)" in page


def test_hook_scene_is_on_screen_from_frame_zero(built: bc.BuildInfo) -> None:
    first = built.plan.scenes[0]
    assert first.kind == "hook" and first.start == 0.0 and built.plan.shots[0].type == geo.SHOT_SPLIT
    assert built.groups[0].start == 0.0


def test_plan_violations_are_clean_and_find_a_repeat(built: bc.BuildInfo) -> None:
    assert pg.plan_violations(built) == []
    dup = list(built.words[:5]) + [rp.Word(w.w, w.start + 20, w.end + 20) for w in built.words[:5]]
    bad = dataclasses.replace(built, words=tuple(dup))
    assert any(v.rule == "repeat" for v in pg.plan_violations(bad))


def test_plan_violations_find_a_static_scene(built: bc.BuildInfo) -> None:
    bad = dataclasses.replace(built, scene_states={**built.scene_states, 0: [0.0]})
    assert any(v.rule == "static" for v in pg.plan_violations(bad))


def _boxes(built: bc.BuildInfo, mutate: dict[str, dict] | None = None) -> dict:
    mutate = mutate or {}
    caps = []
    for g in built.groups:
        slot = built.analysis.slots[g.id]
        y1 = slot.y if slot.anchor == "bottom" else slot.y + 174
        box = {"x0": 200.0, "y0": y1 - 174, "x1": 880.0, "y1": y1}
        box.update(mutate.get(g.id, {}))
        words = [{"text": w.w, "x0": 200.0, "y0": box["y0"], "x1": 300.0, "y1": box["y1"]} for w in g.words]
        caps.append({"id": g.id, "mode": slot.mode, "shot": g.shot_type, "start": g.start, "duration": g.end - g.start, "text": g.text,
                     "w": 680.0, "h": 174.0, **box, "words": words})
    return {"fontsOk": True, "captions": caps, "scenes": [], "roles": {"codeword": {"x0": 100.0, "y0": 420.0, "x1": 900.0, "y1": 600.0, "font": 124.0, "text": "ВЫХОДНЫЕ"}}}


def test_gate_passes_clean_boxes_and_fails_a_caption_over_the_seam(built: bc.BuildInfo) -> None:
    cfg = load_config(EX / "reel_config-test-reel.json")
    assert pg.run_gate(built, _boxes(built), cfg) == []
    split_id = next(g.id for g in built.groups if g.shot_type == geo.SHOT_SPLIT)
    rules = {v.rule for v in pg.run_gate(built, _boxes(built, {split_id: {"y0": 880.0, "y1": 1010.0}}), cfg)}
    assert {"seam", "band"} <= rules


def test_gate_fails_a_caption_over_the_face_and_a_clipped_one(built: bc.BuildInfo) -> None:
    cfg = load_config(EX / "reel_config-test-reel.json")
    speaker_id = next(g.id for g in built.groups if g.shot_type == geo.SHOT_SPEAKER)
    rules = {v.rule for v in pg.run_gate(built, _boxes(built, {speaker_id: {"y0": 1000.0, "y1": 1170.0}}), cfg)}
    assert "face" in rules
    split_id = next(g.id for g in built.groups if g.shot_type == geo.SHOT_SPLIT)
    assert "clipped" in {v.rule for v in pg.run_gate(built, _boxes(built, {split_id: {"x0": 5.0}}), cfg)}


def test_zone_violations_catch_content_in_the_interface_zone_and_overflowing_text() -> None:
    card = {"id": "c", "x0": 80.0, "y0": 200.0, "x1": 1000.0, "y1": 1600.0, "w": 920.0, "h": 1400.0}
    scene = {"id": "s0", "kind": "x", "zone": "full", "start": 0, "dur": 1, "cards": [card], "loose": [],
             "parts": [{"tag": "div", "text": "hello", "x0": 100.0, "y0": 1100.0, "x1": 1050.0, "y1": 1140.0, "card": "c"}]}
    rules = {v.rule for v in pg.zone_violations(scene)}
    assert {"zone", "overflow", "buttons"} <= rules
    ok = dict(scene, cards=[dict(card, y1=1200.0)], parts=[{"tag": "div", "text": "hi", "x0": 100.0, "y0": 300.0, "x1": 600.0, "y1": 340.0, "card": "c"}])
    assert pg.zone_violations(ok) == []


# ---  --------------------------------------------------------------------------------

def test_text_in_the_mock_ups_is_at_least_32_px(built: bc.BuildInfo) -> None:
    import scenes
    page = (built.project / "index.html").read_text(encoding="utf-8")
    assert scenes.lint_fonts(page) == []
    assert any("22px" in p for p in scenes.lint_fonts('<div style="font-size:22px">x</div>'))
    assert any("31" in p for p in scenes.lint_fonts(".lbl { font-size:31px; }"))


def test_gate_fails_text_smaller_than_32_px_measured_in_chrome() -> None:
    card = {"id": "c", "x0": 80.0, "y0": 200.0, "x1": 1000.0, "y1": 900.0, "w": 920.0, "h": 700.0}
    part = {"tag": "div", "text": "tiny", "x0": 100.0, "y0": 300.0, "x1": 300.0, "y1": 320.0, "card": "c", "font": 20.0}
    scene = {"id": "s0", "kind": "x", "zone": "full", "start": 0, "dur": 1, "cards": [card], "loose": [], "parts": [part]}
    assert "font-size" in {v.rule for v in pg.zone_violations(scene)}
    assert "font-size" not in {v.rule for v in pg.zone_violations(dict(scene, parts=[dict(part, font=34.0)]))}


def test_hook_is_sharp_and_its_first_words_are_solid_at_frame_zero(built: bc.BuildInfo) -> None:
    import re
    page = (built.project / "index.html").read_text(encoding="utf-8")
    first = built.groups[0].words[0]
    wid = f"{built.groups[0].id}w00"
    assert first.start == 0.0
    assert re.search(rf'tl\.set\("#{wid}", \{{opacity:1\}}, 0\);', page)             # solid at t=0
    assert f'tl.to("#{wid}"' not in page                                              # no fade of the first word
    for line in page.splitlines():                                                    # no blur-in of the hook at t=0
        if 'blur(' in line and re.search(r'"#s0[a-z]+\d+', line):
            start = float(re.search(r'\}, ([0-9.]+)\);', line).group(1))
            assert start > 0.1, line


def test_speaker_captions_use_chest_level_when_the_face_allows(built: bc.BuildInfo) -> None:
    modes = {built.analysis.slots[g.id].mode for g in built.groups if g.shot_type == geo.SHOT_SPEAKER}
    assert modes <= {geo.MODE_CHEST, geo.MODE_ABOVE_HEAD}
