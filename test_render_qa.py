from unittest import TestCase, mock
from pathlib import Path
from tempfile import TemporaryDirectory
from full_edit import editorial_iterations, write
from render_qa import valid_offsets


class RenderQATests(TestCase):
    def test_face_jitter_stays_on_decodable_frames(self):
        offsets=(-.2,0,.2)
        self.assertEqual(valid_offsets(38.55,38.7,30,offsets),(-.2,0))
        self.assertEqual(valid_offsets(.03,38.7,30,offsets),(0,.2))
        self.assertEqual(valid_offsets(10,38.7,30,offsets),offsets)

    def test_verified_render_resumes_without_a_new_attempt_or_editor_request(self):
        with TemporaryDirectory() as tmp:
            job=Path(tmp)
            folder=job/'attempt-4';(folder/'project').mkdir(parents=True)
            for name in ('render.mp4','project/gate-report.txt','project/reel-meta.json','project/boxes.json','plan.json','brand-mentions.json'):
                (folder/name).touch()
            write(folder/'frozen-audio.json',{'mode':'stream_copy'})
            write(folder/'stage-review.json',{'verdict':'PASS'})
            editor=mock.Mock();review=mock.Mock(return_value='reviewed')
            self.assertEqual(editorial_iterations(job,editor,lambda _:None,resume=True,finish_render=review),('reviewed',4))
            editor.assert_not_called();review.assert_called_once_with(folder)
            self.assertFalse((job/'attempt-5').exists())
