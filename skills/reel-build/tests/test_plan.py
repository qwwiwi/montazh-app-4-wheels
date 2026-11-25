"""Plan: anchors, shots, scenes and the rhythm rules of the canon (run length, breath, shares, call to action)."""

import pytest

import geometry as geo
import reel_plan as rp
from conftest import make_words


def shots(*spec: tuple[str, float, float]) -> list[rp.Shot]:
    return [rp.Shot(a, b, t) for t, a, b in spec]


def test_anchors_resolve_with_lead_plus_and_underscore_at_keys(words: list[rp.Word], raw_plan: dict) -> None:
    raw_plan["scenes"][0]["items"][0]["at"] = {"word": "два", "plus": 0.1}
    raw_plan["scenes"][0]["end_at"] = {"word": "три"}
    plan = rp.build_plan(raw_plan, words, 6.0)
    assert plan.shots[1].start == rp.snap(words[3].start - rp.LEAD)
    times = rp.scene_times(plan.scenes[0])
    assert rp.snap(words[1].start + 0.1) in times and rp.snap(words[2].start) in times


def test_prefix_anchor_is_refused(words: list[rp.Word]) -> None:
    with pytest.raises(rp.PlanError):
        rp.find_word(words, "сем", 0.0)


def test_scene_on_a_speaker_shot_is_refused(words: list[rp.Word], raw_plan: dict) -> None:
    raw_plan["scenes"].append({"shot": 1, "kind": "x10"})
    with pytest.raises(rp.PlanError, match="speaker"):
        rp.build_plan(raw_plan, words, 6.0)


def test_split_shot_without_a_scene_is_refused(words: list[rp.Word], raw_plan: dict) -> None:
    raw_plan["scenes"].pop()
    with pytest.raises(rp.PlanError, match="no scene"):
        rp.build_plan(raw_plan, words, 6.0)


def test_scene_item_outside_its_shot_is_refused(words: list[rp.Word], raw_plan: dict) -> None:
    raw_plan["scenes"][0]["items"][0]["at"] = {"word": "десять"}
    with pytest.raises(rp.PlanError, match="outside"):
        rp.build_plan(raw_plan, words, 6.0)


def test_same_type_longer_than_4_5_seconds_fails() -> None:
    problems = rp.rhythm_problems(shots((geo.SHOT_SPLIT, 0, 4.0), (geo.SHOT_SPLIT, 4.0, 5.0), (geo.SHOT_SPEAKER, 5.0, 6.5)))
    assert any("split run" in p for p in problems)


def test_speaker_breath_must_last_1_3_to_3_seconds() -> None:
    base = [(geo.SHOT_SPLIT, 0, 3.0), (geo.SHOT_SPEAKER, 3.0, 4.0), (geo.SHOT_VISUAL, 4.0, 6.0), (geo.SHOT_SPLIT, 6.0, 9.0)]
    assert any("speaker shot" in p for p in rp.rhythm_problems(shots(*base)))
    ok = [(geo.SHOT_SPLIT, 0, 3.0), (geo.SHOT_SPEAKER, 3.0, 4.6), (geo.SHOT_VISUAL, 4.6, 6.6), (geo.SHOT_SPLIT, 6.6, 9.6)]
    assert not any("speaker shot" in p for p in rp.rhythm_problems(shots(*ok)))


def test_shares_must_stay_in_the_canon_ranges() -> None:
    all_split = shots((geo.SHOT_SPLIT, 0, 4.0), (geo.SHOT_VISUAL, 4.0, 4.5), (geo.SHOT_SPLIT, 4.5, 8.5))
    problems = rp.rhythm_problems(all_split)
    assert any("split takes" in p for p in problems) and any("speaker takes" in p for p in problems)
    shares = rp.shares(shots((geo.SHOT_SPLIT, 0, 5.5), (geo.SHOT_VISUAL, 5.5, 8.5), (geo.SHOT_SPEAKER, 8.5, 10.0)))
    assert shares == {"split": 0.55, "visual": 0.3, "speaker": 0.15}


def test_call_to_action_window_is_5_to_8_seconds() -> None:
    ok = shots((geo.SHOT_SPLIT, 0, 3.0), (geo.SHOT_VISUAL, 3.0, 5.0), (geo.SHOT_SPEAKER, 5.0, 6.0))
    assert any("call to action" in p for p in rp.rhythm_problems(ok, rp.Cta(0, 4.0, "X")))
    assert not any("call to action" in p for p in rp.rhythm_problems(ok, rp.Cta(0, 6.0, "X")))


def test_static_gaps_find_a_picture_that_stays_longer_than_2_seconds() -> None:
    assert rp.static_gaps([0.5, 1.2, 1.9], 0.0, 2.0) == []
    assert rp.static_gaps([0.5], 0.0, 3.5) == [(0.5, 3.5)]
    assert rp.static_gaps([], 0.0, 2.5) == [(0.0, 2.5)]


def test_runs_merge_neighbours_of_one_type() -> None:
    runs = rp.runs(shots((geo.SHOT_SPLIT, 0, 2.0), (geo.SHOT_SPLIT, 2.0, 4.0), (geo.SHOT_VISUAL, 4.0, 5.0)))
    assert runs == [("split", 0, 4.0), ("visual", 4.0, 5.0)]


def test_words_fixture_is_ordered(words: list[rp.Word]) -> None:
    assert make_words("a b c")[2].start > make_words("a b c")[1].start


def test_static_limit_is_tighter_than_two_seconds() -> None:
    assert rp.MAX_STATIC_S <= 1.6
    assert rp.static_gaps([0.5, 2.2], 0.0, 3.0) == [(0.5, 2.2)]


def test_ending_needs_a_reminder_of_the_code_word(words: list[rp.Word], raw_plan: dict) -> None:
    raw_plan["cta"] = {"from": {"word": "два"}, "to": {"word": "восемь"}, "word": "ВЫХОДНЫЕ", "word_anchor": {"word": "десять"}}
    plan = rp.build_plan(raw_plan, words, 7.5)
    assert any("reminder" in p for p in rp.reminder_problems(plan))
    last = raw_plan["scenes"][-1]
    last["reminder"] = {"word": "ВЫХОДНЫЕ", "at": {"word": "десять"}, "type_at": {"word": "десять"}, "send_at": {"word": "десять", "plus": 1.2}}
    good = rp.build_plan(raw_plan, words, 7.5)
    assert rp.reminder_problems(good) == []
    last["reminder"]["word"] = "ДРУГОЕ"
    assert any("code word" in p for p in rp.reminder_problems(rp.build_plan(raw_plan, words, 7.5)))


def test_code_word_must_be_fully_typed_at_least_2_5_s_before_the_end(words: list[rp.Word], raw_plan: dict) -> None:
    """the call to action stays readable and unobstructed for at least 2.5 s at the end."""
    raw_plan["cta"] = {"from": {"word": "два"}, "to": {"word": "восемь"}, "word": "ВЫХОДНЫЕ", "word_anchor": {"word": "десять"}}
    raw_plan["scenes"][-1]["reminder"] = {"word": "ВЫХОДНЫЕ", "at": {"word": "десять"}, "type_at": {"word": "десять", "plus": 0.4},
                                          "send_at": {"word": "десять", "plus": 1.4}}
    late = rp.build_plan(raw_plan, words, 7.5)        # typed at 4.4 + 0.8 = 5.2 s -> only 2.3 s left
    assert any("2.5" in p for p in rp.reminder_problems(late))
    raw_plan["scenes"][-1]["reminder"]["type_at"] = {"word": "десять"}
    assert rp.reminder_problems(rp.build_plan(raw_plan, words, 7.5)) == []


def test_light_scenes_are_an_accent_not_the_default(words: list[rp.Word], raw_plan: dict) -> None:
    """dark + orange by default, light backgrounds at most 25 % of the visual time."""
    plan = rp.build_plan(raw_plan, words, 6.0)
    raw_plan["scenes"][0]["bg"] = "light"
    raw_plan["scenes"][1]["bg"] = "light"
    all_light = rp.build_plan(raw_plan, words, 6.0)
    assert rp.light_share(all_light) == 1.0
    assert any("light" in p for p in rp.palette_problems(all_light))
    raw_plan["scenes"][0]["bg"] = "dark"
    raw_plan["scenes"][1]["bg"] = "accent"
    assert rp.light_share(rp.build_plan(raw_plan, words, 6.0)) == 0.0
    assert rp.palette_problems(rp.build_plan(raw_plan, words, 6.0)) == []
    assert rp.LIGHT_SHARE_MAX <= 0.25 and plan.scenes
