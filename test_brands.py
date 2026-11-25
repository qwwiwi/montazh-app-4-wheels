import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET

from brands import prepare_brands, safe_svg


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 21"><path d="M0 0h2v2Z"/></svg>'


class BrandTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.catalog=self.root/'catalog.json'
        (self.root/'mark.svg').write_text(SVG)

    def brand(self,i,n,aliases=None,file='mark.svg',**extra):
        return dict(id=i,name=n,aliases=aliases or [],file=file,source='owner',**extra)

    def run_case(self,entries,words,candidates=None):
        self.catalog.write_text(json.dumps({'brands':entries}))
        data={'words':[{'w':w,'start':i/2,'end':(i+1)/2} for i,w in enumerate(words)]}
        return prepare_brands(data,self.catalog,self.root/'out',candidates=candidates)

    def test_official_model_and_company_logos_and_provenance(self):
        from prepare_libraries import install_official_ai_marks
        import hashlib
        entries = install_official_ai_marks(self.root)
        result = self.run_case(entries, ["Клода", "и", "Claude", "Opus", "5.5", "сравнили",
                                         "с", "Джеминай", "в", "Антропике"])
        self.assertEqual([m["id"] for m in result["mentions"]], [
            "official:claude", "official:claude-opus", "official:gemini", "official:anthropic"])
        marks = result["mentions"]
        self.assertEqual(marks[1]["mark_family"], "Claude")
        self.assertEqual(marks[0]["sha256"], marks[1]["sha256"])
        self.assertEqual((marks[1]["word_start"], marks[1]["word_end"]), (2, 4))
        for mark in marks:
            self.assertEqual(mark["source"], "official-brand-site")
            self.assertTrue(mark["source_url"].startswith("https://"))
            self.assertEqual(mark["sha256"], hashlib.sha256((self.root/"out"/mark["file"]).read_bytes()).hexdigest())

    def test_bare_opus_requires_model_context_or_editor_approval(self):
        from prepare_libraries import install_official_ai_marks
        entries = install_official_ai_marks(self.root)
        self.assertEqual(self.run_case(entries, ["кодек", "Opus"])["mentions"], [])
        self.assertEqual(self.run_case(entries, ["опус", "композитора"])["mentions"], [])
        for words, approved in ((["модель", "Опус"], None), (["у", "Опуса"], [{"first":1,"last":1}])):
            marks = self.run_case(entries, words, approved)["mentions"]
            self.assertEqual([m["id"] for m in marks], ["official:claude-opus"])

    def test_cyrillic_longest_phrase_and_latin_casefold(self):
        r=self.run_case([self.brand("claude","Claude",["Claude","Клод"]),
                         self.brand("claude-code","Claude Code",["Клод Код"])],
                        ["Открываю","КЛОД","код,","потом","Claude!","клодовый"])
        self.assertEqual([m['id'] for m in r['mentions']],['claude-code','claude'])
        self.assertEqual((r['mentions'][0]['start'],r['mentions'][0]['end']),(.5,1.5))
        self.assertEqual(r['unresolved'],[])
        mark=ET.parse(self.root/'out/claude-code.svg').getroot()
        self.assertEqual(mark.get('viewBox'),'0 0 44 21')
        self.assertEqual(mark.get('preserveAspectRatio'),'xMidYMid meet')

    def test_exact_word_boundaries_and_disabled_generic_brand(self):
        r=self.run_case([self.brand('x','X',auto_match=False),self.brand('openai','OpenAI')],
                        ['X','OpenAICloud','OpenAI'])
        self.assertEqual([m['id'] for m in r['mentions']],['openai'])

    def test_contextual_go_only_at_designated_occurrence(self):
        entries=[self.brand("simple:go","Go",auto_match=False)]
        r=self.run_case(entries,["go","then","Go"],candidates=[{"first":2,"last":2}])
        self.assertEqual([m["word_start"] for m in r["mentions"]],[2])
        self.assertTrue((self.root/'out'/r['mentions'][0]['file']).is_file())
        self.assertEqual(self.run_case(entries,['Go'])['mentions'],[])

    def test_exclusive_alias_and_ambiguous_unknown(self):
        entries=[self.brand("russian:test/word","Мир",["Карта Мир"])]
        r=self.run_case(entries,["мир","Карта","Мир","Бренд"],[{"first":3,"last":3}])
        self.assertEqual(len(r['mentions']),1)
        self.assertEqual(r['mentions'][0]['word_start'],1)
        self.assertEqual(r['unresolved'][0]['reason'],'no_catalog_match')

    def test_contextual_does_not_override_an_exact_curated_alias(self):
        entries=[self.brand("simple:vk","VK",auto_match=False),self.brand("russian:social/vk","VK",["VK","ВК"])]
        r=self.run_case(entries,["VK"],[{"first":0,"last":0}])
        self.assertEqual([m["id"] for m in r["mentions"]],["russian:social/vk"])

    def test_same_alias_of_two_brands_stays_unresolved(self):
        result=self.run_case([self.brand('one','Один',['Код']),self.brand('two','Два',['Код'])],['Код'])
        self.assertEqual(result['mentions'],[])
        self.assertEqual(result['unresolved'][0]['ids'],['one','two'])

    def test_crossing_compound_names_need_disambiguation(self):
        result=self.run_case([self.brand('aa','Alpha Beta'),self.brand('bb','Beta Gamma')],['Alpha','Beta','Gamma'])
        self.assertEqual(result['unresolved'][0]['reason'],'ambiguous_alias')

    def test_missing_and_untrusted_assets(self):
        (self.root/'other.svg').write_text('<svg viewBox="0 0 10 10"><image href="https://example.org/image"/></svg>')
        result=self.run_case([self.brand('one','One',file='absent.svg'),
                              self.brand('two','Two',file='other.svg'),
                              self.brand('three','Three',file='../one.svg')],['one','two','three'])
        self.assertEqual([r['reason'] for r in result['unresolved']],['missing_asset','unsafe_asset','unsafe_asset'])
        self.assertFalse((self.root/'out').exists())

    def test_safe_internal_paint_reference(self):
        src='<svg width="30" height="15"><defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs><path fill="url(#g)" d="M0 0"/></svg>'
        self.assertEqual(ET.fromstring(safe_svg(src.encode())).get('viewBox'),'0 0 30 15')

    def test_static_class_and_inline_paint(self):
        svg='<svg viewBox="0 0 1 1"><style>.mark {fill:#aabbcc;stroke:none}</style><path class="mark" style="fill:#112233" d="M0 0"/></svg>'
        tree=ET.fromstring(safe_svg(svg.encode()))
        self.assertEqual(tree[0].get('fill'),'#112233')
        self.assertEqual(tree[0].get('stroke'),'none')
        self.assertNotIn('style',tree[0].attrib)

    def test_no_script_styles_unknown_urls_or_entities(self):
        for svg in ['<svg viewBox="0 0 1 1"><style>path{fill:red}</style></svg>',
                    '<svg viewBox="0 0 1 1"><path fill="url(other.svg)" /></svg>',
                    '<!DOCTYPE svg><svg viewBox="0 0 1 1"/>',
                    '<svg viewBox="0 0 NaN 1"/>']:
            with self.subTest(svg=svg),self.assertRaises(ValueError):
                safe_svg(svg.encode())
