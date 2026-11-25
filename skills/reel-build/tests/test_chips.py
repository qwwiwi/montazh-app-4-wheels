"""Plus/minus pills and logo tiles (move 6): plan limits, scene output, logos only from the owner's assets, generator and gate."""

import json
from pathlib import Path

import pytest

import prerender_gate as pg
import reel_plan as rp
import scenes
from conftest import EXAMPLES, build_example, replace_scene
from reel_config import load_config
from scenes import SceneContext

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")


def scene(kind: str, items: list[dict], start: float = 10.0, end: float = 13.0, **data: object) -> rp.Scene:
    return rp.Scene(0, 0, kind, "light", start, end, {"items": items, **data})


def chip(text: str, at: float, sign: str | None = "+") -> dict:
    return {"text": text, "at": at, **({"sign": sign} if sign is not None else {})}


def logo(name: str, file: str, at: float) -> dict:
    return {"name": name, "file": file, "at": at}


# ---- plan limits: chips ------------------------------------------------------------------------

def test_chips_inside_the_limits_pass() -> None:
    sc = scene("chips", [chip("Быстро", 10.5), chip("Дорого", 11.5, "-"), chip("Без кода", 12.2, None)])
    assert rp.chips_problems([sc]) == [] and rp.logo_problems([sc]) == []


def test_chips_at_most_four_pills_at_a_time() -> None:
    five = scene("chips", [chip(f"П{i}", 10.2 + i * 0.4) for i in range(5)])
    assert any("1-4" in p for p in rp.chips_problems([five]))
    assert any("1-4" in p for p in rp.chips_problems([scene("chips", [])]))


def test_chips_text_sign_and_count_per_reel() -> None:
    assert any("longer than" in p for p in rp.chips_problems([scene("chips", [chip("очень длинная надпись на пилюле", 10.5)])]))
    assert any("sign" in p for p in rp.chips_problems([scene("chips", [chip("Текст", 10.5, "*")])]))
    assert any("empty" in p for p in rp.chips_problems([scene("chips", [chip("  ", 10.5)])]))
    three = [rp.Scene(i, i, "chips", "light", 10.0 + 4 * i, 13.0 + 4 * i, {"items": [chip("Ок", 10.5 + 4 * i)]}) for i in range(3)]
    assert any("at most 2" in p for p in rp.chips_problems(three))


# ---- plan limits: logo tiles -------------------------------------------------------------------

def test_logo_pop_inside_the_limits_pass() -> None:
    assert rp.logo_problems([scene("logo_pop", [logo("Claude", "claude.svg", 10.5), logo("Codex", "marks/codex.png", 11.5)])]) == []


@pytest.mark.parametrize("file", [
    "https://example.com/logo.png", "//cdn.example.com/a.png", "data:image/png;base64,AAAA", "../secret.png", "/etc/logo.png", "C:\\logo.png",
    "a/../../b.png", "logo.gif", "logo",
])
def test_logo_file_must_be_a_plain_local_image_name(file: str) -> None:
    assert any("file" in p for p in rp.logo_problems([scene("logo_pop", [logo("X", file, 10.5)])])), file


def test_logo_count_and_name_limits() -> None:
    four = scene("logo_pop", [logo(f"N{i}", f"l{i}.png", 10.2 + i * 0.4) for i in range(4)])
    assert any("1-3" in p for p in rp.logo_problems([four]))
    assert any("name" in p for p in rp.logo_problems([scene("logo_pop", [logo("", "a.png", 10.5)])]))
    assert any("name" in p for p in rp.logo_problems([scene("logo_pop", [logo("ОченьДлинноеИмяСервиса", "a.png", 10.5)])]))
    three = [rp.Scene(i, i, "logo_pop", "light", 10.0 + 4 * i, 13.0 + 4 * i, {"items": [logo("A", "a.png", 10.5 + 4 * i)]}) for i in range(3)]
    assert any("at most 2" in p for p in rp.logo_problems(three))


def test_items_that_are_not_objects_are_problems_not_crashes() -> None:
    assert any("object" in p for p in rp.chips_problems([scene("chips", ["abc"])]))
    assert any("object" in p for p in rp.logo_problems([scene("logo_pop", [42])]))
    bad = rp.Scene(0, 0, "chips", "light", 10.0, 13.0, {"items": "not a list"})
    assert any("list" in p for p in rp.chips_problems([bad]))


def test_build_plan_refuses_broken_items() -> None:
    words = rp.load_words(EXAMPLES / "words-test-reel.json")
    raw = json.loads((EXAMPLES / "plan-test-reel.json").read_text(encoding="utf-8"))
    replace_scene(raw, 4, {"kind": "logo_pop", "bg": "light", "items": [{"name": "X", "file": "https://example.com/x.png", "at": {"word": "терминал", "after": 12.0}}]})
    with pytest.raises(rp.PlanError, match="file"):
        rp.build_plan(raw, words, 41.83)


# ---- scene output: chips -----------------------------------------------------------------------

def ctx_with_assets(tmp_path: Path) -> SceneContext:
    (tmp_path / "marks").mkdir(exist_ok=True)
    (tmp_path / "claude.png").write_bytes(PNG)
    (tmp_path / "marks" / "codex.png").write_bytes(PNG)
    return SceneContext(assets_dir=tmp_path.resolve())


def test_chips_pop_on_their_anchors_with_a_sign_and_no_placeholder_slot() -> None:
    sc = scene("chips", [chip("Быстро", 10.5, "+"), chip("Дорого", 11.4, "-")], title="ПЛЮСЫ И МИНУСЫ")
    built = scenes.build_scene(sc, False)
    assert built.html.index("Быстро") < built.html.index("Дорого") and "ПЛЮСЫ И МИНУСЫ" in built.html
    assert ">+<" in built.html and ">–<" in built.html                     # minus is shown as an en dash
    assert 'class="sl"' not in built.html and "dashed" not in built.html     # v4: no empty slot under a pill; the first pop comes with the cut (plan limit)
    pops = [ln for ln in built.gsap if "back.out" in ln]
    assert any(", 10.5)" in ln for ln in pops) and any(", 11.4)" in ln for ln in pops)
    assert {10.5, 11.4} <= set(built.states)


def test_chip_text_is_escaped() -> None:
    built = scenes.build_scene(scene("chips", [chip("<b>x</b>", 10.5)]), False)
    assert "<b>x</b>" not in built.html and "&lt;b&gt;" in built.html


@pytest.mark.parametrize("full", [False, True])
def test_chips_change_state_at_least_every_one_and_a_half_seconds(full: bool) -> None:
    sc = scene("chips", [chip("А", 10.4), chip("Б", 11.6), chip("В", 12.8)], end=13.5)
    built = scenes.build_scene(sc, full)
    assert rp.static_gaps(sorted({*built.states, *rp.scene_times(sc)}), sc.start, sc.end) == []


def test_chips_full_screen_variant_is_bigger() -> None:
    sc = scene("chips", [chip("А", 10.4)])
    assert 'class="clip scene full' in scenes.build_scene(sc, True).html and 'class="clip scene split' in scenes.build_scene(sc, False).html


# ---- scene output: logos -----------------------------------------------------------------------

def test_logo_tiles_use_only_files_from_the_assets_folder(tmp_path: Path) -> None:
    sc = scene("logo_pop", [logo("Claude", "claude.png", 10.5), logo("Codex", "marks/codex.png", 11.5)])
    built = scenes.build_scene(sc, False, ctx_with_assets(tmp_path))
    assert built.html.count("<img") == 2 and "http" not in built.html and "Claude" in built.html
    assert [dst.split("/")[0:2] for _src, dst in built.files] == [["assets", "logos"]] * 2
    assert {src for src, _dst in built.files} == {(tmp_path / "claude.png").resolve(), (tmp_path / "marks" / "codex.png").resolve()}
    assert 'class="sl"' not in built.html and any("back.out" in ln and ", 10.5)" in ln for ln in built.gsap)


def test_logo_scene_needs_the_assets_folder_and_the_file(tmp_path: Path) -> None:
    sc = scene("logo_pop", [logo("Claude", "claude.png", 10.5)])
    with pytest.raises(ValueError, match="assets"):
        scenes.build_scene(sc, False, SceneContext())
    with pytest.raises(ValueError, match="does not exist"):
        scenes.build_scene(sc, False, SceneContext(assets_dir=tmp_path.resolve()))


def test_logo_cannot_leave_the_assets_folder(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "outside.png").write_bytes(PNG)
    with pytest.raises(ValueError, match="inside"):
        scenes.build_scene(scene("logo_pop", [logo("X", "../outside.png", 10.5)]), False, SceneContext(assets_dir=assets.resolve()))
    (assets / "link.png").symlink_to(tmp_path / "outside.png")
    with pytest.raises(ValueError, match="inside"):
        scenes.build_scene(scene("logo_pop", [logo("X", "link.png", 10.5)]), False, SceneContext(assets_dir=assets.resolve()))


def test_config_assets_dir(tmp_path: Path) -> None:
    raw = json.loads((EXAMPLES / "reel_config-test-reel.json").read_text(encoding="utf-8"))
    path = tmp_path / "reel_config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_config(path).assets_dir is None                              # no assets folder: no logos
    (tmp_path / "assets").mkdir()
    assert load_config(path).assets_dir == (tmp_path / "assets").resolve()
    (tmp_path / "brand").mkdir()
    path.write_text(json.dumps({**raw, "assets_dir": "brand"}), encoding="utf-8")
    assert load_config(path).assets_dir == (tmp_path / "brand").resolve()
    path.write_text(json.dumps({**raw, "assets_dir": "nope"}), encoding="utf-8")
    with pytest.raises(ValueError, match="assets_dir"):
        load_config(path)


def _config_with(tmp_path: Path, **extra: object) -> Path:
    raw = json.loads((EXAMPLES / "reel_config-test-reel.json").read_text(encoding="utf-8"))
    path = tmp_path / "reel_config.json"
    path.write_text(json.dumps({**raw, **extra}), encoding="utf-8")
    return path


@pytest.mark.parametrize("bad", ["/", "..", "../other", "sub/../../other"])
def test_assets_dir_cannot_leave_the_config_folder(tmp_path: Path, bad: str) -> None:
    folder = tmp_path / "reel"
    folder.mkdir()
    (tmp_path / "other").mkdir()
    with pytest.raises(ValueError, match="assets_dir.*inside"):
        load_config(_config_with(folder, assets_dir=bad))


def test_assets_dir_symlink_out_of_the_config_folder_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "reel"
    folder.mkdir()
    (tmp_path / "private").mkdir()
    (folder / "brand").symlink_to(tmp_path / "private", target_is_directory=True)
    with pytest.raises(ValueError, match="assets_dir.*inside"):
        load_config(_config_with(folder, assets_dir="brand"))
    (folder / "assets").symlink_to(tmp_path / "private", target_is_directory=True)        # the standard folder is checked as well
    with pytest.raises(ValueError, match="assets_dir.*inside"):
        load_config(_config_with(folder))


def test_root_assets_dir_never_copies_a_private_file(tmp_path: Path) -> None:
    private = tmp_path / "private" / "secret.png"
    private.parent.mkdir()
    (tmp_path / "reel").mkdir()
    private.write_bytes(PNG)
    rel = str(private.resolve()).lstrip("/")                                          # relative to "/" this names the private file

    def edit_plan(raw: dict) -> None:
        replace_scene(raw, 4, {"kind": "logo_pop", "bg": "dark", "items": [{"name": "X", "file": rel, "at": {"word": "терминал", "after": 12.0}}]})

    with pytest.raises(ValueError, match="assets_dir"):
        build_example(tmp_path / "reel", edit_plan=edit_plan, edit_config=lambda raw: raw.update(assets_dir="/"))
    assert not list((tmp_path / "reel").rglob("secret.png"))


# ---- generator and gate on the example reel ----------------------------------------------------

CHIPS = {"kind": "chips", "bg": "dark", "title": "ТЕРМИНАЛ", "items": [
    {"text": "Терминал", "sign": "-", "at": {"word": "терминал", "after": 12.0}},
    {"text": "Не нужен", "sign": "-", "at": {"word": "нужен"}}]}                                   # shot 4: full-screen visual, 12.13-14.23 s
LOGOS = {"kind": "logo_pop", "bg": "light", "title": "ПРИЛОЖЕНИЕ", "items": [
    {"name": "Claude", "file": "claude.png", "at": {"word": "приложение,"}},
    {"name": "Codex", "file": "marks/codex.png", "at": {"word": "любым"}}]}                         # shot 5: split, 14.23-17.63 s


@pytest.fixture(scope="module")
def built_chips(tmp_path_factory: pytest.TempPathFactory):  # noqa: ANN201
    def edit(raw: dict) -> None:
        replace_scene(raw, 4, CHIPS)
        replace_scene(raw, 5, LOGOS)
    return build_example(tmp_path_factory.mktemp("chips"), edit_plan=edit, assets={"claude.png": PNG, "marks/codex.png": PNG})


def test_page_has_pills_tiles_and_copied_logos(built_chips) -> None:  # noqa: ANN001
    page = (built_chips.project / "index.html").read_text(encoding="utf-8")
    assert 'data-kind="chips"' in page and 'data-kind="logo_pop"' in page
    copied = sorted(p.name for p in (built_chips.project / "assets" / "logos").iterdir())
    assert len(copied) == 2 and all(n.endswith(".png") for n in copied)
    assert pg.plan_violations(built_chips) == [] and rp.rhythm_problems(built_chips.plan.shots, built_chips.plan.cta) == []


def test_gate_fails_a_caption_over_a_logo_tile(built_chips) -> None:  # noqa: ANN001
    cfg = load_config(built_chips.project.parent / "reel_config.json")
    sc = next(s for s in built_chips.plan.scenes if s.kind == "logo_pop")

    def boxes(tile_bottom: float) -> dict:
        caps = []
        for g in built_chips.groups:
            slot = built_chips.analysis.slots[g.id]
            y1 = slot.y if slot.anchor == "bottom" else slot.y + 174
            caps.append({"id": g.id, "mode": slot.mode, "shot": g.shot_type, "start": g.start, "duration": g.end - g.start, "text": g.text, "w": 680.0, "h": 174.0,
                         "x0": 200.0, "y0": y1 - 174, "x1": 880.0, "y1": y1,
                         "words": [{"text": w.w, "x0": 200.0, "y0": y1 - 174, "x1": 300.0, "y1": y1} for w in g.words]})
        card = {"id": "c", "x0": 60.0, "y0": 150.0, "x1": 1020.0, "y1": tile_bottom, "w": 960.0, "h": tile_bottom - 150.0}
        return {"fontsOk": True, "captions": caps, "scenes": [{"id": f"s{sc.n}", "kind": "logo_pop", "zone": "split", "start": sc.start, "dur": sc.end - sc.start,
                                                              "cards": [card], "loose": [], "parts": []}], "roles": {"codeword": {"x0": 100.0, "y0": 420.0, "x1": 900.0, "y1": 600.0, "font": 124.0, "text": "ВЫХОДНЫЕ"}}}

    assert pg.run_gate(built_chips, boxes(740.0), cfg) == []
    assert any(v.rule in ("overlap", "zone") for v in pg.run_gate(built_chips, boxes(900.0), cfg))


def test_old_plan_has_no_chips_or_logos(tmp_path: Path) -> None:
    info = build_example(tmp_path)
    page = (info.project / "index.html").read_text(encoding="utf-8")
    assert 'data-kind="chips"' not in page and 'data-kind="logo_pop"' not in page and not (info.project / "assets" / "logos").exists()
