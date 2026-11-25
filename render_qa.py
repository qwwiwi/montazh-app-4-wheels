"""Run the configured reel skill's QA with face samples limited to decoded video time."""
from pathlib import Path
import sys


def valid_offsets(t, duration, fps, offsets):
    last_frame=max(0.0,duration-1/fps)
    return tuple(dt for dt in offsets if 0<=t+dt<=last_frame+1e-7)


def main():
    scripts, rendered, *args=sys.argv[1:]
    sys.path.insert(0,scripts)
    import postrender_check as qa
    original=qa.detect_face_screen
    duration=qa.probe(Path(rendered))['video']

    def within_video(path,t,top,cascade,pad):
        offsets=qa.JITTER_OFFSETS
        try:
            qa.JITTER_OFFSETS=valid_offsets(t,duration,qa.FPS,offsets)
            return original(path,t,top,cascade,pad)
        finally:
            qa.JITTER_OFFSETS=offsets

    qa.detect_face_screen=within_video
    return qa.main([rendered,*args])


if __name__=='__main__':
    raise SystemExit(main())
