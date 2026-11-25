"""Building blocks of the scene builders: stylesheet, the scene builder ``SB`` with its effects, small helpers.

Every effect is a plain tween on the paused GSAP timeline (no callbacks: seeking a paused timeline suppresses them), so the
render is deterministic. Each effect also records the times at which the picture changes; the pre-render gate fails a scene
that stays static for longer than ``reel_plan.MAX_STATIC_S``.

Type sizes: labels and body text of a mock-up are at least 32 px at 1080 px width, code and terminal lines at least 40 px
(``lint_fonts`` and the Chrome measurement fail smaller text), key lines are 48-80 px, counters 150+ px. A card shows 3-5 large
lines, not a page of small ones. Secondary text keeps a contrast of 4.5:1 (``prerender_gate.contrast_ratio``).

No decorative filler: every element on a scene carries content of its phrase (``decor_problems``).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geometry as geo
from reel_config import Account, Colours
from reel_plan import Scene

MIN_TEXT_PX = 32            # labels and body text of a mock-up at 1080 px width; key lines are larger
MIN_MONO_PX = 40            # code and terminal lines (monospace): 3-5 large lines per card
_FONT_SIZE = re.compile(r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)px")
TIP = (7.0, 5.0)            # the pointer's tip inside its 56 px svg
CARET_HOLD = 0.12           # a caret stays this long after its line is typed


def esc(text: str) -> str:
    """HTML-escape."""
    return html.escape(text, quote=True)


def num(x: float) -> str:
    """Time/number for attributes with three decimals."""
    return f"{x:.3f}".rstrip("0").rstrip(".") or "0"


def lint_fonts(text: str, min_px: float = MIN_TEXT_PX) -> list[str]:
    """Font sizes below ``min_px`` in a stylesheet or markup (inline ``font-size:NNpx``): one message per offender."""
    out: list[str] = []
    for m in _FONT_SIZE.finditer(text):
        px = float(m.group(1))
        if px < min_px:
            ctx = text[max(0, m.start() - 60):m.start()].replace("\n", " ")
            out.append(f"font-size {px:g}px < {min_px:g}px near «…{ctx[-50:]}»")
    return out


_KEYWORDS = re.compile(r"\b(const|let|function|return|if|else|for|of|import|from|export|async|await|new)\b")
_STRINGS = re.compile(r"(&#x27;[^&]*&#x27;|&quot;[^&]*&quot;)")


def highlight(line: str) -> str:
    """Tiny syntax colouring for decorative code lines (keywords orange, strings green, comments grey)."""
    safe = esc(line)
    if safe.lstrip().startswith("//"):
        return f'<span class="c">{safe}</span>'
    safe = _STRINGS.sub(r'<span class="s">\1</span>', safe)
    return _KEYWORDS.sub(r'<span class="k">\1</span>', safe)


_SCENE_OPEN = re.compile(r'<div id="s\d+" class="clip scene')
_DECOR = re.compile(r'data-decor="([^"]+)"')
_MISSPELLED = {"ко" + "мент": "«комментарий» is written with a double м"}


def decor_problems(page: str) -> list[str]:
    """Decorative filler on the page: the old ``deco`` blocks are forbidden, and a ``data-decor`` name may belong to one scene only.

    A scene's elements carry content of its phrase; loose blocks that repeat from scene to scene  are what this catches.
    """
    out: list[str] = []
    if re.search(r'data-deco(?!r)', page) or 'class="deco"' in page:
        out.append("decorative filler (class/id «deco»): every element of a scene must carry content of its phrase")
    parts = _SCENE_OPEN.split(page)[1:]
    seen: dict[str, int] = {}
    for n, part in enumerate(parts):
        for name in set(_DECOR.findall(part)):
            if name in seen:
                out.append(f"decorative element «{name}» is reused in scenes {seen[name]} and {n}: no filler may repeat")
            seen.setdefault(name, n)
    return out


def spelling_problems(text: str) -> list[str]:
    """Known misspellings in the on-screen text or the sources (the word «комментарий» written with one м)."""
    low = text.lower()
    return [f"misspelling «{bad}»: {why}" for bad, why in _MISSPELLED.items() if bad in low]


def scene_css(c: Colours) -> str:
    """Stylesheet of every scene (backgrounds, cards, windows, rows, bubbles, buttons, bars, cursor)."""
    return f"""
.scene {{ position:absolute; left:0; top:0; width:1080px; overflow:hidden; z-index:10; }}
.scene.split {{ height:{geo.SEAM}px; border-bottom:6px solid {c.ink}; }}
.scene.full {{ height:{geo.FRAME_H}px; }}
.bgl {{ background-color:{c.paper}; background-image:linear-gradient({c.grid} 2px, transparent 2px), linear-gradient(90deg, {c.grid} 2px, transparent 2px); background-size:54px 54px; color:{c.ink}; }}
.bgd {{ background-color:{c.dark}; background-image:linear-gradient(rgba(244,239,233,.05) 2px, transparent 2px), linear-gradient(90deg, rgba(244,239,233,.05) 2px, transparent 2px); background-size:54px 54px; color:{c.cream}; }}
.bga {{ background-color:{c.accent}; background-image:linear-gradient(rgba(20,17,15,.10) 2px, transparent 2px), linear-gradient(90deg, rgba(20,17,15,.10) 2px, transparent 2px); background-size:54px 54px; color:{c.ink}; }}
.sc {{ position:absolute; left:60px; top:{geo.SPLIT_CONTENT_TOP}px; width:960px; height:{geo.SPLIT_CONTENT_BOTTOM - geo.SPLIT_CONTENT_TOP}px; }}
.sc.full {{ height:{geo.FULL_CONTENT_BOTTOM - geo.SPLIT_CONTENT_TOP}px; }}
.card {{ position:absolute; background:{c.card}; color:{c.ink}; border:4px solid {c.ink}; border-radius:26px; box-shadow:8px 8px 0 {c.ink}; overflow:hidden; }}
.bgd .card {{ box-shadow:8px 8px 0 {c.accent}; }}
.bga .card {{ box-shadow:8px 8px 0 {c.ink}; }}
.card.dk {{ background:{c.dark_card}; color:{c.cream}; }}
.bgd .card.dk {{ border-color:{c.cream}; }}
.wbar {{ height:70px; display:flex; align-items:center; gap:12px; padding:0 24px; background:{c.ink}; color:{c.cream}; font-weight:700; font-size:32px; letter-spacing:.02em; }}
.card:not(.dk) > .wbar.lt {{ background:{c.paper}; color:{c.ink}; border-bottom:4px solid {c.ink}; }}
.dotc {{ width:20px; height:20px; border-radius:50%; background:{c.accent}; }}
.dotc.g {{ background:{c.signal}; }} .dotc.m {{ background:{c.muted}; }}
.mono {{ font-family:'JetBrains Mono', monospace; font-weight:500; white-space:pre; }}
.ln {{ display:block; white-space:pre; line-height:1.38; }}
.ln.cmd {{ color:{c.cream}; }} .ln.out {{ color:{c.dim_on_dark}; }} .ln.err {{ color:{c.accent}; font-weight:700; }} .ln.ok {{ color:{c.signal}; font-weight:700; }}
.ch {{ opacity:0; }} .ch2 {{ display:none; }}
.tyc::after {{ content:""; display:inline-block; width:.55em; margin-right:-.55em; height:1.05em; background:{c.accent}; vertical-align:-.15em; opacity:var(--cr, 0); }}
.lbl {{ font-family:'Golos Text', sans-serif; font-weight:700; font-size:32px; letter-spacing:.07em; text-transform:uppercase; color:{c.dim_on_light}; }}
.card.dk .lbl {{ color:{c.dim_on_dark}; }}
.big {{ font-weight:900; line-height:1; letter-spacing:-.02em; }}
.acc {{ color:{c.accent}; }} .sig {{ color:{c.signal}; }}
.card:not(.dk) .acc {{ color:{c.accent_on_light}; }} .card:not(.dk) .sig {{ color:{c.signal_on_light}; }}
.row {{ display:flex; align-items:center; gap:20px; font-weight:700; font-size:40px; }}
.chk {{ width:50px; height:50px; flex:none; border-radius:50%; border:4px solid {c.ink}; background:{c.card}; display:flex; align-items:center; justify-content:center; font-size:32px; color:{c.ink}; font-weight:900; }}
.chk.on {{ background:{c.signal}; }}
.chk.sq {{ border-radius:12px; }}
.chk.lg {{ width:68px; height:68px; font-size:42px; }}
.tg {{ width:130px; height:72px; border-radius:36px; border:4px solid {c.ink}; background:{c.muted}; position:relative; flex:none; }}
.tg i {{ position:absolute; top:5px; left:5px; width:52px; height:52px; border-radius:50%; background:#fff; border:3px solid {c.ink}; }}
.pill {{ display:inline-block; font-weight:800; font-size:32px; padding:6px 20px; border-radius:28px; border:3px solid {c.ink}; background:{c.card}; color:{c.ink}; letter-spacing:.03em; white-space:nowrap; }}
.pill.ac {{ background:{c.accent}; color:{c.ink}; }} .pill.sg {{ background:{c.signal}; color:{c.ink}; }} .pill.dk {{ background:{c.ink}; color:{c.cream}; }}
.btn {{ display:inline-flex; align-items:center; justify-content:center; font-weight:900; font-size:48px; padding:14px 46px; border-radius:20px; border:4px solid {c.ink}; background:{c.accent}; color:{c.ink}; box-shadow:6px 6px 0 {c.ink}; }}
.btn.sg {{ background:{c.signal}; color:{c.ink}; }} .btn.ghost {{ background:{c.card}; }}
.bub {{ position:absolute; font-weight:700; font-size:38px; line-height:1.22; padding:18px 26px; border-radius:26px; border:4px solid {c.ink}; max-width:900px; }}
.bub.you {{ background:{c.accent}; color:{c.ink}; border-bottom-right-radius:6px; }}
.bub.ai {{ background:{c.card}; color:{c.ink}; border-bottom-left-radius:6px; box-shadow:5px 5px 0 {c.ink}; }}
.bar {{ position:absolute; height:34px; border-radius:18px; border:4px solid {c.ink}; background:{c.card}; overflow:hidden; }}
.bgd .bar, .card.dk .bar {{ border-color:{c.cream}; background:{c.dark}; }}
.bar > i {{ display:block; height:100%; width:0; background:{c.accent}; }}
.bar.sg > i {{ background:{c.signal}; }}
.ctr {{ position:relative; display:inline-block; }}
.ctr > .v {{ position:absolute; right:0; top:0; opacity:0; white-space:nowrap; }}
.ctr > .z {{ visibility:hidden; white-space:nowrap; }}
.cur {{ position:absolute; width:56px; height:56px; z-index:50; left:0; top:0; filter:drop-shadow(3px 3px 0 rgba(20,17,15,.55)); }}
.rip {{ position:absolute; width:44px; height:44px; border-radius:50%; border:6px solid {c.accent}; opacity:0; z-index:49; }}
.stamp {{ position:absolute; font-weight:900; font-size:64px; letter-spacing:.04em; padding:6px 26px; border:6px solid {c.accent}; color:{c.accent_on_light}; border-radius:14px; background:rgba(255,253,249,.92); transform:rotate(-7deg); white-space:nowrap; }}
.av {{ width:84px; height:84px; border-radius:50%; border:4px solid {c.ink}; background:{c.accent}; flex:none; display:flex; align-items:center; justify-content:center; font-weight:900; font-size:40px; color:{c.ink}; }}
.code {{ font-size:40px; color:{c.cream}; }} .code .k {{ color:{c.accent}; }} .code .s {{ color:{c.signal}; }} .code .c {{ color:{c.dim_on_dark}; }}
.flash {{ position:absolute; left:-14px; right:-14px; top:-8px; bottom:-8px; border-radius:16px; background:rgba(63,166,107,.28); opacity:0; pointer-events:none; }}
.hl {{ position:absolute; border-radius:12px; background:rgba(217,119,87,.28); border:3px solid {c.accent}; }}
.dot3 {{ width:16px; height:16px; border-radius:50%; background:{c.ink}; display:inline-block; margin:0 6px; }}
.sk {{ display:block; border-radius:14px; background:#D6CFC6; }}
.rip, .cur, .hl {{ pointer-events:none; }}
"""


@dataclass(frozen=True)
class SceneContext:
    """What a scene may take from the reel config: the owner's account (follow card) and the folder of the owner's own files (logo tiles)."""

    account: Account | None = None
    assets_dir: Path | None = None
    ui_kit: Path | None = None


@dataclass
class Built:
    """One finished scene: markup, GSAP lines, state times, and the owner's files it uses (source path, project-relative target)."""

    html: str
    gsap: list[str]
    states: list[float]
    files: list[tuple[Path, str]] = field(default_factory=list)
    components: tuple[str, ...] = ()       # html-components ids whose stylesheet the scene needs (ui kit)


@dataclass
class SB:
    """Scene builder: ids, markup parts, GSAP lines and the times at which the picture changes."""

    scene: Scene
    parts: list[str] = field(default_factory=list)
    gs: list[str] = field(default_factory=list)
    states: list[float] = field(default_factory=list)
    ctx: SceneContext = field(default_factory=SceneContext)
    files: list[tuple[Path, str]] = field(default_factory=list)
    components: set[str] = field(default_factory=set)
    _k: int = 0

    @property
    def t0(self) -> float:
        """Start of the scene."""
        return self.scene.start

    @property
    def t1(self) -> float:
        """End of the scene."""
        return self.scene.end

    def id(self, tag: str = "e") -> str:
        """A unique element id inside the page."""
        self._k += 1
        return f"s{self.scene.n}{tag}{self._k}"

    def add(self, markup: str) -> None:
        """Append markup to the scene content."""
        self.parts.append(markup)

    def tw(self, line: str) -> None:
        """Append one GSAP line."""
        self.gs.append(line)

    def state(self, *times: float) -> None:
        """Record that the picture changes at these times."""
        self.states.extend(times)

    def asset(self, src: Path, folder: str, name: str) -> str:
        """Register a file of the owner to be copied into the project; returns the project-relative URL used in the markup."""
        dst = f"{folder}/{name}{src.suffix.lower()}"
        self.files.append((src, dst))
        return dst

    def motion(self, t_a: float, t_b: float, step: float = 0.4) -> None:
        """Record continuous motion (a pointer travelling, a bar filling, text scrolling) as states every ``step`` seconds."""
        n = max(1, int((t_b - t_a) / step))
        self.state(*[t_a + k * (t_b - t_a) / n for k in range(n + 1)])

    # --- effects (all deterministic tweens on the paused timeline) -------------------------------
    def card_in(self, eid: str, t: float | None = None, d: float = 0.2, sharp: bool = False) -> None:
        """A card is on screen from its first frame: it settles from 94 % and a blur, never from opacity 0.

        ``sharp=True`` (the hook) draws it fully sharp from frame 0: no blur-in, no scale-in.
        """
        t = self.t0 if t is None else t
        if sharp:
            self.state(t)
            return
        self.tw(f'tl.from("#{eid}", {{scale:.96, filter:"blur(6px)", duration:{num(d)}, ease:"power2.out"}}, {num(t)});')
        self.state(t, t + d)

    def appear(self, eid: str, t: float, y: float = 24, d: float = 0.26) -> None:
        """Blur-in from below: opacity 0 -> 1 with a 12 px blur, the canon's card transition."""
        self.tw(f'tl.from("#{eid}", {{opacity:0, y:{num(y)}, filter:"blur(12px)", duration:{num(d)}, ease:"power2.out"}}, {num(t)});')
        self.state(t, t + d)

    def pop(self, eid: str, t: float, d: float = 0.3, rot: float = 0) -> None:
        """Spring pop: scale 0 -> 1 with overshoot (ticks, badges, stamps)."""
        self.tw(f'tl.from("#{eid}", {{scale:0, rotation:{num(rot)}, opacity:0, duration:{num(d)}, ease:"back.out(2.6)"}}, {num(t)});')
        self.state(t, t + d)

    def hide(self, eid: str, t: float, d: float = 0.2) -> None:
        """Fade an element out."""
        self.tw(f'tl.to("#{eid}", {{opacity:0, duration:{num(d)}, ease:"power1.in"}}, {num(t)});')
        self.state(t, t + d)

    def show_at(self, eid: str, t: float) -> None:
        """Element is hidden (css ``opacity:0`` inline) until ``t`` and solid after."""
        self.tw(f'tl.set("#{eid}", {{opacity:1}}, {num(t)});')
        self.state(t)

    def fill(self, eid: str, t: float, dur: float, pct: float, ease: str = "power1.inOut") -> None:
        """Fill a bar (``.bar > i``) from 0 to ``pct`` per cent."""
        self.tw(f'tl.fromTo("#{eid} > i", {{width:"0%"}}, {{width:"{num(pct)}%", duration:{num(dur)}, ease:"{ease}"}}, {num(t)});')
        self.motion(t, t + dur)

    def typed(self, text: str, t: float, cps: float = 18.0, cls: str = "", caret: bool = False, keep_caret: bool = False) -> tuple[str, float]:
        """Char-by-char reveal; returns the markup of the line and the time typing ends.

        ``caret=True``: characters are inserted one by one (display) so an accent block caret follows the last typed
        character; the caret goes away shortly after the line unless ``keep_caret``.
        """
        eid = self.id("ty")
        dt = 1.0 / cps
        end = t + dt * len(text)
        if not caret:
            chars = "".join(f'<span class="ch">{esc(c)}</span>' for c in text)
            self.tw(f'tl.to("#{eid} .ch", {{opacity:1, duration:.001, stagger:{num(dt)}}}, {num(t)});')
            self.motion(t, end, 0.3)
            return f'<span id="{eid}" class="{cls}">{chars}</span>', end
        spans = []
        for k, c in enumerate(text):
            cid = f"{eid}c{k}"
            spans.append(f'<span class="ch2" id="{cid}">{esc(c)}</span>')
            self.tw(f'tl.set("#{cid}", {{display:"inline"}}, {num(t + k * dt)});')
        # the caret is a ::after of the typed span, switched by a CSS variable: not an element, so it never «occludes» text for the layout check
        self.tw(f'tl.set("#{eid}", {{"--cr":1}}, {num(t)});')
        if not keep_caret:
            self.tw(f'tl.set("#{eid}", {{"--cr":0}}, {num(end + CARET_HOLD)});')
        self.motion(t, end, 0.3)
        return f'<span id="{eid}" class="tyc {cls}">{"".join(spans)}</span>', end

    def counter(self, values: list[str], t: float, dt: float, style: str = "") -> str:
        """Stacked values switched on a schedule (an odometer without callbacks); returns the markup."""
        eid = self.id("ct")
        spans = []
        for k, v in enumerate(values):
            sid = f"{eid}v{k}"
            spans.append(f'<span class="v" id="{sid}">{esc(v)}</span>')
            self.tw(f'tl.set("#{sid}", {{opacity:1}}, {num(t + k * dt)});')
            if k < len(values) - 1:
                self.tw(f'tl.set("#{sid}", {{opacity:0}}, {num(t + (k + 1) * dt)});')
        self.state(*[t + k * dt for k in range(len(values))])
        widest = max(values, key=len)
        return f'<span id="{eid}" class="ctr" style="{style}"><span class="z">{esc(widest)}</span>{"".join(spans)}</span>'

    def counter_at(self, values: list[str], times: list[float]) -> str:
        """Stacked values where ``values[0]`` shows from the start and ``values[k]`` from ``times[k-1]``; returns the markup."""
        eid = self.id("ca")
        spans = []
        for k, v in enumerate(values):
            sid = f"{eid}v{k}"
            spans.append(f'<span class="v" id="{sid}">{esc(v)}</span>')
            self.tw(f'tl.set("#{sid}", {{opacity:1}}, {num(self.t0 if k == 0 else times[k - 1])});')
            if k < len(values) - 1:
                self.tw(f'tl.set("#{sid}", {{opacity:0}}, {num(times[k])});')
        self.state(*times)
        return f'<span id="{eid}" class="ctr"><span class="z">{esc(max(values, key=len))}</span>{"".join(spans)}</span>'

    def ripple(self, t: float, x: float, y: float) -> None:
        """An expanding ring at the point (x, y) of the scene content at time ``t`` (a click)."""
        eid = self.id("rp")
        self.add(f'<div class="rip" id="{eid}" style="left:{num(x - 22)}px;top:{num(y - 22)}px"></div>')
        self.tw(f'tl.fromTo("#{eid}", {{scale:.3, opacity:.95}}, {{scale:2.2, opacity:0, duration:.45, ease:"power2.out", immediateRender:false}}, {num(t)});')
        self.tw(f'tl.set("#{eid}", {{scale:.3}}, {num(t + 0.5)});')
        self.state(t, t + 0.45)

    def pointer(self, start: tuple[float, float, float], stops: list[dict[str, Any]]) -> str:
        """A mouse pointer that visits ``stops`` in order; returns its id.

        ``start`` = (t, x, y) of the pointer tip. A stop is ``{x, y, at, click?, target?, leave?}``: the tip arrives at ``at``,
        presses at ``click`` (pointer dips, a ring expands, the ``target`` element is pushed into its shadow) and leaves at
        ``leave`` (default: 0.12 s after the click, or 0.1 s after arriving).
        """
        eid = self.id("cu")
        cx, cy = start[1], start[2]
        t = start[0]
        self.tw(f'tl.set("#{eid}", {{x:{num(cx - TIP[0])}, y:{num(cy - TIP[1])}}}, 0);')
        for stop in stops:
            ta = float(stop["at"])
            self.tw(f'tl.fromTo("#{eid}", {{x:{num(cx - TIP[0])}, y:{num(cy - TIP[1])}}}, '
                    f'{{x:{num(stop["x"] - TIP[0])}, y:{num(stop["y"] - TIP[1])}, duration:{num(max(ta - t, 0.05))}, ease:"power2.inOut", immediateRender:false}}, {num(t)});')
            self.motion(t, ta, 0.3)
            cx, cy = float(stop["x"]), float(stop["y"])
            click = stop.get("click")
            if click is not None:
                self.tw(f'tl.to("#{eid}", {{scale:.8, duration:.07, yoyo:true, repeat:1, transformOrigin:"{num(TIP[0])}px {num(TIP[1])}px"}}, {num(click)});')
                if stop.get("target"):
                    self.tw(f'tl.to("#{stop["target"]}", {{x:6, y:6, boxShadow:"0px 0px 0 #14110F", duration:.07, yoyo:true, repeat:1}}, {num(click)});')
                self.ripple(float(click), cx, cy)
            t = float(stop.get("leave", (click + 0.08) if click is not None else ta + 0.1))
        svg = ('<svg class="cur" id="%s" viewBox="0 0 24 24"><path d="M3 2 L3 19 L8 14.5 L11.5 22 L14.5 20.6 L11 13.2 L18 13 Z" '
               'fill="#14110F" stroke="#FFFDF9" stroke-width="1.6" stroke-linejoin="round"/></svg>') % eid
        self.add(svg)
        return eid

    def chk(self, on_at: float | None, label: str, extra: str = "", style: str = "", cls: str = "", sq: bool = False, flash: bool = False, big: bool = False) -> str:
        """A row with a checkbox that ticks at ``on_at`` (None = stays empty).

        ``flash=True`` (only for rows positioned absolutely by ``style``): the whole row is tinted green for a moment when it ticks,
        a change big enough to be seen on a phone, not only the small tick.
        """
        eid = self.id("ck")
        mark = fl = ""
        if on_at is not None:
            mark = f'<span class="chk on{" sq" if sq else ""}{" lg" if big else ""}" id="{eid}" style="position:absolute;inset:0">&#10003;</span>'
            self.pop(eid, on_at)
            if flash:
                fid = self.id("fl")
                fl = f'<i id="{fid}" class="flash"></i>'
                self.tw(f'tl.set("#{fid}", {{opacity:1}}, {num(on_at)});')
                self.tw(f'tl.to("#{fid}", {{opacity:0, duration:.5, ease:"power1.out"}}, {num(on_at + 0.05)});')
                self.state(on_at, on_at + 0.5)
        return (f'<div class="row {cls}" style="{style}">{fl}<span class="chk{" sq" if sq else ""}{" lg" if big else ""}" style="position:relative">{mark}</span>'
                f'<span>{label}</span>{extra}</div>')

    def build(self, kind: str, bg: str) -> Built:
        """Wrap the parts into the scene element."""
        s = self.scene
        full = bool(self.scene.data.get("_full", False))
        zone = "full" if full else "split"
        body = (f'<div id="s{s.n}" class="clip scene {"full" if full else "split"} bg{bg[0]}" data-start="{num(s.start)}" '
                f'data-duration="{num(s.end - s.start)}" data-kind="{kind}"><div class="sc{" full" if full else ""}" data-zone="{zone}">'
                f'{"".join(self.parts)}</div></div>')
        return Built(body, self.gs, self.states, self.files, tuple(sorted(self.components)))


def box(x: float, y: float, w: float, h: float, extra: str = "") -> str:
    """Inline position style."""
    return f"left:{num(x)}px;top:{num(y)}px;width:{num(w)}px;height:{num(h)}px;{extra}"


def wbar(title: str, dots: bool = True, light: bool = False, extra: str = "", mono: bool = False) -> str:
    """Window title bar: traffic-light dots (or none), the title, optional extra markup pushed to the right."""
    dots_html = '<span class="dotc"></span><span class="dotc g"></span><span class="dotc m"></span>' if dots else ""
    cls = "wbar lt" if light else "wbar"
    return f'<div class="{cls}">{dots_html}<span{" class=mono" if mono else ""} style="margin-left:{8 if dots else 0}px">{esc(title)}</span>{extra}</div>'
