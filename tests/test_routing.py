import unittest
from routing import select
M='google/gemini-4-argon'
def endpoint(tag,i,o,**extra):
    return dict(tag=tag,pricing=dict(prompt=str(i/1e6),completion=str(o/1e6)),status=0,
                supported_parameters=['response_format'],**extra)
class Routing(unittest.TestCase):
    def test_cheapest(self):
        p=select(M,[endpoint('google-ai-studio',2,10),endpoint('google-ai-studio/flex',1,5,service_tier='flex')])['body_overrides']
        self.assertEqual(p['service_tier'],'flex')
        self.assertEqual(p['provider']['only'],['google-ai-studio/flex'])
        self.assertFalse(p['provider']['allow_fallbacks'])
        self.assertEqual(p['provider']['max_price'],{'prompt':1,'completion':5,'request':0})
    def test_block_expensive_unavailable_or_tradeoff(self):
        cheap=endpoint('cheap',1,5);cheap['status']=-2
        for variants in ([endpoint('standard',2,10)], [cheap,endpoint('other',1.1,5)], [endpoint('a',1,5),endpoint('b',0.9,6)]):
            with self.assertRaises(ValueError):select(M,variants)
