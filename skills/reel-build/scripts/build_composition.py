#!/usr/bin/env python3
"""Generate the HyperFrames project (HTML + paused GSAP timeline) for one reel.

Input: the frozen cut, proofread words, plan, config, head track. Output: a project folder with ``index.html`` and local
assets (cut, fonts, GSAP). The composition follows the reference canon (repository docs/GOLDEN.md): an exact 50/50 split (visual y 0..960, speaker
y 960..1920), full-screen visuals and full-screen speaker «breaths», detailed UI scenes that change state every 0.5-2 s, captions
that accumulate word by word and move with the shot type. Nothing is written by hand: every caption word and every scene
anchor comes from the recognised words.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from brand_captions import BrandMention, load_mentions
import geometry as geo
import reel_captions as rc
import reel_plan as rp
import scenes
import ui_kit
from analysis import Analysis, analyse
from faces import load_track
from reel_config import ReelConfig, load_config
from scenes import esc, num

LOG = logging.getLogger("build_composition")
ROOT_ID = "reel"
SKILL_DIR = Path(__file__).resolve().parent.parent
NODE_MODULES = SKILL_DIR / "node_modules"
FONT_FILES = {
    "golos-cyr": NODE_MODULES / "@fontsource-variable/golos-text/files/golos-text-cyrillic-wght-normal.woff2",
    "golos-lat": NODE_MODULES / "@fontsource-variable/golos-text/files/golos-text-latin-wght-normal.woff2",
    "mono-cyr": NODE_MODULES / "@fontsource/jetbrains-mono/files/jetbrains-mono-cyrillic-500-normal.woff2",
    "mono-lat": NODE_MODULES / "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff2",
}
CYR = "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116"
LAT = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,"
       "U+2215,U+FEFF,U+FFFD")


@dataclass(frozen=True)
class BuildInfo:
    """What the generator produced, for the gate and the report."""

    project: Path
    analysis: Analysis
    groups: tuple[rc.Group, ...]
    plan: rp.Plan
    scene_states: dict[int, list[float]]      # scene n -> times at which its picture changes
    words: tuple[rp.Word, ...]


def page_font(cfg: ReelConfig) -> str:
    """Family of the captions and the page: Golos Text, or the ui kit's Inter Tight when the reel is built from html-components."""
    return ui_kit.UI_FONT if cfg.ui_kit is not None else "Golos Text"


def css(cfg: ReelConfig, components: tuple[str, ...] = ()) -> str:
    """Stylesheet; fonts are local files. ``components``: html-components whose adapted stylesheets the scenes use."""
    c, f = cfg.colours, cfg.fit
    kit = ""
    if cfg.ui_kit is not None:
        kit = "\n".join([ui_kit.font_faces(CYR, LAT), ui_kit.WRAP_CSS] + [ui_kit.component_css(cfg.ui_kit, cid) for cid in components])
    return f"""
@font-face {{ font-family:'Golos Text'; src:url('assets/fonts/golos-cyr.woff2') format('woff2'); font-weight:100 900; unicode-range:{CYR}; }}
@font-face {{ font-family:'Golos Text'; src:url('assets/fonts/golos-lat.woff2') format('woff2'); font-weight:100 900; unicode-range:{LAT}; }}
@font-face {{ font-family:'JetBrains Mono'; src:url('assets/fonts/mono-cyr.woff2') format('woff2'); font-weight:500; unicode-range:{CYR}; }}
@font-face {{ font-family:'JetBrains Mono'; src:url('assets/fonts/mono-lat.woff2') format('woff2'); font-weight:500; unicode-range:{LAT}; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:1080px; height:1920px; overflow:hidden; background:{c.dark}; }}
body {{ font-family:'{page_font(cfg)}', sans-serif; color:{c.ink}; }}
#root {{ position:absolute; left:0; top:0; width:1080px; height:1920px; overflow:hidden; background:{c.dark}; }}
#vbase {{ position:absolute; left:0; top:0; width:1080px; height:1920px; object-fit:cover; z-index:1; }}
{scenes.scene_css(c)}
.cap {{ position:absolute; left:0; right:0; margin:0 auto; width:max-content; z-index:30; display:flex; flex-direction:column; align-items:center;
  gap:{f.line_gap}px; font-weight:800; font-size:{f.font_px}px; line-height:1.1; letter-spacing:.01em; text-transform:uppercase; white-space:nowrap; }}
.cap .ln {{ display:flex; justify-content:center; gap:{f.word_gap}px; }}
.cap .w {{ opacity:0; }}
.cap.lt {{ color:{c.ink}; }} .cap.dk {{ color:{c.cream}; }}
.cap.pl .w {{ background:{c.plate}; color:{c.cream}; padding:{f.pad_y}px {f.pad_x}px; border-radius:{f.radius}px; }}
.cap .ac {{ color:{c.accent}; }}
.cap.lt .ac {{ color:{c.accent_on_light}; }}
{kit}
"""


def caption_html(g: rc.Group, slot: geo.CaptionSlot, bg: str | None, plan: rp.Plan, cfg: ReelConfig,
                 mentions: tuple[BrandMention, ...] = ()) -> tuple[str, list[str]]:
    """One caption group: lines of word spans; every word fades from semi-transparent to solid when it is spoken."""
    accent = set(plan.accent_words)
    theme = "pl" if g.shot_type == geo.SHOT_SPEAKER else ("dk" if bg == "dark" else "lt")
    lines, gs = [], []
    attached: set[BrandMention] = set()
    for n, line in enumerate(g.lines):
        spans = []
        for k, w in enumerate(line):
            wid = f"{g.id}w{n}{k}"
            cls = "w ac" if rp.normalise(w.w) in accent and bg != "accent" else "w"
            chip = ""
            for mention in mentions:
                if mention in attached or w not in mention.words:
                    continue
                attached.add(mention)
                logo_id = f"{wid}brand"
                chip = (f'<img id="{logo_id}" class="brand-chip" src="{esc(mention.target)}" '
                        f'alt="{esc(mention.name)}" data-brand-start="{num(mention.start)}" '
                        f'data-brand-end="{num(mention.end)}" style="visibility:hidden;'
                        f'object-fit:contain;box-sizing:border-box;width:1.3em;height:.84em;'
                        f'vertical-align:-.04em;margin-right:.1em;padding:.06em;'
                        f'background:#fff;border-radius:.12em" />')
                gs.append(f'tl.set("#{logo_id}", {{visibility:"visible"}}, {num(max(g.start, mention.start))});')
                gs.append(f'tl.set("#{logo_id}", {{visibility:"hidden"}}, {num(min(g.end, mention.end))});')
            spans.append(f'<span id="{wid}" class="{cls}">{chip}{esc(rp.display_word(w.w))}</span>')
            t = max(w.start, g.start)
            if g.start <= 0.0 and w.start <= cfg.captions.hook_solid:
                gs.append(f'tl.set("#{wid}", {{opacity:1}}, 0);')       # the hook: readable from frame 0, no fade from empty
                continue
            if g.punch:      # a punch word pops with a spring instead of fading in
                gs.append(f'tl.set("#{wid}", {{opacity:{cfg.captions.fade_from}, scale:.7}}, {num(t)});')
                gs.append(f'tl.to("#{wid}", {{opacity:1, scale:1, duration:.22, ease:"back.out(2.6)"}}, {num(t)});')
            else:
                gs.append(f'tl.set("#{wid}", {{opacity:{cfg.captions.fade_from}}}, {num(t)});')
                gs.append(f'tl.to("#{wid}", {{opacity:1, duration:{cfg.captions.fade}, ease:"none"}}, {num(t)});')
        ln_style = ' style="line-height:1.1"' if g.punch else ""      # the scene rule `.ln` (1.38) would make a big punch line too tall for its band
        lines.append(f'<div class="ln"{ln_style}>{"".join(spans)}</div>')
    pos = f"bottom:{geo.FRAME_H - slot.y:.1f}px" if slot.anchor == "bottom" else f"top:{slot.y:.1f}px"
    if g.punch:
        pos += f";font-size:{geo.punch_px(max((rp.display_word(w.w) for w in g.words), key=len))}px"
    markup = (f'<div id="{g.id}" class="clip cap {theme}" data-start="{num(g.start)}" data-duration="{num(g.end - g.start)}" data-cap="1" '
              f'data-mode="{slot.mode}" data-shot="{g.shot_type}" style="{pos}">{"".join(lines)}</div>')
    return markup, gs


def build_project(
    cut: Path, words: list[rp.Word], plan: rp.Plan, cfg: ReelConfig, head_json: Path, out_dir: Path,
) -> BuildInfo:
    """Write the HyperFrames project to ``out_dir`` and return what was built."""
    track = load_track(head_json, cfg.track_smooth)
    groups = rc.build_groups(words, plan, cfg.captions)
    problems = rc.check_groups(groups, plan)
    if problems:
        raise rp.PlanError("; ".join(problems))
    an = analyse(plan, groups, track, cfg)
    D = plan.duration
    y0 = an.layout.y0

    gs: list[str] = []
    layers: list[str] = []
    states: dict[int, list[float]] = {}
    scene_bg: dict[int, str] = {}
    owner_files: dict[str, Path] = {}          # project-relative target -> the owner's file
    ctx = scenes.SceneContext(account=cfg.account, assets_dir=cfg.assets_dir, ui_kit=cfg.ui_kit)
    used: set[str] = set()
    for sc in plan.scenes:
        built = scenes.build_scene(sc, plan.shots[sc.shot].type == geo.SHOT_VISUAL, ctx)
        layers.append(built.html)
        gs += built.gsap
        owner_files.update({dst: src for src, dst in built.files})
        used.update(built.components)
        states[sc.n] = sorted({*built.states, *rp.scene_times(sc)})
        scene_bg[sc.shot] = sc.bg
    if used and cfg.ui_kit is None:
        raise rp.PlanError(f"scenes use html-components {sorted(used)} but reel_config.json has no «ui_kit» folder")

    # one base video for the whole reel; the speaker half of a split is a 960 px slice shifted to the seam
    zooming = any(s.zoom != 1.0 for s in plan.shots)       # a plan without zoom emits exactly the old lines
    for s in plan.shots:
        info = an.info(s)
        extra = ""
        if zooming:
            extra = (f', scale:{num(info.zoom)}, transformOrigin:"{info.origin[0]:.1f}px {info.origin[1]:.1f}px"'
                     if info.origin is not None else ", scale:1")
        if s.type == geo.SHOT_SPLIT:
            gs.append(f'tl.set("#vbase", {{y:{an.layout.shift}, clipPath:"inset({y0}px 0px 0px 0px)"{extra}}}, {num(s.start)});')
        else:
            gs.append(f'tl.set("#vbase", {{y:0, clipPath:"inset(0px 0px 0px 0px)"{extra}}}, {num(s.start)});')

    brands = load_mentions(cfg, words)
    owner_files.update({m.target: m.source for m in brands})
    caps = []
    for g in groups:
        slot = an.slots.get(g.id)
        if slot is None:
            continue
        markup, g_lines = caption_html(g, slot, scene_bg.get(g.shot), plan, cfg,
                                       tuple(m for m in brands if m.start < g.end and m.end > g.start))
        caps.append(markup)
        gs += g_lines

    page = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=1080, height=1920" />
<meta name="reel-font" content="{page_font(cfg)}" />
<script src="assets/gsap.min.js"></script>
<style>{css(cfg, tuple(sorted(used)))}</style>
</head>
<body>
<div id="root" data-composition-id="{ROOT_ID}" data-start="0" data-duration="{num(D)}" data-width="1080" data-height="1920">
<audio id="narration" src="assets/cut.mp4" data-start="0" data-duration="{num(D)}" data-volume="1"></audio>
<video id="vbase" src="assets/cut.mp4" data-start="0" data-duration="{num(D)}" data-media-start="0" muted playsinline></video>
{chr(10).join(layers)}
{chr(10).join(caps)}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(gs)}
window.__timelines["{ROOT_ID}"] = tl;
tl.seek(0);
</script>
</body>
</html>
"""
    (out_dir / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    for name, src in FONT_FILES.items():
        shutil.copyfile(src, out_dir / "assets" / "fonts" / f"{name}.woff2")
    if cfg.ui_kit is not None:
        for name, src in ui_kit.font_files(cfg.ui_kit).items():
            shutil.copyfile(src, out_dir / "assets" / "fonts" / f"{name}.woff2")
    shutil.copyfile(NODE_MODULES / "gsap" / "dist" / "gsap.min.js", out_dir / "assets" / "gsap.min.js")
    for dst, src in owner_files.items():       # only files the owner supplied are copied: nothing is downloaded
        (out_dir / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out_dir / dst)
    target = out_dir / "assets" / "cut.mp4"
    if not target.exists() or target.stat().st_size != cut.stat().st_size:
        shutil.copyfile(cut, target)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
    }, indent=2), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps({"id": "reel", "name": "reel"}), encoding="utf-8")
    return BuildInfo(out_dir, an, tuple(groups), plan, states, tuple(words))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: build the project once (``reel.py`` adds the Chrome measurement and the gate)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cut", type=Path, required=True)
    ap.add_argument("--words", type=Path, required=True, help="proofread words.json")
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--head", type=Path, required=True, help="head.json from measure_head.py")
    ap.add_argument("--out", type=Path, required=True, help="project folder")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    words = rp.load_words(args.words)
    duration = float(json.loads(args.words.read_text(encoding="utf-8"))["duration"])
    plan = rp.load_plan(args.plan, words, duration)
    args.out.mkdir(parents=True, exist_ok=True)
    info = build_project(args.cut, words, plan, cfg, args.head, args.out)
    LOG.info("project %s: %d shots, %d scenes, %d caption groups, split y0=%d", info.project, len(plan.shots),
             len(plan.scenes), len(info.groups), info.analysis.layout.y0)
    for p in info.analysis.problems:
        LOG.warning("%s %s: %s", p.caption_id, p.rule, p.detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
