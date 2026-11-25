#!/usr/bin/env python3
"""Proofreading step: recognised words -> editable text file -> corrected words.

    proofread.py init  words.raw.json proofread.txt        # write the file to edit
    proofread.py apply words.raw.json proofread.txt words.json [--diff changes.md]

Only single-word fixes are accepted («код» -> «Claude»); adding, removing or merging lines is
refused. The recogniser's timings are kept untouched.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import reel_captions as rc
import reel_plan as rp

LOG = logging.getLogger("proofread")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init")
    init.add_argument("words", type=Path)
    init.add_argument("proofread", type=Path)
    apply = sub.add_parser("apply")
    apply.add_argument("words", type=Path)
    apply.add_argument("proofread", type=Path)
    apply.add_argument("out", type=Path)
    apply.add_argument("--diff", type=Path, default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    words = rp.load_words(args.words)
    if args.cmd == "init":
        rc.write_proofread(words, args.proofread)
        LOG.info("wrote %s (%d words)", args.proofread, len(words))
        return 0

    fixed, changes = rc.read_proofread(args.proofread, words)
    raw = json.loads(args.words.read_text(encoding="utf-8"))
    raw["words"] = [asdict(w) for w in fixed]
    raw["proofread_changes"] = len(changes)
    args.out.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.diff:
        lines = ["# Proofreading changes (single words)", ""] + [
            f"- word {i} ({words[i].start:.2f} s): «{a}» -> «{b}»" for i, a, b in changes]
        args.diff.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOG.info("%d single-word fixes applied -> %s", len(changes), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
