import unittest
from local_transcript import closest, evaluate

class LocalTranscriptTest(unittest.TestCase):
    def test_word_decisions(self):
        def word(w):return {'w':w,'start':1,'end':2,'probability':.95}
        self.assertEqual(evaluate(word('шаговай'),[word('шаговый')]*2),'corrected')
        self.assertEqual(evaluate(word('67'),[word('97')]*2),'unresolved')
        self.assertEqual(evaluate(word('Клод'),[word('плод')]*2),'unresolved')
        self.assertEqual(evaluate(word('тест'),[word('текст'),word('тест')]),'unresolved')
        self.assertEqual(evaluate(word('тест'),[word('тест')]*2),'confirmed')
        self.assertIsNone(closest(word('тест'),[dict(word('тест'),start=3,end=5)]))
