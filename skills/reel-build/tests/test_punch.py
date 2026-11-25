"""Punch word (move 3): plan validation and limits, captions skip the window, slot and band of the punch, generator, gate."""

import dataclasses
import json
from pathlib import Path

import pytest

import geometry as geo
import prerender_gate as pg
import reel_captions as rc
import reel_plan as rp
from conftest import EXAMPLES, build_example, make_words
from geometry import Box
from reel_config import load_config


# ---- plan validation on the small word list (shots: split 0-1.14, speaker 1.14-3.14, split 3.14-) ---------

def plan_with(words: list[rp.Word], raw_plan: dict, *punches: dict) -> rp.Plan:
    raw_plan["punch"] = list(punches)
    return rp.build_plan(raw_plan, words, 6.0)


GOOD = {"from": {"word": "пять"}, "to": {"word": "семь"}, "words": ["пять", "шесть"]}


def test_punch_resolves_to_the_spoken_words(words: list[rp.Word], raw_plan: dict) -> None:
    plan = plan_with(words, raw_plan, GOOD)
    (p,) = plan.punches
    assert [w.w for w in p.words] == ["пять", "шесть"] and p.start == rp.snap(1.6) and p.end == rp.snap(2.8)


def test_plan_without_punch_has_none(words: list[rp.Word], raw_plan: dict) -> None:
    assert rp.build_plan(raw_plan, words, 6.0).punches == ()


def test_punch_words_must_be_spoken_inside_the_window(words: list[rp.Word], raw_plan: dict) -> None:
    with pytest.raises(rp.PlanError, match="not found"):
        plan_with(words, raw_plan, {**GOOD, "words": ["пять", "Земля"]})      # never said: text on screen is the author's speech
    with pytest.raises(rp.PlanError, match="not found"):
        plan_with(words, raw_plan, {**GOOD, "words": ["шесть", "пять"]})      # order of speech is kept


def test_punch_words_are_exactly_the_words_spoken_in_the_window(words: list[rp.Word], raw_plan: dict) -> None:
    # «шесть» is spoken inside the window but not listed: it would silently lose its caption and never be shown
    with pytest.raises(rp.PlanError, match="exactly"):
        plan_with(words, raw_plan, {"from": {"word": "пять"}, "to": {"word": "восемь"}, "words": ["пять", "семь"]})


def test_malformed_punch_entries_are_plan_errors(words: list[rp.Word], raw_plan: dict) -> None:
    raw_plan["punch"] = None
    assert rp.build_plan(raw_plan, words, 6.0).punches == ()           # JSON null = no punch
    for bad in ({"from": 1.6}, "пять", ["пять"], {"a": 1}):
        raw_plan["punch"] = bad
        with pytest.raises(rp.PlanError):
            rp.build_plan(raw_plan, words, 6.0)


@pytest.mark.parametrize("bad", [
    {"from": 1.6, "to": 2.8, "words": None},                                   # TypeError before
    {"from": {}, "to": 2.8, "words": ["пять"]},                                # KeyError before
    {"from": {"word": None}, "to": 2.8, "words": ["пять"]},                    # AttributeError before
    {"from": 1.6, "to": {}, "words": ["пять"]},
    {"from": 1.6, "to": {"word": None}, "words": ["пять"]},
    {"from": {"word": "пять", "after": "x"}, "to": 2.8, "words": ["пять"]},    # ValueError before
    {"from": {"word": "пять", "edge": "middle"}, "to": 2.8, "words": ["пять"]},
    {"from": True, "to": 2.8, "words": ["пять"]},
    {"from": [1.6], "to": 2.8, "words": ["пять"]},
    {"from": 1.6, "to": 2.8, "words": {"пять": 1, "шесть": 2}},                # an object was taken as its keys
    {"from": 1.6, "to": 2.8, "words": 5},
    {"from": 1.6, "to": 2.8, "words": ["пять", None]},
    {"from": 1.6, "to": 2.8, "words": ["пять", {"w": "шесть"}]},
    {"from": 1.6, "to": 2.8, "words": []},
    {"from": 1.6, "to": 2.8, "words": ""},
])
def test_malformed_punch_fields_raise_a_plan_error_with_a_message(words: list[rp.Word], raw_plan: dict, bad: dict) -> None:
    with pytest.raises(rp.PlanError, match="punch"):
        plan_with(words, raw_plan, bad)


def test_a_minimal_word_stays_on_screen_longer_than_its_pop() -> None:
    ws = make_words("раз два три четыре пять шесть семь восемь", step=0.4)
    raw = {"shots": [{"from": 0, "type": "split"}, {"from": {"word": "три"}, "type": "split"}], "scenes": [{"shot": 0, "kind": "x10"}, {"shot": 1, "kind": "x10"}],
           "punch": [{"from": {"word": "четыре"}, "to": {"word": "шесть"}, "words": ["четыре", "пять"]}]}
    plan = rp.build_plan(raw, ws, 3.5)
    shown = [g.end - g.start for g in rc.build_groups(ws, plan) if g.punch]
    assert len(shown) == 2 and all(d >= 0.25 for d in shown), shown          # the spring-in lasts 0.22 s
    too_fast = {**raw["punch"][0], "words": ["четыре", "пять"]}
    ws2 = make_words("раз два три четыре пять шесть семь восемь", step=0.35)
    raw["punch"] = [too_fast]
    with pytest.raises(rp.PlanError, match="too fast"):
        rp.build_plan(raw, ws2, 3.5)


def test_punch_limits_are_pure_and_listed(words: list[rp.Word], raw_plan: dict) -> None:
    ok = plan_with(words, raw_plan, GOOD)
    shots = ok.shots
    p = ok.punches[0]
    assert rp.punch_problems(ok.punches, shots) == []
    three = [dataclasses.replace(p, start=p.start + i * 0.01) for i in range(3)]
    assert any("at most 2" in m for m in rp.punch_problems(three, shots))
    four_words = dataclasses.replace(p, words=p.words * 2)
    assert any("1-3 words" in m for m in rp.punch_problems([four_words], shots))
    long_word = dataclasses.replace(p, words=(rp.Word("Электроэнцефалограмма", 1.6, 2.0),))
    assert any("longer than" in m for m in rp.punch_problems([long_word], shots))
    in_hook = dataclasses.replace(p, start=0.2, end=1.0, words=(rp.Word("Раз", 0.2, 0.5),))
    assert any("hook" in m for m in rp.punch_problems([in_hook], shots))
    across = dataclasses.replace(p, start=2.2, end=3.6)
    assert any("shot" in m for m in rp.punch_problems([across], shots))
    short = dataclasses.replace(p, end=p.start + 0.3)
    assert any("lasts" in m for m in rp.punch_problems([short], shots))
    fast = dataclasses.replace(p, words=(rp.Word("пять", 1.6, 1.7), rp.Word("шесть", 1.75, 1.9)), end=2.1)
    assert any("too fast" in m for m in rp.punch_problems([fast], shots))


def _tail_reel() -> tuple[list[rp.Word], dict]:
    """A 10 s reel whose last word «конец» is spoken 9.9-10.0 s; shots: split 0-5, split 5-10."""
    ws = make_words(" ".join(["слово"] * 23)) + [rp.Word("конец", 9.9, 10.0)]
    raw = {"shots": [{"from": 0, "type": "split"}, {"from": 5.0, "type": "split"}], "scenes": [{"shot": 0, "kind": "x10"}, {"shot": 1, "kind": "x10"}]}
    return ws, raw


def test_punch_cannot_end_after_the_reel() -> None:
    ws, raw = _tail_reel()
    raw["punch"] = [{"from": 9.9, "to": 10.4, "words": ["конец"]}]         # the generator would show the word 9.9-10.0 s: shorter than its 0.22 s pop
    with pytest.raises(rp.PlanError, match="reel"):
        rp.build_plan(raw, ws, 10.0)
    raw["punch"] = [{"from": 9.4, "to": 10.0, "words": ["конец"]}]
    ws[-1] = rp.Word("конец", 9.4, 10.0)
    assert rp.build_plan(raw, ws, 10.0).punches[0].end == 10.0               # ending exactly on the last frame is fine


def test_punch_window_must_lie_inside_the_reel_and_one_shot_as_a_pure_check(words: list[rp.Word], raw_plan: dict) -> None:
    ok = plan_with(words, raw_plan, GOOD)
    p, shots = ok.punches[0], ok.shots
    past_end = dataclasses.replace(p, start=shots[-1].end - 0.2, end=shots[-1].end + 0.3)
    msgs = rp.punch_problems([past_end], shots)
    assert any("reel" in m for m in msgs) and not any("too fast" in m for m in msgs)       # no readability verdict on a window that is not on screen
    before_start = dataclasses.replace(p, start=-0.2, end=0.3)
    assert any("reel" in m for m in rp.punch_problems([before_start], shots))
    inside = dataclasses.replace(p, start=shots[-1].start + 0.1, end=shots[-1].end)
    assert not any("reel" in m for m in rp.punch_problems([inside], shots))


def test_build_plan_raises_on_a_broken_punch(words: list[rp.Word], raw_plan: dict) -> None:
    with pytest.raises(rp.PlanError, match="hook"):
        plan_with(words, raw_plan, {"from": {"word": "Раз"}, "to": {"word": "два"}, "words": ["Раз"]})


# ---- captions step aside ----------------------------------------------------------------------

def test_running_caption_is_hidden_during_the_punch(words: list[rp.Word], raw_plan: dict) -> None:
    plan = plan_with(words, raw_plan, GOOD)
    groups = rc.build_groups(words, plan)
    punch = [g for g in groups if g.punch]
    assert [g.text for g in punch] == ["пять", "шесть"] and all(len(g.words) == 1 for g in punch)
    p = plan.punches[0]
    for g in groups:
        if not g.punch:
            assert not any(p.start - 1e-6 <= w.start < p.end for w in g.words), g.text
            assert g.end <= p.start - rc.TWO_FRAMES + 1e-6 or g.start >= p.end, f"{g.text} overlaps the punch window"
    assert rc.check_groups(groups, plan) == []
    assert [g.start for g in groups] == sorted(g.start for g in groups)


def test_plan_without_punch_groups_are_the_old_groups(words: list[rp.Word], raw_plan: dict) -> None:
    plan = rp.build_plan(raw_plan, words, 6.0)
    groups = rc.build_groups(words, plan)
    assert not any(g.punch for g in groups) and [g.id for g in groups] == [f"c{n:03d}" for n in range(len(groups))]


def test_a_caption_group_never_spans_the_punch_window() -> None:
    ws = make_words("раз два три четыре пять шесть семь восемь девять")        # no pauses: one group without the punch
    raw = {"shots": [{"from": 0, "type": "split"}, {"from": {"word": "три"}, "type": "split"}], "scenes": [{"shot": 0, "kind": "x10"}, {"shot": 1, "kind": "x10"}],
           "punch": [{"from": {"word": "пять"}, "to": {"word": "семь"}, "words": ["пять", "шесть"]}]}
    plan = rp.build_plan(raw, ws, 5.0)
    texts = [g.text for g in rc.build_groups(ws, plan) if not g.punch]
    assert all("пять" not in t and "шесть" not in t for t in texts)
    assert any("четыре" in t for t in texts) and any("семь" in t for t in texts)


# ---- geometry ---------------------------------------------------------------------------------

def test_punch_slot_sits_where_the_caption_does_and_keeps_its_band() -> None:
    head = Box(140, 590, 860, 1476)
    for shot_type, hd in ((geo.SHOT_SPLIT, None), (geo.SHOT_VISUAL, None), (geo.SHOT_SPEAKER, head)):
        base, pun = geo.caption_slot(shot_type, hd), geo.caption_slot(shot_type, hd, punch=True)
        assert pun.mode == geo.MODE_PUNCH and (pun.anchor, pun.y) == (base.anchor, base.y)


def test_punch_band_in_a_split_stays_under_the_card_strip() -> None:
    assert geo.band_for(geo.SHOT_SPLIT, geo.MODE_PUNCH) == (geo.SPLIT_CONTENT_BOTTOM, geo.SEAM - 10)
    inside = Box(100, 790, 980, 944)
    assert geo.check_caption("p", inside, geo.SHOT_SPLIT, geo.MODE_PUNCH, None) == []
    on_card_strip = Box(100, 600, 980, 754)
    assert any(v.rule == "band" for v in geo.check_caption("p", on_card_strip, geo.SHOT_SPLIT, geo.MODE_PUNCH, None))
    assert geo.check_caption("c", on_card_strip, geo.SHOT_SPLIT, geo.MODE_ABOVE_SEAM, None) == []      # the running caption keeps its old band


def test_punch_font_size_is_100_to_140_and_shrinks_with_length() -> None:
    assert geo.punch_px("ВЕК") == geo.PUNCH_PX_MAX and geo.punch_px("ПОДГОТОВКА") < geo.PUNCH_PX_MAX
    assert all(geo.PUNCH_PX_MIN <= geo.punch_px("Ж" * n) <= geo.PUNCH_PX_MAX for n in range(1, geo.PUNCH_MAX_CHARS + 1))


# ---- generator and gate on the example reel ---------------------------------------------------

PUNCH_VISUAL = {"from": {"word": "нажимаешь"}, "to": {"word": "и", "after": 24.6}, "words": ["нажимаешь", "Да"]}   # shot 8, full-screen visual
PUNCH_SPEAKER = {"from": {"word": "боялся", "after": 18.0}, "to": 19.1, "words": ["боялся"]}       # shot 6, full-screen speaker (17.6-19.2 s)


@pytest.fixture(scope="module")
def built_punch(tmp_path_factory: pytest.TempPathFactory):  # noqa: ANN201
    return build_example(tmp_path_factory.mktemp("punch"), edit_plan=lambda raw: raw.update(punch=[PUNCH_VISUAL, PUNCH_SPEAKER]))


def test_page_carries_big_punch_words_and_no_running_caption_in_the_window(built_punch) -> None:  # noqa: ANN001
    page = (built_punch.project / "index.html").read_text(encoding="utf-8")
    assert page.count('data-mode="punch"') == 3                     # нажимаешь, Да, боялся
    for gid in [g.id for g in built_punch.groups if g.punch]:
        tag = page[page.index(f'id="{gid}"'): page.index(">", page.index(f'id="{gid}"'))]
        size = int(tag.split("font-size:")[1].split("px")[0])
        assert geo.PUNCH_PX_MIN <= size <= geo.PUNCH_PX_MAX
    window = built_punch.plan.punches[0]
    assert not any(not g.punch and window.start <= g.start < window.end for g in built_punch.groups)
    assert built_punch.analysis.slots[next(g.id for g in built_punch.groups if g.punch)].mode == geo.MODE_PUNCH


def _boxes(info, mutate: dict | None = None):  # noqa: ANN001, ANN202
    mutate = mutate or {}
    caps = []
    for g in info.groups:
        slot = info.analysis.slots[g.id]
        h = 154.0 if g.punch else 174.0
        y1 = slot.y if slot.anchor == "bottom" else slot.y + h
        box = {"x0": 200.0, "y0": y1 - h, "x1": 880.0, "y1": y1}
        box.update(mutate.get(g.id, {}))
        caps.append({"id": g.id, "mode": slot.mode, "shot": g.shot_type, "start": g.start, "duration": g.end - g.start, "text": g.text, "w": 680.0, "h": h, **box,
                     "words": [{"text": w.w, "x0": 200.0, "y0": box["y0"], "x1": 300.0, "y1": box["y1"]} for w in g.words]})
    return {"fontsOk": True, "captions": caps, "scenes": [], "roles": {"codeword": {"x0": 100.0, "y0": 420.0, "x1": 900.0, "y1": 600.0, "font": 124.0, "text": "ВЫХОДНЫЕ"}}}


def test_gate_passes_clean_punch_boxes_and_keeps_every_caption_rule(built_punch) -> None:  # noqa: ANN001
    cfg = load_config(EXAMPLES / "reel_config-test-reel.json")
    assert pg.run_gate(built_punch, _boxes(built_punch), cfg) == []
    speaker = next(g.id for g in built_punch.groups if g.punch and g.shot_type == geo.SHOT_SPEAKER)
    assert "face" in {v.rule for v in pg.run_gate(built_punch, _boxes(built_punch, {speaker: {"y0": 1000.0, "y1": 1154.0}}), cfg)}
    visual = next(g.id for g in built_punch.groups if g.punch and g.shot_type == geo.SHOT_VISUAL)
    assert "clipped" in {v.rule for v in pg.run_gate(built_punch, _boxes(built_punch, {visual: {"x0": 10.0}}), cfg)}
    assert "band" in {v.rule for v in pg.run_gate(built_punch, _boxes(built_punch, {visual: {"y0": 700.0, "y1": 854.0}}), cfg)}


def test_punch_on_a_speaker_without_room_above_the_head_is_a_no_slot_violation_not_a_crash(tmp_path: Path) -> None:
    # the running captions fit at chest level (face ends at y 1000), but the head starts at y 250: no two lines fit above it
    info = build_example(tmp_path, edit_plan=lambda raw: raw.update(punch=[PUNCH_SPEAKER]), head_box=[250, 250, 800, 1000], face_box=[300, 500, 750, 1000])
    shot = next(i for i, s in enumerate(info.plan.shots) if s.start <= info.plan.punches[0].start < s.end)
    assert any(v.rule == "no-slot" and v.caption_id == f"shot{shot}" and "punch" in v.detail for v in info.analysis.problems)
    punch = next(g for g in info.groups if g.punch)
    assert punch.id not in info.analysis.slots                          # no slot: nothing is placed where it cannot fit, the gate fails on the violation
    assert any(info.analysis.slots[g.id].mode == geo.MODE_CHEST for g in info.groups if g.shot == shot and not g.punch)


def test_old_plan_has_no_punch_markup(tmp_path: Path) -> None:
    info = build_example(tmp_path)
    page = (info.project / "index.html").read_text(encoding="utf-8")
    assert 'data-mode="punch"' not in page and not any(g.punch for g in info.groups)
    assert json.loads((EXAMPLES / "plan-test-reel.json").read_text(encoding="utf-8")).get("punch") is None
