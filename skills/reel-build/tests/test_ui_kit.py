"""html-components as the visual system of a reel: stylesheet adaptation, the config folder, the hc_* scene kinds."""

import json
import re
from pathlib import Path

import pytest

import scenes
import ui_kit
from reel_config import load_config
from reel_plan import Scene
from scene_base import SceneContext, lint_fonts

SAMPLE = """
/* tokens */
.hc-x-root{--lime:#D4FF00}
.hc-x-root .eyebrow{font:600 11px/1.2 var(--mono);letter-spacing:.06em}
.hc-x-root .card{border:1px solid var(--line);border-radius:18px;padding:24px;box-shadow:0 14px 40px rgba(10,10,10,.06)}
.hc-x .list label .mono{font-size:11px;color:var(--muted)}
.hc-x .t{font-size:17px;margin:-8px 0 0 -8px;opacity:.5}
.hc-x .big{font-size:clamp(52px,11vw,104px)}
@media(max-width:640px){.hc-x .wl{grid-template-columns:1fr}.hc-x .inp{min-width:0}}
"""


def test_adapt_css_scales_lengths_and_keeps_numbers_in_declarations() -> None:
    css = ui_kit.adapt_css(SAMPLE, 2.0)
    assert "border-radius:36px" in css and "padding:48px" in css and "0 28px 80px" in css
    assert "margin:-16px 0 0 -16px" in css          # negative lengths scale too
    assert "opacity:.5" in css and "letter-spacing:.06em" in css
    assert "clamp(104px,11vw,208px)" in css


def test_adapt_css_drops_media_and_renames_foreign_classes() -> None:
    css = ui_kit.adapt_css(SAMPLE)
    assert "@media" not in css and "grid-template-columns:1fr" not in css
    assert ".hc-x-root .x-card" in css and ".x-list label .x-mono" in css
    assert not re.search(r"\.card\b", css.replace(".x-card", ""))


def test_adapt_css_lifts_type_to_the_reel_floors() -> None:
    css = ui_kit.adapt_css(SAMPLE)
    assert "font:600 40px/1.2 var(--mono)" in css           # monospace floor
    assert ".x-mono{font-size:40px" in css
    assert ".x-t{font-size:37.4px" in css                     # 17 px x 2.2
    assert lint_fonts(css) == []


def test_component_css_reads_the_kit_and_refuses_unknown_ids(tmp_path: Path) -> None:
    comp = tmp_path / "components" / "kpi"
    comp.mkdir(parents=True)
    (comp / "big-delta.html").write_text("<!-- h -->\n<style>.hc-kpi-big-delta .bar{height:10px}</style>\n<div></div>", encoding="utf-8")
    assert ".hc-kpi-big-delta .x-bar{height:22px}" in ui_kit.component_css(tmp_path, "kpi-big-delta")
    with pytest.raises(ValueError):
        ui_kit.component_css(tmp_path, "kpi-missing")
    with pytest.raises(ValueError):
        ui_kit.component_css(tmp_path, "../etc")


def test_config_ui_kit_must_be_a_kit_folder_inside_the_reel(tmp_path: Path) -> None:
    (tmp_path / "kit" / "components").mkdir(parents=True)
    cfg = tmp_path / "reel_config.json"
    cfg.write_text(json.dumps({"head": {"left": 1, "top": 2, "right": 3, "chin": 4}, "ui_kit": "kit"}), encoding="utf-8")
    assert load_config(cfg).ui_kit == (tmp_path / "kit").resolve()
    cfg.write_text(json.dumps({"head": {"left": 1, "top": 2, "right": 3, "chin": 4}, "ui_kit": ".."}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(cfg)


KIT = Path(__file__).resolve().parents[3] / "in" / "html-components"


@pytest.mark.parametrize("kind", sorted(k for k in scenes.BUILDERS if k.startswith("hc_")))
def test_hc_scene_kinds_name_their_component_and_change_state(kind: str) -> None:
    data = scenes.HC_EXAMPLES[kind]
    sc = Scene(0, 0, kind, "dark", 10.0, 14.0, dict(data))
    built = scenes.build_scene(sc, data.get("_full", False), SceneContext())
    assert built.components, f"{kind} uses no html-components block"
    assert all(re.fullmatch(r"[a-z]+-[a-z0-9-]+", c) for c in built.components)
    gaps = [b - a for a, b in zip(sorted({10.0, 14.0, *built.states}), sorted({10.0, 14.0, *built.states})[1:])]
    assert max(gaps) <= 1.5 + 1e-6
    assert lint_fonts(built.html) == []
    if KIT.is_dir():
        for cid in built.components:
            assert lint_fonts(ui_kit.component_css(KIT, cid)) == []
