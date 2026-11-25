"""Scene builders: detailed UI mock-ups as HTML + GSAP lines, one card per meaningful phrase.

Every scene is built from the plan's data (real text and numbers the speaker says) and animates on the anchors the plan
resolved from the words, so a card appears at the moment its phrase is spoken. A scene returns markup, GSAP lines for the
paused timeline, and the list of times at which its picture changes (the pre-render gate fails a scene that stays static
longer than 1.5 s). Hand-built blocks: the HyperFrames catalog (`hyperframes add`) is refused by the job guard.

Layout (coordinates inside the scene content box, 960 px wide): a split visual is 630 px high (cards y 10..620), a full-screen
visual 1150 px high (cards y 10..1140, so the frame is filled down to the caption at y 1320). Everything on a scene belongs to
its phrase: the main mock-up is enlarged to the frame and a second element of the same phrase (result panel, counter, status,
progress) fills the rest - no decorative filler, no element shared between scenes. Labels and body text are at least 32 px,
code and terminal lines at least 40 px (3-5 large lines per card), key lines 48-80 px. Style (one visual system): backgrounds
dark (default), orange accent, light only as an accent; cards with a 4 px border and a hard 8 px shadow; the accent is orange,
the single signal colour is green. Every scene has a moving pointer, typing, counters or toggles: something new every 0.3-1.2 s.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from reel_config import local_file
from scenes_hc import HC_BUILDERS, HC_EXAMPLES  # noqa: F401  (HC_EXAMPLES re-exported for the tests)
from reel_plan import CHIP_SIGNS, LOGO_SUFFIXES, REMINDER_CPS, Scene
from scene_base import (  # noqa: F401  (re-exported for the generator and tests)
    MIN_MONO_PX, MIN_TEXT_PX, SB, Built, SceneContext, box, decor_problems, esc, highlight, lint_fonts, num, scene_css, spelling_problems, wbar,
)

CODE_LH = 66.24             # line height of 48 px code (1.38)
TERM_LH = 77.3              # line height of 56 px terminal text (1.38)


# ---- scenes ----------------------------------------------------------------------------------

def hook(b: SB, d: dict[str, Any]) -> None:
    """Hook (split, dark): a counting calendar card and a terminal with a few large lines; sharp from frame 0, moving from frame 0."""
    cal, term, stamp, bar = b.id("cal"), b.id("trm"), b.id("st"), b.id("br")
    cnt = d["counter"]
    t_a, t_b, top, lo = cnt["at"], cnt["end_at"], int(cnt["value"]), int(cnt.get("start", 0))
    steps = 36
    values = [str(round(lo + (top - lo) * k / steps)) for k in range(steps + 1)]
    ctr = b.counter(values, t_a, (t_b - t_a) / steps, "font-size:210px")
    tile_html = ""
    for k, tl_ in enumerate(d["tiles"]):
        tid = b.id("tl")
        tile_html += (f'<div style="position:absolute;left:{25 + k * 134}px;top:380px;width:124px;height:96px;border:4px solid #14110F;border-radius:16px;'
                      f'background:#fff;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:34px">{esc(tl_["text"])}'
                      f'<span id="{tid}" class="chk on sq" style="position:absolute;right:-14px;top:-18px;width:44px;height:44px;font-size:32px">&#10003;</span></div>')
        b.pop(tid, tl_["at"])
    b.add(f'<div id="{cal}" class="card" style="{box(0, 10, 450, 610)}">{wbar(d["calendar_title"], dots=False, light=True)}'
          f'<div class="big" style="position:absolute;left:24px;top:92px;width:394px;text-align:right">{ctr}</div>'
          f'<div class="lbl" style="position:absolute;left:30px;top:312px;font-size:40px">{esc(cnt["label"])}</div>{tile_html}'
          f'<div id="{bar}" class="bar" style="left:26px;top:508px;width:390px"><i></i></div>'
          f'<div class="lbl" style="position:absolute;left:30px;top:552px;font-size:32px">{esc(d["bar_label"])}</div></div>')
    b.fill(bar, t_a, t_b - t_a, 100, "none")
    b.card_in(cal, sharp=True)
    body = "".join(f'<span class="ln out">{esc(x)}</span>' for x in d.get("term_prefill", []))
    lines = d["term_lines"]
    for k, ln in enumerate(lines):
        t_html, _ = b.typed(ln["text"], ln["at"], ln.get("cps", 16.0), caret=ln.get("cls", "cmd") == "cmd", keep_caret=k == len(lines) - 1)
        body += f'<span class="ln {ln.get("cls", "cmd")}">{t_html}</span>'
    b.add(f'<div id="{term}" class="card dk" style="{box(480, 10, 480, 610)}">{wbar(d["term_title"])}'
          f'<div class="mono" style="padding:24px 24px;font-size:44px;line-height:1.4">{body}</div>'
          f'<div id="{stamp}" class="stamp" style="left:60px;top:480px;font-size:58px">{esc(d["stamp"]["text"])}</div></div>')
    b.card_in(term, sharp=True)
    b.pop(stamp, d["stamp"]["at"], rot=-14)


def terminal(b: SB, d: dict[str, Any]) -> None:
    """Full-screen dark terminal: five large command lines typed one after another, a highlighted error line the pointer clicks,
    and under the window a command counter and a status that flips from OK to the error."""
    win, hl, status_ok, status_err, cnt_card, st_card = (b.id(k) for k in ("w", "hl", "so", "se", "cc", "sc"))
    lines = d["lines"]
    body, cmd_times = "", []
    err_t, err_k = b.t1 - 0.3, len(lines) - 1
    for k, ln in enumerate(lines):
        cls = ln.get("cls", "cmd")
        t_html, _end = b.typed(ln["text"], ln["at"], ln.get("cps", 45.0), caret=cls == "cmd", keep_caret=k == len(lines) - 1)
        body += f'<span class="ln {cls}">{t_html}</span>'
        if cls == "cmd":
            cmd_times.append(ln["at"])
        if cls == "err":
            err_t, err_k = ln["at"], k
    ctr = b.counter_at([str(k) for k in range(len(cmd_times) + 1)], cmd_times)
    line_y = 4 + 70 + 22 + err_k * TERM_LH                                    # top of the error line inside the window (card border, bar, padding)
    b.add(f'<div id="{win}" class="card dk" style="{box(0, 10, 960, 560)}">{wbar(d["title"])}'
          f'<div id="{hl}" class="hl" style="left:10px;right:10px;top:{num(line_y - 2)}px;height:{num(TERM_LH + 4)}px;opacity:0"></div>'
          f'<div class="mono" style="padding:22px 34px;font-size:56px">{body}</div></div>')
    b.add(f'<div id="{cnt_card}" class="card dk" style="{box(0, 600, 450, 540)}">'
          f'<div class="lbl" style="position:absolute;left:34px;top:30px;font-size:44px">{esc(d["counter_label"])}</div>'
          f'<div class="big acc" style="position:absolute;right:44px;top:150px;font-size:340px">{ctr}</div></div>')
    b.add(f'<div id="{st_card}" class="card dk" style="{box(480, 600, 480, 540)}">'
          f'<div class="lbl" style="position:absolute;left:34px;top:30px;font-size:44px">{esc(d["status_label"])}</div>'
          f'<div id="{status_ok}" class="big sig" style="position:absolute;left:34px;top:210px;font-size:190px">{esc(d["ok_label"])}</div>'
          f'<div id="{status_err}" class="big acc" style="position:absolute;left:34px;top:240px;font-size:72px;opacity:0">{esc(d["error_label"])}</div></div>')
    b.card_in(win)
    b.card_in(cnt_card, b.t0 + 0.04)
    b.card_in(st_card, b.t0 + 0.08)
    b.tw(f'tl.set("#{status_ok}", {{opacity:0}}, {num(err_t)});')
    b.tw(f'tl.set("#{status_err}", {{opacity:1}}, {num(err_t)});')
    b.tw(f'tl.from("#{status_err}", {{scale:.5, transformOrigin:"left center", duration:.3, ease:"back.out(2.4)", immediateRender:false}}, {num(err_t)});')
    b.tw(f'tl.to("#{win}", {{x:10, duration:.05, yoyo:true, repeat:5}}, {num(err_t)});')
    b.state(err_t, err_t + 0.3)
    click = min(err_t + 0.3, b.t1 - 0.25)
    b.tw(f'tl.set("#{hl}", {{opacity:1}}, {num(click)});')
    b.tw(f'tl.to("#{win}", {{borderColor:"#D97757", duration:.15}}, {num(click)});')
    b.state(click)
    b.pointer((b.t0 + 0.12, 900, 1100), [{"x": 905, "y": 10 + line_y + TERM_LH / 2, "at": click - 0.1, "click": click}])


def code_sea(b: SB, d: dict[str, Any]) -> None:
    """Split (dark): a profile card whose rows are crossed out under a big «НЕ», and a code window showing three large lines at a time
    under a growing line counter."""
    prof, code = b.id("pf"), b.id("cd")
    rows = ""
    first_cross = None
    for k, r in enumerate(d["profile_rows"]):
        y = 80 + k * 74
        mark, strk = b.id("x"), b.id("sk")
        rows += (f'<div class="row" style="position:absolute;left:160px;top:{y}px;font-size:56px;gap:16px"><span class="chk sq" style="width:52px;height:52px;position:relative">'
                 f'<span id="{mark}" class="chk" style="position:absolute;inset:-4px;width:52px;height:52px;background:#D97757;color:#14110F;font-size:36px;opacity:0">&#10005;</span></span>'
                 f'<span style="position:relative">{esc(r["text"])}<i id="{strk}" style="position:absolute;left:-6px;right:-6px;top:52%;height:8px;background:#D97757;opacity:0"></i></span></div>')
        if r.get("cross_at") is not None:
            t = r["cross_at"]
            first_cross = t if first_cross is None else first_cross
            b.tw(f'tl.set("#{mark}", {{opacity:1}}, {num(t)});')
            b.tw(f'tl.from("#{mark}", {{scale:0, rotation:-30, duration:.3, ease:"back.out(2.6)"}}, {num(t)});')
            b.tw(f'tl.set("#{strk}", {{opacity:1}}, {num(t)});')
            b.tw(f'tl.from("#{strk}", {{scaleX:0, transformOrigin:"left center", duration:.35, ease:"power2.out"}}, {num(t)});')
            b.state(t, t + 0.35)
    no_id = b.id("no")
    b.add(f'<div id="{prof}" class="card" style="{box(0, 10, 960, 236)}">{wbar(d["profile_title"], dots=False, light=True)}'
          f'<div class="av" style="position:absolute;left:26px;top:94px;width:112px;height:112px;font-size:60px">Я</div>{rows}'
          f'<div id="{no_id}" class="big acc" style="position:absolute;right:34px;top:84px;font-size:120px">{esc(d["no_label"])}</div></div>')
    b.pop(no_id, first_cross if first_cross is not None else b.t0 + 0.3, rot=-10)
    c, win = b.id("cl"), b.id("wn")
    steps = 40
    t_a, t_b = d["lines_counter"]["at"], d["lines_counter"]["end_at"]
    values = [f"{round(d['lines_counter']['value'] * k / steps):,}".replace(",", " ") for k in range(steps + 1)]
    ctr = b.counter(values, t_a, (t_b - t_a) / steps, "font-size:56px")
    lh, wh, card_h = CODE_LH, 214, 364
    per_page = int(wh / lh)                                         # three large lines are on screen at any moment
    pages = [d["code_lines"][k:k + per_page] for k in range(0, len(d["code_lines"]), per_page)]
    t_page = (b.t1 - b.t0) / len(pages)
    body = ""
    for g, page_lines in enumerate(pages):
        gid = f"{c}g{g}"
        body += f'<div id="{gid}" style="position:absolute;left:0;top:0;width:100%;padding:12px 24px">'
        body += "".join(f'<span class="ln">{highlight(ln)}</span>' for ln in page_lines) + "</div>"
        t_in = b.t0 + g * t_page
        if g > 0:
            b.appear(gid, t_in, y=26, d=0.22)                       # the next page blurs in from below
            b.tw(f'tl.set("#{pages_prev}", {{opacity:0}}, {num(t_in)});')
        pages_prev = gid
    b.add(f'<div id="{code}" class="card dk" style="{box(0, 256, 960, card_h)}">{wbar(d["code_title"])}'
          f'<div id="{win}" style="position:absolute;left:0;top:70px;width:100%;height:{wh}px;overflow:hidden">'
          f'<div id="{c}" class="mono code" style="position:relative;height:{wh}px;font-size:48px">{body}</div></div>'
          f'<div style="position:absolute;left:0;top:{70 + wh}px;width:100%;height:{card_h - 8 - 70 - wh}px;border-top:4px solid #F4EFE9;background:#14110F;padding:0 24px;display:flex;align-items:center;justify-content:space-between">'
          f'<span class="lbl" style="font-size:36px">{esc(d["lines_counter"]["label"])}</span><span class="big acc">{ctr}</span></div></div>')
    b.card_in(prof)
    b.card_in(code, b.t0 + 0.05)
    b.motion(b.t0, b.t1, 0.4)


def toggle(b: SB, d: dict[str, Any]) -> None:
    """Full-screen visual (colour): a settings card where a pointer flips the terminal-related switches off one by one and the app switch on."""
    card, stamp = b.id("cd"), b.id("st")
    rows = ""
    stops = []
    for k, r in enumerate(d["rows"]):
        y = 235 + k * 190
        tg, knob = b.id("tg"), b.id("kn")
        on_first = r["start_on"]
        rows += (f'<div class="row" style="position:absolute;left:36px;top:{y}px;width:880px;height:100px;justify-content:space-between">'
                 f'<span style="font-size:60px;line-height:1">{esc(r["text"])}<br><span class="lbl" style="font-size:34px">{esc(r["sub"])}</span></span>'
                 f'<span id="{tg}" class="tg" style="background:{"#3FA66B" if on_first else "#8A817A"}"><i id="{knob}"></i></span></div>')
        t = r["at"]
        new_bg, new_x = ("#8A817A", 0) if on_first else ("#3FA66B", 60)
        b.tw(f'tl.set("#{knob}", {{x:{60 if on_first else 0}}}, 0);')
        b.tw(f'tl.to("#{tg}", {{backgroundColor:"{new_bg}", duration:.2, ease:"power1.inOut"}}, {num(t)});')
        b.tw(f'tl.to("#{knob}", {{x:{new_x}, duration:.2, ease:"back.out(2)"}}, {num(t)});')
        b.state(t, t + 0.2)
        stops.append({"x": 855, "y": 24 + y + 50, "at": t - 0.12, "click": t, "target": tg})
    b.add(f'<div id="{card}" class="card" style="{box(0, 10, 960, 1130)}">{wbar(d["title"], dots=False, light=True)}'
          f'<div class="big" style="position:absolute;left:36px;top:100px;font-size:70px;width:880px">{esc(d["heading"])}</div>{rows}'
          f'<div id="{stamp}" class="stamp" style="left:200px;top:960px;font-size:92px">{esc(d["stamp"]["text"])}</div></div>')
    b.card_in(card)
    b.pop(stamp, d["stamp"]["at"], rot=-20)
    b.pointer((b.t0 + 0.1, 900, 1040), stops)


def app(b: SB, d: dict[str, Any]) -> None:
    """Split (light): install card (pointer presses «download», a bar fills, ticks), then the app window: a prompt is typed, sent, the reply arrives."""
    inst, win, btn, bar = b.id("in"), b.id("ap"), b.id("bt"), b.id("br")
    send, you, ai = b.id("sd"), b.id("yo"), b.id("ai")
    ticks = ""
    for k, t in enumerate(d["ticks"]):
        ticks += b.chk(t["at"], esc(t["text"]), style=f"position:absolute;left:24px;top:{330 + k * 90}px;font-size:38px", sq=True, flash=True)
    b.add(f'<div id="{inst}" class="card" style="{box(0, 10, 420, 610)}">{wbar(d["install_title"], dots=False, light=True)}'
          f'<div class="lbl" style="position:absolute;left:24px;top:88px">{esc(d["install_sub"])}</div>'
          f'<div id="{btn}" class="btn" style="position:absolute;left:24px;top:136px;width:364px;font-size:46px;padding:14px 0">{esc(d["install_btn"])}</div>'
          f'<div id="{bar}" class="bar sg" style="left:24px;top:250px;width:364px"><i></i></div>{ticks}</div>')
    bt = d["download"]["at"]
    b.fill(bar, bt + 0.1, d["download"]["dur"], 100)
    b.card_in(inst)
    typed_html, _t_end = b.typed(d["prompt"]["text"], d["prompt"]["at"], 26.0)
    b.add(f'<div id="{win}" class="card" style="{box(450, 10, 510, 610)}">{wbar(d["app_title"])}'
          f'<div class="big" style="position:absolute;left:24px;top:98px;font-size:46px;width:440px">{esc(d["welcome"])}</div>'
          f'<div id="{you}" class="bub you" style="right:20px;top:190px;font-size:36px;padding:14px 22px">{esc(d["prompt"]["text"])}</div>'
          f'<div id="{ai}" class="bub ai" style="left:20px;top:316px;width:420px;font-size:34px;padding:14px 22px">{esc(d["reply"]["text"])}</div>'
          f'<div style="position:absolute;left:20px;top:490px;width:462px;height:84px;border:4px solid #14110F;border-radius:42px;background:#fff;padding:0 20px;display:flex;align-items:center;font-size:34px;font-weight:700">'
          f'{typed_html}<span id="{send}" class="chk" style="position:absolute;right:8px;top:8px;width:60px;height:60px;background:#D97757;color:#14110F;font-size:34px">&#8593;</span></div></div>')
    b.card_in(win, b.t0 + 0.06)
    skg = b.id("sg")
    b.add(f'<div id="{skg}" style="position:absolute;left:{450 + 24}px;top:{10 + 4 + 310}px;width:300px"><span class="sk" style="width:300px;height:28px;margin-bottom:16px"></span>'
          f'<span class="sk" style="width:210px;height:24px;background:#E7E1D8"></span></div>')
    b.hide(skg, d["reply"]["at"] - 0.04, 0.08)
    b.tw(f'tl.to("#{win}", {{borderColor:"#D97757", duration:.15}}, {num(d["open_at"])});')
    b.state(d["open_at"])
    b.appear(you, d["send_at"] + 0.05, y=16, d=0.22)
    b.appear(ai, d["reply"]["at"])
    b.tw(f'tl.to("#{send}", {{scale:1.25, duration:.1, yoyo:true, repeat:1}}, {num(d["send_at"])});')
    b.pointer((b.t0 + 0.15, 900, 560), [
        {"x": 210, "y": 191, "at": bt - 0.15, "click": bt, "target": btn},
        {"x": 700, "y": 300, "at": d["open_at"] - 0.2, "click": d["open_at"]},
        {"x": 902, "y": 554, "at": d["send_at"] - 0.1, "click": d["send_at"]},
    ])


def agent_chat(b: SB, d: dict[str, Any]) -> None:
    """Split (dark): the agent writes files in a terminal under a growing line counter, the author's words arrive as a bubble, the agent shows a plan."""
    term, you, dots, plan = b.id("tm"), b.id("yo"), b.id("dt"), b.id("pl")
    lines = ""
    for k, ln in enumerate(d["term_lines"]):
        cls = ln.get("cls", "cmd")
        t_html, _ = b.typed(ln["text"], ln["at"], ln.get("cps", 30.0), caret=cls == "cmd", keep_caret=k == len(d["term_lines"]) - 1)
        lines += f'<span class="ln {cls}">{t_html}</span>'
    cnt = d["counter"]
    steps = 30
    ctr = b.counter([str(round(cnt["value"] * k / steps)) for k in range(steps + 1)], cnt["at"], (cnt["end_at"] - cnt["at"]) / steps,
                    "font-size:40px;font-weight:800;color:#D97757")
    extra = (f'<span class="lbl" style="margin-left:auto;color:#F4EFE9">{esc(cnt["label"])}</span>{ctr}'
             f'<span class="pill ac" style="margin-left:14px">{esc(d["term_tag"])}</span>')
    b.add(f'<div id="{term}" class="card dk" style="{box(0, 10, 960, 318)}">{wbar(d["term_title"], extra=extra)}'
          f'<div class="mono" style="padding:12px 24px;font-size:40px">{lines}</div></div>')
    b.card_in(term)
    chatc, ghost, field = b.id("cc"), b.id("gh"), b.id("fd")
    b.add(f'<div id="{chatc}" class="card" style="{box(0, 344, 960, 276)}">'
          f'<div id="{ghost}" style="position:absolute;left:24px;top:20px"><span class="av" style="background:#D6CFC6;position:absolute;left:0;top:0;width:64px;height:64px"></span>'
          f'<span class="sk" style="position:absolute;left:84px;top:6px;width:170px;height:24px"></span>'
          f'<span class="sk" style="position:absolute;left:84px;top:42px;width:120px;height:20px;background:#E7E1D8"></span></div>'
          f'<div id="{field}" style="position:absolute;left:24px;right:24px;top:176px;height:76px;border:4px solid #14110F;border-radius:38px;background:#fff;'
          f'display:flex;align-items:center;padding:0 28px;font-size:34px;color:#5C544D;font-weight:600">{esc(d["input_placeholder"])}</div></div>')
    b.card_in(chatc, b.t0 + 0.06)
    typed_html, y_end = b.typed(d["you"]["text"], d["you"]["at"], 22.0)
    b.add(f'<div id="{you}" class="bub you" style="right:14px;top:356px;width:640px;font-size:38px">{typed_html}</div>')
    b.appear(you, d["you"]["at"] - 0.05)
    b.hide(field, y_end + 0.02, 0.1)
    b.hide(ghost, y_end + 0.02, 0.1)
    dot_html = ""
    reps = int(max(1, (d["plan_at"] - y_end) / 0.36))
    for k in range(3):
        did = b.id("d")
        dot_html += f'<span id="{did}" class="dot3"></span>'
        b.tw(f'tl.to("#{did}", {{y:-14, duration:.18, yoyo:true, repeat:{reps}, ease:"power1.inOut"}}, {num(y_end + 0.05 + k * 0.1)});')
    b.add(f'<div id="{dots}" class="bub ai" style="left:14px;top:480px;padding:22px 20px">{dot_html}</div>')
    b.appear(dots, y_end + 0.02, y=12, d=0.18)
    b.motion(y_end, d["plan_at"], 0.3)
    b.hide(dots, d["plan_at"] - 0.02, 0.05)
    chips = "".join(b.chk(it["at"], esc(it["text"]), style="font-size:36px", sq=True) for it in d["plan"])
    b.add(f'<div id="{plan}" class="card" style="{box(14, 464, 932, 148)}"><div class="lbl" style="position:absolute;left:24px;top:10px">{esc(d["plan_title"])}</div>'
          f'<div style="position:absolute;left:24px;top:66px;display:flex;gap:32px">{chips}</div></div>')
    b.appear(plan, d["plan_at"])


def confirm(b: SB, d: dict[str, Any]) -> None:
    """Full-screen visual (colour): the agent asks to apply changes, a pointer presses «Да», a live preview appears and the pointer adds to the cart."""
    chat, yes, no = b.id("ch"), b.id("by"), b.id("bn")
    files = ""
    for k, f in enumerate(d["files"]):
        files += b.chk(f["at"], f'<span class="mono" style="font-size:44px">{esc(f["text"])}</span>', style=f"position:absolute;left:30px;top:{184 + k * 76}px", sq=True, flash=True)
    done, res, cart, btn2 = b.id("dn"), b.id("rs"), b.id("ct"), b.id("b2")
    b.add(f'<div id="{chat}" class="card" style="{box(0, 10, 960, 550)}">{wbar(d["title"], dots=False, light=True)}'
          f'<div class="big" style="position:absolute;left:30px;top:94px;font-size:52px;width:890px">{esc(d["question"])}</div>{files}'
          f'<div id="{yes}" class="btn sg" style="position:absolute;left:30px;top:420px;width:410px;font-size:56px">{esc(d["yes"])}</div>'
          f'<div id="{no}" class="btn ghost" style="position:absolute;left:480px;top:420px;width:410px;font-size:56px;box-shadow:6px 6px 0 #14110F">{esc(d["no"])}</div></div>')
    b.card_in(chat)
    t_click = d["click"]["at"]
    ctr = b.counter_at(["0", "1"], [d["cart_at"]])
    done_pill = f'<span id="{done}" class="pill sg" style="margin-left:auto">{esc(d["done_text"])}</span>'
    real, skel = b.id("rl"), b.id("sl")
    b.add(f'<div id="{res}" class="card" style="{box(0, 600, 960, 540)}">{wbar(d["preview_title"], extra=done_pill)}'
          f'<div id="{skel}" style="position:absolute;left:0;top:70px;width:100%;height:450px">'
          f'<span class="sk" style="position:absolute;left:36px;top:36px;width:420px;height:84px"></span>'
          f'<span class="sk" style="position:absolute;right:36px;top:36px;width:200px;height:84px"></span>'
          f'<span class="sk" style="position:absolute;left:36px;top:170px;width:560px;height:40px;background:#E7E1D8"></span>'
          f'<span class="sk" style="position:absolute;left:36px;top:280px;width:320px;height:90px"></span></div>'
          f'<div id="{real}" style="position:absolute;left:0;top:0;width:100%;height:100%">'
          f'<div class="big" style="position:absolute;left:36px;top:100px;font-size:92px">{esc(d["preview_heading"])}</div>'
          f'<div id="{cart}" style="position:absolute;right:36px;top:100px;text-align:right"><span class="lbl" style="font-size:34px">{esc(d["cart_label"])}</span><br>'
          f'<span class="big acc" style="font-size:84px">{ctr}</span></div>'
          f'<div class="row" style="position:absolute;left:36px;top:250px;font-size:46px"><span class="chk on">&#10003;</span><span>{esc(d["preview_line"])}</span></div>'
          f'<div id="{btn2}" class="btn" style="position:absolute;left:36px;top:370px;font-size:54px">{esc(d["preview_btn"])}</div></div></div>')
    b.card_in(res, b.t0 + 0.08)
    b.appear(real, d["done_at"], y=30)
    b.hide(skel, d["done_at"], 0.1)
    b.pop(done, d["done_at"] + 0.3)
    b.tw(f'tl.to("#{done}", {{scale:1.15, duration:.18, yoyo:true, repeat:3}}, {num(d["live_at"])});')
    b.state(d["live_at"], d["live_at"] + 0.7)
    b.tw(f'tl.to("#{cart}", {{scale:1.2, duration:.12, yoyo:true, repeat:1, transformOrigin:"right top"}}, {num(d["cart_at"])});')
    b.pointer((b.t0 + 0.1, 880, 1000), [
        {"x": 235, "y": 494, "at": t_click - 0.12, "click": t_click, "target": yes},
        {"x": 235, "y": 1006, "at": d["cart_at"] - 0.1, "click": d["cart_at"], "target": btn2},
        {"x": 700, "y": 880, "at": d["live_at"] + 0.2},
    ])


def files(b: SB, d: dict[str, Any]) -> None:
    """Split (light): a project file list, a pointer selects CLAUDE.md (its rules are typed) and skills/ (its files appear)."""
    lst, pv, hl, pa, pb = b.id("fl"), b.id("pv"), b.id("hl"), b.id("pa"), b.id("pb")
    rows, picks = "", []
    for k, f in enumerate(d["files"]):
        rows += b.chk(f.get("at"), f'<span class="mono" style="font-size:40px">{esc(f["text"])}</span>', style=f"position:absolute;left:22px;top:{98 + k * 90}px", sq=True)
        if f.get("at") is not None:
            picks.append((k, float(f["at"])))
    b.add(f'<div id="{lst}" class="card" style="{box(0, 10, 390, 610)}">{wbar(d["list_title"], dots=False, light=True)}'
          f'<div id="{hl}" class="hl" style="left:8px;top:90px;width:366px;height:80px;opacity:0"></div>{rows}</div>')
    b.card_in(lst)
    stops = []
    for k, t in picks:
        y = 90 + k * 90
        b.tw(f'tl.set("#{hl}", {{opacity:1}}, {num(t)});')
        b.tw(f'tl.to("#{hl}", {{y:{y - 90}, duration:.12, ease:"power2.out"}}, {num(t)});')
        b.state(t)
        stops.append({"x": 150, "y": 10 + 4 + y + 40, "at": t - 0.1, "click": t})
    lines_a = ""
    for k, ln in enumerate(d["claude_md"]):
        t_html, _ = b.typed(ln["text"], ln["at"], 26.0, caret=True, keep_caret=k == len(d["claude_md"]) - 1)
        lines_a += f'<span class="ln {ln.get("cls", "cmd")}">{t_html}</span>'
    lines_b = ""
    for ln in d["skills"]:
        sk = b.id("sk")
        lines_b += f'<span class="ln" id="{sk}" style="font-size:48px">{esc(ln["text"])}</span>'
        b.appear(sk, ln["at"], y=14, d=0.2)
    b.add(f'<div id="{pv}" class="card dk" style="{box(420, 10, 540, 610)}">{wbar(d["pv_title"])}'
          f'<div id="{pa}" class="mono" style="position:absolute;left:0;top:70px;padding:28px 24px;font-size:48px;line-height:1.5">{lines_a}</div>'
          f'<div id="{pb}" data-layout-allow-overlap data-layout-allow-occlusion class="mono" style="position:absolute;left:0;top:70px;width:100%;height:536px;padding:28px 24px;font-size:48px;background:#1C1916;color:#F4EFE9">'
          f'<div class="lbl" style="margin-bottom:16px">{esc(d["skills_title"])}</div>{lines_b}</div></div>')
    b.card_in(pv, b.t0 + 0.05)
    skp = b.id("sp")
    b.add(f'<div id="{skp}" style="position:absolute;left:{420 + 28}px;top:{10 + 4 + 70 + 40}px;width:480px">'
          + "".join(f'<span class="sk" style="width:{w}px;height:30px;margin-bottom:26px;background:#2A2623"></span>' for w in (360, 440, 300, 400)) + '</div>')
    b.hide(skp, d["claude_md"][0]["at"], 0.1)
    b.tw(f'tl.from("#{pb}", {{opacity:0, duration:.2}}, {num(d["switch_at"])});')
    b.state(d["switch_at"], d["switch_at"] + 0.2)
    b.pointer((b.t0 + 0.1, 860, 560), stops)


def workspace(b: SB, d: dict[str, Any]) -> None:
    """Full-screen visual (dark): the workspace tree whose entries a pointer ticks one by one under a progress counter."""
    card, bar = b.id("ws"), b.id("br")
    rows, stops = "", []
    for k, e in enumerate(d["entries"]):
        y = 190 + k * 130
        rows += b.chk(e["at"], f'<span class="mono" style="font-size:52px">{esc(e["text"])}</span>', extra=f'<span class="lbl" style="margin-left:auto;font-size:34px">{esc(e["sub"])}</span>',
                      style=f"position:absolute;left:32px;top:{y}px;width:890px;height:100px", sq=True, flash=True)
        stops.append({"x": 61, "y": 10 + 4 + y + 50, "at": e["at"] - 0.06, "click": e["at"]})
    n = len(d["entries"])
    ctr = b.counter_at([f"{k}/{n}" for k in range(n + 1)], [e["at"] for e in d["entries"]])
    b.add(f'<div id="{card}" class="card dk" style="{box(0, 10, 960, 1130)}">{wbar(d["title"])}'
          f'<div class="big" style="position:absolute;left:32px;top:100px;font-size:66px">{esc(d["heading"])}</div>{rows}'
          f'<div id="{bar}" class="bar sg" style="left:32px;top:960px;width:560px;height:44px"><i></i></div>'
          f'<div class="big acc" style="position:absolute;right:90px;top:920px;font-size:110px">{ctr}</div></div>')
    b.card_in(card)
    b.fill(bar, d["entries"][0]["at"], d["entries"][-1]["at"] - d["entries"][0]["at"] + 0.3, 100, "none")
    b.pointer((b.t0 + 0.1, 860, 1000), stops)


def cta_comment(b: SB, d: dict[str, Any]) -> None:
    """Split (dark): the code word is typed into a comment field, a pointer presses send, the comment lands and the guide starts to arrive."""
    card, send, posted, bar, ph = b.id("cm"), b.id("sd"), b.id("ps"), b.id("br"), b.id("ph")
    typed_html, _end = b.typed(d["word"], d["type_at"], d.get("cps", 14.0))
    sk1 = b.id("sk")
    skeleton = "".join(f'<div class="row" style="position:absolute;left:30px;top:{y}px;width:900px"><span class="av" style="background:#D6CFC6"></span>'
                       f'<span style="flex:1"><span class="sk" style="height:26px;width:{w}%;margin-bottom:14px"></span><span class="sk" style="height:20px;width:80%;background:#E7E1D8"></span></span></div>'
                       for y, w in ((96, 45), (188, 60)))
    b.add(f'<div id="{card}" class="card" style="{box(0, 10, 960, 610)}">{wbar(d["title"], dots=False, light=True)}<div id="{sk1}">{skeleton}</div>'
          f'<div id="{posted}" style="position:absolute;left:30px;top:100px;width:900px"><div class="row" style="gap:18px"><span class="av">{esc(d["avatar"])}</span>'
          f'<span><span class="lbl">{esc(d["posted_meta"])}</span><br><span class="big" style="font-size:60px">{esc(d["word"])}</span></span>'
          f'<span class="chk on" style="margin-left:auto">&#10003;</span></div></div>'
          f'<div style="position:absolute;left:30px;top:300px;width:900px;height:130px;border:4px solid #14110F;border-radius:65px;background:#fff;display:flex;align-items:center;padding:0 40px;font-size:68px;font-weight:900;letter-spacing:.04em">'
          f'<span id="{ph}" style="font-size:36px;font-weight:600;letter-spacing:0;color:#5C544D;position:absolute;left:44px">{esc(d["placeholder"])}</span>'
          f'<span style="position:relative">{typed_html}</span>'
          f'<span id="{send}" class="chk" style="margin-left:auto;width:92px;height:92px;background:#D97757;color:#14110F;font-size:50px">&#8593;</span></div>'
          f'<div class="lbl" style="position:absolute;left:30px;top:466px;font-size:34px;text-transform:none;letter-spacing:0">{esc(d["status"])}</div>'
          f'<div id="{bar}" class="bar sg" style="left:30px;top:530px;width:900px;height:40px"><i></i></div></div>')
    b.tw(f'tl.to("#{ph}", {{opacity:0, duration:.05}}, {num(d["type_at"])});')
    b.card_in(card)
    b.tw(f'tl.from("#{posted}", {{opacity:0, y:-40, duration:.3, ease:"power2.out"}}, {num(d["send_at"] + 0.1)});')
    b.state(d["send_at"] + 0.1)
    b.hide(sk1, d["send_at"] + 0.08, 0.1)
    b.pointer((b.t0 + 0.1, 800, 580), [{"x": 852, "y": 10 + 4 + 300 + 65, "at": d["send_at"] - 0.1, "click": d["send_at"], "target": send}])
    b.fill(bar, d["bar_at"], d["bar_dur"], 100)


def dm(b: SB, d: dict[str, Any]) -> None:
    """Full-screen visual (colour): a message from the guide slides into the inbox, the guide opens as a document - the cover, a page turn,
    then the checklist fills under a progress counter."""
    inbox, guide, new = b.id("ib"), b.id("gd"), b.id("nw")
    n = d["new"]
    b.add(f'<div id="{inbox}" class="card" style="{box(0, 10, 960, 240)}">{wbar(d["inbox_title"], dots=False, light=True)}'
          f'<div id="{new}" class="row" style="position:absolute;left:20px;top:92px;width:916px;height:130px;background:#FFF2D8;border:4px solid #14110F;border-radius:20px;padding:0 20px;font-size:54px;box-shadow:5px 5px 0 #14110F">'
          f'<span class="av" style="width:92px;height:92px;font-size:48px">{esc(n["avatar"])}</span>'
          f'<span style="flex:1"><b>{esc(n["name"])}</b><br><span class="lbl" style="font-size:34px;text-transform:none;letter-spacing:0">{esc(n["text"])}</span></span>'
          f'<span class="pill ac" style="font-size:40px">{esc(n["badge"])}</span></div></div>')
    b.card_in(inbox)
    b.tw(f'tl.from("#{new}", {{x:900, opacity:0, duration:.35, ease:"power3.out"}}, {num(n["at"])});')
    b.state(n["at"], n["at"] + 0.35)
    cover, page, bar, skel, real = b.id("cv"), b.id("pg"), b.id("br"), b.id("sl"), b.id("rl")
    checks = d["checks"]
    total = len(checks)
    ticks = "".join(b.chk(t["at"], esc(t["text"]), style=f"position:absolute;left:40px;top:{150 + k * 118}px;font-size:60px", sq=True, flash=True, big=True)
                    for k, t in enumerate(checks))
    ctr = b.counter_at([f"{k}/{total}" for k in range(total + 1)], [t["at"] for t in checks])
    b.add(f'<div id="{guide}" class="card" style="{box(0, 280, 960, 860)}">{wbar(d["guide_title"])}'
          f'<div id="{page}" style="position:absolute;left:0;top:70px;width:100%;height:786px">'
          f'<div class="big" style="position:absolute;left:40px;top:34px;font-size:60px">{esc(d["list_heading"])}</div>{ticks}'
          f'<div id="{bar}" class="bar sg" style="left:40px;top:704px;width:560px;height:44px"><i></i></div>'
          f'<div class="big acc" style="position:absolute;right:110px;top:676px;font-size:90px">{ctr}</div></div>'
          f'<div id="{cover}" style="position:absolute;left:0;top:70px;width:100%;height:786px;background:#FFFDF9;transform-origin:left center">'
          f'<div id="{skel}"><span class="sk" style="position:absolute;left:44px;top:50px;width:190px;height:36px"></span>'
          f'<span class="sk" style="position:absolute;left:44px;top:130px;width:820px;height:84px"></span>'
          f'<span class="sk" style="position:absolute;left:44px;top:240px;width:700px;height:84px"></span>'
          f'<span class="sk" style="position:absolute;left:44px;top:500px;width:200px;height:200px;border-radius:50%"></span></div>'
          f'<div id="{real}" style="position:absolute;left:0;top:0;width:100%;height:100%">'
          f'<div class="lbl" style="position:absolute;left:44px;top:50px;font-size:40px">{esc(d["guide_kicker"])}</div>'
          f'<div class="big" style="position:absolute;left:44px;top:120px;font-size:84px;width:870px;line-height:1.06">{esc(d["guide_heading"])}</div>'
          f'<div class="chk on" style="position:absolute;left:44px;top:500px;width:200px;height:200px;font-size:130px;border-width:8px">&#10003;</div>'
          f'<div class="pill ac" style="position:absolute;left:290px;top:560px;font-size:56px;padding:12px 36px">{esc(d["guide_tag"])}</div></div></div></div>')
    b.card_in(guide, b.t0 + 0.06)
    b.appear(real, d["guide_at"], y=30)
    b.hide(skel, d["guide_at"], 0.1)
    b.tw(f'tl.fromTo("#{cover}", {{rotationY:0, transformPerspective:1600}}, {{rotationY:-100, transformPerspective:1600, duration:.5, ease:"power2.in", immediateRender:false}}, {num(d["flip_at"])});')
    b.tw(f'tl.set("#{cover}", {{opacity:0}}, {num(d["flip_at"] + 0.5)});')
    b.motion(d["flip_at"], d["flip_at"] + 0.5, 0.25)
    b.fill(bar, checks[0]["at"], checks[-1]["at"] - checks[0]["at"] + 0.3, 100, "none")
    stops = [{"x": 700, "y": 10 + 4 + 92 + 65, "at": d["guide_at"] - 0.14, "click": d["guide_at"] - 0.06},
             {"x": 880, "y": 280 + 400, "at": d["flip_at"] - 0.1, "click": d["flip_at"] - 0.05}]
    stops += [{"x": 62, "y": 280 + 4 + 70 + 150 + k * 118 + 34, "at": t["at"] - 0.06, "click": t["at"]} for k, t in enumerate(checks)]
    b.pointer((b.t0 + 0.05, 900, 700), stops)


def x10(b: SB, d: dict[str, Any]) -> None:
    """Split (dark): a compact ×1 → ×10 strip on top and, as the largest thing of the visual half, the comment field: the code word is typed
    in 128 px letters, a pointer presses «Отправить», the guide badge appears. From the moment the word is typed it stays untouched to the last frame."""
    big, rem, field, send, done, ok, ph, label = (b.id(k) for k in ("bg", "rm", "fd", "sd", "dn", "ok", "ph", "lb"))
    t_a, t_b = d["counter"]["at"], d["counter"]["end_at"]
    steps = 18
    ctr = b.counter_at([f"×{1 + round(9 * k / steps)}" for k in range(steps + 1)], [t_a + k * (t_b - t_a) / steps for k in range(steps)])
    bars = ""
    for k in range(5):
        bid = b.id("bb")
        bars += (f'<div id="{bid}" style="position:absolute;left:{560 + k * 74}px;bottom:18px;width:58px;height:{40 + k * 22}px;background:#D97757;'
                 f'border:4px solid #F4EFE9;border-radius:10px 10px 0 0"></div>')
        b.tw(f'tl.from("#{bid}", {{height:14, duration:.4, ease:"power2.out"}}, {num(t_a + k * (t_b - t_a) / 6)});')
    b.state(*[t_a + k * (t_b - t_a) / 6 for k in range(6)])
    b.add(f'<div id="{big}" class="card dk" style="{box(0, 10, 960, 190)}">'
          f'<div class="lbl" style="position:absolute;left:30px;top:14px">{esc(d["title"])}</div>'
          f'<div class="big acc" style="position:absolute;left:30px;top:60px;font-size:112px">{ctr}</div>{bars}</div>')
    b.card_in(big)
    r = d["reminder"]
    typed_html, _ = b.typed(r["word"], r["type_at"], float(r.get("cps", REMINDER_CPS)), caret=True)
    b.add(f'<div id="{rem}" data-role="reminder" class="card" style="{box(0, 224, 960, 396)}">'
          f'<span class="av" style="position:absolute;left:24px;top:14px;width:76px;height:76px;font-size:40px">{esc(r["avatar"])}</span>'
          f'<div style="position:absolute;left:120px;top:20px;font-size:52px;font-weight:800;line-height:1">{esc(r["label"])}</div>'
          f'<div id="{field}" style="position:absolute;left:12px;top:108px;width:928px;height:176px;border:4px solid #14110F;border-radius:88px;background:#fff;color:#14110F;display:flex;align-items:center;justify-content:center;padding:0 30px;font-size:128px;font-weight:900;letter-spacing:.01em">'
          f'<span id="{ph}" style="position:absolute;left:56px;font-size:40px;font-weight:600;letter-spacing:0;color:#5C544D">{esc(r["placeholder"])}</span>'
          f'<span data-role="codeword" style="position:relative;line-height:1.2;white-space:nowrap">{typed_html}</span></div>'
          f'<span id="{done}" class="pill sg" style="position:absolute;left:24px;top:308px;font-size:44px;padding:10px 30px">{esc(r["done_text"])}</span>'
          f'<div id="{send}" class="btn" style="position:absolute;left:576px;top:298px;width:340px;height:80px;font-size:44px;padding:0;box-shadow:6px 6px 0 #14110F">'
          f'<span id="{label}">{esc(r["send_label"])}</span><span id="{ok}" style="position:absolute;opacity:0;white-space:nowrap;font-size:40px">&#10003; {esc(r["sent_label"])}</span></div></div>')
    b.card_in(rem, b.t0 + 0.04)
    b.tw(f'tl.to("#{ph}", {{opacity:0, duration:.05}}, {num(r["type_at"])});')
    b.tw(f'tl.to("#{field}", {{borderColor:"#D97757", duration:.15}}, {num(r["at"])});')
    b.state(r["at"], r["at"] + 0.15)
    b.pop(done, r["send_at"] + 0.15)
    b.tw(f'tl.set("#{label}", {{opacity:0}}, {num(r["send_at"])});')
    b.tw(f'tl.set("#{ok}", {{opacity:1}}, {num(r["send_at"])});')
    b.tw(f'tl.to("#{send}", {{backgroundColor:"#3FA66B", duration:.15}}, {num(r["send_at"])});')
    pulses = max(3, int((b.t1 - (r["send_at"] + 0.6)) / 0.4)) * 2 - 1
    b.tw(f'tl.to("#{done}", {{scale:1.08, duration:.2, yoyo:true, repeat:{pulses}}}, {num(r["send_at"] + 0.6)});')
    b.tw(f'tl.to("#{big}", {{scale:1.03, duration:.35, yoyo:true, repeat:{pulses}, ease:"sine.inOut"}}, {num(t_b)});')
    b.state(r["send_at"], r["send_at"] + 0.6, r["send_at"] + 1.0, r["send_at"] + 1.4, t_b, t_b + 0.4, t_b + 0.8)
    # the pointer enters from the bottom right, never crosses the word, presses the button and rests below the field
    b.pointer((b.t0 + 0.1, 895, 574), [
        {"x": 4 + 576 + 170, "y": 224 + 4 + 298 + 40, "at": r["send_at"] - 0.12, "click": r["send_at"], "target": send},
        {"x": 430, "y": 574, "at": r["send_at"] + 0.9},
    ])


def _beat(b: SB, eid: str, t_from: float, t_to: float) -> None:
    """A slow pulse on one element between two moments (every 1.2 s), so the picture changes at least every 1.5 s while the speech goes on."""
    t = t_from
    while t < t_to - 0.4:
        b.tw(f'tl.to("#{eid}", {{scale:1.04, duration:.18, yoyo:true, repeat:1}}, {num(t)});')
        b.state(t, t + 0.36)
        t += 1.2


def follow_card(b: SB, d: dict[str, Any]) -> None:
    """Follow card (split or full-screen): the owner's account, a cursor presses the button and «Подписаться» switches to «Подписки».

    Handle, display name and avatar come from the reel config (``SceneContext.account``), never from the plan or the code. No follower or
    post counters (they would be invented or stale) and no grey stand-in posts (v4: no decorative placeholders): the full-screen card is
    filled by a second element of the same phrase, a status line that flips «Вы не подписаны» -> «Вы подписаны» with the button.
    The button and the status are stacked layers with a cross-faded opacity, so the switch is a plain tween that survives seeking.
    Text is at least 32 px (v4), the name line included.
    """
    acc = b.ctx.account
    if acc is None:
        raise ValueError("follow_card needs `account` (handle) in reel_config.json")
    full = bool(d.get("_full"))
    flip = float(d["flip_at"])
    av, top, height = (240, 220, 710) if full else (120, 150, 330)
    btn_h, btn_fs, base_fs, st_fs = (170, 64, 50, 56) if full else (104, 46, 46, 0)
    card, btn_a, btn_b, tick = b.id("fc"), b.id("fa"), b.id("fb"), b.id("ft")
    name_x = 30 + av + 28
    handle = f"@{acc.handle}"
    fs = base_fs if len(handle) <= 17 else max(MIN_TEXT_PX, int(base_fs * 17 / len(handle)))
    if acc.avatar is not None:
        src = b.asset(acc.avatar, "assets/account", "avatar")
        face = f'<img class="av" src="{esc(src)}" alt="" style="position:absolute;left:30px;top:30px;width:{av}px;height:{av}px;object-fit:cover">'
    else:
        face = (f'<span class="av" style="position:absolute;left:30px;top:30px;width:{av}px;height:{av}px;font-size:{av // 2}px">'
                f'{esc(acc.handle[:1].upper())}</span>')
    sub = (f'<div class="lbl" style="position:absolute;left:{name_x}px;top:{30 + av // 2 + 10}px;width:{892 - name_x}px;font-size:{MIN_TEXT_PX}px;'
           f'text-transform:none;letter-spacing:0;white-space:nowrap">{esc(acc.display_name)}</div>') if acc.display_name else ""
    btn_top = 30 + av + 40
    common = f"position:absolute;left:30px;top:{btn_top}px;width:892px;height:{btn_h}px;font-size:{btn_fs}px;padding:0"
    status = ""
    st_a, st_b = b.id("sa"), b.id("sb")
    if full:
        st_style = f"position:absolute;left:30px;top:{btn_top + btn_h + 56}px;width:892px;text-align:center;font-weight:900;font-size:{st_fs}px;line-height:1.1;white-space:nowrap"
        status = (f'<div id="{st_a}" style="{st_style}">Вы не подписаны</div>'
                  f'<div id="{st_b}" class="sig" style="{st_style};opacity:0">Вы подписаны</div>')
    b.add(f'<div id="{card}" class="card" style="{box(0, top, 960, height)}">{face}'
          f'<div class="big" style="position:absolute;left:{name_x}px;top:{30 + av // 2 - fs - 6 if acc.display_name else 30 + (av - fs) // 2}px;width:{892 - name_x}px;'
          f'font-size:{fs}px;white-space:nowrap">{esc(handle)}</div>{sub}'
          f'<span id="{tick}" class="chk on" style="position:absolute;left:{30 + av - 34}px;top:{30 + av - 34}px;width:54px;height:54px;font-size:{MIN_TEXT_PX}px">&#10003;</span>'
          f'<div id="{btn_a}" class="btn" style="{common}">Подписаться</div>'
          f'<div id="{btn_b}" class="btn ghost" style="{common};opacity:0">Подписки</div>{status}</div>')
    b.card_in(card)
    b.tw(f'tl.to("#{btn_a}", {{opacity:0, duration:.12, ease:"none"}}, {num(flip)});')
    b.tw(f'tl.to("#{btn_b}", {{opacity:1, duration:.12, ease:"none"}}, {num(flip)});')
    if full:
        b.tw(f'tl.to("#{st_a}", {{opacity:0, duration:.12, ease:"none"}}, {num(flip)});')
        b.tw(f'tl.to("#{st_b}", {{opacity:1, duration:.12, ease:"none"}}, {num(flip)});')
    b.state(flip, flip + 0.12)
    b.pop(tick, flip + 0.12)
    # the cursor travels in legs of at most 1.5 s, so a long approach still shows a new state every 1.5 s
    y_btn = top + btn_top + btn_h // 2
    start, end = b.t0 + 0.2, flip - 0.35
    legs = max(1, math.ceil((end - start) / 1.5))
    path = [(start + (end - start) * k / legs, 860 + (620 - 860) * k / legs, y_btn + 170 + (0 - 170) * k / legs) for k in range(legs + 1)]
    stops: list[dict[str, Any]] = [{"x": x, "y": y, "at": t_k} for t_k, x, y in path[1:]]
    stops[-1].update(click=flip, target=btn_a)
    b.pointer(path[0], stops)
    _beat(b, btn_b, flip + 0.9, b.t1)         # a slow heartbeat on the new button keeps the card alive after the switch


def _stage(d: dict[str, Any]) -> tuple[bool, int, int, int]:
    """Geometry of the card that holds pills / tiles: full-screen flag, top, height, and the offset under the optional title bar."""
    full = bool(d.get("_full"))
    top, height = (100, 900) if full else (20, 590)
    return full, top, height, (62 if d.get("title") else 0)


def _stage_card(b: SB, d: dict[str, Any], inner: str) -> None:
    """Add the stage card (title bar from the plan's ``title``, if any) around ``inner`` and settle it in from frame 0."""
    _full, top, height, _off = _stage(d)
    card = b.id("st")
    bar = f'<div class="wbar lt"><span class="lbl" style="color:#14110F">{esc(str(d["title"]))}</span></div>' if d.get("title") else ""
    b.add(f'<div id="{card}" class="card" style="{box(0, top, 960, height)}">{bar}{inner}</div>')
    b.card_in(card)


CHIP_BADGE = {"+": ("#14110F", "#3FA66B"), "–": ("#14110F", "#D97757")}      # sign -> (glyph colour, disc colour); both pairs keep 4.5:1 (v4)


def _rows(n: int, full: bool, height: int, off: int) -> tuple[int, int, int]:
    """Row height, gap and first row's top for ``n`` pills / logo rows that fill the stage card (v4: no lone chip on an empty panel)."""
    gap = 40 if full else 24
    avail = height - 8 - off - 2 * 28
    ph = min(260 if full else 170, (avail - (n - 1) * gap) // n)
    block = n * ph + (n - 1) * gap
    return ph, gap, off + 28 + (avail - block) // 2


def chips(b: SB, d: dict[str, Any]) -> None:
    """Plus/minus pills that spring onto the card at the words the author says (split or full-screen visual; up to four pills).

    The pills fill the card, so their size follows their count; there are no empty slots under them (v4: no decorative placeholders): the plan
    puts the first pop at the cut (``reel_plan.FIRST_POP_S``), and a slow pulse on the newest pill keeps a new state at least every 1.5 s.
    The sign (+ green, – orange) is drawn in our palette with dark glyphs (4.5:1). Text is what the author says, from 32 px.
    """
    full, _top, height, off = _stage(d)
    items = d["items"]
    ph, gap, y0 = _rows(len(items), full, height, off)
    longest = max(len(str(it["text"]).strip()) for it in items)
    fs = max(MIN_TEXT_PX, min(int(ph * 0.42), int(780 / (0.62 * max(longest, 1)))))
    badge = int(ph * 0.6)
    inner = ""
    pills: list[tuple[float, str]] = []
    for k, it in enumerate(items):
        y = y0 + k * (ph + gap)
        pill = b.id("pl")
        sign = CHIP_SIGNS.get(str(it.get("sign") or ""), "")
        glyph, disc = CHIP_BADGE.get(sign, ("", ""))
        mark = (f'<span style="flex:none;width:{badge}px;height:{badge}px;border-radius:50%;border:4px solid #14110F;display:flex;align-items:center;'
                f'justify-content:center;font-weight:900;font-size:{max(MIN_TEXT_PX, int(badge * 0.62))}px;line-height:1;color:{glyph};'
                f'background:{disc}">{sign}</span>') if sign else ""
        inner += (f'<div id="{pill}" style="position:absolute;left:30px;top:{y}px;width:892px;height:{ph}px;display:flex;align-items:center;gap:20px;'
                  f'padding:0 {14 if sign else 36}px;border:4px solid #14110F;border-radius:{ph // 2}px;background:#FFFDF9;box-shadow:5px 5px 0 #14110F;'
                  f'font-weight:800;font-size:{fs}px;white-space:nowrap">{mark}<span>{esc(str(it["text"]).strip())}</span></div>')
        b.pop(pill, float(it["at"]))
        pills.append((float(it["at"]), pill))
    _stage_card(b, d, inner)
    _pulse_newest(b, pills)


def _pulse_newest(b: SB, popped: list[tuple[float, str]]) -> None:
    """From each pop until the next one (or the end of the scene) the newest element pulses, so the scene never stands still for 1.5 s."""
    order = sorted(popped)
    for k, (t, eid) in enumerate(order):
        _beat(b, eid, t + 0.9, order[k + 1][0] if k + 1 < len(order) else b.t1)


def logo_file(assets: Path | None, name: str) -> Path:
    """Resolve a logo the owner put into the reel's assets folder; nothing is downloaded and nothing outside the folder is read.

    Raises:
        ValueError: when there is no assets folder, the name is a URL, the file is missing, has a wrong type or lies outside the folder.
    """
    if assets is None:
        raise ValueError("logo_pop needs the reel's assets folder (assets/ next to reel_config.json, or `assets_dir` in it) with the owner's logo files")
    return local_file(name, assets, LOGO_SUFFIXES, "logo")      # refuses URLs and anything outside the folder


def logo_pop(b: SB, d: dict[str, Any]) -> None:
    """Logo tiles of the services the author names, springing onto the card at their words (split or full-screen visual; up to three).

    Logos come only from files the owner supplied in the reel's assets folder (``reel_config`` ``assets_dir``); the label is the name the
    author says, from 32 px. Split: a row of square tiles. Full-screen: one wide row per service (logo left, name right) so the stack fills
    the frame. No empty slots (v4: no decorative placeholders); the first pop comes with the cut and the newest tile pulses slowly.
    """
    full, _top, height, off = _stage(d)
    items = d["items"]
    n = len(items)
    inner = ""
    popped: list[tuple[float, str]] = []
    if full:
        ph, gap, y0 = _rows(n, True, height, off)
        mark = ph - 56
    else:
        gap = 30
        ts = min(height - 8 - off - 2 * 28, (892 - (n - 1) * gap) // n, 330)
        left0 = (952 - (n * ts + (n - 1) * gap)) // 2
        y = off + (height - 8 - off - ts) // 2
    for k, it in enumerate(items):
        src = logo_file(b.ctx.assets_dir, str(it["file"]))
        url = b.asset(src, "assets/logos", f"{re.sub(r'[^a-z0-9_-]', '', src.stem.lower())}-{hashlib.sha1(str(src).encode()).hexdigest()[:8]}")
        tile = b.id("tl")
        name = esc(str(it["name"]).strip())
        if full:
            yy = y0 + k * (ph + gap)
            inner += (f'<div id="{tile}" style="position:absolute;left:30px;top:{yy}px;width:892px;height:{ph}px;display:flex;align-items:center;gap:36px;'
                      f'padding:0 28px;border:4px solid #14110F;border-radius:26px;background:#FFFDF9;box-shadow:8px 8px 0 #14110F;overflow:hidden">'
                      f'<img src="{esc(url)}" alt="" style="flex:none;width:{mark}px;height:{mark}px;object-fit:contain">'
                      f'<span style="font-weight:800;font-size:64px;white-space:nowrap">{name}</span></div>')
        else:
            x = left0 + k * (ts + gap)
            label = MIN_TEXT_PX if ts < 300 else 40
            inner += (f'<div id="{tile}" style="position:absolute;left:{x}px;top:{y}px;width:{ts}px;height:{ts}px;border:4px solid #14110F;border-radius:26px;'
                      f'background:#FFFDF9;box-shadow:8px 8px 0 #14110F;overflow:hidden">'
                      f'<img src="{esc(url)}" alt="" style="position:absolute;left:15%;top:8%;width:70%;height:{ts - label - 64}px;object-fit:contain">'
                      f'<div style="position:absolute;left:0;bottom:14px;width:100%;text-align:center;font-weight:800;font-size:{label}px;'
                      f'white-space:nowrap">{name}</div></div>')
        b.pop(tile, float(it["at"]))
        popped.append((float(it["at"]), tile))
    _stage_card(b, d, inner)
    _pulse_newest(b, popped)


BUILDERS: dict[str, Callable[[SB, dict[str, Any]], None]] = {
    "hook": hook, "terminal": terminal, "code_sea": code_sea, "toggle": toggle, "app": app, "agent_chat": agent_chat,
    "confirm": confirm, "files": files, "workspace": workspace, "cta_comment": cta_comment, "dm": dm, "x10": x10,
    "follow_card": follow_card, "chips": chips, "logo_pop": logo_pop,
    **HC_BUILDERS,       # scenes built from the owner's component library (html-components), see scenes_hc.py
}


def build_scene(scene: Scene, full: bool, ctx: SceneContext | None = None) -> Built:
    """Build one scene from its plan data; ``ctx`` carries what the reel config supplies (the owner's account)."""
    if scene.kind not in BUILDERS:
        raise ValueError(f"unknown scene kind {scene.kind!r}; known: {sorted(BUILDERS)}")
    data = dict(scene.data)
    data["_full"] = full
    sc = Scene(scene.n, scene.shot, scene.kind, scene.bg, scene.start, scene.end, data)
    b = SB(sc, ctx=ctx or SceneContext())
    BUILDERS[scene.kind](b, data)
    return b.build(scene.kind, scene.bg)
