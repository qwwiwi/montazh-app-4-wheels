"""Offline rough cut for the local upload demo (FFmpeg and FFprobe only)."""
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile

from pace import DEFAULT_SPEED, check_speed

FPS = 30
MAX_DURATION = 20 * 60
# Restrict both parsers to self-contained video containers.
INPUT = ["-protocol_whitelist", "file", "-format_whitelist",
         "mov,matroska,webm,avi,flv,mpegts,mpeg"]
# Hold a natural breath between phrases as in reel-build's cut_takes.py.
HOLD = 0.22
EVENT = re.compile(r"silence_(start|end):\s*(-?[0-9.]+)")


def run(args, description, timeout):
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                errors="replace", timeout=timeout, check=False)
    except FileNotFoundError:
        raise ValueError("Для монтажа нужны FFmpeg и FFprobe.") from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"{description}: превышено время обработки.") from None
    if result.returncode:
        raise ValueError(f"{description}: проверьте формат и целостность видео.")
    return result


def metadata(path):
    parsed = json.loads(run(["ffprobe", "-v", "error", *INPUT, "-show_streams",
                             "-show_format", "-of", "json", str(path)],
                            "Чтение видео", 30).stdout)
    streams = parsed.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if not video or not int(video.get("width", 0)) or not int(video.get("height", 0)):
        raise ValueError("В файле не найдена видеодорожка.")
    duration = float(video.get("duration") or parsed["format"].get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_DURATION:
        raise ValueError("Поддерживаются видео длительностью до 20 минут.")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return video, audio, duration


def removal_windows(log, duration):
    """Frame-aligned half-open intervals removed from both streams."""
    windows = []
    start = None
    events = EVENT.findall(log) + [("end", str(duration))]
    for name, value in events:
        if name == "start":
            start = max(0.0, float(value))
        elif start is not None:
            end = min(duration, float(value))
            if end - start >= 0.60:
                left = math.ceil((start + HOLD / 2) * FPS)
                right = math.floor((end - HOLD / 2) * FPS)
                if right > left:
                    windows.append((left, right))
            start = None
    if sum(b - a for a, b in windows) / FPS > duration - 0.35:
        return []
    return windows


def edit(src: Path, dst: Path, progress, *, speed=DEFAULT_SPEED) -> dict:
    speed = check_speed(speed)
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst:
        raise ValueError("Исходный и готовый файл должны различаться.")
    progress("Проверяем видео")
    video, audio, duration = metadata(src)
    windows = []
    if audio:
        progress("Находим длинные паузы")
        detection = run(["ffmpeg", "-nostdin", "-hide_banner", "-nostats", *INPUT,
                         "-i", str(src), "-map", f"0:{audio['index']}", "-af",
                         "aresample=48000:async=1:first_pts=0,silencedetect=noise=-40dB:d=0.60",
                         "-f", "null", "-"], "Анализ звука", 300)
        windows = removal_windows(detection.stderr, duration)
    # Convert both streams to identical 1/30-second units before cutting. This
    # keeps audio and video aligned across many cuts, including VFR input.
    exclude = "+".join(f"between(n,{a},{b-1})" for a,b in windows)
    select = f"select='not({exclude})'," if exclude else ""
    vfilter = (f"fps=fps={FPS}:start_time=0,{select}settb=AVTB,setpts=N/({FPS}*{speed}*TB),fps={FPS},"
               "scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1,"
               "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1")
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", *INPUT, "-i", str(src),
            "-map", f"0:{video['index']}", "-vf", vfilter, "-c:v", "libx264",
            "-threads:v", "3", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"]
    if audio:
        aselect = f"aselect='not({exclude})'," if exclude else ""
        afilter = ("aresample=48000:async=1:first_pts=0,apad,"
                   f"atrim=duration={duration:.6f},asetnsamples=n=1600:p=1,"
                   f"{aselect}asetpts=N/SR/TB,atempo={speed}")
        args += ["-map", f"0:{audio['index']}", "-af", afilter, "-c:a", "aac",
                 "-b:a", "144k", "-ac", "2", "-shortest"]
    args += ["-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart"]
    progress(f"Собираем вертикальный MP4 · скорость ×{speed:g}")
    dst.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(dir=dst.parent) as scratch:
        output = Path(scratch) / "result.mp4"
        run([*args, str(output)], "Монтаж", 2400)
        progress("Проверяем результат")
        final_video, final_audio, rendered = metadata(output)
        expected = (duration - sum(b-a for a,b in windows) / FPS) / speed
        if (final_video["codec_name"] != "h264" or final_video["width"] != 720
                or final_video["height"] != 1280 or (audio and not final_audio)
                or abs(rendered - expected) > max(.25, duration * .001)):
            raise ValueError("Результат не прошёл проверку дорожек или длительности.")
        output.replace(dst)
    return {"original_seconds": round(duration, 2), "output_seconds": round(rendered, 2),
            "removed_seconds": round(max(0, duration-rendered), 2), "cuts": len(windows),
            "playback_speed": speed, "mode": "Локальный монтаж по паузам"}
