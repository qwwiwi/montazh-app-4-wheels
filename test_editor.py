from pathlib import Path
import subprocess
import tempfile
import unittest

from editor import edit, metadata, removal_windows


class EditorTests(unittest.TestCase):
    def test_full_silence_keeps_video(self):
        self.assertEqual(removal_windows("silence_start: 0\nsilence_end: 6", 6), [])

    def test_gap_keeps_breath(self):
        self.assertEqual(removal_windows("silence_start: 1\nsilence_end: 3", 5),
                         [(34, 86)])

    def test_vertical_encode_and_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = (Path(temp)/n for n in ["input.mp4","result.mp4"])
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=320x180:duration=4:rate=24", "-f", "lavfi", "-i",
                            "aevalsrc=if(between(t\\,1\\,3)\\,0\\,0.3*sin(880*PI*t)):d=4",
                            "-c:v", "libx264","-c:a","aac","-shortest",str(source)], check=True)
            result = edit(source, target, lambda _: None)
            self.assertEqual(result["cuts"], 1)
            self.assertEqual(result["playback_speed"], 1.3)
            self.assertAlmostEqual(result["output_seconds"], (4 - 52/30)/1.3, delta=.08)
            video, audio, _ = metadata(target)
            self.assertEqual(video['avg_frame_rate'], '30/1')
            self.assertLess(abs(float(audio['duration'])-float(video['duration'])), .05)
            self.assertTrue(target.is_file())

    def test_silent_input_supports_alternative_14_tempo(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = (Path(temp)/n for n in ["input.mp4", "result.mp4"])
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",
                            "color=size=180x320:duration=2.8:rate=30","-c:v","libx264",str(source)],check=True)
            result = edit(source, target, lambda _: None, speed=1.4)
            self.assertEqual(result["playback_speed"], 1.4)
            _, audio, duration = metadata(target)
            self.assertIsNone(audio)
            self.assertAlmostEqual(duration, 2, delta=.04)
