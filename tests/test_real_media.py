from unittest import TestCase

from real_media import apply_mix, evidence, review_metrics


class SourceMediaGolden(TestCase):
    def proof(self, spans, kind='website', rights='CC0'):
        assets=[{'id':'site','kind':kind,'source_url':'https://example.org/news','rights':rights}]
        placements=[{'asset_id':'site','start':a,'end':b} for a,b in spans]
        return evidence({'assets':assets,'placements':placements},[
            {'type':'speaker','start':0,'end':10},{'type':'split','start':10,'end':20},
            {'type':'visual','start':20,'end':30}])

    def test_speaker_is_excluded_and_overlaps_count_once(self):
        m=review_metrics(self.proof([(0,14),(13,16)]))
        self.assertEqual(m,{'illustration_seconds':20,'qualified_seconds':6,'qualified_intervals':[[10,16]],'share':.30})

    def test_invisible_or_untraceable_sources_cannot_pass(self):
        for kind,rights,spans in [('website','CC0',[(10,15.9)]),('logo','CC0',[(10,30)]),
                                  ('photo','',[(10,30)]),('footage','CC0',[])]:
            row={'verdict':'PASS','evidence':'Example.','observed_intervals':[{'asset_id':'site','start':a,'end':b} for a,b in spans]}
            apply_mix(row,self.proof([(10,30)],kind,rights),final=True)
            self.assertNotEqual(row['verdict'],'PASS')

    def test_observations_must_correspond_to_same_sourced_asset(self):
        proof=self.proof([(13,19)])
        for aid,start,end,status in [('site',10,20,'PASS'),('invented',10,30,'REVISE'),('site',19,30,'REVISE')]:
            row={'verdict':'PASS','evidence':'Example.','observed_intervals':[{'asset_id':aid,'start':start,'end':end}]}
            apply_mix(row,proof,final=True)
            self.assertEqual(row['verdict'],status)
        row={'verdict':'PASS','evidence':'No timing.'}
        apply_mix(row,proof,final=True)
        self.assertEqual(row['verdict'],'UNVERIFIED')

    def test_half_is_target_not_ceiling(self):
        row={'verdict':'PASS','evidence':'Relevant photo.'}
        apply_mix(row,self.proof([(10,28)],kind='photo'),final=False)
        self.assertEqual(row['verdict'],'PASS')
