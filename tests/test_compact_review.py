from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from compact_review import INPUT_CEILING, OUTPUT_CEILING, OUTPUT_TOKENS, TEXT_BYTES, _content, _prompt, reserve_usd
from job_budget import input_bound
from model_stages import SYSTEM


class CompactFinalReview(unittest.TestCase):
    def test_reservation_covers_full_text_video_audio_and_proxy_drift(self):
        refs=[64.61,57.8,56.98]
        reserve=reserve_usd(45.4,refs)
        content=_content('z'*TEXT_BYTES,[{'type':'video_url'}]*4)
        tokens=input_bound([{'content':SYSTEM},{'content':content}],[45.46,*refs])
        self.assertGreaterEqual(reserve,tokens*INPUT_CEILING+OUTPUT_TOKENS*OUTPUT_CEILING)
        self.assertLess(reserve,Decimal('0.18'))
        with self.assertRaises(ValueError):
            reserve_usd(45.4,refs[:2])

    def test_compact_review_preserves_words_findings_and_rule_after_shell_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            rubric=Path(tmp)/'rules.md'
            fence=chr(96)*3
            rubric.write_text('Style targets\n'+fence+'sh\nprivate command\n'+fence+'\nGolden last rule.')
            source={'words':[{'w':'Первый','start':0.0},{'w':'раз','start':2.11}]}
            report={'numbers':{'caption_count':3},'failures':['visual layout'], 'renderer_findings':['overlap']}
            prompt,extra=_prompt(rubric,report,source,source,None,None)
            self.assertEqual(extra,[])
            for expression in ('reference_A','reference_B','reference_C','Первый','раз','visual layout','overlap','Golden last rule.'):
                self.assertIn(expression,prompt)
            self.assertNotIn('private command',prompt)
