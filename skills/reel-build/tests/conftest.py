"""Shared fixtures: the scripts folder is flat, so put it on the path; a tiny word list and plan."""

import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import reel_plan as rp  # noqa: E402


def make_words(spec: str, step: float = 0.4, gap_after: dict[int, float] | None = None) -> list[rp.Word]:
    """Words from a space separated string, 0.3 s long, ``step`` apart (+ optional extra gaps)."""
    gap_after = gap_after or {}
    words: list[rp.Word] = []
    t = 0.0
    for i, w in enumerate(spec.split()):
        words.append(rp.Word(w, round(t, 3), round(t + 0.3, 3)))
        t += step + gap_after.get(i, 0.0)
    return words


EXAMPLES = SKILL / "examples"


def build_example(tmp: Path, edit_plan=None, edit_config=None, assets: dict[str, bytes] | None = None,  # noqa: ANN001, ANN201
                  head_box: list[float] | None = None, face_box: list[float] | None = None):
    """Build the example reel (words, plan, config of ``examples/``) into ``tmp`` after optional edits of the raw plan / config dicts.

    ``head_box`` / ``face_box`` replace the constant head / face samples of the stub track (source pixels x0, y0, x1, y1).

    ``assets`` maps file names to bytes written into ``tmp/assets`` (the reel's assets folder next to the config).
    Returns the ``BuildInfo``; no media and no browser are involved (the cut is a stub file).
    """
    import json

    import build_composition as bc
    from reel_config import load_config

    cut = tmp / "cut.mp4"
    cut.write_bytes(b"x")
    head = tmp / "head.json"
    samples = [{"t": i * 0.25, "box": head_box or [140, 590, 860, 1476], "face": face_box or [190, 780, 820, 1450]} for i in range(180)]
    head.write_text(json.dumps({"step": 0.25, "samples": samples}), encoding="utf-8")
    for name, data in (assets or {}).items():
        target = tmp / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    words = rp.load_words(EXAMPLES / "words-test-reel.json")
    duration = json.loads((EXAMPLES / "words-test-reel.json").read_text(encoding="utf-8"))["duration"]
    raw_plan = json.loads((EXAMPLES / "plan-test-reel.json").read_text(encoding="utf-8"))
    if edit_plan:
        edit_plan(raw_plan)
    raw_cfg = json.loads((EXAMPLES / "reel_config-test-reel.json").read_text(encoding="utf-8"))
    if edit_config:
        edit_config(raw_cfg)
    (tmp / "reel_config.json").write_text(json.dumps(raw_cfg), encoding="utf-8")
    plan = rp.build_plan(raw_plan, words, duration)
    cfg = load_config(tmp / "reel_config.json")
    return bc.build_project(cut, words, plan, cfg, head, tmp / "reel")


def replace_scene(raw_plan: dict, shot: int, scene: dict) -> None:
    """Swap the scene of ``shot`` in a raw plan for ``scene`` (the shot index is filled in)."""
    raw_plan["scenes"] = [s for s in raw_plan["scenes"] if s["shot"] != shot] + [{"shot": shot, **scene}]
    raw_plan["scenes"].sort(key=lambda s: s["shot"])


@pytest.fixture()
def words() -> list[rp.Word]:
    """Twelve words, one pause after the sixth."""
    return make_words("Раз два три четыре пять шесть семь восемь девять десять Claude Code", gap_after={5: 0.4})


@pytest.fixture()
def raw_plan() -> dict:
    """Split with a scene, speaker, split with a scene."""
    return {
        "shots": [
            {"from": 0, "type": "split"},
            {"from": {"word": "четыре"}, "type": "speaker"},
            {"from": {"word": "восемь"}, "type": "split"},
        ],
        "scenes": [
            {"shot": 0, "kind": "x10", "bg": "dark", "items": [{"text": "a", "at": {"word": "два"}}]},
            {"shot": 2, "kind": "x10", "bg": "light"},
        ],
        "accent_words": ["claude"],
    }
