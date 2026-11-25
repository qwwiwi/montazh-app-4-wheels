"""Caption groups: accumulate up to two lines of 1-3 words, never cross a shot, keep two frames apart; proofreading is single-word only."""

from pathlib import Path

import pytest

import reel_captions as rc
import reel_plan as rp
from conftest import make_words


def plan_for(words: list[rp.Word], raw: dict) -> rp.Plan:
    return rp.build_plan(raw, words, words[-1].end + 0.2)


def test_groups_hold_at_most_two_lines_of_three_words(words: list[rp.Word], raw_plan: dict) -> None:
    groups = rc.build_groups(words, plan_for(words, raw_plan))
    assert groups and all(len(g.lines) <= 2 and all(1 <= len(line) <= 3 for line in g.lines) for g in groups)
    assert rc.check_groups(groups, plan_for(words, raw_plan)) == []


def test_a_group_accumulates_words_on_two_lines() -> None:
    ws = make_words("один два три четыре пять шесть семь")
    raw = {"shots": [{"from": 0, "type": "split"}], "scenes": [{"shot": 0, "kind": "x10"}]}
    groups = rc.build_groups(ws, plan_for(ws, raw))
    assert [len(line) for line in groups[0].lines] == [3, 3] and len(groups[1].words) == 1


def test_group_never_crosses_a_shot_change(words: list[rp.Word], raw_plan: dict) -> None:
    plan = plan_for(words, raw_plan)
    for g in rc.build_groups(words, plan):
        shot = plan.shots[g.shot]
        assert shot.start - 1e-6 <= g.start and g.end <= shot.end + 1e-6
        assert all(plan.shot_index(w.start) == g.shot for w in g.words)


def test_pause_and_sentence_end_start_a_new_group() -> None:
    ws = make_words("да нет. потом снова", gap_after={1: 0.0})
    raw = {"shots": [{"from": 0, "type": "split"}], "scenes": [{"shot": 0, "kind": "x10"}]}
    texts = [g.text for g in rc.build_groups(ws, plan_for(ws, raw))]
    assert texts == ["да нет.", "потом снова"]
    slow = make_words("раз два три", gap_after={0: 0.5})
    assert [g.text for g in rc.build_groups(slow, plan_for(slow, raw))] == ["раз", "два три"]


def test_groups_keep_two_frames_apart(words: list[rp.Word], raw_plan: dict) -> None:
    groups = rc.build_groups(words, plan_for(words, raw_plan))
    for a, b in zip(groups, groups[1:]):
        assert b.start >= a.end + rc.TWO_FRAMES - 1e-3


def test_proofreading_accepts_single_word_fixes_only(words: list[rp.Word], tmp_path: Path) -> None:
    f = tmp_path / "p.txt"
    rc.write_proofread(words, f)
    text = f.read_text(encoding="utf-8").replace("\tClaude", "\tКлод")
    f.write_text(text, encoding="utf-8")
    fixed, changes = rc.read_proofread(f, words)
    assert [c[1:] for c in changes] == [("Claude", "Клод")] and fixed[-2].w == "Клод"
    f.write_text(text.replace("\tCode", "\tдва слова"), encoding="utf-8")
    with pytest.raises(rp.PlanError):
        rc.read_proofread(f, words)
