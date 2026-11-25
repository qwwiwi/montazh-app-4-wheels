"""Face boxes of the take over time, from ``head.json`` written by ``measure_head.py``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from geometry import Box


@dataclass(frozen=True)
class FaceTrack:
    """Sampled face and head boxes, source pixels, keyed by time."""

    step: float
    times: tuple[float, ...]
    faces: tuple[Box | None, ...]
    heads: tuple[Box | None, ...]

    def _window(self, boxes: tuple[Box | None, ...], t0: float, t1: float) -> Box | None:
        """Union of the boxes of samples that touch ``[t0, t1]`` (one sample of slack each side)."""
        out: Box | None = None
        for t, b in zip(self.times, boxes):
            if b is None or t + self.step < t0 or t - self.step > t1:
                continue
            out = b if out is None else out.union(b)
        return out

    def face(self, t0: float, t1: float, pad: float = 0.0) -> Box | None:
        """Union of face boxes (brow..chin) in the window, padded."""
        box = self._window(self.faces, t0, t1)
        return box.pad(pad) if box else None

    def head(self, t0: float, t1: float) -> Box | None:
        """Union of whole-head boxes (with hair) in the window."""
        return self._window(self.heads, t0, t1)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def smooth_boxes(boxes: list[Box | None], radius: int) -> list[Box | None]:
    """Rolling per-coordinate median over ``2*radius+1`` samples.

    The Haar detector jitters by tens of pixels from sample to sample (box size changes with no
    real head motion); the median removes that noise but keeps real movement.
    """
    out: list[Box | None] = []
    for i, b in enumerate(boxes):
        if b is None or radius <= 0:
            out.append(b)
            continue
        near = [x for x in boxes[max(0, i - radius): i + radius + 1] if x is not None]
        out.append(Box(_median([x.x0 for x in near]), _median([x.y0 for x in near]),
                       _median([x.x1 for x in near]), _median([x.y1 for x in near])))
    return out


def load_track(path: Path, smooth: int = 1) -> FaceTrack:
    """Load ``head.json``; ``smooth`` is the median radius in samples (0 = raw)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    times: list[float] = []
    faces: list[Box | None] = []
    heads: list[Box | None] = []
    for s in data["samples"]:
        times.append(float(s["t"]))
        faces.append(Box(*s["face"]) if s.get("face") else None)
        heads.append(Box(*s["box"]) if s.get("box") else None)
    return FaceTrack(float(data["step"]), tuple(times), tuple(smooth_boxes(faces, smooth)),
                     tuple(smooth_boxes(heads, smooth)))
