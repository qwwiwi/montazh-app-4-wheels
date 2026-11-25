#!/usr/bin/env python3
"""Re-cut the raw recording from a list of kept source ranges (one take per thought).

The agent reads the recognised text of the raw take, decides which takes stay (default: the last complete
one; false starts and slips go) and writes ``keep.json``::

    {"keep": [[0.96, 4.80], [6.55, 15.58]], "max_pause": 0.30, "keep_pause": 0.22, "snap": 0.04}

* every boundary is moved to the quietest 10 ms window within ``snap`` seconds, so a cut never lands inside a word;
* a silence longer than ``max_pause`` inside a kept range is shortened to ``keep_pause`` (pauses go, rhythm stays);
* 8 ms audio fades at every join remove clicks.

Outputs the cut MP4 (h264 1080x1920 30 fps + AAC) and ``<out>.map.json`` with the source range of every piece in
cut time, so that removed takes can be reported with source times and words can be mapped back.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

LOG = logging.getLogger("cut_takes")
SR = 16000
FRAME = SR // 100          # 10 ms analysis windows
FADE = 0.008


@dataclass(frozen=True)
class Piece:
    """One kept source range and where it lands in the cut."""

    src_start: float
    src_end: float
    cut_start: float

    @property
    def cut_end(self) -> float:
        """End in cut time."""
        return self.cut_start + (self.src_end - self.src_start)


def decode_mono(path: Path) -> np.ndarray:
    """Decode the audio track to float32 mono 16 kHz."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def frame_rms(samples: np.ndarray) -> np.ndarray:
    """RMS per 10 ms window."""
    n = len(samples) // FRAME
    return np.sqrt((samples[: n * FRAME].reshape(n, FRAME) ** 2).mean(axis=1) + 1e-12)


def snap_quiet(rms: np.ndarray, t: float, radius: float) -> float:
    """Move ``t`` to the centre of the quietest window within ``radius`` seconds (nearest on ties)."""
    lo = max(0, int((t - radius) * 100))
    hi = min(len(rms), int((t + radius) * 100) + 1)
    if hi <= lo:
        return t
    seg = rms[lo:hi]
    best = [i for i, v in enumerate(seg) if v <= seg.min() * 1.0001]
    idx = min(best, key=lambda i: abs((lo + i) / 100 + 0.005 - t))
    return round((lo + idx) / 100 + 0.005, 3)


def tighten_pauses(ranges: list[tuple[float, float]], rms: np.ndarray, max_pause: float, keep_pause: float,
                   floor_db: float = -38.0) -> list[tuple[float, float]]:
    """Split ranges at silences longer than ``max_pause`` and leave ``keep_pause`` of each."""
    thr = 10 ** (floor_db / 20)
    quiet = rms < thr
    out: list[tuple[float, float]] = []
    half = keep_pause / 2
    for a, b in ranges:
        i0, i1 = int(a * 100), min(int(b * 100), len(quiet))
        cur = a
        i = i0
        while i < i1:
            if not quiet[i]:
                i += 1
                continue
            j = i
            while j < i1 and quiet[j]:
                j += 1
            if (j - i) / 100 > max_pause and i > i0 and j < i1:
                out.append((cur, round(i / 100 + half, 3)))
                cur = round(j / 100 - half, 3)
            i = j
        out.append((cur, b))
    return out


def plan_pieces(spec: dict, rms: np.ndarray) -> list[Piece]:
    """Resolve ``keep.json`` into pieces: snap boundaries, merge touching ranges, tighten pauses."""
    snap = float(spec.get("snap", 0.04))
    ranges = [(snap_quiet(rms, float(a), snap), snap_quiet(rms, float(b), snap)) for a, b in spec["keep"]]
    for a, b in ranges:
        if b <= a:
            raise ValueError(f"empty range after snapping: {a}..{b}")
    ranges = tighten_pauses(ranges, rms, float(spec.get("max_pause", 0.30)), float(spec.get("keep_pause", 0.22)))
    pieces: list[Piece] = []
    t = 0.0
    for a, b in ranges:
        pieces.append(Piece(a, b, round(t, 3)))
        t += b - a
    return pieces


def render(source: Path, pieces: list[Piece], out: Path) -> None:
    """Concatenate the pieces with ffmpeg (video re-encoded, audio faded at joins)."""
    parts: list[str] = []
    for i, p in enumerate(pieces):
        d = p.src_end - p.src_start
        parts.append(f"[0:v]trim={p.src_start:.3f}:{p.src_end:.3f},setpts=PTS-STARTPTS,fps=30[v{i}]")
        parts.append(f"[0:a]atrim={p.src_start:.3f}:{p.src_end:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={FADE},afade=t=out:st={d - FADE:.3f}:d={FADE}[a{i}]")
    n = len(pieces)
    joined = "".join(f"[v{i}][a{i}]" for i in range(n))
    parts.append(f"{joined}concat=n={n}:v=1:a=1[v][a]")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(out)], check=True)


def removed_ranges(pieces: list[Piece], duration: float) -> list[tuple[float, float]]:
    """Source ranges that are NOT in the cut (gaps between pieces, plus head and tail)."""
    gaps: list[tuple[float, float]] = []
    prev = 0.0
    for p in pieces:
        if p.src_start - prev > 0.02:
            gaps.append((round(prev, 3), round(p.src_start, 3)))
        prev = p.src_end
    if duration - prev > 0.02:
        gaps.append((round(prev, 3), round(duration, 3)))
    return gaps


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("--keep", type=Path, required=True, help="keep.json")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    spec = json.loads(args.keep.read_text(encoding="utf-8"))
    rms = frame_rms(decode_mono(args.source))
    pieces = plan_pieces(spec, rms)
    render(args.source, pieces, args.out)
    duration = len(rms) / 100
    mapping = {
        "source_duration": duration,
        "cut_duration": round(pieces[-1].cut_end, 3),
        "pieces": [{"src": [p.src_start, p.src_end], "cut": [p.cut_start, round(p.cut_end, 3)]} for p in pieces],
        "removed": [list(r) for r in removed_ranges(pieces, duration)],
    }
    args.out.with_suffix(".map.json").write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    LOG.info("cut %s: %d pieces, %.2f s of %.2f s", args.out, len(pieces), mapping["cut_duration"], duration)
    for a, b in mapping["removed"]:
        LOG.info("  removed source %.2f..%.2f", a, b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
