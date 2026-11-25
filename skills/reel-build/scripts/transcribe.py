#!/usr/bin/env python3
"""Re-recognise the frozen cut and write word timings to JSON.

The words feed the caption groups and every plan anchor, so they must come from the frozen
cut itself (never from the raw take): all times are in cut seconds.

Engine: faster-whisper (MIT, local, no key). The model weights are downloaded once into
``HF_HOME`` (set it to a project-local folder). Rules taken from montage-pipeline:

* a word that starts after the end of the file is dropped before anything else;
* order is kept exactly as the recogniser returned it (timestamps can be non-monotonic).
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

LOG = logging.getLogger("transcribe")
DEFAULT_MODEL = "large-v3-turbo"


@dataclass(frozen=True)
class Word:
    """One recognised word, times in seconds of the recognised file."""

    w: str
    start: float
    end: float


def probe_duration(path: Path) -> float:
    """Return the media duration in seconds via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def drop_words_past_end(words: list[Word], duration: float) -> tuple[list[Word], int]:
    """Drop words that start at or after the end of the file (recogniser hallucinations).

    Args:
        words: Words in recogniser order.
        duration: Length of the recognised file in seconds.

    Returns:
        The kept words (order preserved) and how many were dropped.
    """
    kept = [w for w in words if w.start < duration]
    return kept, len(words) - len(kept)


def clamp_ends(words: list[Word], duration: float) -> list[Word]:
    """Make sure no word ends after the file or before its own start."""
    fixed: list[Word] = []
    for w in words:
        end = min(max(w.end, w.start), duration)
        fixed.append(Word(w.w, round(w.start, 3), round(end, 3)))
    return fixed


def load_wav(path: Path) -> "np.ndarray":
    """Read a 16 kHz mono PCM wav as float32 (avoids the PyAV decode path of faster-whisper)."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as fh:
        raw = fh.readframes(fh.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def recognise(media: Path, model_name: str, language: str) -> tuple[list[Word], str]:
    """Run faster-whisper on the media file; return words and the engine label."""
    from faster_whisper import WhisperModel  # heavy import, keep it lazy

    wav = media.with_suffix(".rec16k.wav")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(wav)],
        check=True,
    )
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        load_wav(wav), language=language, word_timestamps=True, vad_filter=False,
        condition_on_previous_text=False, beam_size=5,
    )
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(text, float(w.start), float(w.end)))
    wav.unlink(missing_ok=True)
    return words, f"faster-whisper {model_name} (cpu, int8)"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("media", type=Path, help="frozen cut (mp4)")
    ap.add_argument("-o", "--out", type=Path, required=True, help="words JSON to write")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--language", default="ru")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    duration = probe_duration(args.media)
    words, engine = recognise(args.media, args.model, args.language)
    words, dropped = drop_words_past_end(words, duration)
    if dropped:
        LOG.warning("dropped %d word(s) that start after the end of the file", dropped)
    words = clamp_ends(words, duration)
    payload = {
        "recogniser": engine,
        "duration": duration,
        "dropped_past_end": dropped,
        "words": [asdict(w) for w in words],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    LOG.info("%d words -> %s (%s)", len(words), args.out, engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
