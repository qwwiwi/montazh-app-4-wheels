import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import compact_editor as editor


class CompactEditorTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.path=self.root/'words.json'
        self.path.write_text(json.dumps({'duration':3,'words':[
            {'w':'CRM','start':0,'end':1},{'w':'АМСРМ','start':1,'end':2}]}))
        self.plan={'scenes':[{'shot':0,'kind':'hook','text':'Дальше','at':{'word':'АМСРМ'}},
                             {'shot':1,'kind':'hc_cta','text':'Second'}, {'shot':2,'kind':'hc_cta','text':'Last'}],
                   'shots':[{}, {}, {}]}
        self.feedback=[{'verdict':'REVISE','id':'readability','start':0,'end':.4,
                        'evidence':'«Дальше» overlaps','fix':'Shorten the label.'}]
        self.notes={'surviving_shots':{0:0,1:1,2:2},
                    'compressed_shots':[{'old_shot':1,'start':1,'end':1.1}]}

    def request(self, result):
        with patch.object(editor,'model_call',return_value=result) as paid, patch.object(editor,'validate_storyboard') as validate:
            payload=editor.direct_mapped(self.plan,self.notes,self.path,self.root,self.root/'ledger',self.feedback)
            self.assertEqual(paid.call_args.args[:2],('opus-compact',editor.OPUS))
            self.assertEqual(paid.call_args.kwargs,{'output_token_limit':2500})
            validate.assert_called_once()
            return payload

    def test_edit_scoped_copy_and_anchor_preserves_times(self):
        revised, words=self.request({'slots':[[0,'Далее']], 'captions':[[1,'amoCRM']], 'merge_into_previous':[1]})
        self.assertEqual([s['shot'] for s in revised['scenes']],[0,1])
        self.assertEqual(revised['scenes'][0]['text'],'Далее')
        self.assertEqual(revised['scenes'][0]['at']['word'],'amoCRM')
        self.assertEqual(revised['scenes'][0]['at']['after'],1)
        self.assertEqual(words['words'][1],{'w':'amoCRM','start':1,'end':2})
        self.assertEqual(self.plan['scenes'][0]['at'],{'word':'АМСРМ'})

    def test_rejects_out_of_scope_changes(self):
        for result in ({'slots':[[1,'Changed']], 'captions':[]},
                       {'slots':[], 'captions':[], 'merge_into_previous':[0]},
                       {'slots':[], 'captions':[[2,'word']]}):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.request(result)
