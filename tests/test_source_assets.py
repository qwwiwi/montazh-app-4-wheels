from pathlib import Path
import tempfile
import subprocess
import unittest

from source_assets import _match, ingest, source_manifest, attach_source, clean_metadata

class SourceTests(unittest.TestCase):
    def test_real_image_timeline_and_escaped_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); project=p/'project'; (project/'assets').mkdir(parents=True)
            data=subprocess.check_output(['ffmpeg','-loglevel','error','-f','lavfi','-i','color=size=320x240',
                                          '-frames:v','1','-c:v','png','-f','image2pipe','-'])
            meta=clean_metadata('A&B','amoCRM','https://example.org/article','news')
            ingest(p/'src',data,meta)
            words={'duration':12,'words':[{'w':'Вот','start':0},{'w':'АМСРМ,','start':2},{'w':'CRM','start':5}]}
            self.assertEqual(_match(words['words'],'amoCRM'),1)
            self.assertIsNone(_match([{'w':'CRM'}],'amoCRM'))
            bundle=(p/'src',meta,1)
            manifest=source_manifest(bundle,words,{'source_cues':[{'word_index':1,'duration':2},{'word_index':2,'duration':4}]})
            (project/'index.html').write_text('</div>\n<script>\nwindow.__timelines["reel"] = tl;')
            attach_source(project,p/'src',manifest)
            html=(project/'index.html').read_text()
            self.assertIn('A&amp;B · example.org',html)
            self.assertEqual(html.count('tl.set('),4)
            self.assertTrue((project/'assets/cited-source-0.png').is_file())
            with self.assertRaises(ValueError):ingest(p/'bad',b'<svg></svg>',meta)
            with self.assertRaises(ValueError):source_manifest(bundle,words,{'source_cues':[{'word_index':1,'duration':4},{'word_index':2,'duration':3}]})
            with self.assertRaises(ValueError):clean_metadata('A','brand','javascript:alert(1)','website')

    def test_news_cues_follow_sped_up_transcript_and_available_assets(self):
        from source_assets import suggested_cues
        from real_media import evidence,review_metrics
        spoken='Google выпустил новый Gemini Neon сегодня Теперь рассмотрим результаты теста GraphWalks Посмотрим эту строку В Cursor модель впереди'.split()
        words={'words':[{'w':w,'start':i*.8} for i,w in enumerate(spoken)],'duration':15}
        def asset(key, phrases):
            return {'id':key,'cue_phrases':phrases,'source_url':'https://habr.com/ru/articles/1/',
                    'kind':'news','title':key,'credit':'habr.com','rights':'credited screenshot'}
        meta=asset('article',['Google выпустил'])
        meta['related_sources']=[asset('table',['результаты теста']),asset('graph',['GraphWalks']),
                                 asset('coding',['В Cursor']),asset('other',['рейтинг моделей'])]
        material=(None,meta,None)
        proposed=suggested_cues(material,words)
        self.assertEqual([c['asset_id'] for c in proposed],['article','table','graph','coding'])
        manifest=source_manifest(material,words,{})
        self.assertEqual([round(c['start'],1) for c in manifest['placements']],[0,6.4,8.0,11.2])
        self.assertGreaterEqual(review_metrics(evidence(manifest,[{'start':0,'end':15,'type':'visual'}]))['share'],.30)
        authored=source_manifest(material,words,{'source_cues':[{'asset_id':'graph','word_index':10,'duration':2}]})
        self.assertEqual(len(authored['placements']),1)
