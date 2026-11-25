"""Caption groups: proofreading file, grouping into flashes that accumulate up to two lines, timing.

Canon (CANON.md, reference reels): uppercase, one font, about 60 px, 1-3 words per flash, accumulating up to two lines, every
word fades from semi-transparent to solid in about 0.3 s; the group clears when it is full, at a sentence end, at a pause or
at a shot change. Rules the code keeps:

* the text is the re-recognised speech; only single-word fixes are allowed (proofreading file);
* a group never crosses a shot change (the layout under it changes);
* neighbouring groups keep a two-frame gap so the layout check sees one message per frame;
* a punch word (plan ``punch``) replaces the running caption for its window: the caption words inside the window are dropped, a group never spans
  the window, and every punch word is a one-word group (``punch=True``) shown in turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

import reel_plan as rp
from reel_plan import Plan, Word

TWO_FRAMES = 2 / rp.FPS
PUNCH_EDGE = 0.02            # `to` is snapped to the frame grid: the word it points at (starting up to a frame earlier) is not part of the window


@dataclass(frozen=True)
class CaptionStyle:
    """Grouping and timing knobs; the defaults are the canon values."""

    max_words_per_line: int = 3
    max_lines: int = 2
    max_chars: int = 17           # per line, so that a 60 px uppercase line stays clear of the button column
    gap_break: float = 0.35       # a silence this long between words ends the group
    lead: float = 0.04            # group appears this early
    hold: float = 0.30            # and stays this long after the last word
    fade: float = 0.25            # a word goes from semi-transparent to solid in this time
    fade_from: float = 0.55       # starting opacity of a word (0.3 read as a greyed caption on dark scenes)
    hook_solid: float = 0.45      # in the group that starts at frame 0 the words spoken within this time are solid from t=0 (no fade)


@dataclass(frozen=True)
class Group:
    """One caption group: lines of words, shown from ``start`` to ``end``; words appear at their own times."""

    id: str
    lines: tuple[tuple[Word, ...], ...]
    start: float
    end: float
    shot_type: str
    shot: int
    punch: bool = False         # a key word shown large instead of the running caption

    @property
    def words(self) -> tuple[Word, ...]:
        """All words in reading order."""
        return tuple(w for line in self.lines for w in line)

    @property
    def text(self) -> str:
        """Display text (lines joined by a space)."""
        return " ".join(w.w for w in self.words)


# ---- proofreading file ---------------------------------------------------------------------

def write_proofread(words: list[Word], path: Path) -> None:
    """Write the editable file: ``index<TAB>time<TAB>word``, one recognised word per line."""
    lines = ["# Proofreading: change ONLY the third column, one word for one word.",
             "# No lines may be added, removed or merged. Replace a single word (e.g. «код» -> «Claude»)."]
    lines += [f"{i}\t{w.start:.2f}\t{w.w}" for i, w in enumerate(words)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_proofread(path: Path, words: list[Word]) -> tuple[list[Word], list[tuple[int, str, str]]]:
    """Apply the edited file to the recognised words.

    Returns:
        The corrected words and the list of ``(index, before, after)`` changes.

    Raises:
        rp.PlanError: when a line was added, removed, renumbered or holds more than one word
            (phrase replacement is not allowed: the video must not lie).
    """
    rows = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    if len(rows) != len(words):
        raise rp.PlanError(f"proofreading file has {len(rows)} lines, expected {len(words)}: single-word fixes only")
    out: list[Word] = []
    changes: list[tuple[int, str, str]] = []
    for i, (row, w) in enumerate(zip(rows, words)):
        parts = row.split("\t")
        if len(parts) != 3 or int(parts[0]) != i:
            raise rp.PlanError(f"line {i}: bad format or index: {row!r}")
        new = parts[2].strip()
        if not new or re.search(r"\s", new):
            raise rp.PlanError(f"line {i}: «{new}» is not a single word")
        if new != w.w:
            changes.append((i, w.w, new))
        out.append(rp.Word(new, w.start, w.end))
    return out, changes


# ---- grouping ------------------------------------------------------------------------------

def _ends_sentence(token: str) -> bool:
    return token.rstrip("»\"')").endswith((".", "!", "?", "…"))


def build_groups(words: list[Word], plan: Plan, style: CaptionStyle = CaptionStyle()) -> list[Group]:
    """Group the words into accumulating flashes and time them.

    A new group starts when the shot changes, there is a pause longer than ``gap_break``, the previous word ended a
    sentence, or the group already holds ``max_lines`` full lines.
    """
    raw: list[tuple[list[list[Word]], int]] = []      # (lines, shot index)
    cur: list[list[Word]] = []
    cur_shot = -1
    cur_behind = 0
    prev: Word | None = None
    for w in words:
        if any(p.start - rp.PUNCH_ANCHOR_SLACK <= w.start < p.end - PUNCH_EDGE for p in plan.punches):
            continue                                       # the punch word replaces the caption while it is on screen
        shot = plan.shot_index(w.start)
        behind = sum(1 for p in plan.punches if w.start >= p.end - PUNCH_EDGE)     # punch windows already passed: a group never spans one
        new_group = not cur
        if cur:
            gap = w.start - prev.end > style.gap_break if prev else False
            full_line = (len(cur[-1]) >= style.max_words_per_line
                         or len(" ".join(x.w for x in cur[-1] + [w])) > style.max_chars)
            if shot != cur_shot or behind != cur_behind or gap or _ends_sentence(prev.w if prev else "") \
                    or (full_line and len(cur) >= style.max_lines):
                raw.append((cur, cur_shot))
                new_group = True
        if new_group:
            cur, cur_shot, cur_behind = [[w]], shot, behind
        elif len(cur[-1]) < style.max_words_per_line and len(" ".join(x.w for x in cur[-1] + [w])) <= style.max_chars:
            cur[-1].append(w)
        else:
            cur.append([w])
        prev = w
    if cur:
        raw.append((cur, cur_shot))
    return _time(raw, plan, style)


def _time(raw: list[tuple[list[list[Word]], int]], plan: Plan, style: CaptionStyle) -> list[Group]:
    out: list[Group] = []
    for n, (lines, shot_i) in enumerate(raw):
        shot = plan.shots[shot_i]
        first, last = lines[0][0], lines[-1][-1]
        start = max(rp.snap(first.start - style.lead), shot.start)
        end = min(rp.snap(last.end + style.hold), shot.end)
        for p in plan.punches:                 # a group that follows a punch window starts after it (the gap loop below trims the punch's last word)
            if first.start >= p.end - PUNCH_EDGE:
                start = max(start, p.end)
                end = max(end, start + 1 / rp.FPS)
        out.append(Group(f"c{n:03d}", tuple(tuple(line) for line in lines), start, end, shot.type, shot_i))
    if plan.punches:
        out = sorted(out + _punch_groups(plan, style), key=lambda g: g.start)
    for i in range(len(out) - 1):          # two-frame gap before the next group
        a, b = out[i], out[i + 1]
        limit = rp.snap(b.start - TWO_FRAMES)
        if a.end > limit:
            out[i] = replace(a, end=max(limit, a.start + 1 / rp.FPS))
    return out


def _punch_groups(plan: Plan, style: CaptionStyle) -> list[Group]:
    """One one-word group per punch word, shown in turn from the moment it is spoken; the last stays until the end of the window."""
    out: list[Group] = []
    for pi, p in enumerate(plan.punches):
        shot_i = plan.shot_index(p.start)
        shot = plan.shots[shot_i]
        for k, w in enumerate(p.words):
            start = max(rp.snap(w.start - style.lead), p.start, shot.start)
            end = rp.snap(p.words[k + 1].start - style.lead) if k + 1 < len(p.words) else min(p.end, shot.end)
            out.append(Group(f"p{pi}{k}", ((w,),), start, max(end, start + 1 / rp.FPS), shot.type, shot_i, True))
    return out


def check_groups(groups: list[Group], plan: Plan) -> list[str]:
    """Return problems: a group crossing a shot change, more than three words on a line, or groups closer than two frames."""
    problems: list[str] = []
    for g in groups:
        s = plan.shots[g.shot]
        if g.end > s.end + 1e-6 or g.start < s.start - 1e-6:
            problems.append(f"{g.id} «{g.text}» crosses the cut at {s.start}/{s.end}")
        if any(len(line) > 3 for line in g.lines) or len(g.lines) > 2:
            problems.append(f"{g.id} «{g.text}» has more than 3 words on a line or more than 2 lines")
    for a, b in zip(groups, groups[1:]):
        if b.start < a.end + TWO_FRAMES - 1e-3:
            problems.append(f"{a.id}/{b.id} are closer than two frames")
    return problems
