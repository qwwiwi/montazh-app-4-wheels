"""Encode a reel at delivery tempo with pitch-preserving speech."""
import json
from pathlib import Path
import subprocess
import tempfile

DEFAULT_SPEED = 1.3


def check_speed(speed):
    try:
        value = float(speed)
    except (ValueError, TypeError):
        value = None
    if value not in (1.3, 1.4):
        raise ValueError("Допустимая скорость — ×1,3 или ×1,4.")
    return value


def accelerate(src, dst, speed=DEFAULT_SPEED):
    src, dst = Path(src).resolve(), Path(dst).resolve()
    speed = check_speed(speed)
    if src == dst or dst.exists():
        raise ValueError("Для ускоренной версии нужен отдельный файл.")
    probe = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(src)])
    data = json.loads(probe)
    has_audio = any(s['codec_type'] == 'audio' for s in data['streams'])
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dst.parent) as temp:
        out = Path(temp)/"pace.mp4"
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(src),
               "-map", "0:v:0", "-vf", f"settb=AVTB,setpts=(PTS-STARTPTS)/{speed},fps=30",
               "-c:v", "libx264", "-threads:v", "4", "-preset", "veryfast", "-crf", "18", "-pix_fmt","yuv420p"]
        if has_audio:
            cmd += ["-map","0:a:0","-af",f"asetpts=PTS-STARTPTS,atempo={speed}","-c:a","aac","-b:a","192k"]
        subprocess.run([*cmd,"-map_metadata","-1","-movflags","+faststart",str(out)],check=True,timeout=2400)
        actual = json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-of","json",str(out)]))
        target = float(data['format']['duration'])/speed
        durations = [float(s["duration"]) for s in actual["streams"] if s['codec_type'] in ('audio','video')]
        if len(durations) != 1+int(has_audio) or any(abs(d-target)>.09 for d in durations):
            raise ValueError("Проверка длительности ускоренного ролика не прошла.")
        out.replace(dst)
