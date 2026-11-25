import unittest
from timeline_transfer import _project


class TransferTests(unittest.TestCase):
    def test_kept_media_maps_back_through_source_and_deleted_gap_collapses(self):
        old = [{'src':[1,5], 'cut':[0,4]}, {'src':[7,10], 'cut':[4,7]}]
        new = [{'src':[1,3], 'cut':[0,2]}, {'src':[7,10], 'cut':[2,5]}]
        def project(value):
            return _project(_project(value, old, 'cut', 'src'), new, 'src', 'cut')
        self.assertEqual(project(3), 2)
        self.assertEqual(project(5), 3)

    def test_speed_preserves_source_time_and_projects_cuts_at_different_rates(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import full_edit as editor
        with tempfile.TemporaryDirectory() as temp:
            cut = Path(temp)/'cut.mp4'
            def join(*args):
                unpaced = args[-1]
                editor.write(unpaced.with_suffix('.map.json'), {'source_duration':10,'cut_duration':7,
                             'pieces':[{'src':[1,5],'cut':[0,4]}, {'src':[7,10],'cut':[4,7]}], 'removed':[[0,1],[5,7]]})
                unpaced.touch()
            with patch.object(editor,'accelerate',side_effect=lambda src,dst,speed:dst.touch()):
                editor.freeze_paced_cut(Path('raw'),Path('keep'),cut,1.4,join,lambda _:None)
            mapping = editor.read(cut.with_suffix('.map.json'))
            self.assertEqual(mapping['removed'], [[0,1],[5,7]])
            self.assertEqual(mapping['cut_duration'],5)
            self.assertEqual(mapping['source_duration'],10)
            self.assertEqual(_project(10,mapping['pieces'],'src','cut'),5)
            self.assertAlmostEqual(_project(4/1.4,mapping['pieces'],'cut','src'),5)

    def test_head_and_tail_map_to_nearest_boundaries(self):
        pieces = [{'src':[2,5],'cut':[0,3]}]
        self.assertEqual(_project(1, pieces, 'src','cut'),0)
        self.assertEqual(_project(5.2, pieces,'src','cut'),3)
