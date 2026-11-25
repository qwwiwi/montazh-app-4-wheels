import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from plan_repair import apply_edits, approved_repeat


class StoryboardRevision(unittest.TestCase):
    def test_edits_leave_source_and_unmentioned_scenes_unchanged(self):
        plan = {'scenes': [{'kind': 'hook'}, {'kind': 'hc_steps'}]}
        revised = apply_edits(plan, {'edits': [{'path': ['scenes', 1, 'bg'], 'value': 'dark'}]})
        self.assertEqual(revised['scenes'], [plan['scenes'][0], {'kind': 'hc_steps', 'bg': 'dark'}])
        self.assertNotIn('bg', plan['scenes'][1])

    def test_add_optional_arrays_and_refine_them_within_one_repair(self):
        previous = {'scenes': []}
        revised = apply_edits(previous, {'edits': [
            {'path': ['source_cues'], 'value': [{'word_index': 2, 'duration': 4}]},
            {'path': ['source_cues', 0, 'duration'], 'value': 3},
            {'path': ['brand_omissions'], 'value': []},
        ]})
        self.assertEqual(revised['source_cues'], [{'word_index': 2, 'duration': 3}])
        self.assertEqual(revised['brand_omissions'], [])
        self.assertEqual(previous, {'scenes': []})

    def test_first_plan_uses_requested_validation_policy(self):
        from model_stages import opus_plan
        plan = {'scenes': []}
        src = {'words': []}
        for allow_style in (True, False):
            with self.subTest(allow_style=allow_style), patch('model_stages.transcript', return_value=src), \
                    patch('model_stages.planner_context', return_value=''), \
                    patch('model_stages.model_call', return_value=plan), \
                    patch('model_stages.validate_storyboard', return_value=plan) as validate:
                opus_plan('words', 'skill', 'rubric', 'audit', use_kit=True, allow_style_findings=allow_style)
                validate.assert_called_once_with(plan, src, 'skill', True, allow_style)

    def test_edits_reject_invalid_path(self):
        for path in ([], ['scenes', -1], ['scenes', 4], ['scenes', 0, 'missing', 'x'], ['never']):
            with self.subTest(path=path), self.assertRaises(ValueError):
                apply_edits({'scenes': [{}]}, {'edits': [{'path': path, 'value': 0}]})

    def test_closing_reminder_revision_goes_to_opus(self):
        from model_stages import OPUS, opus_plan
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rubric = root/'rubric'
            rubric.write_text('Review the closing reminder.')
            previous = {'scenes':[{'kind':'hc_audience'}]}
            feedback = json.dumps({'previous_storyboard':previous,
                'corrections':{'stage':'plan','local_failures':['the last scene has no reminder of the code word']}})
            response = {'edits':[{'path':['scenes',0,'kind'],'value':'hc_cta'}]}
            with patch('model_stages.transcript',return_value={'words':[]}), patch('model_stages.model_call',return_value=response) as paid, patch('model_stages.validate_storyboard',side_effect=lambda plan,*args:plan):
                plan = opus_plan(root/'words.json',root,rubric,root/'usage.jsonl',feedback)
            self.assertEqual(paid.call_args.args[:2],('opus-revise',OPUS))
            self.assertEqual(plan['scenes'][0]['kind'],'hc_cta')

    def test_editorial_repeat_approval_is_bound_to_transcript_and_two_times(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'words.json'
            words = {'words': [{'w': t, 'start': i} for i, t in enumerate('a b c d a b c'.split())]}
            path.write_text(json.dumps(words))
            spec = {'words_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'phrase': 'a b c',
                    'starts': [0, 4], 'reason': 'Distinct list entries.'}
            (path.parent / 'approved-repeat.json').write_text(json.dumps(spec))
            self.assertEqual(approved_repeat(path, path.parent/'usage.jsonl', words), spec)
            words['words'][-1]['w'] = 'd'
            with self.assertRaisesRegex(ValueError, 'does not match'):
                approved_repeat(path, path.parent/'usage.jsonl', words)
            path.write_text(json.dumps(words))
            with self.assertRaisesRegex(ValueError, 'different frozen'):
                approved_repeat(path, path.parent/'usage.jsonl', words)
