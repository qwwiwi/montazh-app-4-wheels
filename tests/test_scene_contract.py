from pathlib import Path
import json
from types import SimpleNamespace
from unittest import TestCase, mock
import tempfile

from full_edit import revision_feedback
from scene_contract import ComponentError, validate


class ComponentContractTests(TestCase):
    def test_native_failure_names_affected_shot_schema_and_time(self):
        sample={'hc_steps':{'result':{'wait':'before','done':'after','label':'Result','at':1}}}
        plan=SimpleNamespace(shots=[SimpleNamespace(type='split')],
                             scenes=[SimpleNamespace(shot=0,kind='hc_steps',start=2.25,end=4.5)])
        builders=mock.Mock()
        builders.build_scene.side_effect=KeyError('result')
        with mock.patch.dict('sys.modules',{'scenes_hc':SimpleNamespace(HC_EXAMPLES=sample)}):
            with self.assertRaisesRegex(ComponentError,r'shot 0 hc_steps 2.250-4.500:.*required field result:.*done'):
                validate(plan,builders)
        builders.build_scene.assert_called_once_with(plan.scenes[0],False)

    def test_legacy_approved_plan_recovers_without_mutating_or_replacing_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);folder=job/'attempt-3';folder.mkdir()
            (job/'words.json').write_text('{}')
            (folder/'storyboard.json').write_text('{"scenes":[{"kind":"hc_steps"}]}')
            (folder/'stage-review.json').write_text('{"verdict":"PASS"}')
            with mock.patch('model_stages.validate_storyboard',side_effect=ComponentError('shot 10 hc_steps 26.5-29.7: missing result')):
                feedback=revision_feedback(folder)
            self.assertEqual(feedback['previous_storyboard'],json.loads((folder/'storyboard.json').read_text()))
            self.assertEqual(feedback['corrections']['stage'],'component_schema')
            self.assertFalse((folder/'revision-request.json').exists())
