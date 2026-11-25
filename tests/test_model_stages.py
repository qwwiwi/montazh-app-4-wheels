import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import model_stages as ms

FIXTURE_PRICES = {'prompt':'0.000004','completion':'0.00002'}


class EditorialStages(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir=Path(temp.name)
        self.audit=self.dir/'usage.jsonl'
        self.words=self.dir/'words.json'
        self.words.write_text(json.dumps({'duration':4.0,'words':[{'w':'Первый','start':0.0,'end':1.0}]}))
        self.rubric=self.dir/'rubric.md'
        self.rubric.write_text('Read actual evidence.')

    def response(self,model,content):
        return {'id':'test-id','model':model,'provider':'test',
                'usage':{'cost':0.01,'prompt_tokens':12,'completion_tokens':18,'total_tokens':30},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]}

    @patch.dict('os.environ',{'REEL_OPENROUTER_API_KEY':'fixture-only-no-value'},clear=True)
    def test_route_and_billing_record(self):
        route={'body_overrides':{'provider':{'only':['test/flex']},'service_tier':'flex'},'evidence':{'endpoint':'test/flex','listed_prices':FIXTURE_PRICES}}
        with patch.object(ms,'cheapest_route',return_value=route),patch.object(ms,'post_json',return_value=self.response(ms.OPUS,{})) as call:
            ms.model_call('opus-plan',ms.OPUS,'not logged',self.audit)
        sent=call.call_args.args[0]
        self.assertEqual(sent['model'],ms.OPUS)
        self.assertEqual(sent['provider'],route['body_overrides']['provider'])
        self.assertEqual(sent['service_tier'],'flex')
        self.assertEqual(sent['reasoning']['effort'],'medium')
        row=json.loads(self.audit.read_text())
        self.assertEqual((row['route'],row['provider'],row['usage']['cost']),(route['evidence'],'test',0.01))
        self.assertNotIn('fixture-only',self.audit.read_text())

    @patch.dict('os.environ',{'OPENROUTER_API_KEY':'wrong-scope'},clear=True)
    def test_wrong_key_never_routes(self):
        with patch.object(ms,'cheapest_route') as route,self.assertRaisesRegex(ValueError,'REEL_OPENROUTER'):
            ms.model_call('opus-keep',ms.OPUS,[],self.audit)
        route.assert_not_called()

    @patch.dict('os.environ',{'REEL_OPENROUTER_API_KEY':'mock'},clear=True)
    def test_failure_billed_on_truncation_no_retry(self):
        resp=self.response(ms.ARGON,{}); resp['choices'][0]['finish_reason']='length'
        with patch.object(ms,'cheapest_route',return_value={'body_overrides':{},'evidence':{'listed_prices':FIXTURE_PRICES}}),patch.object(ms,'post_json',return_value=resp) as call,self.assertRaisesRegex(ValueError,'Incomplete'):
            ms.model_call('argon-review',ms.ARGON,[],self.audit)
        self.assertEqual(call.call_count,1)
        self.assertEqual(ms.budget_snapshot(self.audit)['remaining_usd'],1.99)
        self.assertFalse(self.audit.with_suffix('.pending').exists())
        self.assertEqual(json.loads(self.audit.read_text())['usage']['cost'],0.01)

    def test_intervals_in_source_time(self):
        (self.dir/'examples').mkdir()
        (self.dir/'examples'/'keep-test-reel.json').write_text('{}')
        for ranges,valid in [([[0,1],[2,4]],True),([[1,3],[2.5,3]],False),([[0,5]],False)]:
            keep={'keep':ranges,'snap':0.02,'keep_pause':0.22,'max_pause':0.30}
            with patch.object(ms,'model_call',return_value=keep):
                if valid: self.assertEqual(ms.opus_keep(self.words,self.dir,self.rubric,self.audit),keep)
                else:
                    with self.assertRaises(ValueError): ms.opus_keep(self.words,self.dir,self.rubric,self.audit)

    def review(self):
        return {'score':4,'checks':[dict(id=i,verdict='PASS',start=0,end=0.2,evidence='Caption at opening frame',
                                         reference_time=0.1,fix='') for i in (*ms.CANON,'reference_A','reference_B','reference_C')]}

    def test_fail_closed_judgement(self):
        report=self.review()
        self.assertEqual(ms.verdict(report,[3]*4)['verdict'],'PASS')  # score is advisory
        report['checks'][0].update(verdict='UNVERIFIED',fix='Watch source at frame zero')
        self.assertEqual(ms.verdict(report,[3]*4)['verdict'],'REVISE')
        report['checks'][-1]['reference_time']=4
        with self.assertRaisesRegex(ValueError,'timestamp'): ms.verdict(report,[3]*4)
        report['checks'].pop()
        with self.assertRaisesRegex(ValueError,'Incomplete'): ms.verdict(report,[3]*4)

    def test_native_gate_and_incomplete_postcheck(self):
        pre=self.dir/'gate-report.txt';post=self.dir/'postcheck.json'
        pre.write_text('clean\n');post.write_text('{"failures":[]}')
        with self.assertRaisesRegex(ValueError,'post-render'): ms.check_post(pre,post)
        pre.write_text('  [face] caption hits speaker')
        with self.assertRaisesRegex(ValueError,'Pre-render'): ms.check_post(pre,post)

    def test_all_media_transmitted_with_provenance(self):
        media=[(2.0,str(i),{'type':'video_url','video_url':{'url':f'fixture-{i}'}}) for i in range(4)]
        post={'numbers':{'duration':{'render':{'video':2}}}}
        (self.dir/'reel-meta.json').write_text(json.dumps({'shots':[{'type':'visual','start':0,'end':2}]}))
        manifest={'assets':[{'id':'website','kind':'website','source_url':'https://example.org','rights':'owner'}],
                  'placements':[{'asset_id':'website','start':0,'end':1}]}
        (self.dir/'real-media.json').write_text(json.dumps(manifest))
        response=self.review()
        mix=next(r for r in response['checks'] if r['id']=='real_media_mix')
        mix['observed_intervals']=manifest['placements']
        with patch.object(ms,'check_post',return_value=post),patch.object(ms,'video_evidence',side_effect=media),patch.object(ms,'model_call',return_value=response) as call:
            value=ms.argon_review(self.dir/'final',list('ABC'),self.dir/'pre',self.dir/'post',self.rubric,self.audit,
                                  raw_words=self.words,cut_words=self.words)
        self.assertEqual(value['verdict'],'PASS')
        self.assertEqual(value['evidence_sha256'],dict(zip(('final','A','B','C'),'0123')))
        self.assertEqual(call.call_args.args[:2],('argon-review',ms.ARGON))
        content=call.call_args.args[2]
        self.assertEqual([c for c in content if c['type']=='video_url'],[m[2] for m in media])
        self.assertIn('frozen_cut_words',content[0]['text'])

    def test_duplicate_video_rejected_before_paid_review(self):
        post={'numbers':{'duration':{'render':{'video':2}}}}
        with patch.object(ms,'check_post',return_value=post),patch.object(ms,'video_evidence',return_value=(2,'same',{})),patch.object(ms,'model_call') as call,self.assertRaisesRegex(ValueError,'Duplicate'):
            ms.argon_review(1,[1,1,1],2,3,self.rubric,self.audit,raw_words=self.words,cut_words=self.words)
        call.assert_not_called()

class ReviewStyleGates(unittest.TestCase):
    def test_advisory_requires_verified_build_and_preserves_all_measurements(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            pre=root/'gate-report.txt'
            post=root/'postcheck.json'
            observation='[rhythm] split: same shot type for 8 seconds'
            pre.write_text(observation)
            findings=['shot 14 split 44.9-49.3: the picture does not change for 2.4 s']
            numbers=dict.fromkeys(('duration','palette','shot_types','segments','hook','captions','repeated_takes','sync'),{})
            report={'numbers':numbers,'captions':[{}],'frame_types_10fps':['split'],'failures':findings}
            post.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'Pre-render'):
                ms.check_post(pre,post,True)
            (root/'review-style.json').write_text(json.dumps({'runtime_check':'passed','findings':[observation]}))
            checked=ms.check_post(pre,post,True)
            self.assertEqual(checked['precheck'],observation)
            self.assertEqual(checked['failures'],findings)
            for failure in ('audio duration 5 vs cut 4', 'speaker clip at 2.2 is out of sync', 'unknown defect'):
                report['failures']=[failure]
                post.write_text(json.dumps(report))
                with self.subTest(failure=failure), self.assertRaisesRegex(ValueError,'Post-render check failed'):
                    ms.check_post(pre,post,True)
