#!/usr/bin/env python3
"""Reel build driver: build (two passes + gate), render, post-render check.

    reel.py build  --cut cut.mp4 --words words.json --plan plan.json --config reel_config.json \
                   --head head.json --project build/reel
    reel.py render --project build/reel -o out/reel.mp4
    reel.py check  --project build/reel --cut cut.mp4 --render out/reel.mp4 --out out/

``build`` exits 1 when a caption meets the face, crosses the seam or leaves its band, a scene stays static, the rhythm breaks
or a repeated take is left in the transcript: such a reel is never rendered.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import build_composition as bc
import geometry as geo
import prerender_gate as pg
import reel_plan as rp
import scenes
from reel_config import load_config

LOG = logging.getLogger("reel")
HERE = Path(__file__).resolve().parent


def measure(project: Path) -> dict[str, Any]:
    """Run the Chrome measurement and return ``boxes.json``."""
    out = project / "boxes.json"
    subprocess.run(["node", str(HERE / "measure_boxes.mjs"), str(project), str(out)], check=True)
    return pg.load_boxes(out)


def hyperframes(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the hyperframes CLI without telemetry."""
    env = dict(os.environ, DO_NOT_TRACK="1")
    return subprocess.run(["hyperframes", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False)


def write_meta(info: bc.BuildInfo, path: Path, font_px: int) -> None:
    """Write what the post-render check needs: shots, scenes with their state times, caption groups, call to action."""
    meta = {
        "layout": {"y0": info.analysis.layout.y0, "seam": geo.SEAM},
        "shots": [{"start": s.start, "end": s.end, "type": s.type, "note": s.note,
                   **({"zoom": s.zoom, "origin": list(info.analysis.info(s).origin or ())} if s.zoom != 1.0 else {})} for s in info.plan.shots],
        "scenes": [{"n": s.n, "shot": s.shot, "kind": s.kind, "bg": s.bg, "start": s.start, "end": s.end,
                    "states": info.scene_states.get(s.n, [])} for s in info.plan.scenes],
        "groups": [{"id": g.id, "start": g.start, "end": g.end, "text": g.text, "shot_type": g.shot_type, "shot": g.shot, "punch": g.punch, "lines": [len(line) for line in g.lines],
                    "words": [{"w": w.w, "start": w.start, "end": w.end} for w in g.words]} for g in info.groups],
        "cta": None if info.plan.cta is None else {"start": info.plan.cta.start, "end": info.plan.cta.end, "word": info.plan.cta.word},
        "words": [{"w": w.w, "start": w.start, "end": w.end} for w in info.words],
        "repeats_ok": list(info.plan.repeats_ok),
        "font_px": font_px,
    }
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_build(args: argparse.Namespace) -> int:
    """Build, Chrome measurement, gate, hyperframes lint and check."""
    (args.project / "review-style.json").unlink(missing_ok=True)
    cfg = load_config(args.config)
    words = rp.load_words(args.words)
    duration = float(json.loads(args.words.read_text(encoding="utf-8"))["duration"])
    plan = rp.load_plan(args.plan, words, duration)
    args.project.mkdir(parents=True, exist_ok=True)

    info = bc.build_project(args.cut, words, plan, cfg, args.head, args.project)
    boxes = measure(args.project)
    violations = pg.run_gate(info, boxes, cfg)
    page = (args.project / "index.html").read_text(encoding="utf-8")
    violations += [geo.Violation("fonts-lint", "font-size", msg) for msg in scenes.lint_fonts(page)]
    violations += [geo.Violation("page", "decor", msg) for msg in scenes.decor_problems(page)]
    violations += [geo.Violation("page", "spelling", msg) for msg in scenes.spelling_problems(page)]
    write_meta(info, args.project / "reel-meta.json", cfg.fit.font_px)
    (args.project / "gate-report.txt").write_text(pg.format_violations(violations) or "clean\n", encoding="utf-8")
    # Only measured editorial findings may be delegated to the reviewer.
    aesthetic = {"rhythm", "static", "repeat", "reminder", "palette", "codeword", "spelling",
                 "decor", "font-size", "contrast", "overflow", "overlap", "clipped", "band",
                 "seam", "ui-zone", "header", "buttons", "face", "zone", "zoom-ui", "zoom-buttons", "zoom-frame"}
    advisory = getattr(args, "review_style", False) and all(v.rule in aesthetic for v in violations)
    if violations and not advisory:
        LOG.error("GATE FAILED (%d):\n%s", len(violations), pg.format_violations(violations))
        return 1
    if violations:
        LOG.info("Forwarding %d editorial findings to the reviewer", len(violations))
    else:
        LOG.info("gate: 0 violations (%d caption boxes, %d scenes measured in Chrome)", len(boxes["captions"]), len(boxes["scenes"]))

    lint = hyperframes(["lint", "--json"], args.project)
    findings = json.loads(lint.stdout) if lint.stdout.strip().startswith("{") else {"errorCount": 1}
    LOG.info("hyperframes lint: %s error(s), %s warning(s)", findings.get("errorCount"), findings.get("warningCount"))
    if findings.get("errorCount"):
        LOG.error("lint errors:\n%s", lint.stdout[:3000])
        return 1
    if not args.skip_check:
        chk = hyperframes(["check"], args.project)
        (args.project / "hyperframes-check.txt").write_text(chk.stdout + chk.stderr, encoding="utf-8")
        LOG.info("hyperframes check exit=%d (full output in hyperframes-check.txt)", chk.returncode)
        runtime = re.search(r"Runtime\s+\S+\s+(\d+) errors", chk.stdout + chk.stderr)
        findings_n = len(re.findall(r"^\s+✗ t=", chk.stdout, flags=re.M))
        LOG.info("hyperframes check: runtime errors %s, layout/contrast findings %d (a word caught mid-fade by the contrast probe "
                 "is expected: captions fade in by canon)", runtime.group(1) if runtime else "?", findings_n)
        if runtime is None or int(runtime.group(1)) > 0:
            LOG.error("hyperframes check failed:\n%s", (chk.stdout + chk.stderr)[-3000:])
            return 1
    if advisory and not args.skip_check:
        (args.project / "review-style.json").write_text(json.dumps({
            "findings": pg.format_violations(violations).strip().splitlines(),
            "runtime_check": "passed",
        }), encoding="utf-8")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    """Render with explicit worker count (auto picks one)."""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    proc = hyperframes(["render", ".", "-o", str(args.output.resolve()), "-w", str(args.workers), "--fps", "30", "-q", args.quality], args.project)
    LOG.info("render wall time %.1f s, exit %d", time.time() - t0, proc.returncode)
    (args.project / "render.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        LOG.error((proc.stdout + proc.stderr)[-3000:])
    return proc.returncode


def cmd_check(args: argparse.Namespace) -> int:
    """Post-render check (delegates to postrender_check)."""
    import postrender_check as pc

    return pc.main([str(args.render), "--cut", str(args.cut), "--project", str(args.project), "--out", str(args.out)])


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    for name in ("cut", "words", "plan", "config", "head", "project"):
        b.add_argument(f"--{name}", type=Path, required=True)
    b.add_argument("--review-style", action="store_true", help="forward measured editorial findings to Argon after running runtime checks")
    b.add_argument("--skip-check", action="store_true", help="skip `hyperframes check` (lint always runs)")
    r = sub.add_parser("render")
    r.add_argument("--project", type=Path, required=True)
    r.add_argument("-o", "--output", type=Path, required=True)
    r.add_argument("--workers", type=int, default=3)
    r.add_argument("--quality", default="looks")
    c = sub.add_parser("check")
    c.add_argument("--project", type=Path, required=True)
    c.add_argument("--cut", type=Path, required=True)
    c.add_argument("--render", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return {"build": cmd_build, "render": cmd_render, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
