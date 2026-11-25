from unittest import TestCase
from brand_golden import apply, proof, pinned_assets


class LogoReviewTests(TestCase):
    def setUp(self):
        self.words={'words':[{'w':'Gemini','start':1,'end':2}]}
        self.cue=dict(id='official:gemini',name='Gemini',file='gemini.svg',start=1,end=2,
                      source='official-brand-site',source_url=pinned_assets()['official:gemini']['source_url'],sha256=pinned_assets()['official:gemini']['sha256'])
        self.obs=dict(id='official:gemini',start=1,end=2.2,evidence='Four-point gradient silhouette above the subtitles.')

    def result(self,cues,observations):
        row={'verdict':'PASS','observed_logos':observations}
        apply(row,proof(self.words,{'mentions':cues}),4)
        return row

    def test_required_even_if_resolver_returns_no_cues(self):
        row=self.result([],[])
        self.assertEqual((row['verdict'],row['start'],row['end']),('REVISE',1,2))
        self.assertIn('Gemini',row['fix'])

    def test_source_and_visible_identity_and_word_overlap_are_all_required(self):
        self.assertEqual(self.result([self.cue],[self.obs])['verdict'],'PASS')
        for cue,obs in [(dict(self.cue,sha256=''),self.obs),(self.cue,dict(self.obs,id='official:anthropic')),
                        (self.cue,dict(self.obs,start=2,end=3)),(self.cue,dict(self.obs,evidence=''))]:
            self.assertEqual(self.result([cue],[obs])['verdict'],'REVISE')

    def test_claude_opus_uses_family_mark_and_no_corporate_substitution(self):
        self.words['words'][0]['w']='Клод'
        cue=dict(self.cue, **{k:pinned_assets()['official:claude-opus'][k] for k in ('id','name','source_url','sha256')})
        self.assertEqual(self.result([cue],[dict(self.obs,id=cue['id'])])['verdict'],'PASS')
        cue=dict(cue,id='official:anthropic')
        self.assertEqual(self.result([cue],[dict(self.obs,id=cue['id'])])['verdict'],'REVISE')

    def test_ordinary_speech_does_not_require_logo(self):
        self.words['words'][0]['w']='музыка'
        self.assertEqual(self.result([],[])['verdict'],'PASS')
