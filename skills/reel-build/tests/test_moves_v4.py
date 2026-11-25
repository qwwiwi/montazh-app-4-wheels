"""The dynamics moves (follow_card, chips, logo_pop) obey the v4 rules: no decorative placeholders, text from 32 px, contrast 4.5:1, a new state every 1.5 s."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import prerender_gate as pg
import reel_plan as rp
import scene_base
import scenes
from conftest import SKILL, build_example, replace_scene
from reel_config import Account
from scenes import SceneContext
from test_chips import PNG, chip, ctx_with_assets, logo, scene

CHROME = Path(os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
needs_browser = pytest.mark.skipif(
    not ((SKILL / "node_modules").exists() and CHROME.exists() and shutil.which("node") and shutil.which("npm") and shutil.which("hyperframes")),
    reason="needs npm install in skills/reel-build, Google Chrome and the global hyperframes install",
)

ACCOUNT = Account("test.handle_01", "Тестовый автор", None)
LONG_ACCOUNT = Account("a_very_long_handle_of_thirty_c", "Имя", None)


def follow(full: bool, account: Account = ACCOUNT) -> scene_base.Built:
    sc = rp.Scene(0, 0, "follow_card", "dark", 10.0, 14.0, {"flip_at": 12.0})
    return scenes.build_scene(sc, full, SceneContext(account=account))


def chips_built(full: bool, gap: float = 1.0) -> scene_base.Built:
    return scenes.build_scene(scene("chips", [chip("А", 10.2), chip("Б", 10.2 + gap, "-"), chip("В", 10.2 + 2 * gap)], end=14.0, title="ТЕМА"), full)


def logos_built(full: bool, tmp_path: Path, gap: float = 1.0) -> scene_base.Built:
    sc = scene("logo_pop", [logo("Claude", "claude.png", 10.2), logo("Codex", "marks/codex.png", 10.2 + gap)], end=14.0, title="ТЕМА")
    return scenes.build_scene(sc, full, ctx_with_assets(tmp_path))


def every_move(tmp_path: Path) -> list[tuple[str, scene_base.Built]]:
    out = []
    for full in (False, True):
        out += [(f"follow full={full}", follow(full)), (f"follow long handle full={full}", follow(full, LONG_ACCOUNT)),
                (f"chips full={full}", chips_built(full)), (f"logo_pop full={full}", logos_built(full, tmp_path))]
    return out


# ---- no decorative placeholders ----------------------------------------------------------------

def test_no_placeholder_shapes_on_any_dynamics_scene(tmp_path: Path) -> None:
    for label, built in every_move(tmp_path):
        assert 'class="sk"' not in built.html, f"{label}: grey skeleton stand-in"
        assert 'class="sl"' not in built.html and "dashed" not in built.html, f"{label}: empty dashed slot"
        assert scene_base.decor_problems(built.html) == [], label


def test_full_follow_card_fills_the_lower_part_with_a_status_that_flips() -> None:
    built = follow(True)
    assert "Вы подписаны" in built.html and "Вы не подписаны" in built.html                  # a second element of the same phrase, not a grey stand-in
    assert any("Вы подписаны" not in ln and "12" in ln for ln in built.gsap)                  # it flips on the same anchor as the button (the exact tweens: the test below)
    assert "Вы подписаны" not in follow(False).html                                          # the split strip has no room: the card stays compact


def _opacity_tween(built: scene_base.Built, element_id: str, opacity: int, at: float) -> bool:
    """True when the GSAP lines hold a ``tl.to`` of exactly this element to this opacity at time ``at``."""
    pattern = re.compile(rf'tl\.to\("#{re.escape(element_id)}", \{{[^}}]*\bopacity:{opacity}\b[^}}]*\}}, {at:g}\)')
    return any(pattern.search(ln) for ln in built.gsap)


def test_follow_status_elements_flip_on_the_same_anchor_as_the_button() -> None:
    built = follow(True)                                                                     # flip_at = 12.0
    off = re.search(r'<div id="([^"]+)"[^>]*>Вы не подписаны</div>', built.html)
    on = re.search(r'<div id="([^"]+)"[^>]*>Вы подписаны</div>', built.html)
    assert off and on, "both status elements are on the page"
    assert 'opacity:0' in on.group(0) and 'opacity:0' not in off.group(0)                    # «Вы подписаны» starts hidden
    assert _opacity_tween(built, off.group(1), 0, 12.0), "«Вы не подписаны» fades out at flip_at"
    assert _opacity_tween(built, on.group(1), 1, 12.0), "«Вы подписаны» fades in at flip_at"
    btn_off = re.search(r'<div id="([^"]+)" class="btn" [^>]*>Подписаться</div>', built.html)
    btn_on = re.search(r'<div id="([^"]+)" class="btn ghost" [^>]*>Подписки</div>', built.html)
    assert btn_off and btn_on and {btn_off.group(1), btn_on.group(1)}.isdisjoint({off.group(1), on.group(1)})   # the button tweens do not stand in for the status
    assert _opacity_tween(built, btn_off.group(1), 0, 12.0) and _opacity_tween(built, btn_on.group(1), 1, 12.0)


# ---- text from 32 px ---------------------------------------------------------------------------

def test_every_dynamics_text_is_at_least_32_px(tmp_path: Path) -> None:
    for label, built in every_move(tmp_path):
        assert scene_base.lint_fonts(built.html) == [], label


# ---- contrast ----------------------------------------------------------------------------------

def _rgb(hex_colour: str) -> tuple[float, float, float]:
    return tuple(float(int(hex_colour[i:i + 2], 16)) for i in (1, 3, 5))  # type: ignore[return-value]


def test_chip_signs_keep_a_contrast_of_4_5() -> None:
    assert set(scenes.CHIP_BADGE) == {"+", "–"}
    for sign, (fg, bg) in scenes.CHIP_BADGE.items():
        assert pg.contrast_ratio(_rgb(fg), _rgb(bg)) >= pg.MIN_CONTRAST, sign


# ---- a new state every 1.5 s even when the words are 2 s apart ---------------------------------

@pytest.mark.parametrize("full", [False, True])
def test_pills_and_tiles_stay_alive_between_distant_words(full: bool, tmp_path: Path) -> None:
    for built in (chips_built(full, 2.0), logos_built(full, tmp_path, 2.0)):
        assert rp.static_gaps(built.states, 10.0, 14.0) == []


def test_first_pop_must_come_with_the_cut() -> None:
    late = scene("chips", [chip("А", 11.2), chip("Б", 11.8)], end=13.0)                       # the panel would be empty for 1.2 s
    assert any("first" in p for p in rp.chips_problems([late]))
    assert any("first" in p for p in rp.logo_problems([scene("logo_pop", [logo("X", "x.png", 11.2)], end=13.0)]))
    ok = scene("chips", [chip("А", 10.3), chip("Б", 11.8)], end=13.0)
    assert rp.chips_problems([ok]) == []


def test_tile_name_has_to_fit_a_tile_at_32_px() -> None:
    assert rp.LOGO_NAME_MAX <= 12
    assert any("name" in p for p in rp.logo_problems([scene("logo_pop", [logo("Тринадцатьбукв", "a.png", 10.2)])]))


# ---- the real page in Chrome: size, contrast, strip, tiles --------------------------------------

def _measure(project: Path) -> dict:
    out = project.parent / "boxes.json"
    subprocess.run(["node", str(SKILL / "scripts" / "measure_boxes.mjs"), str(project), str(out)], check=True, capture_output=True, timeout=180)
    return json.loads(out.read_text(encoding="utf-8"))


def _moves_gate(raw_edit, tmp_path: Path) -> list[str]:  # noqa: ANN001
    with mock.patch.object(rp, "follow_problems", lambda *a, **k: []):                         # the 60-90 % window is about timing, not about layout
        info = build_example(tmp_path, edit_plan=raw_edit, edit_config=lambda raw: raw.update(account={"handle": "@test.handle_01", "display_name": "Тестовый автор"}),
                             assets={"claude.png": PNG, "marks/codex.png": PNG})
    out: list[str] = []
    for sc in _measure(info.project)["scenes"]:
        if sc["kind"] in {"chips", "logo_pop", "follow_card"}:
            out += [f"{sc['kind']}/{sc['zone']}: {v.rule} {v.caption_id} {v.detail}" for v in pg.zone_violations(sc)]
            assert sc["cards"], sc["kind"]
    return out


@needs_browser
def test_measured_in_chrome_full_screen_chips_split_logos_split_follow(tmp_path: Path) -> None:
    def edit(raw: dict) -> None:
        replace_scene(raw, 4, {"kind": "chips", "bg": "dark", "title": "ТЕРМИНАЛ", "items": [
            {"text": "Терминал", "sign": "-", "at": {"word": "терминал", "after": 12.0}}, {"text": "Не нужен", "sign": "+", "at": {"word": "нужен"}}]})
        replace_scene(raw, 5, {"kind": "logo_pop", "bg": "light", "title": "ПРИЛОЖЕНИЕ", "items": [
            {"name": "Claude", "file": "claude.png", "at": {"word": "приложение,"}}, {"name": "Claude Code", "file": "marks/codex.png", "at": {"word": "любым"}}]})
        replace_scene(raw, 9, {"kind": "follow_card", "bg": "dark", "flip_at": {"word": "разобраться"}})
    assert _moves_gate(edit, tmp_path) == []


@needs_browser
def test_measured_in_chrome_full_screen_follow_and_logos_split_chips(tmp_path: Path) -> None:
    def edit(raw: dict) -> None:
        replace_scene(raw, 8, {"kind": "follow_card", "bg": "dark", "flip_at": {"word": "работать."}})
        replace_scene(raw, 4, {"kind": "logo_pop", "bg": "dark", "items": [
            {"name": "Claude", "file": "claude.png", "at": {"word": "терминал", "after": 12.0}}, {"name": "Codex", "file": "marks/codex.png", "at": {"word": "нужен."}}]})
        replace_scene(raw, 5, {"kind": "chips", "bg": "light", "items": [
            {"text": "Скачал", "sign": "+", "at": {"word": "приложение,"}}, {"text": "Без терминала", "sign": "+", "at": {"word": "любым"}}]})
    assert _moves_gate(edit, tmp_path) == []
