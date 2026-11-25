#!/usr/bin/env python3
"""Duplicate-take detector over the transcript of a cut.

The detector compares nearby normalized word sequences. Three complementary checks flag repeats:

* ``sentence`` – two sentences within the window share most of their content words (shorter one: >= 60 %, at least 3);
* ``ngram`` – the same run of >= 3 words (>= 2 of them content words) twice within the window;
* ``echo`` – a sentence opens with a word (>= 4 letters) that the previous sentence ended with, the restart slip
  «…море кода. Поэтому оказалось…».

A deliberate repeat is explained in the plan (``repeats_ok``: phrases); anything else is a failure.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from reel_plan import Word, load_words

STOP = frozenset("""
я ты он она оно мы вы они мне тебе ему ей нам вам им меня тебя его ее их себя мой твой свой наш ваш
и а но да или либо что чтобы как так то это эти этот эта этого тот те там тут здесь вот же ли бы не ни
в во на с со к ко по о об от до из за для при про без над под между у я
когда если потому поэтому тоже еще уже все всё вся весь только очень просто буквально можно нужно
был была было были есть будет быть
""".split())
SENTENCE_END = (".", "?", "!", "…")
PAUSE_BREAK = 0.6          # a silence this long also ends a sentence when the recogniser gave no punctuation
MIN_NGRAM = 3
SENTENCE_OVERLAP = 0.6
ECHO_LOOKBACK = 8


@dataclass(frozen=True)
class Repeat:
    """One repeated stretch: what was said first, what again, and where."""

    kind: str
    first: str
    second: str
    t_first: float
    t_second: float


def norm(token: str) -> str:
    """Lower-case letters and digits only, ё -> е."""
    return "".join(re.findall(r"[0-9a-zа-я]+", token.lower().replace("ё", "е")))


def is_content(token: str) -> bool:
    """A word that carries meaning: not a stop word, at least three characters (digits count)."""
    return token not in STOP and (len(token) >= 3 or token.isdigit())


def same_word(a: str, b: str) -> bool:
    """Fuzzy word equality: equal, a shared stem of >= 4 letters (endings differ), or a close spelling."""
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    stem = 0
    for x, y in zip(a, b):
        if x != y:
            break
        stem += 1
    if stem >= max(4, int(0.7 * min(len(a), len(b)))):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def _sentences(words: list[Word]) -> list[list[int]]:
    """Split word indices into sentences by end punctuation or a long pause."""
    out: list[list[int]] = [[]]
    for i, w in enumerate(words):
        out[-1].append(i)
        last = i + 1 == len(words)
        ends = w.w.rstrip("»\"')").endswith(SENTENCE_END)
        pause = not last and words[i + 1].start - w.end > PAUSE_BREAK
        if (ends or pause) and not last:
            out.append([])
    return [s for s in out if s]


def _text(words: list[Word], idx: list[int]) -> str:
    return " ".join(words[i].w for i in idx)


def _sentence_repeats(words: list[Word], toks: list[str], window_s: float) -> list[tuple[Repeat, set[int]]]:
    sents = _sentences(words)
    found: list[tuple[Repeat, set[int]]] = []
    for a in range(len(sents)):
        for b in range(a + 1, min(len(sents), a + 7)):
            sa, sb = sents[a], sents[b]
            if words[sb[0]].start - words[sa[0]].start > window_s:
                break
            ca = [toks[i] for i in sa if is_content(toks[i])]
            cb = [toks[i] for i in sb if is_content(toks[i])]
            short, long_ = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
            if len(short) < 3:
                continue
            hits = sum(1 for t in short if any(same_word(t, u) for u in long_))
            if hits >= 3 and hits / len(short) >= SENTENCE_OVERLAP:
                found.append((Repeat("sentence", _text(words, sa), _text(words, sb), words[sa[0]].start, words[sb[0]].start),
                              set(sa) | set(sb)))
    return found


def _echo_repeats(words: list[Word], toks: list[str]) -> list[Repeat]:
    sents = _sentences(words)
    found: list[Repeat] = []
    for prev, cur in zip(sents, sents[1:]):
        head = toks[cur[0]]
        if len(head) < 4:
            continue
        tail = prev[-ECHO_LOOKBACK:]
        for i in tail:
            if same_word(head, toks[i]) and i != cur[0]:
                found.append(Repeat("echo", _text(words, prev[-ECHO_LOOKBACK:]), _text(words, cur[:ECHO_LOOKBACK]),
                                    words[i].start, words[cur[0]].start))
                break
    return found


def _ngram_repeats(words: list[Word], toks: list[str], window_s: float, covered: set[int]) -> list[Repeat]:
    n = len(words)
    seen: set[tuple[int, int]] = set()
    matches: list[tuple[int, int]] = []           # (i, j) start indices of equal n-grams
    for i in range(n - MIN_NGRAM + 1):
        gi = toks[i:i + MIN_NGRAM]
        if sum(1 for t in gi if is_content(t)) < 2:
            continue
        for j in range(i + MIN_NGRAM, n - MIN_NGRAM + 1):
            if words[j].start - words[i].start > window_s:
                break
            if all(same_word(a, b) for a, b in zip(gi, toks[j:j + MIN_NGRAM])):
                matches.append((i, j))
    found: list[Repeat] = []
    for i, j in matches:
        if (i, j) in seen:
            continue
        length = MIN_NGRAM                         # extend the run while the next words match too
        seen.add((i, j))
        while (i + 1, j + 1) in set(matches):
            i, j = i + 1, j + 1
            seen.add((i, j))
            length += 1
        i0, j0 = i - (length - MIN_NGRAM), j - (length - MIN_NGRAM)
        if all(k in covered for k in (*range(i0, i0 + length), *range(j0, j0 + length))):
            continue                               # already reported as a repeated sentence
        found.append(Repeat("ngram", _text(words, list(range(i0, i0 + length))), _text(words, list(range(j0, j0 + length))),
                            words[i0].start, words[j0].start))
    return found


def find_repeats(words: list[Word], window_s: float = 25.0) -> list[Repeat]:
    """Every repeated stretch of the transcript (see the module docstring), sorted by time."""
    toks = [norm(w.w) for w in words]
    sentence = _sentence_repeats(words, toks, window_s)
    covered: set[int] = set().union(*(s for _, s in sentence)) if sentence else set()
    found = [r for r, _ in sentence] + _echo_repeats(words, toks) + _ngram_repeats(words, toks, window_s, covered)
    return sorted(found, key=lambda r: (r.t_second, r.kind))


def unexplained(found: list[Repeat], allow: list[str] | tuple[str, ...] = ()) -> list[Repeat]:
    """Drop repeats that the plan explains (``repeats_ok``: a phrase contained in either side)."""
    keys = [" ".join(norm(t) for t in a.split()) for a in allow]

    def explained(r: Repeat) -> bool:
        sides = [" ".join(norm(t) for t in s.split()) for s in (r.first, r.second)]
        return any(k and k in s for k in keys for s in sides)

    return [r for r in found if not explained(r)]


def format_repeats(found: list[Repeat]) -> str:
    """One line per repeat: kind, both stretches with their times."""
    return "\n".join(f"  [{r.kind}] «{r.first}» ({r.t_first:.1f} s) ~ «{r.second}» ({r.t_second:.1f} s)" for r in found)


def check_takes(words: list[Word], allow: list[str] | tuple[str, ...] = (), window_s: float = 25.0) -> list[str]:
    """Gate/post-check entry: failure messages, empty when the transcript has no unexplained repeat."""
    return [f"repeated take [{r.kind}]: «{r.first}» ({r.t_first:.1f} s) ~ «{r.second}» ({r.t_second:.1f} s)"
            for r in unexplained(find_repeats(words, window_s), allow)]


def main(argv: list[str] | None = None) -> int:
    """CLI: ``takes.py words.json [--allow phrase ...]``; exit 1 while an unexplained repeat remains."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", type=Path)
    ap.add_argument("--allow", action="append", default=[], help="phrase of a deliberate repeat (repeatable)")
    ap.add_argument("--window", type=float, default=25.0)
    args = ap.parse_args(argv)
    problems = check_takes(load_words(args.words), args.allow, args.window)
    print("\n".join(problems) if problems else json.dumps({"repeats": 0}))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
