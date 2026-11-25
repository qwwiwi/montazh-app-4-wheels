from array import array
from pathlib import Path
import subprocess
import tempfile
import unittest

from pace import accelerate, check_speed


class PaceTests(unittest.TestCase):
    def test_speech_pitch_is_preserved_at_default_speed(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = (Path(tmp)/name for name in ('src.mp4','dst.mp4'))
            subprocess.run(['ffmpeg','-loglevel','error','-f','lavfi','-i','color=s=64x64:r=30:d=2.6',
                            '-f','lavfi','-i','sine=frequency=440:duration=2.6','-c:v','libx264',
                            '-c:a','aac','-shortest',str(src)],check=True)
            accelerate(src,dst)
            samples = array('h',subprocess.check_output(['ffmpeg','-v','error','-i',str(dst),'-map','0:a:0',
                                '-ar','16000','-ac','1','-f','s16le','-']))
            self.assertAlmostEqual(len(samples)/16000,2,delta=.06)
            middle = samples[4000:20000]
            rising = sum(a<0<=b for a,b in zip(middle,middle[1:]))
            self.assertAlmostEqual(rising,440,delta=3)

    def test_speed_choices(self):
        self.assertEqual(check_speed('1.4'),1.4)
        with self.assertRaises(ValueError):check_speed('nan')
