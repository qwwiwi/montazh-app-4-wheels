"""Follow card (move 1): account in the config, plan limits (60-90 % of the runtime, once, length, flip), scene output, gate."""

import json
from pathlib import Path

import pytest

import geometry as geo
import prerender_gate as pg
import reel_plan as rp
import scenes
from conftest import EXAMPLES, build_example, replace_scene
from reel_config import Account, load_config
from scenes import SceneContext

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")
ACCOUNT = {"handle": "@test.handle_01", "display_name": "Тестовый автор"}


def follow_scene(start: float, end: float, flip: float | None) -> rp.Scene:
    data = {} if flip is None else {"flip_at": flip}
    return rp.Scene(0, 0, "follow_card", "dark", start, end, data)


# ---- config ------------------------------------------------------------------------------------

def write_cfg(tmp_path: Path, **extra: object) -> Path:
    raw = json.loads((EXAMPLES / "reel_config-test-reel.json").read_text(encoding="utf-8"))
    raw.update(extra)
    path = tmp_path / "reel_config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_old_config_has_no_account() -> None:
    assert load_config(EXAMPLES / "reel_config-test-reel.json").account is None


def test_account_comes_from_the_config_and_the_avatar_path_is_relative_to_it(tmp_path: Path) -> None:
    (tmp_path / "avatar.png").write_bytes(PNG)
    cfg = load_config(write_cfg(tmp_path, account={**ACCOUNT, "avatar": "avatar.png"}))
    assert cfg.account == Account("test.handle_01", "Тестовый автор", (tmp_path / "avatar.png").resolve())


@pytest.mark.parametrize("account", [
    {"handle": ""}, {"handle": "bad handle!"}, {"handle": "a" * 31}, {"display_name": "no handle"},
    {"handle": "ok", "followers": 12000},                      # counters of followers are never shown
    {"handle": "ok", "avatar": "missing.png"},                 # the file must exist
    {"handle": "ok", "avatar": "https://example.com/a.png"},   # never downloaded
])
def test_bad_account_is_refused(tmp_path: Path, account: dict) -> None:
    with pytest.raises(ValueError):
        load_config(write_cfg(tmp_path, account=account))


def test_avatar_cannot_leave_the_config_folder(tmp_path: Path) -> None:
    folder = tmp_path / "reel"
    folder.mkdir()
    (tmp_path / "outside.png").write_bytes(PNG)
    (folder / "inside.png").write_bytes(PNG)
    (folder / "link.png").symlink_to(tmp_path / "outside.png")
    for bad in ("../outside.png", str(tmp_path / "outside.png"), "link.png"):
        cfg = json.loads((EXAMPLES / "reel_config-test-reel.json").read_text(encoding="utf-8"))
        cfg["account"] = {"handle": "ok", "avatar": bad}
        (folder / "reel_config.json").write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(ValueError, match="inside"):
            load_config(folder / "reel_config.json")
    cfg["account"] = {"handle": "ok", "avatar": "inside.png"}
    (folder / "reel_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert load_config(folder / "reel_config.json").account.avatar == (folder / "inside.png").resolve()


def test_avatar_path_contract_is_relative_without_parent_steps(tmp_path: Path) -> None:
    """SKILL.md: a relative path; an absolute path and a parent step are refused even when the file stays inside the config folder."""
    folder = tmp_path / "reel"
    (folder / "assets").mkdir(parents=True)
    (folder / "sub").mkdir()
    for name in ("inside.png", "assets/avatar.png", "sub/avatar.png"):
        (folder / name).write_bytes(PNG)

    def load(avatar: str) -> Account | None:
        cfg = json.loads((EXAMPLES / "reel_config-test-reel.json").read_text(encoding="utf-8"))
        cfg["account"] = {"handle": "ok", "avatar": avatar}
        (folder / "reel_config.json").write_text(json.dumps(cfg), encoding="utf-8")
        return load_config(folder / "reel_config.json").account

    parent = ".."
    for bad in (str(folder / "inside.png"), str((folder / "assets" / "avatar.png").resolve()),     # absolute, but inside the folder
                f"sub/{parent}/inside.png", f"sub/{parent}/assets/avatar.png", f"assets/{parent}/inside.png", f"./sub/{parent}/inside.png",
                f"sub\\{parent}\\inside.png", "\\inside.png"):
        with pytest.raises(ValueError, match="inside"):
            load(bad)
    for good in ("inside.png", "assets/avatar.png", "sub/avatar.png", "./assets/avatar.png"):          # the standard relative forms keep working
        account = load(good)
        assert account is not None and account.avatar == (folder / good).resolve()


# ---- plan limits -------------------------------------------------------------------------------

def test_follow_inside_the_window_passes() -> None:
    assert rp.follow_problems([follow_scene(26.0, 29.5, 27.5)], 41.8, None) == []


def test_follow_outside_60_to_90_percent_fails() -> None:
    early = rp.follow_problems([follow_scene(10.0, 13.5, 11.5)], 41.8, None)
    late = rp.follow_problems([follow_scene(35.0, 38.5, 36.5)], 41.8, None)
    assert any("60-90 %" in p for p in early) and any("60-90 %" in p for p in late)


def test_follow_at_most_once_per_reel() -> None:
    a, b = follow_scene(26.0, 29.5, 27.5), rp.Scene(1, 1, "follow_card", "dark", 29.5, 33.0, {"flip_at": 31.0})
    assert any("at most one" in p for p in rp.follow_problems([a, b], 41.8, None))


def test_follow_length_and_flip_position() -> None:
    assert any("lasts" in p for p in rp.follow_problems([follow_scene(26.0, 28.0, 27.0)], 41.8, None))
    assert any("lasts" in p for p in rp.follow_problems([follow_scene(25.5, 30.5, 27.0)], 41.8, None))
    assert any("flip" in p for p in rp.follow_problems([follow_scene(26.0, 29.5, None)], 41.8, None))
    assert any("flip" in p for p in rp.follow_problems([follow_scene(26.0, 29.5, 26.4)], 41.8, None))     # button flips too early
    assert any("flip" in p for p in rp.follow_problems([follow_scene(26.0, 29.5, 29.0)], 41.8, None))     # and too late


def test_follow_keeps_clear_of_the_call_to_action() -> None:
    cta = rp.Cta(29.0, 35.0, "X")
    assert any("call to action" in p for p in rp.follow_problems([follow_scene(26.0, 29.5, 27.5)], 41.8, cta))
    assert rp.follow_problems([follow_scene(26.0, 29.5, 27.5)], 41.8, rp.Cta(32.4, 38.2, "X")) == []


def test_build_plan_refuses_a_follow_card_outside_the_window() -> None:
    words = rp.load_words(EXAMPLES / "words-test-reel.json")
    raw = json.loads((EXAMPLES / "plan-test-reel.json").read_text(encoding="utf-8"))
    replace_scene(raw, 1, {"kind": "follow_card", "bg": "dark", "flip_at": {"word": "раз"}})
    with pytest.raises(rp.PlanError, match="follow_card"):
        rp.build_plan(raw, words, 41.83)


# ---- scene output ------------------------------------------------------------------------------

def build(scene: rp.Scene, *, full: bool = False, avatar: str | None = None, account: Account | None = None):  # noqa: ANN201
    ctx = SceneContext(account=Account("test.handle_01", "Тестовый автор", None) if account is None else account)
    return scenes.build_scene(scene, full, ctx)


def test_scene_shows_handle_and_both_button_states_and_flips_on_the_anchor() -> None:
    built = build(follow_scene(10.0, 13.5, 11.5))
    assert "@test.handle_01" in built.html and "Тестовый автор" in built.html
    assert "Подписаться" in built.html and "Подписки" in built.html
    flip = [ln for ln in built.gsap if "opacity:1" in ln and ", 11.5)" in ln]
    assert flip, "the second button layer fades in at flip_at"
    assert 11.5 in built.states


def test_handle_is_not_hard_coded() -> None:
    other = build(follow_scene(10.0, 13.5, 11.5), account=Account("someone_else", "", None))
    assert "@someone_else" in other.html and "test.handle_01" not in other.html


def test_scene_without_an_account_in_the_config_is_refused() -> None:
    with pytest.raises(ValueError, match="account"):
        scenes.build_scene(follow_scene(10.0, 13.5, 11.5), False, SceneContext())


def test_avatar_file_is_used_when_given_else_the_first_letter(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(PNG)
    with_img = build(follow_scene(10.0, 13.5, 11.5), account=Account("zed", "", (tmp_path / "a.png").resolve()))
    assert '<img' in with_img.html and with_img.files == [((tmp_path / "a.png").resolve(), "assets/account/avatar.png")]
    letter = build(follow_scene(10.0, 13.5, 11.5), account=Account("zed", "", None))
    assert "<img" not in letter.html and ">Z<" in letter.html and letter.files == []


@pytest.mark.parametrize(("start", "end", "flip"), [(10.0, 13.0, 11.0), (10.0, 14.5, 12.0), (10.0, 14.5, 11.0), (10.0, 14.5, 13.4)])
def test_scene_changes_state_at_least_every_one_and_a_half_seconds(start: float, end: float, flip: float) -> None:
    sc = follow_scene(start, end, flip)
    states = sorted({*build(sc).states, *rp.scene_times(sc)})
    assert rp.static_gaps(states, start, end) == []


def test_full_screen_variant_is_taller_than_the_split_one() -> None:
    split = build(follow_scene(10.0, 13.5, 11.5), full=False)
    full = build(follow_scene(10.0, 13.5, 11.5), full=True)
    assert 'class="clip scene split' in split.html and 'class="clip scene full' in full.html
    assert 'class="sk"' not in full.html and 'class="sk"' not in split.html                  # v4: no grey stand-in posts, a status line fills the big card instead
    assert "Вы подписаны" in full.html and "Вы подписаны" not in split.html


# ---- generator and gate on the example reel ----------------------------------------------------

@pytest.fixture(scope="module")
def built_follow(tmp_path_factory: pytest.TempPathFactory):  # noqa: ANN201
    tmp = tmp_path_factory.mktemp("follow")
    # shot 9 (split, 25.8-29.0 s = 62-69 % of 41.8 s) becomes the follow card; the call to action starts at 32.4 s
    return build_example(
        tmp,
        edit_plan=lambda raw: replace_scene(raw, 9, {"kind": "follow_card", "bg": "dark", "flip_at": {"word": "разобраться"}}),
        edit_config=lambda raw: raw.update(account={**ACCOUNT, "avatar": "assets/avatar.png"}),
        assets={"avatar.png": PNG},
    )


def test_page_holds_the_follow_card_and_the_copied_avatar(built_follow) -> None:  # noqa: ANN001
    page = (built_follow.project / "index.html").read_text(encoding="utf-8")
    assert page.count('data-kind="follow_card"') == 1 and "@test.handle_01" in page
    assert (built_follow.project / "assets" / "account" / "avatar.png").read_bytes() == PNG
    assert rp.rhythm_problems(built_follow.plan.shots, built_follow.plan.cta) == []
    assert pg.plan_violations(built_follow) == []


def _boxes(info, cap_over_card: bool):  # noqa: ANN001, ANN202
    caps = []
    for g in info.groups:
        slot = info.analysis.slots[g.id]
        y1 = slot.y if slot.anchor == "bottom" else slot.y + 174
        box = {"x0": 200.0, "y0": y1 - 174, "x1": 880.0, "y1": y1}
        caps.append({"id": g.id, "mode": slot.mode, "shot": g.shot_type, "start": g.start, "duration": g.end - g.start, "text": g.text, "w": 680.0, "h": 174.0,
                     **box, "words": [{"text": w.w, "x0": 200.0, "y0": box["y0"], "x1": 300.0, "y1": box["y1"]} for w in g.words]})
    sc = next(s for s in info.plan.scenes if s.kind == "follow_card")
    top = 600.0 if cap_over_card else 280.0
    scene = {"id": f"s{sc.n}", "kind": "follow_card", "zone": "split", "start": sc.start, "dur": sc.end - sc.start,
             "cards": [{"id": "c", "x0": 60.0, "y0": top, "x1": 1020.0, "y1": top + 330.0, "w": 960.0, "h": 330.0}], "loose": [], "parts": []}
    return {"fontsOk": True, "captions": caps, "scenes": [scene], "roles": {"codeword": {"x0": 100.0, "y0": 420.0, "x1": 900.0, "y1": 600.0, "font": 124.0, "text": "ВЫХОДНЫЕ"}}}


def test_gate_fails_a_caption_that_meets_the_follow_card(built_follow) -> None:  # noqa: ANN001
    cfg = load_config(built_follow.project.parent / "reel_config.json")
    assert pg.run_gate(built_follow, _boxes(built_follow, cap_over_card=False), cfg) == []
    bad = pg.run_gate(built_follow, _boxes(built_follow, cap_over_card=True), cfg)
    assert any(v.rule == "overlap" for v in bad)


def test_old_plan_page_does_not_mention_the_follow_card(tmp_path: Path) -> None:
    info = build_example(tmp_path)
    page = (info.project / "index.html").read_text(encoding="utf-8")
    assert "follow_card" not in page and not (info.project / "assets" / "account").exists()
    assert geo.SHOT_SPLIT in {s.type for s in info.plan.shots}
