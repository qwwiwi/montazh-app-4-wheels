"""Editorial gate tests: no upstream models, publishing or real charges."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import full_edit as editor


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_recut_resumes_after_budget_refuses_first_plan_without_recharging_takes(self):
        editor.write(self.root/'origin.json',{'review':'attempt-5/review.json'})
        first=self.root/'attempt-1'
        first.mkdir()
        editor.write(first/'budget-stop.json',{'reason':'preflight cap'})
        self.assertEqual(editor.resume_point(self.root),(2,None))

    def test_visual_feedback_goes_to_opus_and_both_versions_survive(self):
        issue={"id":"hook","start":0.12,"end":0.7,"verdict":"REVISE","evidence":"Low contrast","fix":"Increase title contrast"}
        received=[]
        def attempt(folder, feedback):
            received.append(feedback)
            (folder/'render.mp4').write_bytes(folder.name.encode())
            editor.write(folder/'storyboard.json',{'shots':[folder.name]})
            if not feedback:
                raise editor.RevisionNeeded({"stage":"argon","issues":[issue],"postcheck_failures":[]})
            return "pass"
        result,count=editor.editorial_iterations(self.root,attempt,lambda _:None)
        self.assertEqual((result,count),('pass',2))
        feedback=json.loads(received[1])
        self.assertEqual(feedback['previous_storyboard'],{'shots':['attempt-1']})
        self.assertEqual(feedback['corrections']['issues'],[issue])
        self.assertTrue((self.root/'attempt-1/render.mp4').is_file())
        self.assertTrue((self.root/'attempt-2/feedback-to-opus.json').is_file())
        self.assertTrue((self.root/'attempt-2/render.mp4').is_file())

    def test_multiple_revisions_until_pass_and_stop_on_budget_rejection(self):
        def attempt(folder,feedback):
            if folder.name=="attempt-5":
                raise ValueError("недостаточно бюджета")
            editor.write(folder/'storyboard.json',{'v':folder.name})
            raise editor.RevisionNeeded({'stage':'build','local_failures':['contrast']})
        with self.assertRaisesRegex(ValueError,'бюджета'):
            editor.editorial_iterations(self.root,attempt,lambda _:None)
        self.assertEqual(len(list(self.root.glob('attempt-*'))),5)
        self.assertFalse((self.root/'edit.mp4').exists())

    def test_resume_preserves_legacy_attempts_and_forwards_latest_evidence(self):
        for number in (1,2):
            folder=self.root/f"attempt-{number}"
            folder.mkdir()
            editor.write(folder/'storyboard.json',{'v':number})
            editor.write(folder/'revision-request.json',{'stage':'plan','local_failures':[str(number)]})
        def approved(folder,feedback):
            self.assertEqual(json.loads(feedback)['corrections']['local_failures'],['2'])
            self.assertEqual(folder.name,'attempt-3')
            return "ok"
        self.assertEqual(editor.editorial_iterations(self.root,approved,lambda _:None,resume=True),("ok",3))
        self.assertEqual(editor.read(self.root/'attempt-1/storyboard.json'),{'v':1})

    def test_budget_stop_keeps_same_job_resume_point_and_unknown_billing_blocks(self):
        from job_budget import BudgetExceeded
        for name in ("raw.mp4","cut.mp4","words.json","raw-words.json","keep.json","head.json","cut.map.json"):
            (self.root/name).touch()
        (self.root/"usage.jsonl").write_text('{"usage":{"cost":0.8}}\n')
        def attempt(folder,feedback):
            if feedback:
                raise BudgetExceeded("Лимит")
            editor.write(folder/'storyboard.json',{'v':1})
            raise editor.RevisionNeeded({'stage':'build','local_failures':['contrast']})
        with self.assertRaises(BudgetExceeded):
            editor.editorial_iterations(self.root,attempt,lambda _:None)
        self.assertTrue(editor.can_resume(self.root))
        number,feedback=editor.resume_point(self.root)
        self.assertEqual(number,3)
        self.assertEqual(feedback["previous_storyboard"],{"v":1})
        (self.root/"usage.pending").touch()
        self.assertFalse(editor.can_resume(self.root))

    def test_no_retry_on_uncertain_evidence_or_take_defect(self):
        def manual(folder,feedback):
            raise editor.RevisionNeeded({'stage':'argon','issues':[{'id':'audio_sync'}]},manual=True)
        with self.assertRaisesRegex(ValueError,'ручная'):
            editor.editorial_iterations(self.root,manual,lambda _:None)
        self.assertFalse((self.root/'attempt-2').exists())

    def test_no_new_model_charge_after_network_or_billing_error(self):
        def failed(folder,feedback):
            raise ValueError('OpenRouter HTTP 503')
        with self.assertRaisesRegex(ValueError,'503'):
            editor.editorial_iterations(self.root,failed,lambda _:None)
        self.assertFalse((self.root/'attempt-2').exists())

    def test_postcheck_evidence_required_for_local_revision(self):
        self.assertIsNone(editor.local_defect(self.root,'postcheck'))
        (self.root/'qa').mkdir()
        editor.write(self.root/'qa/postcheck.json',{'failures':['caption overlaps face at 12.2']})
        self.assertEqual(editor.local_defect(self.root,'postcheck').evidence['local_failures'],['caption overlaps face at 12.2'])
        editor.write(self.root/'qa/postcheck.json',{'failures':['shot out of sync at 2.0']})
        self.assertTrue(editor.local_defect(self.root,'postcheck').manual)

    def test_legacy_padding_recovers_with_other_visual_findings_only(self):
        (self.root/'qa').mkdir()
        editor.write(self.root/'storyboard.json', {'v':1})
        def record(failures):
            editor.write(self.root/'qa/postcheck.json',{'failures':failures})
            editor.write(self.root/'revision-request.json',{'stage':'postcheck','manual':True,'local_failures':failures})
        record(['audio duration 53.1 vs cut 53.04 (more than 40 ms)','caption not found'])
        self.assertEqual(editor.revision_feedback(self.root)['corrections']['local_failures'],['caption not found'])
        record(['audio duration 53.1 vs cut 53.04 (more than 40 ms)','speaker clip is out of sync'])
        with self.assertRaisesRegex(ValueError,'ручная'):
            editor.revision_feedback(self.root)
        record(['audio duration 53.1 vs cut 53.04 (more than 40 ms)'])
        self.assertTrue(editor.revision_feedback(self.root)['corrections']['restore_frozen_audio'])
        editor.write(self.root/'frozen-audio.json',{'audio_source':'cut.mp4'})
        with self.assertRaisesRegex(ValueError,'ручная'):
            editor.revision_feedback(self.root)

    def test_reasoned_omission_can_only_hide_exact_confirmed_brand(self):
        report={'mentions':[{'word_start':1,'word_end':2,'name':'Acme'},{'word_start':5,'word_end':5,'name':'Widget'}]}
        with self.assertRaises(ValueError):
            editor.apply_omissions(report,[{'first':1,'last':1,'reason':'near caption'}])
        editor.apply_omissions(report,[{'first':1,'last':2,'reason':'Repeats same identity in the preceding shot'}])
        self.assertEqual(report['mentions'][0]['name'],'Widget')
        self.assertEqual(report['editorial_omissions'][0]['name'],'Acme')

    def test_argon_take_findings_reach_opus_before_freezing_the_selection(self):
        original={'keep':[[0,4]]}
        corrected={'keep':[[1,4]]}
        issue={'id':'join_boundaries','verdict':'REVISE','start':0,'end':1,
               'evidence':'Repeated start','fix':'Use the second take'}
        first={'verdict':'REVISE','checks':[issue]}
        passed={'verdict':'PASS','checks':[]}
        def freeze(_,keep,cut,*args):
            cut.write_bytes(keep.read_bytes())
            editor.write(cut.with_suffix('.map.json'),{'cut_duration':3,'pieces':[]})
        with patch.object(editor,'freeze_paced_cut',side_effect=freeze), patch('stage_reviews.review_rough_cut',side_effect=[first,passed]) as reviews, patch('stage_reviews.revise_takes',return_value=corrected) as revise:
            editor.supervised_takes(self.root,'source','words',original,4,'audit',lambda x:None,1.3,None)
        revise.assert_called_once_with('words',original,first,'audit')
        self.assertEqual(reviews.call_count,2)
        self.assertEqual(editor.read(self.root/'keep.json')['keep'],corrected['keep'])
        self.assertTrue((self.root/'cut.mp4').samefile(self.root/'take-2/rough-cut.mp4'))
        self.assertEqual(editor.read(self.root/'take-1/stage-review.json')['checks'],[issue])
        self.assertEqual(editor.read(self.root/'take-2/feedback-to-opus.json'),first)
        self.assertEqual(editor.read(self.root/'take-2/stage-review.json')['verdict'],'PASS')

    def test_existing_draft_review_starts_only_one_recut_on_the_shared_ledger(self):
        root=self.root
        folder=root/'attempt-5'
        folder.mkdir()
        for f in ('raw.mp4','raw-words.json','usage.jsonl','keep.json'):
            (root/f).touch()
        editor.write(folder/'storyboard.json',{'v':5})
        editor.write(folder/'review.json',{'verdict':'REVISE','checks':[{'id':'take_completeness','verdict':'REVISE'}]})
        self.assertTrue(editor.can_recut(root))
        self.assertEqual(editor.reviewed_takes(root),folder)
        (root/'recut-1').mkdir()
        self.assertFalse(editor.can_recut(root))
        self.assertEqual(editor.latest_run(root),root/'recut-1')

    def test_integrated_visual_revision_charges_and_rechecks(self):
        case=self.root/'job'
        case.mkdir()
        source=case/'source.mp4'
        source.touch()
        refs=[self.root/f'{letter}.mp4' for letter in 'ABC']
        for ref in refs:
            ref.write_text(ref.name)
        approvals=[]
        drafts=[]
        def simulate(args,**kwargs):
            args=list(map(str,args))
            if 'pytest' in args:return
            if args[0]=='ffmpeg':
                out=Path(args[-1])
                if out.name=='frozen-audio.mp4':
                    self.assertIn('1:a:0',args)
                    out.write_bytes(Path(args[args.index('-i')+1]).read_bytes())
                else:
                    out.touch()
                return
            name=Path(args[1]).name
            if name=='local_transcript.py':editor.write(Path(args[args.index('-o')+1]),{'duration':4,'words':[{'w':'x','start':0,'end':4}]})
            if name=='render_qa.py':
                qa=Path(args[-1]);qa.mkdir();editor.write(qa/'postcheck.json',{'failures':[],'numbers':{}})
            if name=='measure_head.py':editor.write(Path(args[args.index('-o')+1]),{'worst_case':{}})
            if name=='cut_takes.py':
                cut=Path(args[args.index('-o')+1]);cut.touch();editor.write(cut.with_suffix('.map.json'),{'removed':[],'cut_duration':4,'pieces':[{'src':[0,4],'cut':[0,4]}]})
            if name in ('reel.py','source_scene.py'):
                op=args[3] if name=='source_scene.py' else args[2]
                if op=='build':
                    project=Path(args[-1]);project.mkdir();(project/'gate-report.txt').write_text('clean')
                if op=='render':Path(args[-1]).write_bytes(args[-1].encode())
                if op=='check':
                    qa=Path(args[-1]);qa.mkdir();editor.write(qa/'postcheck.json',{'failures':[],'numbers':{}})
        def bill(path,value):
            with path.open('a') as log:log.write('{"usage":{"cost":0.05}}\n')
            return value
        def argon(*args,**kwargs):
            verdict='REVISE' if not approvals else 'PASS'
            approvals.append(verdict)
            return bill(args[5],{'verdict':verdict,'score':8,'checks':[{'id':'hook','verdict':verdict,'start':0,'end':.6,'fix':'increase contrast','evidence':'text contrast'}]})
        def plan(*args,**kwargs):
            drafts.append(kwargs)
            return bill(args[3],{'shots':[len(drafts)],'brand_candidates':[]})
        def initial_keep(words,skill,rubric,audit,feedback):
            self.assertEqual(json.loads(feedback),[{'direction':'keep start'}])
            self.assertTrue((case/'full/source-review.json').is_file())
            self.assertEqual(len(audit.read_text().splitlines()),1)
            return bill(audit,{'keep':[[0,4]]})
        def early(stage):
            return lambda *args:bill(args[-1],{'verdict':'PASS','checks':[],'stage':stage})
        with patch.object(editor,'accelerate',side_effect=lambda src,dst,speed:dst.touch()) as speedup,patch('stage_reviews.review_rough_cut',side_effect=early('rough_cut')),patch('stage_reviews.inspect_source',side_effect=lambda *a:bill(a[2],{'status':'OK','notes':[{'direction':'keep start'}]})),patch('stage_reviews.review_storyboard',side_effect=early('storyboard')),patch.object(editor,'availability',return_value={'ready':True}),patch.object(editor,'project_key',return_value=True),patch.object(editor,'settings',return_value=(self.root,'python',refs)),patch.object(editor,'metadata',return_value=({'width':1080,'height':1920},{'index':1},4)),patch('subprocess.run',side_effect=simulate),patch('model_stages.opus_keep',side_effect=initial_keep),patch('model_stages.opus_plan',side_effect=plan),patch('model_stages.argon_review',side_effect=argon),patch('brands.prepare_brands',return_value={'mentions':[],'unresolved':[]}),patch('creative_context.creative_context',return_value={'catalog':'test evidence'}),patch.object(editor,'configure_graphics',return_value={'mentions':[]}):
            result=editor.full_edit(source,case/'edit.mp4',lambda _:None)
        self.assertEqual(editor.read(case/'full/take-1/stage-review.json')['stage'],'rough_cut')
        self.assertEqual(editor.read(case/'full/attempt-1/stage-review.json')['stage'],'storyboard')
        self.assertEqual(result['playback_speed'],1.3)
        self.assertEqual(editor.read(case/'full/pace.json')['speed'],1.3)
        speedup.assert_called_once()
        self.assertEqual(result['editorial_attempts'],2)
        self.assertEqual(result['cost_usd'],.45)
        self.assertEqual(approvals,['REVISE','PASS'])
        self.assertEqual(drafts[0]['creative_context']['catalog'],'test evidence')
        self.assertEqual(drafts[0]['creative_context']['source_playback_notes']['notes'],[{'direction':'keep start'}])
        self.assertIn('increase contrast',drafts[1]['feedback'])
        self.assertEqual((case/'edit.mp4').read_bytes(),(case/'full/attempt-2/render.mp4').read_bytes())
        self.assertNotEqual((case/'edit.mp4').read_bytes(),(case/'full/attempt-1/render.mp4').read_bytes())
