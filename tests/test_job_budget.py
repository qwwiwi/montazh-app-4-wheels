import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import model_stages as stages
from job_budget import BillingUnknown, BudgetExceeded, budget_snapshot, input_bound


class JobBudget(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.audit=Path(tmp.name)/'usage.jsonl'
        opts=patch.dict('os.environ',{'REEL_OPENROUTER_API_KEY':'fixture'})
        opts.start()
        self.addCleanup(opts.stop)
        route=patch.object(stages,'cheapest_route',return_value={
            'body_overrides':{}, 'evidence':{'listed_prices':{'prompt':'0.000004','completion':'0.00002'}}})
        route.start()
        self.addCleanup(route.stop)

    def spent(self, amount):
        self.audit.write_text(json.dumps({'usage':{'cost':amount}})+'\n')

    def test_prior_job_spend_blocks_new_call(self):
        self.spent(1.99)
        with patch.object(stages,'post_json') as post,self.assertRaises(BudgetExceeded):
            stages.model_call('opus-plan',stages.OPUS,'some input',self.audit)
        post.assert_not_called()

    def test_local_ceiling_shrinks_output_even_for_retries(self):
        self.spent(1.6)
        response={'id':'paid','model':stages.OPUS,'usage':{'cost':0.11},
                  'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        with patch.object(stages,'post_json',return_value=response) as post:
            stages.model_call('opus-revise',stages.OPUS,'prompt',self.audit)
        body=post.call_args.args[0]
        self.assertLess(body['max_tokens'],8192)
        last=json.loads(self.audit.read_text().splitlines()[-1])
        self.assertLessEqual(last['budget']['max_request_usd'],0.16)
        self.assertEqual(budget_snapshot(self.audit)['used_usd'],1.71)

    def test_crash_or_unknown_billing_blocks_resume(self):
        for raw in ['{','{"usage":{"cost":null}}','{"usage":{"cost":-1}}']:
            self.audit.write_text(raw)
            with patch.object(stages,'post_json') as post,self.assertRaises(BillingUnknown):
                stages.model_call('opus-plan',stages.OPUS,'x',self.audit)
            post.assert_not_called()
        self.spent(0.4)
        self.audit.with_suffix('.pending').touch()
        self.assertIsNone(budget_snapshot(self.audit)['remaining_usd'])
        with patch.object(stages,'post_json') as post,self.assertRaises(BillingUnknown):
            stages.model_call('opus-plan',stages.OPUS,'x',self.audit)
        post.assert_not_called()

    def test_parallel_admission_observes_first_charge(self):
        from threading import Event,Thread
        entered=Event()
        release=Event()
        failures=[]
        self.spent(1.6)
        def post(*_):
            entered.set()
            release.wait(4)
            return {'id':'paid','model':stages.OPUS,'usage':{'cost':0.15},
                    'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        def worker():
            try:
                stages.model_call('opus-plan',stages.OPUS,'text',self.audit)
            except BudgetExceeded:
                failures.append('refused')
        with patch.object(stages,'post_json',side_effect=post) as fn:
            first=Thread(target=worker)
            second=Thread(target=worker)
            first.start()
            self.assertTrue(entered.wait(2))
            self.assertIsNone(budget_snapshot(self.audit)['remaining_usd'])
            second.start()
            release.set()
            first.join(4)
            second.join(4)
        self.assertEqual(fn.call_count,1)
        self.assertEqual(failures,['refused'])

    def test_gateway_payload_rejection_releases_zero_charge_reservation(self):
        with patch.object(stages,'post_json',side_effect=stages.PayloadRejected('413')),self.assertRaises(stages.PayloadRejected):
            stages.model_call('argon-review',stages.ARGON,'x',self.audit)
        row=json.loads(self.audit.read_text())
        self.assertEqual((row['http_status'],row['usage']['cost'],row['id']),(413,0,None))
        self.assertEqual(budget_snapshot(self.audit)['remaining_usd'],2)

    def test_weekly_headroom_blocks_admission_before_transmission(self):
        from decimal import Decimal
        with patch.object(stages,'weekly_remaining',return_value=Decimal('0.001')),patch.object(stages,'post_json') as post,self.assertRaises(BudgetExceeded):
            stages.model_call('argon-review',stages.ARGON,'x',self.audit)
        post.assert_not_called()

    def test_all_videos_and_audio_budgeted_before_transmission(self):
        content=[{'type':'video_url','video_url':{'url':'data:video/mp4;base64,fixture'}}]*4
        with self.assertRaisesRegex(ValueError,'длительности'):
            input_bound([{'content':content}],[])
        self.assertEqual(input_bound([{'content':content}],[53,65,58,57]),4096+(233+8)*512)
        self.spent(1.9)
        with patch.object(stages,'post_json') as post,self.assertRaises(BudgetExceeded):
            stages.model_call('argon-review',stages.ARGON,content,self.audit,media_durations=[53,65,58,57])
        post.assert_not_called()


if __name__=='__main__':
    unittest.main()
