import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

import source_scene


class SourceSceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = bytes.fromhex("89504e470d0a1a0a") + b"fixture"
        (self.root/"source.png").write_bytes(self.image)
        self.digest = hashlib.sha256(self.image).hexdigest()
        self.asset = {"id":"news", "kind":"news", "title":"Public chart", "credit":"Publisher",
                      "screenshot_sha256":self.digest}
        self.words = {"duration":4, "words":[{"w":"Results", "start":0, "end":1}]}
        self.plan = {"shots":[{"from":0, "type":"split", "source":"news"}], "scenes":[],
                     "source_cues":[{"asset_id":"news", "word_index":0, "duration":4}]}
        self.rp = SimpleNamespace(LEAD=.06, snap=lambda t:t, resolve=lambda ref,*_,**kw:ref)

    def adapt(self):
        with source_scene.using_material((self.root,self.asset,0)):
            return source_scene.adapt(self.plan,self.words,self.rp,[])

    def test_verified_image_and_visible_credit_are_the_native_scene(self):
        native, manifest = self.adapt()
        self.assertEqual(self.plan["scenes"], [])
        self.assertEqual(manifest["placements"][0]["native_shot"], 0)
        target = self.root/"assets"
        target.mkdir()
        source_scene.prepare_images(self.root,target,manifest)
        scene = native["scenes"][0]
        builder=Mock(ctx=SimpleNamespace(assets_dir=target), t0=0)
        builder.asset.return_value="assets/sources/fixture.png"
        source_scene.build(builder,scene)
        markup=builder.add.call_args.args[0]
        self.assertIn('<img src="assets/sources/fixture.png"',markup)
        self.assertIn('Public chart · Publisher',markup)
        (target/(self.digest+".png")).write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError,"pixels"):
            source_scene.build(builder,scene)

    def test_unknown_or_partial_placement_does_not_fill_a_shot(self):
        self.plan["shots"][0]["source"] = "unknown"
        with self.assertRaisesRegex(ValueError, "explicit word cue"):
            self.adapt()
        self.plan["shots"][0]["source"] = "news"
        self.plan["source_cues"][0]["duration"] = 2
        with self.assertRaisesRegex(ValueError, "explicit word cue"):
            self.adapt()
        self.plan["shots"][0].pop("source")
        native, manifest = self.adapt()
        self.assertEqual(native["scenes"], [])
        self.assertNotIn("native_shot",manifest["placements"][0])

    def test_renderer_kind_cannot_be_supplied_directly(self):
        self.plan["scenes"] = [{"kind":source_scene.KIND, "shot":0, "digest":"anything"}]
        with self.assertRaisesRegex(ValueError, "derived"):
            self.adapt()
