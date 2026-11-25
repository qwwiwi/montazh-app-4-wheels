#!/usr/bin/env python3
"""Measure the head on the actual take.

Samples frames of the frozen cut, detects the face with the OpenCV Haar cascade (BSD) and writes
a per-sample list plus the worst-case head box. The face detector returns brow-to-chin only;
hair and ears are added with ``HAIR_UP`` / ``SIDE`` factors that were calibrated by eye on grid
frames of this take (``--grid`` writes such frames). The result is a starting point: the owner
of the reel confirms it on the grid frame and may overwrite ``head`` in the config.

Everything is in source pixels of the 1080x1920 cut.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

LOG = logging.getLogger("measure_head")

# Haar box (brow..chin-ish) -> whole head: hair above, ears/headphones on the sides.
HAIR_UP = 0.36      # extra height above the Haar top, as a fraction of the Haar height
CHIN_DOWN = 0.06    # Haar boxes stop 20-50 px above the chin tip on this take (checked by eye)
SIDE = 0.08         # extra width on each side, fraction of the Haar width (the box already spans the ears)


@dataclass(frozen=True)
class FaceSample:
    """Head box of one sampled frame (source pixels) or None when no face was found."""

    t: float
    box: tuple[int, int, int, int] | None    # whole head incl. hair, x0 y0 x1 y1
    face: tuple[int, int, int, int] | None = None  # brow..chin, x0 y0 x1 y1 (hard rule: captions stay off it)


def head_from_face(face: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Grow a Haar face box (x, y, w, h) into a head box (x0, y0, x1, y1)."""
    x, y, w, h = face
    return (
        int(round(x - SIDE * w)),
        int(round(y - HAIR_UP * h)),
        int(round(x + w + SIDE * w)),
        int(round(y + h + CHIN_DOWN * h)),
    )


def face_from_haar(face: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Haar face box as x0 y0 x1 y1, lengthened down to the chin tip."""
    x, y, w, h = face
    return (x, y, x + w, int(round(y + h + CHIN_DOWN * h)))


def union_box(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    """Smallest box that holds every given box."""
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


def extract_frame(media: Path, t: float) -> np.ndarray | None:
    """Decode one frame at time ``t`` as a BGR array via ffmpeg (raw pipe)."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(media), "-frames:v", "1",
         "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, check=False,
    )
    if not proc.stdout:
        return None
    return cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)


def detect_face(frame: np.ndarray, cascade: cv2.CascadeClassifier) -> tuple[int, int, int, int] | None:
    """Return the largest frontal face (x, y, w, h) found, or None."""
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=6, minSize=(200, 200))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: int(f[2]) * int(f[3]))
    return int(x), int(y), int(w), int(h)


def make_cascade() -> cv2.CascadeClassifier:
    """Load the frontal-face Haar cascade shipped with OpenCV."""
    path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(path))
    if cascade.empty():
        raise RuntimeError(f"cannot load cascade {path}")
    return cascade


def measure(media: Path, duration: float, step: float) -> list[FaceSample]:
    """Sample the cut every ``step`` seconds and detect the head."""
    cascade = make_cascade()
    samples: list[FaceSample] = []
    t = 0.0
    while t < duration - 0.05:
        frame = extract_frame(media, t)
        box = None
        face_box = None
        if frame is not None:
            face = detect_face(frame, cascade)
            box = head_from_face(face) if face else None
            face_box = face_from_haar(face) if face else None
        samples.append(FaceSample(round(t, 3), box, face_box))
        t += step
    return samples


def write_grid(media: Path, times: list[float], out_dir: Path) -> list[Path]:
    """Write grid frames (a line every 100 source px) to eyeball the measurement."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for t in times:
        p = out_dir / f"grid_{t:06.2f}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(media), "-frames:v", "1",
             "-vf", "scale=540:960,drawgrid=w=50:h=50:t=1:c=red@0.6", str(p)],
            check=True,
        )
        paths.append(p)
    return paths


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("media", type=Path, help="frozen cut")
    ap.add_argument("-o", "--out", type=Path, required=True, help="head.json to write")
    ap.add_argument("--step", type=float, default=0.25, help="sampling step, seconds")
    ap.add_argument("--grid", type=Path, default=None, help="folder for grid frames at the extremes")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(args.media)],
        check=True, capture_output=True, text=True).stdout.strip())
    samples = measure(args.media, duration, args.step)
    found = [s for s in samples if s.box is not None]
    if not found:
        LOG.error("no face found in any sample")
        return 1
    boxes = [s.box for s in found if s.box is not None]
    worst = union_box(boxes)
    chins = sorted(b[3] for b in boxes)
    tops = sorted(b[1] for b in boxes)
    payload = {
        "step": args.step,
        "samples": [
            {"t": s.t, "box": list(s.box) if s.box else None, "face": list(s.face) if s.face else None}
            for s in samples
        ],
        "worst_case": {"left": worst[0], "top": worst[1], "right": worst[2], "chin": worst[3]},
        "percentiles": {
            "top_p5": tops[int(0.05 * (len(tops) - 1))], "top_p50": tops[len(tops) // 2],
            "chin_p50": chins[len(chins) // 2], "chin_p95": chins[int(0.95 * (len(chins) - 1))],
        },
        "missed": len(samples) - len(found),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    LOG.info("worst case: %s; percentiles: %s; %d of %d samples without a face",
             payload["worst_case"], payload["percentiles"], payload["missed"], len(samples))
    if args.grid:
        lowest = max(found, key=lambda s: s.box[3] if s.box else 0)
        highest = min(found, key=lambda s: s.box[1] if s.box else 1e9)
        write_grid(args.media, sorted({lowest.t, highest.t}), args.grid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
