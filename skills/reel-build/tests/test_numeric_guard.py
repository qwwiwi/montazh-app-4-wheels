"""Malformed numbers in the optional dynamics fields (punch, zoom, follow flip, chips, logo tiles): only a PlanError, never an OverflowError.

The base plan is the example reel with every move switched on; one field at a time gets a bad value.
"""

import copy
import json
from pathlib import Path
from typing import Any, Callable

import pytest

import reel_plan as rp
from conftest import EXAMPLES, replace_scene

DURATION = json.loads((EXAMPLES / "words-test-reel.json").read_text(encoding="utf-8"))["duration"]

CHIPS = {"kind": "chips", "bg": "dark", "title": "ТЕРМИНАЛ", "items": [
    {"text": "Терминал", "sign": "-", "at": {"word": "терминал", "after": 12.0}},
    {"text": "Не нужен", "sign": "-", "at": {"word": "нужен"}}]}                                   # shot 4: full-screen visual, 12.13-14.23 s
LOGOS = {"kind": "logo_pop", "bg": "light", "title": "ПРИЛОЖЕНИЕ", "items": [
    {"name": "Claude", "file": "claude.png", "at": {"word": "приложение,"}},
    {"name": "Codex", "file": "marks/codex.png", "at": {"word": "любым"}}]}                         # shot 5: split, 14.23-17.63 s
FOLLOW = {"kind": "follow_card", "bg": "dark", "flip_at": {"word": "разобраться"}}                 # shot 9: split, 25.83-28.97 s

# the bad values of the review: huge, infinite, NaN, a 401-digit integer, negative, a string, null, a bool, a list, an object
BAD = [1e308, 1e309, float("nan"), 10 ** 400, -1, "3", None, True, [], {}]


def words() -> list[rp.Word]:
    return rp.load_words(EXAMPLES / "words-test-reel.json")


def base_raw() -> dict[str, Any]:
    """The example plan with a follow card, chips, logo tiles, a zoom and a punch word, all valid."""
    raw = json.loads((EXAMPLES / "plan-test-reel.json").read_text(encoding="utf-8"))
    replace_scene(raw, 4, copy.deepcopy(CHIPS))
    replace_scene(raw, 5, copy.deepcopy(LOGOS))
    replace_scene(raw, 9, copy.deepcopy(FOLLOW))
    raw["shots"][2]["zoom"] = 1.12                         # speaker shot at «И» (6.64 s): a sentence boundary
    raw["punch"] = [{"from": {"word": "боялся", "after": 18.0, "before": 19.0, "nth": 0, "plus": 0},
                     "to": {"word": "пишет", "after": 19.0, "before": 20.0, "plus": -0.1},
                     "words": ["боялся"]}]                 # speaker shot 17.63-19.17 s
    return raw


def build(raw: dict[str, Any]) -> rp.Plan:
    return rp.build_plan(raw, words(), DURATION)


def test_the_base_plan_with_every_move_is_valid() -> None:
    plan = build(base_raw())
    assert len(plan.punches) == 1 and plan.shots[2].zoom == 1.12 and {s.kind for s in plan.scenes} >= {"chips", "logo_pop", "follow_card"}


# ---- invalid numeric input corpus --------------------------------------

@pytest.mark.parametrize("punch", [
    {"from": 1e308, "to": 19.1, "words": ["боялся"]},
    {"from": 1e309, "to": 19.1, "words": ["боялся"]},
    {"from": {"word": "боялся", "after": 18, "plus": 1e309}, "to": 19.1, "words": ["боялся"]},
    {"from": {"word": "боялся", "after": 18}, "to": {"word": "пишет", "after": 19, "plus": 1e309}, "words": ["боялся"]},
])
def test_review_punch_inputs_are_plan_errors(punch: dict[str, Any]) -> None:
    raw = base_raw()
    raw["punch"] = [punch]
    with pytest.raises(rp.PlanError, match="punch"):
        build(raw)


def test_review_inputs_arrive_as_json_text() -> None:
    """json.loads turns 1e309 into inf and NaN / Infinity into floats: the same errors for a plan read from a file."""
    for text in ('[{"from":1e308,"to":19.1,"words":["боялся"]}]', '[{"from":1e309,"to":19.1,"words":["боялся"]}]',
                 '[{"from":NaN,"to":19.1,"words":["боялся"]}]', '[{"from":{"word":"боялся","after":18,"plus":Infinity},"to":19.1,"words":["боялся"]}]'):
        raw = base_raw()
        raw["punch"] = json.loads(text)
        with pytest.raises(rp.PlanError, match="punch"):
            build(raw)


# ---- every time value of the punch -------------------------------------------------------------------

def _punch(key: str, sub: str | None = None) -> Callable[[dict[str, Any], Any], None]:
    def put(raw: dict[str, Any], value: Any) -> None:
        if sub is None:
            raw["punch"][0][key] = value
        else:
            raw["punch"][0][key][sub] = value
    return put


# field label in the message -> how to put a value there
PUNCH_FIELDS: dict[str, Callable[[dict[str, Any], Any], None]] = {
    "punch.from": _punch("from"),
    "punch.to": _punch("to"),
    "punch.from.after": _punch("from", "after"),
    "punch.from.before": _punch("from", "before"),
    "punch.from.plus": _punch("from", "plus"),
    "punch.from.nth": _punch("from", "nth"),
    "punch.to.after": _punch("to", "after"),
    "punch.to.before": _punch("to", "before"),
    "punch.to.plus": _punch("to", "plus"),
}


@pytest.mark.parametrize("label", PUNCH_FIELDS)
@pytest.mark.parametrize("bad", BAD, ids=lambda v: repr(v)[:14])
def test_bad_number_in_a_punch_field_is_a_plan_error_naming_the_field(label: str, bad: Any) -> None:
    if label.endswith(".plus") and bad == -1:
        pytest.skip("a negative plus is a legal shift back in time; see test_negative_plus_is_a_shift")
    raw = base_raw()
    PUNCH_FIELDS[label](raw, bad)
    with pytest.raises(rp.PlanError, match=label.replace(".", r"\.")):
        build(raw)


def test_negative_plus_is_a_shift_and_a_shift_out_of_the_reel_is_refused() -> None:
    raw = base_raw()
    assert build(raw).punches[0].end == rp.snap(19.22 - 0.1)
    raw["punch"][0]["from"]["plus"] = -1e308
    with pytest.raises(rp.PlanError, match=r"punch\.from\.plus"):
        build(raw)
    raw = base_raw()
    raw["punch"][0]["from"] = {"word": "боялся", "after": 18, "edge": "end", "plus": -40}      # in range alone, below zero after the arithmetic
    with pytest.raises(rp.PlanError, match=r"punch\.from"):
        build(raw)


# ---- zoom of a shot ------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", BAD, ids=lambda v: repr(v)[:14])
def test_bad_zoom_is_a_plan_error_naming_the_field(bad: Any) -> None:
    raw = base_raw()
    raw["shots"][2]["zoom"] = bad
    with pytest.raises(rp.PlanError, match="zoom"):
        build(raw)


def test_review_zoom_input_a_401_digit_integer() -> None:
    raw = base_raw()
    raw["shots"][2] = json.loads('{"from": {"word": "И", "after": 6.0, "before": 7.0}, "type": "speaker", "zoom": ' + "1" + "0" * 400 + "}")
    with pytest.raises(rp.PlanError, match="zoom"):
        build(raw)


def test_zoom_one_means_off_and_an_integer_one_is_fine() -> None:
    raw = base_raw()
    raw["shots"][2]["zoom"] = 1
    assert build(raw).shots[2].zoom == 1.0


# ---- the times of follow_card (flip_at), chips and logo_pop (at) ------------------------------------------

def _scene(kind: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda raw: next(s for s in raw["scenes"] if s["kind"] == kind)


def _item(kind: str, *sub: str) -> Callable[[dict[str, Any], Any], None]:
    """Put a value into ``items[0].at`` (or one of its anchor keys ``sub``) of the scene of ``kind``; the anchor becomes a word object for a key."""
    def put(raw: dict[str, Any], value: Any) -> None:
        item = _scene(kind)(raw)["items"][0]
        if not sub:
            item["at"] = value
        else:
            item["at"] = {"word": "терминал", "after": 12.0, **{sub[0]: value}}
    return put


def _flip(*sub: str) -> Callable[[dict[str, Any], Any], None]:
    def put(raw: dict[str, Any], value: Any) -> None:
        scene = _scene("follow_card")(raw)
        scene["flip_at"] = value if not sub else {"word": "разобраться", sub[0]: value}
    return put


SCENE_FIELDS: dict[str, Callable[[dict[str, Any], Any], None]] = {
    "flip_at": _flip(),
    "flip_at.after": _flip("after"),
    "flip_at.before": _flip("before"),
    "flip_at.plus": _flip("plus"),
    "flip_at.nth": _flip("nth"),
    "items[0].at": _item("chips"),
    "items[0].at.after": _item("chips", "after"),
    "items[0].at.before": _item("chips", "before"),
    "items[0].at.plus": _item("chips", "plus"),
    "items[0].at.nth": _item("chips", "nth"),
}
SCENE_FIELDS |= {f"logo_pop {k}": v for k, v in {
    "items[0].at": _item("logo_pop"),
    "items[0].at.after": _item("logo_pop", "after"),
    "items[0].at.before": _item("logo_pop", "before"),
    "items[0].at.plus": _item("logo_pop", "plus"),
    "items[0].at.nth": _item("logo_pop", "nth"),
}.items()}


@pytest.mark.parametrize("label", SCENE_FIELDS)
@pytest.mark.parametrize("bad", BAD, ids=lambda v: repr(v)[:14])
def test_bad_number_in_a_scene_time_is_a_plan_error_naming_the_field(label: str, bad: Any) -> None:
    if label.endswith(".plus") and bad == -1:
        pytest.skip("a negative plus is a legal shift back in time")
    raw = base_raw()
    SCENE_FIELDS[label](raw, bad)
    with pytest.raises(rp.PlanError, match=label.split(" ")[-1].replace("[", r"\[").replace("]", r"\]").replace(".", r"\.")):
        build(raw)


def test_negative_plus_in_a_scene_time_is_still_a_shift() -> None:
    raw = base_raw()
    _flip("plus")(raw, -0.2)
    assert build(raw) is not None


def test_a_time_far_beyond_the_reel_is_refused_where_it_used_to_pass_the_type_check() -> None:
    raw = base_raw()
    _scene("chips")(raw)["items"][0]["at"] = DURATION + 5
    with pytest.raises(rp.PlanError, match=r"items\[0\]\.at"):
        build(raw)
