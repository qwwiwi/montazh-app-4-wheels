"""Scene kinds built from the owner's component library (qwwiwi/html-components), the ``hc_*`` kinds.

Each kind takes one component of the library: its stylesheet comes from the kit folder (``ui_kit.component_css``: scaled x2.2 for the
1080 px frame, type floors 32/40 px, foreign classes renamed to ``x-<name>``), the markup below uses the component's own class
structure (``hc-<id>`` + ``x-card``, ``x-eyebrow``, ``x-tag``, ``x-num``, ``x-btn`` ...) and fills it with the words of the phrase.
The look is the library's: Inter Tight, warm paper cards with a thin line border and a soft shadow, the dark card, lime only as a marker.
The reel's own rules stay: every scene is a measured ``.card`` (wrapper ``hcw``, no border of its own), content of the phrase only,
a new state at least every 1.5 s (row switches, counters, fills, pops, a pointer that clicks; ``_keep_alive`` adds a soft pulse to
any longer gap), text from 32 px, the ending's code word the biggest text of its scene.

Layout inside the scene content box (960 px wide): split y 10..620, full screen y 10..1140.
"""

from __future__ import annotations

import math
from typing import Any

from scene_base import SB, box, esc, num

INK, BG, PAPER, LINE, DARK, LIME, SOFT, MUTED, SAND = (
    "#24251E", "#FAF8F2", "#FFFEFA", "#D8D7C9", "#15150F", "#D4FF00", "#4F5147", "#5C6053", "#E9E7DA")
CHECK = '<svg viewBox="0 0 16 16" width="34" height="34" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'


# ---- helpers ---------------------------------------------------------------------------------

def _root(b: SB, comp: str, inner: str, style: str = "") -> str:
    """The component's root and block elements around ``inner``; registers the component's stylesheet."""
    b.components.add(comp)
    return f'<div class="hc-{comp}-root"><div class="hc-{comp}" style="position:relative;height:100%;{style}">{inner}</div></div>'


def _wrap(b: SB, comp: str, x: float, y: float, w: float, h: float, inner: str, tag: str = "hw") -> tuple[str, str]:
    """A measured card (the gate's box) holding one component; returns (id, markup)."""
    eid = b.id(tag)
    return eid, f'<div id="{eid}" class="card hcw" style="{box(x, y, w, h)}">{_root(b, comp, inner)}</div>'


def _paint(b: SB, eid: str, t: float, bg: str, fg: str, border: str | None = None, d: float = 0.16) -> None:
    """Switch an element's surface (a row / step becomes active)."""
    extra = f', borderColor:"{border}"' if border else ""
    b.tw(f'tl.to("#{eid}", {{backgroundColor:"{bg}", color:"{fg}"{extra}, duration:{num(d)}, ease:"power1.inOut"}}, {num(t)});')
    b.state(t, t + d)


def _swap(b: SB, old: str | None, new: str, t: float) -> None:
    """Hide ``old`` and show ``new`` (hidden by inline opacity:0) at ``t``, the new one rising a little."""
    if old:
        b.tw(f'tl.set("#{old}", {{opacity:0}}, {num(t)});')
    b.tw(f'tl.set("#{new}", {{opacity:1}}, {num(t)});')
    b.tw(f'tl.from("#{new}", {{y:26, duration:.22, ease:"power2.out", immediateRender:false}}, {num(t)});')
    b.state(t, t + 0.22)


def _keep_alive(b: SB, eid: str, scale: float = 1.03) -> None:
    """A soft pulse of ``eid`` in every gap between states longer than 1.2 s, so the picture never stands still for 1.5 s."""
    ts = sorted({b.t0, b.t1, *[t for t in b.states if b.t0 <= t <= b.t1]})
    for a, c in zip(ts, ts[1:]):
        if c - a <= 1.2:
            continue
        t = a + 0.6
        while t < c - 0.3:
            b.tw(f'tl.to("#{eid}", {{scale:{num(scale)}, duration:.18, yoyo:true, repeat:1, ease:"sine.inOut"}}, {num(t)});')
            b.state(t, t + 0.36)
            t += 0.9


def _counter(b: SB, values: list[str], t_a: float, t_b: float) -> str:
    """Values switched evenly from ``t_a`` to ``t_b`` (the first one shows from the scene start)."""
    if len(values) < 2:
        return esc(values[0])
    step = (t_b - t_a) / (len(values) - 1)
    return b.counter_at(values, [t_a + k * step for k in range(len(values) - 1)])


def _in(b: SB, eid: str, d: dict[str, Any]) -> None:
    """Settle the scene's main card: sharp from frame 0 on the hook, a short blur-in otherwise."""
    b.card_in(eid, sharp=bool(d.get("hook")))


# ---- landing-feature-list: services list with a detail panel -------------------------------

def hc_services(b: SB, d: dict[str, Any]) -> None:
    """Services the author names (component ``landing-feature-list``): a numbered list on the left (on top in full screen), a detail panel
    on the right; at each spoken service its row switches to the dark active state, the pointer clicks it and the panel types the service.
    ``mode: "multi"`` keeps earlier rows active (a list that fills up)."""
    comp = "landing-feature-list"
    full = bool(d.get("_full"))
    items = d["items"]
    n = len(items)
    H = 1130 if full else 610
    if full:
        gap, row_h = 20, 128
        lx, ly, lw = 0, 0, 960
        dx, dy, dw = 0, n * (row_h + gap) + 10, 960
        dh = H - dy
        row_font, what_font = 60, 84
    else:
        gap = 16
        row_h = (H - (n - 1) * gap) / n
        lx, ly, lw = 0, 0, 420
        dx, dy, dw, dh = 450, 0, 510, H
        row_font, what_font = 46, 66
    rows, panels, row_ids = "", "", []
    for k, it in enumerate(items):
        rid, mid = b.id("rw"), b.id("rn")
        row_ids.append((rid, mid))
        y = ly + k * (row_h + gap)
        rows += (f'<label id="{rid}" style="position:absolute;{box(lx, y, lw, row_h)}display:flex;align-items:center;gap:22px;font-size:{row_font}px;font-weight:650;line-height:1.05">'
                 f'<span id="{mid}" class="x-mono" style="font-size:40px;flex:none;white-space:nowrap">{esc(it.get("n", f"{k + 1:02d}"))}</span>{esc(it["text"])}</label>')
        if it.get("show_at") is not None:
            b.appear(rid, it["show_at"], y=30)
    eyebrow = f'<span class="x-eyebrow" style="position:absolute;left:44px;top:40px">{esc(d.get("detail_label", "Что продаёте"))}</span>'
    prev: str | None = None
    intro = d.get("intro")
    if intro:
        pid = b.id("pn")
        t_html = esc(intro["text"]) if d.get("hook") else b.typed(intro["text"], intro["at"], float(intro.get("cps", 24)), caret=True)[0]
        panels += (f'<div id="{pid}" class="x-pn" style="display:block;position:absolute;left:44px;right:44px;top:110px">'
                   f'<p class="x-what" style="font-size:{what_font}px;line-height:1.08;margin:0">{t_html}</p></div>')
        prev = pid
    stops = []
    active: list[str] = []
    for k, it in enumerate(items):
        if it.get("at") is None:
            continue
        t = float(it["at"])
        rid, mid = row_ids[k]
        if d.get("mode") != "multi":
            for old in active:
                _paint(b, old, t, PAPER, INK, LINE)
            active.clear()
        _paint(b, rid, t, INK, BG, INK)
        b.tw(f'tl.to("#{mid}", {{color:"{LIME}", duration:.16}}, {num(t)});')
        active.append(rid)
        pid = b.id("pn")
        t_html, _ = b.typed(it.get("what", it["text"]), t + 0.02, float(it.get("cps", 30)))
        unit = f'<p class="x-unit" style="font-size:44px;margin:26px 0 0"><mark>{esc(it["mark"])}</mark></p>' if it.get("mark") else ""
        big_no = (f'<span class="x-num" style="position:absolute;right:{110 if full else 0}px;top:{dh - 110 - (300 if full else 230)}px;font-size:{260 if full else 190}px;'
                  f'line-height:1;color:{INK}"><mark>{esc(it.get("n", f"{k + 1:02d}"))}</mark></span>')
        panels += (f'<div id="{pid}" class="x-pn" style="display:block;position:absolute;left:44px;right:44px;top:110px;bottom:40px;opacity:0">'
                   f'<p class="x-what" style="font-size:{what_font}px;line-height:1.08;margin:0">{t_html}</p>{unit}{big_no}</div>')
        _swap(b, prev, pid, t)
        prev = pid
        y = ly + k * (row_h + gap)
        stops.append({"x": lx + lw - 70, "y": 10 + y + row_h / 2, "at": t - 0.14, "click": t, "target": rid})
    detail = f'<div class="x-detail" style="position:absolute;{box(dx, dy, dw, dh)}min-height:0">{eyebrow}{panels}</div>'
    cid, markup = _wrap(b, comp, 0, 10, 960, H, f'<div class="x-list" style="position:absolute;inset:0">{rows}</div>{detail}')
    b.add(markup)
    _in(b, cid, d)
    if stops:
        b.pointer((b.t0 + 0.05, dx + dw - 80, min(H - 40, 560)), stops)
    _keep_alive(b, active[-1] if active else cid)


# ---- landing-banner-waitlist: announcement, links, the code word ---------------------------

def _banner(b: SB, cls: str, x: float, y: float, w: float, h: float, inner: str, font: int) -> tuple[str, str]:
    eid = b.id("bn")
    return eid, (f'<div id="{eid}" class="x-bn {cls}" style="position:absolute;{box(x, y, w, h)}font-size:{font}px;border-radius:30px;padding:0 40px;flex-wrap:nowrap">'
                 f'{inner}</div>')


def hc_event(b: SB, d: dict[str, Any]) -> None:
    """The live stream announcement (component ``landing-banner-waitlist``): a lime banner, a dark banner with the date typed, the time as
    the big number that counts up to the spoken time, the place, and a button the pointer presses."""
    comp = "landing-banner-waitlist"
    full = bool(d.get("_full"))
    H = 1130 if full else 610
    b1h, b2h = (190, 210) if full else (118, 128)
    wl_y = b1h + b2h + 40
    b1_id, b1 = _banner(b, "x-b1", 0, 0, 960, b1h,
                        f'<div class="x-m"><span class="x-dot" style="width:22px;height:22px"></span><b>{esc(d["b1"]["text"])}</b></div><a>{esc(d["b1"]["link"])}</a>',
                        64 if full else 46)
    date_html, _ = b.typed(d["b2"]["text"], d["b2"]["at"], float(d["b2"].get("cps", 22)))
    b2_id, b2 = _banner(b, "x-b2", 0, b1h + 20, 960, b2h,
                        f'<div class="x-m"><span class="x-tag" style="font-size:44px;padding:14px 22px">{esc(d["b2"]["tag"])}</span>'
                        f'<span style="font-weight:700">{date_html}</span></div>', 64 if full else 50)
    w = d["wl"]
    ctr = _counter(b, w["values"], w["count_at"], w["count_end_at"])
    place_id, btn, ok, lbl = b.id("pl"), b.id("bt"), b.id("ok"), b.id("lb")
    wl = (f'<div class="x-wl" style="position:absolute;{box(0, wl_y, 960, H - wl_y)}display:block;padding:0">'
          f'<div class="x-cnt" style="position:absolute;left:40px;top:24px">'
          f'<span class="x-num" style="font-size:{200 if full else 150}px;line-height:1">{ctr}</span>'
          f'<span id="{place_id}" class="x-d" style="font-size:{56 if full else 44}px;font-weight:700;color:{INK};opacity:0">{esc(w["label"])}</span></div>'
          f'<div class="x-f" style="position:absolute;left:40px;right:40px;bottom:28px;align-items:center;flex-wrap:nowrap">'
          f'<span class="x-inp" style="flex:1;font-size:{44 if full else 38}px;color:{MUTED}">{esc(w["field"])}</span>'
          f'<a id="{btn}" class="x-btn" style="position:relative;font-size:{48 if full else 40}px;padding:24px 44px;white-space:nowrap">'
          f'<span id="{lbl}">{esc(w["button"])}</span><span id="{ok}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;opacity:0">{esc(w["done"])}</span></a></div></div>')
    cid, markup = _wrap(b, comp, 0, 10, 960, H, b1 + b2 + wl)
    b.add(markup)
    _in(b, cid, d)
    b.pop(b2_id, d["b2"]["at"], d=0.26)
    b.show_at(place_id, w["label_at"])
    b.tw(f'tl.from("#{place_id}", {{x:-40, duration:.25, ease:"power2.out", immediateRender:false}}, {num(w["label_at"])});')
    t = w["click_at"]
    _paint(b, btn, t, INK, LIME)
    b.tw(f'tl.set("#{lbl}", {{opacity:0}}, {num(t)});')
    b.tw(f'tl.set("#{ok}", {{opacity:1}}, {num(t)});')
    btn_y = 10 + wl_y + (H - wl_y) - 28 - 50
    b.pointer((b.t0 + 0.05, 600, 10 + wl_y + 40), [{"x": 820, "y": btn_y, "at": t - 0.15, "click": t, "target": btn}])
    _keep_alive(b, b1_id)


def hc_links(b: SB, d: dict[str, Any]) -> None:
    """«Links below» (component ``landing-banner-waitlist``, full screen): a lime banner with an arrow that points down, the stream banner,
    and the comment block whose label is typed as the author asks to write the code word."""
    comp = "landing-banner-waitlist"
    H = 1130 if d.get("_full") else 610
    full = H > 700
    arrow = b.id("ar")
    b1_id, b1 = _banner(b, "x-b1", 0, 0, 960, 300 if full else 170,
                        f'<b style="font-size:{96 if full else 64}px;line-height:1">{esc(d["b1"]["text"])}</b>'
                        f'<span id="{arrow}" style="font-size:{170 if full else 110}px;font-weight:800;line-height:1">&#8595;</span>', 96 if full else 64)
    b2y = (300 if full else 170) + 24
    b2_id, b2 = _banner(b, "x-b2", 0, b2y, 960, 200 if full else 120,
                        f'<div class="x-m"><span class="x-tag" style="font-size:44px;padding:14px 22px">{esc(d["b2"]["tag"])}</span>'
                        f'<span style="font-weight:700">{esc(d["b2"]["text"])}</span></div>', 60 if full else 44)
    wy = b2y + (200 if full else 120) + 24
    lab, _ = b.typed(d["wl"]["label"], d["wl"]["type_at"], float(d["wl"].get("cps", 26)), caret=True)
    wl_id = b.id("wl")
    wl = (f'<div id="{wl_id}" class="x-wl" style="position:absolute;{box(0, wy, 960, H - wy)}display:block;padding:0">'
          f'<div style="position:absolute;left:40px;top:44px;font-size:{96 if full else 56}px;font-weight:800;line-height:1.05;width:880px;letter-spacing:-.02em">{lab}</div>'
          f'<div class="x-f" style="position:absolute;left:40px;right:40px;bottom:40px;flex-wrap:nowrap;align-items:center">'
          f'<span class="x-inp" style="flex:1;font-size:44px;color:{MUTED}">{esc(d["wl"]["field"])}</span>'
          f'<a class="x-btn" style="font-size:44px;padding:24px 40px">{esc(d["wl"]["button"])}</a></div></div>')
    cid, markup = _wrap(b, comp, 0, 10, 960, H, b1 + b2 + wl)
    b.add(markup)
    _in(b, cid, d)
    if d["b2"].get("at") is not None:         # without «at» the stream banner is there from the cut (the cut lands on content)
        b.appear(b2_id, d["b2"]["at"])
    b.appear(wl_id, d["wl"]["at"])
    # the arrow points down again and again (every 0.5 s), the way the author points at the links under the video
    t = b.t0 + 0.1
    while t < b.t1 - 0.3:
        b.tw(f'tl.to("#{arrow}", {{y:36, duration:.22, yoyo:true, repeat:1, ease:"power2.inOut"}}, {num(t)});')
        b.state(t, t + 0.44)
        t += 0.55
    _keep_alive(b, b1_id)


def hc_cta(b: SB, d: dict[str, Any]) -> None:
    """The ending (component ``landing-banner-waitlist``, split): the stream banner on top and the comment block as the biggest thing of the
    visual half: the code word is typed in 128 px letters, the pointer presses «Отправить», a lime badge pops. From the moment the word is
    typed nothing covers or moves it (the pointer comes from the right, presses the button and rests below the field)."""
    comp = "landing-banner-waitlist"
    r = d["reminder"]
    b2_id, b2 = _banner(b, "x-b2", 0, 0, 960, 130,
                        f'<div class="x-m"><span id="{b.id("tg")}" class="x-tag" style="font-size:44px;padding:14px 22px">{esc(d["b2"]["tag"])}</span>'
                        f'<span style="font-weight:700">{esc(d["b2"]["text"])}</span></div>', 46)
    field, ph, send, lbl, ok, done = (b.id(k) for k in ("fd", "ph", "sd", "lb", "ok", "dn"))
    typed_html, _ = b.typed(r["word"], r["type_at"], float(r.get("cps", 10)), caret=True)
    wl_y = 154
    wl = (f'<div class="x-wl" data-role="reminder" style="position:absolute;{box(0, wl_y, 960, 610 - wl_y)}display:block;padding:0">'
          f'<span class="x-eyebrow" style="position:absolute;left:40px;top:26px">{esc(r["label"])}</span>'
          f'<div id="{field}" class="x-inp" style="position:absolute;left:24px;top:86px;width:912px;height:180px;min-width:0;padding:0;display:flex;align-items:center;justify-content:center;'
          f'border-width:4px;color:{INK};font-size:128px;font-weight:800;letter-spacing:.01em">'
          f'<span id="{ph}" style="position:absolute;left:48px;font-size:42px;font-weight:500;color:{MUTED}">{esc(r["placeholder"])}</span>'
          f'<span data-role="codeword" style="position:relative;line-height:1.2;white-space:nowrap">{typed_html}</span></div>'
          f'<span id="{done}" class="x-tag" style="position:absolute;left:24px;top:318px;font-size:44px;padding:18px 30px">{esc(r["done_text"])}</span>'
          f'<a id="{send}" class="x-btn" style="position:absolute;left:560px;top:300px;width:376px;height:110px;padding:0;display:flex;align-items:center;justify-content:center;font-size:46px">'
          f'<span id="{lbl}">{esc(r["send_label"])}</span><span id="{ok}" style="position:absolute;opacity:0;white-space:nowrap">&#10003; {esc(r["sent_label"])}</span></a></div>')
    cid, markup = _wrap(b, comp, 0, 10, 960, 610, b2 + wl)
    b.add(markup)
    b.card_in(cid)
    b.tw(f'tl.to("#{ph}", {{opacity:0, duration:.05}}, {num(r["type_at"])});')
    b.tw(f'tl.to("#{field}", {{borderColor:"{INK}", duration:.15}}, {num(r["at"])});')
    b.state(r["at"], r["at"] + 0.15)
    s = r["send_at"]
    _paint(b, send, s, INK, LIME)
    b.tw(f'tl.set("#{lbl}", {{opacity:0}}, {num(s)});')
    b.tw(f'tl.set("#{ok}", {{opacity:1}}, {num(s)});')
    b.tw(f'tl.set("#{done}", {{opacity:0}}, 0);')
    b.tw(f'tl.set("#{done}", {{opacity:1}}, {num(s + 0.15)});')
    b.pop(done, s + 0.15)
    for pulse in d.get("strip_pulses", []):
        t = float(pulse["at"])
        b.tw(f'tl.to("#{b2_id}", {{scale:1.04, duration:.16, yoyo:true, repeat:1}}, {num(t)});')
        b.state(t, t + 0.32)
    # field click on the right end (clear of the word), the button, then rest below the field
    b.pointer((b.t0 + 0.05, 900, 600), [
        {"x": 880, "y": 10 + wl_y + 86 + 90, "at": r["at"] - 0.12, "click": r["at"]},
        {"x": 760, "y": 10 + wl_y + 300 + 55, "at": s - 0.12, "click": s, "target": send},
        {"x": 440, "y": 540, "at": s + 0.7},
    ])
    _keep_alive(b, done)


# ---- diagram-steps-flow: how the agents take the work -----------------------------------

def hc_steps(b: SB, d: dict[str, Any]) -> None:
    """Numbered steps (component ``diagram-steps-flow``) that switch to the dark «hot» state as the author names them, the pointer
    clicking each; under them a result strip whose bar fills and whose status flips at the last word."""
    comp = "diagram-steps-flow"
    full = bool(d.get("_full"))
    H = 1130 if full else 610
    steps = d["steps"]
    n = len(steps)
    res_h = 250 if full else 150
    gap = 22 if full else 14
    st_h = (H - res_h - gap * n) / n
    inner, stops, last = "", [], None
    for k, s in enumerate(steps):
        sid, no = b.id("st"), b.id("no")
        y = k * (st_h + gap)
        d_html = f'<div class="x-d" style="font-size:{40 if full else 34}px">{esc(s["d"])}</div>' if s.get("d") else ""
        inner += (f'<div id="{sid}" class="x-st" style="position:absolute;{box(0, y, 960, st_h)}padding:0 44px 0 150px;justify-content:center">'
                  f'<div id="{no}" class="x-no" style="position:absolute;left:40px;top:50%;margin-top:-40px;width:80px;height:80px;font-size:40px">{k + 1}</div>'
                  f'<div class="x-t" style="font-size:{68 if full else 48}px">{esc(s["t"])}</div>{d_html}</div>')
        t = float(s["at"])
        _paint(b, sid, t, DARK, BG, DARK)
        b.tw(f'tl.to("#{no}", {{backgroundColor:"{LIME}", color:"{INK}", duration:.16}}, {num(t)});')
        b.tw(f'tl.to("#{sid} .x-d", {{color:"#C9C7B8", duration:.16}}, {num(t)});')     # the component's colour of .hot .d
        b.pop(no, t, d=0.3)
        stops.append({"x": 880, "y": 10 + y + st_h / 2, "at": t - 0.14, "click": t, "target": sid})
        last = sid
    r = d["result"]
    bar, ok, wait = b.id("br"), b.id("ok"), b.id("wt")
    ry = n * (st_h + gap)
    pad_r = 130 if full else 44            # full screen: the result row reaches y 1080+, clear of the like / comment column (x >= 950)
    inner += (f'<div class="x-st" style="position:absolute;{box(0, ry, 960, res_h)}padding:30px {pad_r}px 30px 44px;gap:18px">'
              f'<div style="display:flex;justify-content:space-between;align-items:center;gap:20px">'
              f'<span class="x-t" style="font-size:{56 if full else 44}px">{esc(r["label"])}</span>'
              f'<span style="position:relative;font-size:{48 if full else 38}px;font-weight:800;white-space:nowrap">'
              f'<span id="{wait}" style="color:{SOFT}">{esc(r["wait"])}</span>'
              f'<span id="{ok}" style="position:absolute;right:0;top:0;background:{LIME};color:{INK};padding:0 14px;border-radius:12px">{esc(r["done"])}</span></span></div>'
              f'<div style="position:relative;height:{40 if full else 30}px;border-radius:20px;background:{SAND};overflow:hidden;border:2px solid {LINE}">'
              f'<i id="{bar}" style="position:absolute;left:0;top:0;bottom:0;width:0;background:{INK};border-radius:20px"></i></div></div>')
    cid, markup = _wrap(b, comp, 0, 10, 960, H, inner)
    b.add(markup)
    _in(b, cid, d)
    t_a, t_b = float(steps[0]["at"]), float(r["at"])
    b.tw(f'tl.fromTo("#{bar}", {{width:"0%"}}, {{width:"100%", duration:{num(t_b - t_a)}, ease:"none"}}, {num(t_a)});')
    b.motion(t_a, t_b)
    b.tw(f'tl.set("#{wait}", {{opacity:0}}, {num(t_b)});')
    b.pop(ok, t_b)            # hidden by the pop's from-state until the last word
    b.pointer((b.t0 + 0.05, 900, H - 60), stops)
    _keep_alive(b, last or cid)


# ---- kpi-big-delta: «в десятки раз» ---------------------------------------------------------

def hc_delta(b: SB, d: dict[str, Any]) -> None:
    """One big number (component ``kpi-big-delta``): the marker number counts up while the author says it, the phrase is typed under it,
    the bar fills to the lime dot."""
    comp = "kpi-big-delta"
    full = bool(d.get("_full"))
    H = 1130 if full else 610
    c = d["counter"]
    ctr = _counter(b, [str(v) for v in c["values"]], c["at"], c["end_at"])
    p_html, _ = b.typed(d["text"], d["text_at"], float(d.get("cps", 26)))
    bar, dot = b.id("br"), b.id("dt")
    inner = (f'<div class="x-card" style="position:absolute;inset:0;padding:44px 52px">'
             f'<div class="x-top"><span class="x-eyebrow">{esc(d["eyebrow"])}</span><span class="x-tag x-line" style="font-size:40px;padding:12px 20px">{esc(d["tag"])}</span></div>'
             f'<div class="x-big x-num" style="font-size:{300 if full else 210}px;margin:{40 if full else 14}px 0 {20 if full else 6}px"><mark>{ctr}</mark></div>'
             f'<p class="x-p" style="font-size:{60 if full else 46}px;font-weight:700;color:{INK};max-width:none;margin:0;line-height:1.1">{p_html}</p>'
             f'<div class="x-bar" style="position:absolute;left:52px;right:52px;bottom:{70 if full else 44}px;height:30px;border-radius:15px">'
             f'<i id="{bar}" style="width:0;border-radius:15px"></i><b id="{dot}" style="left:0;width:44px;height:44px;margin:-22px 0 0 -22px"></b></div></div>')
    cid, markup = _wrap(b, comp, 0, 10, 960, H, inner)
    b.add(markup)
    _in(b, cid, d)
    t_a, t_b = float(c["at"]), float(d.get("bar_end_at", c["end_at"]))
    b.tw(f'tl.fromTo("#{bar}", {{width:"0%"}}, {{width:"100%", duration:{num(t_b - t_a)}, ease:"power1.inOut"}}, {num(t_a)});')
    b.tw(f'tl.fromTo("#{dot}", {{x:0}}, {{x:856, duration:{num(t_b - t_a)}, ease:"power1.inOut"}}, {num(t_a)});')     # bar is 960 - 2 x 52 px wide
    b.motion(t_a, t_b)
    _keep_alive(b, cid)


# ---- slide-before-after: a small team grows -----------------------------------------------

def hc_growth(b: SB, d: dict[str, Any]) -> None:
    """The «стало» panel of ``slide-before-after`` (dark, lime ticks) whose list fills as the author speaks, and the component's number strip
    under it whose cells pop at their words."""
    comp = "slide-before-after"
    full = bool(d.get("_full"))
    H = 1130 if full else 610
    pn_h = int(H * 0.62)
    mark = b.id("mk")
    items = ""
    for k, it in enumerate(d["items"]):
        lid = b.id("li")
        items += (f'<li id="{lid}" style="font-size:{52 if full else 42}px;padding:{22 if full else 14}px 0;align-items:center;font-weight:600">'
                  f'<span class="x-ic" style="width:56px;height:56px">{CHECK}</span><span class="x-tx">{esc(it["text"])}</span></li>')
        b.appear(lid, it["at"], y=20)
    h3 = f'{esc(d["title"])} <mark id="{mark}" style="display:inline-block">{esc(d["mark"]["text"])}</mark>'
    pn = (f'<section class="x-pn x-new" style="position:absolute;{box(0, 0, 960, pn_h)}padding:36px 44px;gap:14px">'
          f'<span class="x-eyebrow">{esc(d["eyebrow"])}</span><h3 style="font-size:{72 if full else 54}px">{h3}</h3><ul>{items}</ul></section>')
    cells = ""
    for k, s in enumerate(d["strip"]):
        sid = b.id("sc")
        cells += (f'<div id="{sid}" class="x-st" style="justify-content:center;padding:20px 30px">'
                  f'<span class="x-num" style="font-size:{84 if full else 64}px">{esc(s["value"])}</span>'
                  f'<span class="x-eyebrow" style="font-size:40px">{esc(s["label"])}</span></div>')
        if s.get("at") is not None:
            b.pop(sid, s["at"], d=0.3)
    strip = (f'<div class="x-strip" style="position:absolute;{box(0, pn_h + 20, 960, H - pn_h - 20)}margin:0;'
             f'grid-template-columns:repeat({len(d["strip"])},minmax(0,1fr))">{cells}</div>')
    cid, markup = _wrap(b, comp, 0, 10, 960, H, pn + strip)
    b.add(markup)
    _in(b, cid, d)
    b.pop(mark, d["mark"]["at"], d=0.3, rot=-6)
    _keep_alive(b, cid)


# ---- data-meter: more clients, more margin --------------------------------------------------

def hc_meter(b: SB, d: dict[str, Any]) -> None:
    """A headline with a marker word and two-three meters (component ``data-meter``) that fill and flip their value as the author names
    them."""
    comp = "data-meter"
    full = bool(d.get("_full"))
    H = 1130 if full else 610
    mark = b.id("mk")
    head = (f'<span class="x-eyebrow">{esc(d["eyebrow"])}</span>'
            f'<div style="font-size:{96 if full else 64}px;font-weight:800;letter-spacing:-.03em;line-height:1.02;margin:{22 if full else 10}px 0 {30 if full else 12}px">'
            f'{esc(d["title"])} <mark id="{mark}" style="display:inline-block">{esc(d["mark"]["text"])}</mark></div>')
    meters = ""
    for m in d["meters"]:
        fl, old, new = b.id("fl"), b.id("vo"), b.id("vn")
        meters += (f'<div class="x-m"><div class="x-top"><span class="x-lb" style="font-size:{50 if full else 42}px">{esc(m["label"])}</span>'
                   f'<span class="x-vv" style="position:relative;font-size:{64 if full else 50}px"><span id="{old}">{esc(m.get("from_text", "–"))}</span>'
                   f'<span id="{new}" style="position:absolute;right:0;top:0;opacity:0;white-space:nowrap">{esc(m["text"])}</span></span></div>'
                   f'<div class="x-tr" style="height:{44 if full else 34}px"><div id="{fl}" class="x-fl{" x-lime" if m.get("lime") else ""}" style="width:{m.get("from", 12)}%"></div></div></div>')
        t = float(m["at"])
        b.tw(f'tl.to("#{fl}", {{width:"{m["pct"]}%", duration:.7, ease:"power2.out"}}, {num(t)});')
        b.motion(t, t + 0.7, 0.2)
        b.tw(f'tl.set("#{old}", {{opacity:0}}, {num(t + 0.2)});')
        b.tw(f'tl.set("#{new}", {{opacity:1}}, {num(t + 0.2)});')
        b.state(t + 0.2)
    inner = (f'<div class="x-card" style="position:absolute;inset:0;padding:40px 52px;gap:{40 if full else 30}px;justify-content:{"flex-start" if full else "space-between"}">'
             f'<div>{head}</div>{meters}</div>')
    cid, markup = _wrap(b, comp, 0, 10, 960, H, inner)
    b.add(markup)
    _in(b, cid, d)
    b.pop(mark, d["mark"]["at"], d=0.3, rot=-6)
    _keep_alive(b, mark)


# ---- landing-audience-grid: who this is for ------------------------------------------------

def hc_audience(b: SB, d: dict[str, Any]) -> None:
    """Audience cards (component ``landing-audience-grid``): the card of the person the author addresses switches to the dark «hot» card,
    its text is typed, its tag pops; the pointer points at it."""
    comp = "landing-audience-grid"
    full = bool(d.get("_full"))
    H = 1130 if full else 610
    cards = d["cards"]
    n = len(cards)
    w = (960 - 24 * (n - 1)) / n
    inner, stops, hot_id = "", [], None
    for k, c in enumerate(cards):
        aid, av, tag = b.id("au"), b.id("av"), b.id("tg")
        p_html = esc(c.get("p", ""))
        if c.get("p_at") is not None:
            p_html, _ = b.typed(c["p"], c["p_at"], float(c.get("cps", 28)))
        x = k * (w + 24)
        inner += (f'<div id="{aid}" class="x-a" style="position:absolute;{box(x, 0, w, H)}padding:40px 36px;gap:22px">'
                  f'<div id="{av}" class="x-av" style="width:140px;height:140px;border-radius:36px;font-size:72px">{esc(c["av"])}</div>'
                  f'<h3 style="font-size:{68 if full else 58}px;line-height:1.05">{esc(c["h"])}</h3>'
                  f'<p style="font-size:{50 if full else 44}px;line-height:1.2;flex:0 1 auto">{p_html}</p>'
                  f'<span id="{tag}" class="x-tag{"" if c.get("hot_at") is not None else " x-line"}" style="align-self:flex-start;font-size:40px;padding:14px 22px">{esc(c["tag"])}</span></div>')
        if c.get("tag_at") is not None:
            b.tw(f'tl.set("#{tag}", {{opacity:0}}, 0);')
            b.tw(f'tl.set("#{tag}", {{opacity:1}}, {num(c["tag_at"])});')
            b.pop(tag, c["tag_at"])
        if c.get("hot_at") is not None:
            t = float(c["hot_at"])
            _paint(b, aid, t, DARK, BG, LIME)
            b.tw(f'tl.to("#{av}", {{backgroundColor:"{LIME}", borderColor:"{LIME}", color:"{INK}", duration:.16}}, {num(t)});')
            b.tw(f'tl.to("#{aid} p", {{color:"#D9D7CA", duration:.16}}, {num(t)});')
            stops.append({"x": x + w - 90, "y": 10 + 110, "at": t - 0.14, "click": t, "target": aid})
            hot_id = aid
    cid, markup = _wrap(b, comp, 0, 10, 960, H, inner)
    b.add(markup)
    _in(b, cid, d)
    if stops:
        b.pointer((b.t0 + 0.05, 480, H - 80), stops)
    _keep_alive(b, hot_id or cid)


# ---- diagram-hub-service: you help the specialist --------------------------------------------

def hc_hub(b: SB, d: dict[str, Any]) -> None:
    """Hub and rays (component ``diagram-hub-service``, drawn in HTML so the text stays large): the specialist in the dark centre, the
    services around, and the lime node «you + agents» that joins at the author's word; the chips under the hub pop one by one."""
    comp = "diagram-hub-service"
    full = bool(d.get("_full"))
    H = 1130 if full else 610
    hub_h = 760 if full else 470
    cx, cy, r = 480, 90 + (hub_h - 90) / 2, 160 if full else 100
    inner = f'<span class="x-hd x-eyebrow" style="position:absolute;left:44px;top:34px">{esc(d["eyebrow"])}</span>'
    nodes = d["nodes"]
    lines = ""
    node_html = ""
    hot_t = None
    for k, nd in enumerate(nodes):
        nx, ny = nd["x"], nd["y"] * (hub_h / 760)
        dx, dy = nx - cx, ny - cy
        length = (dx * dx + dy * dy) ** 0.5
        ang = math.degrees(math.atan2(dy, dx))
        lid, nid = b.id("ln"), b.id("nd")
        hot = bool(nd.get("hot"))
        lines += (f'<i id="{lid}" style="position:absolute;left:{num(cx)}px;top:{num(cy - 2)}px;width:{num(length)}px;height:{6 if hot else 4}px;'
                  f'background:{INK};transform-origin:0 50%;transform:rotate({num(ang)}deg)"></i>')
        bg = LIME if hot else PAPER
        node_html += (f'<div id="{nid}" style="position:absolute;left:{num(nx - 170)}px;top:{num(ny - 56)}px;width:340px;height:112px;border-radius:26px;'
                      f'background:{bg};border:4px solid {INK};display:flex;align-items:center;justify-content:center;font-size:{48 if full else 40}px;font-weight:750;color:{INK};white-space:nowrap">{esc(nd["text"])}</div>')
        if nd.get("at") is not None:
            t = float(nd["at"])
            if hot:
                b.tw(f'tl.set("#{nid}", {{opacity:0}}, 0);')
                b.tw(f'tl.set("#{nid}", {{opacity:1}}, {num(t)});')
                b.pop(nid, t, d=0.32)
                b.tw(f'tl.fromTo("#{lid}", {{scaleX:0}}, {{scaleX:1, duration:.35, ease:"power2.out", immediateRender:true}}, {num(t)});')
                hot_t = t
            else:
                b.tw(f'tl.to("#{nid}", {{backgroundColor:"{SAND}", duration:.12, yoyo:true, repeat:1}}, {num(t)});')
                b.state(t, t + 0.24)
    center = (f'<div id="{b.id("cn")}" style="position:absolute;left:{num(cx - r)}px;top:{num(cy - r)}px;width:{2 * r}px;height:{2 * r}px;border-radius:50%;background:{DARK};'
              f'color:{BG};display:flex;align-items:center;justify-content:center;text-align:center;font-size:{44 if full else 36}px;font-weight:800;line-height:1.05">{esc(d["center"])}</div>')
    chips = ""
    for k, ch in enumerate(d.get("chips", [])):
        chid = b.id("ch")
        chips += (f'<span id="{chid}" class="x-ch{" x-hm" if ch.get("hot") else ""}" style="font-size:{44 if full else 36}px;padding:14px 26px 14px 14px;gap:16px">'
                  f'<b style="width:60px;height:60px;font-size:40px">{k + 1}</b>{esc(ch["text"])}</span>')
        b.tw(f'tl.set("#{chid}", {{opacity:0}}, 0);')
        b.tw(f'tl.set("#{chid}", {{opacity:1}}, {num(ch["at"])});')
        b.pop(chid, ch["at"])
    chs = (f'<div class="x-chs" style="position:absolute;left:30px;right:30px;top:{hub_h + 10}px;bottom:30px;margin:0;align-content:center;gap:20px">{chips}</div>'
           if chips else "")
    body = f'<div class="x-card" style="position:absolute;inset:0;padding:0">{inner}{lines}{center}{node_html}{chs}</div>'
    cid, markup = _wrap(b, comp, 0, 10, 960, H, body)
    b.add(markup)
    _in(b, cid, d)
    if hot_t is not None:
        hot = next(n for n in nodes if n.get("hot"))
        b.pointer((b.t0 + 0.05, 860, H - 80), [{"x": hot["x"] + 120, "y": 10 + hot["y"] * (hub_h / 760), "at": hot_t + 0.25, "click": hot_t + 0.35}])
    _keep_alive(b, cid, 1.02)


HC_BUILDERS = {
    "hc_services": hc_services, "hc_event": hc_event, "hc_links": hc_links, "hc_cta": hc_cta, "hc_steps": hc_steps,
    "hc_delta": hc_delta, "hc_growth": hc_growth, "hc_meter": hc_meter, "hc_audience": hc_audience, "hc_hub": hc_hub,
}

# one resolved example per kind (scene 10..14 s), used by the tests
HC_EXAMPLES: dict[str, dict[str, Any]] = {
    "hc_services": {"hook": True, "intro": {"text": "Услуги", "at": 10.0}, "items": [
        {"text": "Реклама", "at": 10.5}, {"text": "Бухгалтерия", "at": 11.5, "show_at": 10.3}, {"text": "Финансы", "at": 12.6}]},
    "hc_event": {"b1": {"text": "Эфир завтра", "link": "YouTube"}, "b2": {"tag": "ЭФИР", "text": "26 ноября", "at": 10.2},
                 "wl": {"values": ["18:59", "19:00"], "count_at": 11.0, "count_end_at": 11.4, "label": "по Москве", "label_at": 11.6,
                        "field": "YouTube", "button": "Прийти", "done": "Приду", "click_at": 12.6}},
    "hc_links": {"_full": True, "b1": {"text": "Ссылки ниже"}, "b2": {"tag": "ЭФИР", "text": "завтра", "at": 10.6},
                 "wl": {"label": "Пишите кодовое слово", "type_at": 11.5, "at": 11.0, "field": "Комментарий", "button": "Отправить"}},
    "hc_cta": {"b2": {"tag": "ЭФИР", "text": "завтра"}, "strip_pulses": [{"at": 12.9}], "reminder": {
        "word": "ЭФИР", "label": "Комментарий", "placeholder": "Кодовое слово", "send_label": "Отправить", "sent_label": "Готово",
        "done_text": "Жду", "cps": 10, "at": 10.4, "type_at": 10.6, "send_at": 11.8}},
    "hc_steps": {"_full": True, "steps": [{"t": "Расскажу", "at": 10.1}, {"t": "Агенты", "at": 11.2}, {"t": "Автоматизация", "at": 12.3}],
                 "result": {"label": "Ваша работа", "wait": "вручную", "done": "сама", "at": 13.2}},
    "hc_delta": {"eyebrow": "Эффективность", "tag": "с агентами", "counter": {"values": ["×1", "×5", "×10"], "at": 10.5, "end_at": 11.5},
                 "text": "в десятки раз", "text_at": 10.1, "bar_end_at": 13.0},
    "hc_growth": {"eyebrow": "С агентами", "title": "Команда", "mark": {"text": "растёт", "at": 10.4},
                  "items": [{"text": "клиенты", "at": 11.2}, {"text": "больше", "at": 12.2}],
                  "strip": [{"value": "=", "label": "команда"}, {"value": "↑", "label": "клиенты", "at": 13.0}]},
    "hc_meter": {"_full": True, "eyebrow": "Проекты", "title": "Больше", "mark": {"text": "маржи", "at": 10.2},
                 "meters": [{"label": "Клиенты", "text": "больше", "pct": 80, "at": 10.6}, {"label": "Маржа", "text": "больше", "pct": 90, "at": 11.4}]},
    "hc_audience": {"cards": [{"av": "С", "h": "Специалист", "p": "услуги", "tag": "есть"},
                              {"av": "Н", "h": "Начинающий", "p": "нет услуг", "p_at": 12.0, "tag": "вы", "hot_at": 10.6, "tag_at": 11.4}]},
    "hc_hub": {"_full": True, "eyebrow": "Помогать", "center": "Специалист", "nodes": [
        {"text": "Реклама", "x": 480, "y": 150, "at": 10.2}, {"text": "Вы + агенты", "x": 480, "y": 690, "hot": True, "at": 11.3}],
        "chips": [{"text": "помогаете", "at": 12.0}, {"text": "людям", "at": 12.8}]},
}
