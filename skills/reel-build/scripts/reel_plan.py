"""Reel plan: words, anchors, shots, scenes, call to action, and the rhythm rules of the canon.

Every boundary and every timed item in the plan is anchored to a recognised word of the frozen cut (exact match, in a
window after a given time), never to a hand-typed second. The plan is a JSON file written by the agent from the actual
speech; this module loads it, resolves the anchors and validates the montage rhythm (CANON.md of the references):

* shots are contiguous hard cuts of three types: split (visual above, speaker below), visual (full screen), speaker (full screen);
* one scene per split / visual shot, none on a speaker shot; the scene's own timeline is anchored to the same words;
* no type longer than 4.5 s in a row; a speaker «breath» lasts 1.3-3 s; shares of the three types stay in the canon ranges;
* the call to action is a window of 5-8 s.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geometry as geo

FPS = 30
LEAD = 0.06                  # a shot starts this long before its anchor word so the first sound is not clipped
TIME_MARGIN_S = 1.0          # a time of the plan may exceed the reel duration by this much (a word that ends a hair after the cut); more is a typo
MAX_RUN_S = 4.5              # the same shot type never lasts longer in a row
SPEAKER_MIN_S, SPEAKER_MAX_S = 1.3, 3.0
SHARE_RANGES = {geo.SHOT_SPLIT: (0.50, 0.60), geo.SHOT_VISUAL: (0.25, 0.30), geo.SHOT_SPEAKER: (0.10, 0.20)}
SHARE_TOLERANCE = 0.03
CTA_MIN_S, CTA_MAX_S = 5.0, 8.0
MAX_STATIC_S = 1.5           # a visual shows a new state at least this often (canon: 2 s; 0.5 s of margin for the measured render)
LIGHT_SHARE_MAX = 0.25       # light-background scenes: at most this share of the visual time (dark + orange is the default, light an accent)
REMINDER_HOLD_MIN_S = 2.5    # the code word is fully typed at least this long before the last frame and stays unobstructed
REMINDER_CPS = 10.0          # typing speed of the reminder (characters per second)
REMINDER_EARLIEST_S = 4.0    # the code-word reminder appears no earlier than this long before the end ...
REMINDER_LATEST_S = 1.8      # ... and no later than this (it must stay on screen for a while); its send click is before the last 0.3 s

ZOOM_RANGE = (1.05, 1.18)            # punch-in scale of the speaker; the research saw 112-118 %
ZOOM_MAX_SHOTS = 2
ZOOM_SANE_MAX = 10.0                 # anything above is a typo; the dosed range is ZOOM_RANGE, this only keeps a malformed number out of float()
ZOOM_MIN_GAP_S = 6.0                 # a zoom more often than this is a tic, not an accent
ZOOM_PAUSE_S = 0.25                  # a pause this long also counts as a sentence boundary

PUNCH_MAX = 2                        # key words in a large size per reel: more dilutes the accent
PUNCH_WORDS = (1, 3)
PUNCH_WINDOW_S = (0.4, 2.5)
PUNCH_WORD_MIN_S = 0.4               # spoken time per word; on screen it is about 0.11 s less (lead, two-frame gap), still longer than the 0.22 s pop
PUNCH_ANCHOR_SLACK = 0.05            # `from` is snapped to the frame grid, so the first word may start a hair before it
PUNCH_END_EDGE = 0.02                # and the word `to` points at is not part of the window

CHIPS_KIND, LOGO_KIND = "chips", "logo_pop"
CHIPS_MAX_SCENES, CHIPS_MAX_ITEMS, CHIP_TEXT_MAX = 2, 4, 24     # pills duplicate the caption: few scenes, at most four pills at a time
LOGO_MAX_SCENES, LOGO_MAX_ITEMS, LOGO_NAME_MAX = 2, 3, 12       # 12 letters at 32 px still fit a 250 px tile
FIRST_POP_S = 0.8            # the first pill / tile pops this soon after the cut: the cut lands on content, not on an empty card (v4: no placeholders)
LOGO_SUFFIXES = (".svg", ".png", ".webp", ".jpg", ".jpeg")
CHIP_SIGNS = {"+": "+", "-": "–", "–": "–", "−": "–"}            # a minus is always drawn as an en dash

FOLLOW_KIND = "follow_card"
FOLLOW_WINDOW = (0.60, 0.90)         # the follow card sits inside this share of the runtime (design target)
FOLLOW_MIN_S, FOLLOW_MAX_S = 3.0, 4.5
FOLLOW_FLIP_MARGIN_S = 1.0           # the button flips at least this long after the card starts and this long before it ends
FOLLOW_CTA_GAP_S = 2.0               # clear time between the card and the call to action (the research prefers 8 s: see SKILL.md)


class PlanError(ValueError):
    """The plan breaks a rule or an anchor cannot be found."""


@dataclass(frozen=True)
class Word:
    """One word of the frozen cut (after proofreading)."""

    w: str
    start: float
    end: float

    @property
    def norm(self) -> str:
        """Lower-case letters and digits only, for exact matching."""
        return normalise(self.w)


def normalise(token: str) -> str:
    """Lower-case a token and strip everything but letters and digits."""
    return "".join(re.findall(r"[0-9a-zа-яё]+", token.lower()))


def display_word(token: str) -> str:
    """A word as shown on screen: the transcript token without sentence punctuation and guillemets (case is set by the style)."""
    return token.rstrip(",.;:!?…»").lstrip("«")


def load_words(path: Path) -> list[Word]:
    """Load ``words.json`` written by ``transcribe.py``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Word(str(x["w"]), float(x["start"]), float(x["end"])) for x in data["words"]]


def snap(t: float) -> float:
    """Snap a time to the 30 fps frame grid."""
    return round(round(t * FPS) / FPS, 4)


def find_word(words: list[Word], token: str, after: float = 0.0, before: float = float("inf"), nth: int = 0) -> Word:
    """Find a word by EXACT normalised match inside the window ``[after, before)``.

    Prefix search is forbidden on purpose (error E36 from a prefix collision).

    Raises:
        PlanError: when the word is not in the window.
    """
    want = normalise(token)
    hits = [w for w in words if w.norm == want and after - 1e-6 <= w.start < before]
    if len(hits) <= nth:
        raise PlanError(f"anchor «{token}» (nth={nth}) not found in {after}..{before}")
    return hits[nth]


def _short(value: Any) -> str:
    """A value for an error message: a huge integer is described, never printed in full (and never converted to str)."""
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > 64:
        return f"an integer of {value.bit_length()} bits"
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _time_field(value: Any, label: str, hi: float, *, signed: bool = False) -> float:
    """A time value of the plan as a float: a real number (no bool), finite, from 0 (``-hi`` when ``signed``) to ``hi``.

    The range is checked on the value itself, before any float() / round(): a 400-digit integer, 1e308, inf and NaN all fail the comparison.

    Raises:
        PlanError: naming ``label`` when the value is not a number or lies outside the range.
    """
    lo = -hi if signed else 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise PlanError(f"{label} must be a number of seconds from {lo:g} to {hi:g}, got {_short(value)}")
    return float(value)


def resolve(ref: Any, words: list[Word], duration: float, *, lead: float = 0.0, label: str = "anchor") -> float:
    """Resolve an anchor to a time in seconds.

    A ref is a number (seconds), ``"end"``, or ``{"word": "...", "after": s, "before": s, "nth": n, "edge": "start"|"end",
    "plus": seconds}``. A word ref gives the start of the word minus ``lead`` plus ``plus``.

    Every number is checked before it is used: finite and from 0 to the reel duration plus ``TIME_MARGIN_S`` (``plus`` may be
    negative, down to minus that), and so is the resulting time. ``label`` names the field in the error.

    Raises:
        PlanError: on a malformed or out-of-range value, or when the word is not found.
    """
    hi = duration + TIME_MARGIN_S
    if isinstance(ref, (int, float)):
        return snap(_time_field(ref, label, hi))
    if isinstance(ref, str) and ref == "end":
        return snap(duration)
    if isinstance(ref, dict):
        word_token = ref.get("word")
        if not isinstance(word_token, str):
            raise PlanError(f"{label}.word must be a spoken word (a string), got {_short(word_token)}")
        after = _time_field(ref.get("after", 0.0), f"{label}.after", hi)
        before = _time_field(ref["before"], f"{label}.before", hi) if "before" in ref else float("inf")
        nth = ref.get("nth", 0)
        if isinstance(nth, bool) or not isinstance(nth, int) or not 0 <= nth < max(len(words), 1):      # the n-th hit cannot exceed the word count
            raise PlanError(f"{label}.nth must be a whole number from 0 below the number of words ({len(words)}), got {_short(nth)}")
        plus = _time_field(ref.get("plus", 0.0), f"{label}.plus", hi, signed=True)
        word = find_word(words, word_token, after, before, nth)
        if ref.get("edge", "start") == "end":
            return snap(_time_field(word.end + plus, label, hi))
        return snap(_time_field(max(0.0, word.start - lead + plus), label, hi))
    raise PlanError(f"bad anchor {label}: {_short(ref)}")


@dataclass(frozen=True)
class Shot:
    """One layout between two hard cuts."""

    start: float
    end: float
    type: str
    note: str = ""
    zoom: float = 1.0           # punch-in of the full-screen speaker: 1.0 = off

    @property
    def dur(self) -> float:
        """Length in seconds."""
        return round(self.end - self.start, 4)


@dataclass(frozen=True)
class Scene:
    """The visual of one split or full-screen shot: kind, background and data with every ``at`` resolved to seconds."""

    n: int
    shot: int
    kind: str
    bg: str
    start: float
    end: float
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Cta:
    """Call to action: the window of the animated example and the code word spoken by the author."""

    start: float
    end: float
    word: str


@dataclass(frozen=True)
class Punch:
    """A key word or short phrase shown in a large size instead of the running caption: window and the spoken words (one at a time)."""

    start: float
    end: float
    words: tuple[Word, ...]


@dataclass(frozen=True)
class Plan:
    """Resolved plan, all times in cut seconds on the frame grid."""

    duration: float
    shots: tuple[Shot, ...]
    scenes: tuple[Scene, ...]
    cta: Cta | None
    repeats_ok: tuple[str, ...]
    accent_words: tuple[str, ...]
    raw: dict[str, Any]
    punches: tuple[Punch, ...] = ()

    def shot_at(self, t: float) -> Shot:
        """The shot that is on screen at time ``t``."""
        for s in self.shots:
            if s.start - 1e-6 <= t < s.end - 1e-6:
                return s
        return self.shots[-1]

    def shot_index(self, t: float) -> int:
        """Index of the shot on screen at ``t``."""
        return self.shots.index(self.shot_at(t))


# ---- rhythm rules (pure, tested) --------------------------------------------------------------

def shares(shots: tuple[Shot, ...] | list[Shot]) -> dict[str, float]:
    """Share of the reel taken by each shot type (0..1)."""
    total = sum(s.dur for s in shots) or 1.0
    return {t: round(sum(s.dur for s in shots if s.type == t) / total, 4) for t in geo.SHOT_TYPES}


def runs(shots: tuple[Shot, ...] | list[Shot]) -> list[tuple[str, float, float]]:
    """Runs of the same shot type: ``(type, start, end)`` with neighbours of one type merged."""
    out: list[tuple[str, float, float]] = []
    for s in shots:
        if out and out[-1][0] == s.type and abs(out[-1][2] - s.start) < 1e-3:
            out[-1] = (s.type, out[-1][1], s.end)
        else:
            out.append((s.type, s.start, s.end))
    return out


def rhythm_problems(shots: tuple[Shot, ...] | list[Shot], cta: Cta | None = None) -> list[str]:
    """Violations of the canon rhythm: run length, speaker breath, shares, call-to-action window."""
    problems: list[str] = []
    for t, a, b in runs(shots):
        if b - a > MAX_RUN_S + 1e-3:
            problems.append(f"{t} run {a:.2f}..{b:.2f} lasts {b - a:.2f} s > {MAX_RUN_S} s")
    for s in shots:
        if s.type == geo.SHOT_SPEAKER and not SPEAKER_MIN_S - 0.05 <= s.dur <= SPEAKER_MAX_S + 0.05:
            problems.append(f"speaker shot {s.start:.2f}..{s.end:.2f} lasts {s.dur:.2f} s, canon {SPEAKER_MIN_S}-{SPEAKER_MAX_S} s")
    for t, share in shares(shots).items():
        lo, hi = SHARE_RANGES[t]
        if not lo - SHARE_TOLERANCE <= share <= hi + SHARE_TOLERANCE:
            problems.append(f"{t} takes {share * 100:.0f} % of the reel, canon {lo * 100:.0f}-{hi * 100:.0f} %")
    if cta is not None and not CTA_MIN_S - 0.05 <= cta.end - cta.start <= CTA_MAX_S + 0.05:
        problems.append(f"call to action lasts {cta.end - cta.start:.2f} s, canon {CTA_MIN_S:.0f}-{CTA_MAX_S:.0f} s")
    return problems


def static_gaps(times: list[float], start: float, end: float, limit: float = MAX_STATIC_S) -> list[tuple[float, float]]:
    """Stretches longer than ``limit`` between consecutive state times of a scene (borders included)."""
    ts = sorted({start, end, *[t for t in times if start <= t <= end]})
    return [(a, b) for a, b in zip(ts, ts[1:]) if b - a > limit + 1e-6]


def word_cut_by(words: list[Word], t: float) -> Word | None:
    """The spoken word that a cut at ``t`` slices, or None.

    The cut may reach at most ``LEAD`` (the usual head start of a shot before its anchor word) plus a frame of rounding into the
    previous word; deeper than that it is a cut in the middle of a word. Words that start at or after ``t - 0.02`` are the next ones.
    """
    prev = next((w for w in reversed(words) if w.start < t - 0.02), None)
    return prev if prev is not None and prev.end > t + LEAD + 0.02 else None


def at_sentence_boundary(words: list[Word], t: float) -> bool:
    """True when the cut at ``t`` (a shot start) falls right after a sentence end or a pause of 0.25 s or more (or at the very start).

    A cut inside a spoken word (see ``word_cut_by``) is never a boundary, even when that word ends a sentence.
    """
    if word_cut_by(words, t) is not None:
        return False
    nxt = next((i for i, w in enumerate(words) if w.start >= t - 0.02), None)
    if nxt is None or nxt == 0:
        return True
    prev = words[nxt - 1]
    return prev.w.rstrip("»\"')").endswith((".", "!", "?", "…")) or words[nxt].start - prev.end >= ZOOM_PAUSE_S


def zoom_problems(shots: tuple[Shot, ...] | list[Shot], words: list[Word]) -> list[str]:
    """Limits of the punch-in zoom: full-screen speaker shots only, 1.05-1.18, at most 2 per reel, 6 s apart, at a sentence boundary."""
    zoomed = [s for s in shots if s.zoom != 1.0]
    problems: list[str] = []
    if len(zoomed) > ZOOM_MAX_SHOTS:
        problems.append(f"zoom: at most {ZOOM_MAX_SHOTS} zoomed shots per reel, the plan has {len(zoomed)}")
    for a, b in zip(zoomed, zoomed[1:]):
        if b.start - a.start < ZOOM_MIN_GAP_S - 1e-6:
            problems.append(f"zoom at {b.start:.2f} s comes {b.start - a.start:.1f} s after the one at {a.start:.2f} s, keep {ZOOM_MIN_GAP_S:.0f} s or more apart")
    for s in zoomed:
        tag = f"zoom {s.zoom} on the {s.type} shot at {s.start:.2f} s"
        if s.type != geo.SHOT_SPEAKER:
            problems.append(f"{tag}: only a full-screen speaker shot can zoom (a split shows a 960 px slice, a visual has no speaker)")
        if not ZOOM_RANGE[0] - 1e-6 <= s.zoom <= ZOOM_RANGE[1] + 1e-6:
            problems.append(f"{tag} is outside the range {ZOOM_RANGE[0]}-{ZOOM_RANGE[1]}")
        cut_word = word_cut_by(words, s.start)
        if cut_word is not None:
            problems.append(f"{tag} switches in the middle of the spoken word «{display_word(cut_word.w)}» ({cut_word.start:.2f}..{cut_word.end:.2f} s): start the shot at a word boundary")
        elif not at_sentence_boundary(words, s.start):
            problems.append(f"{tag} does not start at a sentence boundary (a sentence end or a pause of {ZOOM_PAUSE_S} s)")
    return problems


def plain_relative_name(name: str) -> bool:
    """True for a file name that is relative, local and stays inside its folder: no URL, drive, absolute path or parent step."""
    if not name or re.match(r"^[a-z][a-z0-9+.-]*:|^//", name, flags=re.I) or name.startswith(("/", "\\")) or "\\" in name:
        return False
    return ".." not in name.split("/")


def _first_pop_problems(tag: str, start: float, items: list[Any]) -> list[str]:
    """The first pill / tile pops within ``FIRST_POP_S`` of the cut: there are no placeholder slots, so a later pop leaves an empty card."""
    ats = [float(it["at"]) for it in items if isinstance(it, dict) and isinstance(it.get("at"), (int, float))]
    if ats and min(ats) > start + FIRST_POP_S + 0.02:
        return [f"{tag}: the first item pops {min(ats) - start:.2f} s after the cut, allowed {FIRST_POP_S} s (no empty slots: start the shot on the first word or drop the scene)"]
    return []


def chips_problems(scenes: tuple[Scene, ...] | list[Scene]) -> list[str]:
    """Limits of the plus/minus pill scenes: scenes per reel, 1-4 pills, short text, a known sign."""
    cards = [s for s in scenes if s.kind == CHIPS_KIND]
    problems: list[str] = []
    if len(cards) > CHIPS_MAX_SCENES:
        problems.append(f"{CHIPS_KIND}: at most {CHIPS_MAX_SCENES} scenes per reel, the plan has {len(cards)}")
    for s in cards:
        tag = f"{CHIPS_KIND} {s.start:.2f}..{s.end:.2f}"
        items = s.data.get("items") or []
        if not isinstance(items, list):
            problems.append(f"{tag}: items must be a list")
            continue
        if not 1 <= len(items) <= CHIPS_MAX_ITEMS:
            problems.append(f"{tag} holds {len(items)} pills, allowed 1-{CHIPS_MAX_ITEMS}")
        for it in items:
            if not isinstance(it, dict):
                problems.append(f"{tag}: every pill must be an object {{text, sign, at}}, got {it!r}")
                continue
            text = str(it.get("text", "")).strip()
            if not text:
                problems.append(f"{tag}: a pill has empty text")
            elif len(text) > CHIP_TEXT_MAX:
                problems.append(f"{tag}: «{text}» is longer than {CHIP_TEXT_MAX} characters")
            if it.get("sign") not in (None, "", *CHIP_SIGNS):
                problems.append(f"{tag}: sign {it.get('sign')!r} is not one of {sorted(CHIP_SIGNS)}")
            if it.get("at") is None:
                problems.append(f"{tag}: «{text}» has no `at` word anchor")
        problems += _first_pop_problems(tag, s.start, items)
    return problems


def logo_problems(scenes: tuple[Scene, ...] | list[Scene]) -> list[str]:
    """Limits of the logo tile scenes: scenes per reel, 1-3 tiles, a name, and a plain local image file from the reel's assets (never a URL)."""
    cards = [s for s in scenes if s.kind == LOGO_KIND]
    problems: list[str] = []
    if len(cards) > LOGO_MAX_SCENES:
        problems.append(f"{LOGO_KIND}: at most {LOGO_MAX_SCENES} scenes per reel, the plan has {len(cards)}")
    for s in cards:
        tag = f"{LOGO_KIND} {s.start:.2f}..{s.end:.2f}"
        items = s.data.get("items") or []
        if not isinstance(items, list):
            problems.append(f"{tag}: items must be a list")
            continue
        if not 1 <= len(items) <= LOGO_MAX_ITEMS:
            problems.append(f"{tag} holds {len(items)} tiles, allowed 1-{LOGO_MAX_ITEMS}")
        for it in items:
            if not isinstance(it, dict):
                problems.append(f"{tag}: every tile must be an object {{name, file, at}}, got {it!r}")
                continue
            name, file = str(it.get("name", "")).strip(), str(it.get("file", ""))
            if not name or len(name) > LOGO_NAME_MAX:
                problems.append(f"{tag}: tile name {name!r} must be 1-{LOGO_NAME_MAX} characters (the service the author names)")
            if not plain_relative_name(file) or not file.lower().endswith(LOGO_SUFFIXES):
                problems.append(f"{tag}: file {file!r} must be a local image ({', '.join(LOGO_SUFFIXES)}) inside the reel's assets, never a URL")
            if it.get("at") is None:
                problems.append(f"{tag}: tile «{name}» has no `at` word anchor")
        problems += _first_pop_problems(tag, s.start, items)
    return problems


def _shot_index_at(shots: tuple[Shot, ...] | list[Shot], t: float) -> int:
    for i, s in enumerate(shots):
        if s.start - 1e-6 <= t < s.end - 1e-6:
            return i
    return len(shots) - 1


def punch_problems(punches: tuple[Punch, ...] | list[Punch], shots: tuple[Shot, ...] | list[Shot]) -> list[str]:
    """Limits of the punch words: count per reel, 1-3 words that fit the line, window length, one shot, not the hook, readable pace, no overlap."""
    problems: list[str] = []
    if len(punches) > PUNCH_MAX:
        problems.append(f"punch: at most {PUNCH_MAX} per reel, the plan has {len(punches)}")
    prev_end: float | None = None
    for p in sorted(punches, key=lambda x: x.start):
        tag = f"punch {p.start:.2f}..{p.end:.2f}"
        if not PUNCH_WORDS[0] <= len(p.words) <= PUNCH_WORDS[1]:
            problems.append(f"{tag} must hold {PUNCH_WORDS[0]}-{PUNCH_WORDS[1]} words, has {len(p.words)}")
        for w in p.words:
            if len(display_word(w.w)) > geo.PUNCH_MAX_CHARS:
                problems.append(f"{tag}: «{display_word(w.w)}» is longer than {geo.PUNCH_MAX_CHARS} characters and would not fit the line")
        if not PUNCH_WINDOW_S[0] - 0.02 <= p.end - p.start <= PUNCH_WINDOW_S[1] + 0.02:
            problems.append(f"{tag} lasts {p.end - p.start:.2f} s, allowed {PUNCH_WINDOW_S[0]}-{PUNCH_WINDOW_S[1]} s")
        reel_start, reel_end = shots[0].start, shots[-1].end
        if p.start < reel_start - 1e-3 or p.end > reel_end + 1e-3:      # a time outside the reel would otherwise be counted to the last shot
            problems.append(f"{tag} lies outside the reel {reel_start:.2f}..{reel_end:.2f} s: the words would be shown shorter than the window says")
            prev_end = p.end
            continue
        first = _shot_index_at(shots, p.start)
        if p.end > shots[first].end + 1e-3:
            problems.append(f"{tag} crosses a shot change: a caption never crosses one")
        if first == 0:
            problems.append(f"{tag} sits in the hook shot: canon 7 keeps the running caption from frame 0")
        for k, w in enumerate(p.words):
            until = p.words[k + 1].start if k + 1 < len(p.words) else p.end
            if until - w.start < PUNCH_WORD_MIN_S - 1e-6:
                problems.append(f"{tag}: «{display_word(w.w)}» stays {until - w.start:.2f} s, too fast to read (minimum {PUNCH_WORD_MIN_S} s)")
        if prev_end is not None and p.start < prev_end:
            problems.append(f"{tag} overlaps the previous punch")
        prev_end = p.end
    return problems


def _number(value: Any) -> bool:
    """True for a real JSON number (a bool is not one)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_punch_anchor(ref: Any, label: str) -> None:
    """Refuse a malformed ``from`` / ``to`` of a punch before it is resolved: numbers, ``"end"`` or a word object with sane fields.

    Raises:
        PlanError: with the field name when the anchor has a wrong shape or a wrong value type.
    """
    if _number(ref) or ref == "end":
        return
    if not isinstance(ref, dict):
        raise PlanError(f"punch.{label} must be seconds, \"end\" or {{word, after, before, nth, edge, plus}}, got {ref!r}")
    word = ref.get("word")
    if not isinstance(word, str) or not normalise(word):
        raise PlanError(f"punch.{label} needs `word`, a non-empty string of a spoken word, got {word!r}")
    unknown = set(ref) - {"word", "after", "before", "nth", "edge", "plus"}
    if unknown:
        raise PlanError(f"punch.{label}: unknown anchor keys {sorted(unknown)}")
    for key in ("after", "before", "plus"):
        if key in ref and not _number(ref[key]):
            raise PlanError(f"punch.{label}.{key} must be a number, got {ref[key]!r}")
    if "nth" in ref and (isinstance(ref["nth"], bool) or not isinstance(ref["nth"], int) or ref["nth"] < 0):
        raise PlanError(f"punch.{label}.nth must be a whole number from 0, got {ref['nth']!r}")
    if ref.get("edge", "start") not in ("start", "end"):
        raise PlanError(f"punch.{label}.edge must be \"start\" or \"end\", got {ref['edge']!r}")


def _punch_tokens(raw: Any) -> list[str]:
    """The listed words of a punch: a string split on spaces or a list of strings; anything else is refused.

    Raises:
        PlanError: when ``words`` is missing, an object, a number, empty or holds a non-string.
    """
    tokens = raw.split() if isinstance(raw, str) else raw
    if not isinstance(tokens, list) or not tokens or not all(isinstance(t, str) and normalise(t) for t in tokens):
        raise PlanError(f"punch.words must be a non-empty list of spoken words (or one string), got {raw!r}")
    return tokens


def _build_punches(specs: Any, words: list[Word], duration: float) -> tuple[Punch, ...]:
    """Resolve ``punch`` entries ``{from, to, words}``: the listed words are exactly the words spoken, in order, inside the window.

    A spoken word of the window that is not listed would lose its caption and never be shown, so it is refused.
    """
    if specs is None:
        return ()
    if not isinstance(specs, list):
        raise PlanError("punch must be a list of {from, to, words}")
    out: list[Punch] = []
    for spec in specs:
        if not isinstance(spec, dict) or not {"from", "to", "words"} <= set(spec):
            raise PlanError(f"punch needs from, to and words: {spec}")
        _check_punch_anchor(spec["from"], "from")
        _check_punch_anchor(spec["to"], "to")
        tokens = _punch_tokens(spec["words"])
        start = resolve(spec["from"], words, duration, label="punch.from")
        end = resolve(spec["to"], words, duration, label="punch.to")
        picked: list[Word] = []
        after = start - PUNCH_ANCHOR_SLACK
        for token in tokens:
            w = find_word(words, str(token), after, end - PUNCH_END_EDGE)          # text on screen is the author's speech, in spoken order
            picked.append(w)
            after = w.start + 1e-3
        spoken = [w for w in words if start - PUNCH_ANCHOR_SLACK <= w.start < end - PUNCH_END_EDGE]
        if spoken != picked:
            raise PlanError(f"punch {start:.2f}..{end:.2f} must list exactly the words spoken in its window; "
                            f"not listed: {[display_word(w.w) for w in spoken if w not in picked]}")
        out.append(Punch(start, end, tuple(picked)))
    return tuple(out)


def follow_problems(scenes: tuple[Scene, ...] | list[Scene], duration: float, cta: Cta | None = None) -> list[str]:
    """Limits of the follow card: once per reel, inside 60-90 % of the runtime, 3-4.5 s, the button flips mid-card, clear of the call to action."""
    cards = [s for s in scenes if s.kind == FOLLOW_KIND]
    problems: list[str] = []
    if len(cards) > 1:
        problems.append(f"{FOLLOW_KIND}: at most one per reel, the plan has {len(cards)}")
    lo, hi = FOLLOW_WINDOW[0] * duration, FOLLOW_WINDOW[1] * duration
    for s in cards:
        tag = f"{FOLLOW_KIND} {s.start:.2f}..{s.end:.2f}"
        if s.start < lo - 0.05 or s.end > hi + 0.05:
            problems.append(f"{tag} is outside {FOLLOW_WINDOW[0] * 100:.0f}-{FOLLOW_WINDOW[1] * 100:.0f} % of the runtime ({lo:.1f}..{hi:.1f} s)")
        if not FOLLOW_MIN_S - 0.05 <= s.end - s.start <= FOLLOW_MAX_S + 0.05:
            problems.append(f"{tag} lasts {s.end - s.start:.2f} s, allowed {FOLLOW_MIN_S}-{FOLLOW_MAX_S} s")
        flip = s.data.get("flip_at")
        if flip is None:
            problems.append(f"{tag} has no flip_at: the button must visibly switch «Подписаться» -> «Подписки»")
        elif not s.start + FOLLOW_FLIP_MARGIN_S - 0.05 <= float(flip) <= s.end - FOLLOW_FLIP_MARGIN_S + 0.05:
            problems.append(f"{tag}: flip at {float(flip):.2f} s must fall {FOLLOW_FLIP_MARGIN_S} s or more after the start and before the end")
        if cta is not None and s.end > cta.start - FOLLOW_CTA_GAP_S and s.start < cta.end:
            problems.append(f"{tag} comes too close to the call to action {cta.start:.2f}..{cta.end:.2f} (keep {FOLLOW_CTA_GAP_S} s clear)")
    return problems


def reminder_problems(plan: Plan) -> list[str]:
    """The ending shows the code word again (comment field / badge with an animated action) in the last seconds.

    The last scene carries ``reminder: {word, at, type_at, send_at}``: the word equals the call to action's code word,
    it appears 1.8-4 s before the end, is fully typed (``type_at`` + characters / ``cps``) at least 2.5 s before the last frame, and its send action lands before the last 0.3 s. A plan without a call to action has no rule.
    """
    if plan.cta is None:
        return []
    if not plan.scenes:
        return ["reminder: the plan has no scenes"]
    data = plan.scenes[-1].data.get("reminder")
    if not isinstance(data, dict):
        return [f"reminder: the last scene has no reminder of the code word «{plan.cta.word}» (comment field / badge in the final seconds)"]
    out: list[str] = []
    if normalise(str(data.get("word", ""))) != normalise(plan.cta.word):
        out.append(f"reminder: shows «{data.get('word')}», the code word is «{plan.cta.word}»")
    at, send = float(data.get("at", -1)), float(data.get("send_at", -1))
    left = plan.duration - at
    if not REMINDER_LATEST_S - 1e-6 <= left <= REMINDER_EARLIEST_S + 1e-6:
        out.append(f"reminder: appears {left:.1f} s before the end, expected {REMINDER_LATEST_S}-{REMINDER_EARLIEST_S} s")
    if not at <= send <= plan.duration - 0.3 + 1e-6:
        out.append(f"reminder: the send action at {send:.2f} s is not between its appearance and the last 0.3 s")
    typed = float(data.get("type_at", at)) + len(str(data.get("word", ""))) / float(data.get("cps", REMINDER_CPS))
    if plan.duration - typed < REMINDER_HOLD_MIN_S - 1e-6:
        out.append(f"reminder: the code word is fully typed at {typed:.2f} s, only {plan.duration - typed:.1f} s before the end: it must stay readable "
                   f"for at least {REMINDER_HOLD_MIN_S} s (start typing earlier)")
    return out


def light_share(plan: Plan) -> float:
    """Share of the scene time spent on a light background (0..1); the orange and dark backgrounds are the default palette."""
    total = sum(s.end - s.start for s in plan.scenes)
    return round(sum(s.end - s.start for s in plan.scenes if s.bg == "light") / total, 4) if total > 0 else 0.0


def light_share_of(scenes: list[dict[str, Any]]) -> float:
    """``light_share`` over the scene records of ``reel-meta.json`` (dicts with bg, start, end)."""
    total = sum(s["end"] - s["start"] for s in scenes)
    return round(sum(s["end"] - s["start"] for s in scenes if s["bg"] == "light") / total, 4) if total > 0 else 0.0


def palette_problems(plan: Plan) -> list[str]:
    """Dark + orange is the default: light scenes take at most ``LIGHT_SHARE_MAX`` of the visual time."""
    share = light_share(plan)
    if share > LIGHT_SHARE_MAX + 1e-6:
        return [f"palette: light-background scenes take {share * 100:.0f} % of the visual time, limit {LIGHT_SHARE_MAX * 100:.0f} % (dark + orange is the default)"]
    return []


# ---- plan building ----------------------------------------------------------------------------

def _is_anchor_key(key: str) -> bool:
    """Plan keys that hold a word anchor: ``at`` and anything ending in ``_at`` (``end_at``, ``type_at``...)."""
    return key == "at" or key.endswith("_at")


def _resolve_tree(node: Any, words: list[Word], duration: float, where: str = "", path: str = "") -> Any:
    """Resolve every anchor (``at`` / ``*_at``) found in nested dicts and lists to seconds; ``where`` + the key path name the field in an error."""
    if isinstance(node, dict):
        return {k: (resolve(v, words, duration, label=f"{where} {path + '.' if path else ''}{k}".strip()) if _is_anchor_key(k)
                    else _resolve_tree(v, words, duration, where, f"{path}.{k}" if path else k)) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_tree(v, words, duration, where, f"{path}[{i}]") for i, v in enumerate(node)]
    return node


def build_plan(raw: dict[str, Any], words: list[Word], duration: float) -> Plan:
    """Resolve anchors and validate the plan.

    Raises:
        PlanError: on the first broken structural rule (rhythm problems are reported by the gate, which lists them all).
    """
    specs = raw["shots"]
    bounds = [resolve(s["from"], words, duration, lead=LEAD if s["from"] != 0 else 0.0) for s in specs]
    bounds[0] = 0.0
    ends = bounds[1:] + [snap(duration)]
    shots: list[Shot] = []
    for spec, start, end in zip(specs, bounds, ends):
        if spec["type"] not in geo.SHOT_TYPES:
            raise PlanError(f"unknown shot type {spec['type']!r}")
        if end <= start:
            raise PlanError(f"shot {spec} has no length ({start}..{end})")
        zoom = spec.get("zoom", 1.0)
        if isinstance(zoom, bool) or not isinstance(zoom, (int, float)) or not 0 < zoom <= ZOOM_SANE_MAX:      # compared before float(): a 400-digit integer must not reach it
            raise PlanError(f"shot at {start:.2f} s: zoom must be a number (1.05-1.18, or 1 for off), got {_short(zoom)}")
        shots.append(Shot(start, end, spec["type"], str(spec.get("note", "")), float(zoom)))

    scenes: list[Scene] = []
    covered: set[int] = set()
    for n, spec in enumerate(raw.get("scenes", [])):
        idx = int(spec["shot"])
        if not 0 <= idx < len(shots):
            raise PlanError(f"scene {n} points at shot {idx}, the plan has {len(shots)}")
        shot = shots[idx]
        if shot.type == geo.SHOT_SPEAKER:
            raise PlanError(f"scene {n} ({spec['kind']}) sits on a speaker shot: a full-screen speaker shows only the speaker")
        if idx in covered:
            raise PlanError(f"shot {idx} has two scenes")
        covered.add(idx)
        data = _resolve_tree({k: v for k, v in spec.items() if k not in ("shot", "kind", "bg")}, words, duration,
                             where=f"scene {n} ({spec['kind']})")
        for at in _times(data):
            if not shot.start - 1e-6 <= at <= shot.end + 1e-6:
                raise PlanError(f"scene {n} ({spec['kind']}) has an item at {at} outside its shot {shot.start}..{shot.end}")
        scenes.append(Scene(n, idx, str(spec["kind"]), str(spec.get("bg", "light")), shot.start, shot.end, data))
    bare = [i for i, s in enumerate(shots) if s.type != geo.SHOT_SPEAKER and i not in covered]
    if bare:
        raise PlanError(f"shots {bare} have no scene: a lone speaker in a split or visual shot is an empty panel")

    cta = None
    if "cta" in raw:
        c = raw["cta"]
        cta = Cta(resolve(c["from"], words, duration, lead=LEAD), resolve(c["to"], words, duration, lead=LEAD), str(c["word"]))
        find_word(words, c["word_anchor"]["word"], float(c["word_anchor"].get("after", 0.0)))   # the code word was spoken
    follow = follow_problems(scenes, snap(duration), cta)
    if follow:
        raise PlanError("; ".join(follow))
    items = chips_problems(scenes) + logo_problems(scenes) + zoom_problems(shots, words)
    if items:
        raise PlanError("; ".join(items))
    punches = _build_punches(raw.get("punch"), words, duration)
    broken = punch_problems(punches, shots)
    if broken:
        raise PlanError("; ".join(broken))
    return Plan(snap(duration), tuple(shots), tuple(scenes), cta, tuple(raw.get("repeats_ok", [])),
                tuple(normalise(a) for a in raw.get("accent_words", [])), raw, punches)


def _times(node: Any) -> list[float]:
    """Every resolved ``at`` value in a scene's data."""
    out: list[float] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += [float(v)] if _is_anchor_key(k) else _times(v)
    elif isinstance(node, list):
        for v in node:
            out += _times(v)
    return out


def scene_times(scene: Scene) -> list[float]:
    """State times declared in the scene's data."""
    return _times(scene.data)


def load_plan(path: Path, words: list[Word], duration: float) -> Plan:
    """Read ``plan.json`` and build the validated plan."""
    return build_plan(json.loads(path.read_text(encoding="utf-8")), words, duration)
