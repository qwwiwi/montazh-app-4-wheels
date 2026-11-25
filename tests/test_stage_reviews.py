import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import stage_reviews as stages


class EarlyReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.words = self.root/'words.json'
        self.words.write_text(json.dumps({'duration':5, 'words':[{'start':1, 'end':2, 'w':'книга'}]}))
        self.ledger = self.root/'usage.jsonl'

    def result(self, ids):
        return {'checks':[{'id':k,'verdict':'PASS','start':0,'end':2,'evidence':'Two complete words.'}
                          for k in ids]}

    def test_source_analysis_has_bounded_notes_with_media_and_durations(self):
        media={'type':'video_url','video_url':{'url':'data:video/mp4;base64,AA=='}}
        notes=[{'action':'retain','start':1,'end':2,'evidence':'Слышно слово книга','direction':'Оставить полную фразу'}]
        with patch('stage_reviews.subprocess.run'), patch('stage_reviews.video_evidence',return_value=(5,'digest',media)), patch('stage_reviews.model_call',return_value={'status':'OK','notes':notes}) as call:
            actual=stages.inspect_source('unedited.mp4',self.words,self.ledger)
        self.assertEqual(actual['notes'],notes)
        self.assertEqual(call.call_args.args[:2],('argon-source',stages.ARGON))
        self.assertEqual(call.call_args.args[2][-1],media)
        self.assertEqual(call.call_args.kwargs['media_durations'],[5])
        with patch('stage_reviews.video_review',return_value=({'status':'OK','notes':[dict(notes[0],end=20)]},{})),self.assertRaisesRegex(ValueError,'тайм-код'):
            stages.inspect_source('unedited.mp4',self.words,self.ledger)

    def test_actual_rough_cut_review_returns_mapped_source_evidence(self):
        review=self.result(stages.TAKE_CHECKS)
        review['checks'][0].update(verdict='REVISE',start=.5,end=1.5,fix='Подправить склейку')
        media={'type':'video_url','video_url':{'url':'data:video/mp4;base64,AA=='}}
        mapping={'cut_duration':2,'pieces':[{'src':[0,2],'cut':[0,1]},{'src':[3,5],'cut':[1,2]}]}
        with patch('stage_reviews.subprocess.run') as encoder,patch('stage_reviews.video_evidence',return_value=(2,'sha',media)),patch('stage_reviews.model_call',return_value=review) as paid:
            result=stages.review_rough_cut('joined.mp4',self.words,{'keep':[[0,2],[3,5]]},mapping,self.ledger)
        self.assertEqual(('REVISE','rough_cut'),(result['verdict'],result['timeline']))
        self.assertEqual(result['checks'][0]['source_intervals'],[[1,2],[3,4]])
        self.assertIn(str(Path('joined.mp4').resolve()),encoder.call_args.args[0])
        self.assertEqual(paid.call_args.args[:2],('argon-rough-cut',stages.ARGON))
        self.assertEqual(paid.call_args.kwargs['media_durations'],[2])

    def test_storyboard_is_labelled_text_only(self):
        with patch('stage_reviews.model_call', return_value=self.result(stages.PLAN_CHECKS)) as call:
            result=stages.review_storyboard(self.words,{'scenes':[]},self.ledger)
        self.assertEqual(result['verdict'],'UNVERIFIED')
        self.assertEqual(result['evidence_mode'],'storyboard_and_transcript_only')
        self.assertIsInstance(call.call_args.args[2],str)

    def test_incomplete_out_of_range_unverified(self):
        rows=self.result(stages.TAKE_CHECKS)
        rows['checks'][0]['verdict']='UNVERIFIED'
        rows['checks'][0]['fix']='Listen to the source.'
        self.assertEqual(stages.verified_review(rows,stages.TAKE_CHECKS,5,'x')['verdict'],'UNVERIFIED')
        rows['checks'][0]['end']=7
        with self.assertRaises(ValueError): stages.verified_review(rows,stages.TAKE_CHECKS,5,'x')
        rows['checks'].pop()
        with self.assertRaises(ValueError): stages.verified_review(rows,stages.TAKE_CHECKS,5,'x')

    def test_opus_uses_source_timeline_and_original_ledger(self):
        with patch('stage_reviews.model_call', return_value={'keep':[[1,3]]}) as call:
            result=stages.revise_takes(self.words,{'keep':[[0,4]]},self.result(stages.TAKE_CHECKS),self.ledger)
        self.assertEqual(result['keep'],[[1,3]])
        self.assertEqual(call.call_args.args[-1],self.ledger)
        with patch('stage_reviews.model_call',return_value={'keep':[[1,4],[3,5]]}):
            with self.assertRaises(ValueError):
                stages.revise_takes(self.words,{'keep':[[0,4]]},self.result(stages.TAKE_CHECKS),self.ledger)

    def test_retime_resets_old_word_indices_and_validates_new_timeline(self):
        previous = {'shots':[{}], 'scenes':[], 'brand_candidates':[{'first':99,'last':99}]}
        response = {'edits':[{'path':['shots',0,'from'],'value':0}]}
        with patch('model_stages.validate_storyboard',side_effect=lambda plan,*a,**k:plan) as validate, patch('stage_reviews.model_call',return_value=response):
            plan = stages.opus_retime(previous,self.words,self.root,self.ledger)
        self.assertEqual(plan['brand_candidates'],[])
        self.assertEqual(previous['brand_candidates'][0]['first'],99)
        self.assertTrue(validate.call_args.kwargs['allow_style_findings'])
