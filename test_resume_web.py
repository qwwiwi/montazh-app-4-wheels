import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import server


class ResumeWebTest(unittest.TestCase):
    def test_published_reviews_include_nested_recut_and_legacy_render(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for leaf, data in [
                ('attempt-5/review.json', {'checks': [], 'verdict':'REVISE'}),
                ('recut-1/take-1/stage-review.json', {'stage':'takes','checks':[], 'verdict':'PASS'}),
                ('recut-1/attempt-1/stage-review.json', {'stage':'storyboard','checks':[], 'verdict':'REVISE'}),
            ]:
                path = root/leaf
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(data))
            self.assertCountEqual([r['stage'] for r in server.stage_reports(root)], ['final','takes','storyboard'])

    def test_same_job_can_only_be_queued_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root/('a' * 32)
            job.mkdir()
            (job/'source.mov').touch()
            server.save(job, 'error', 'stopped')
            httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            worker = threading.Thread(target=httpd.serve_forever, daemon=True)
            worker.start()
            try:
                def request(_):
                    conn = http.client.HTTPConnection('127.0.0.1', httpd.server_port)
                    try:
                        conn.request('POST', '/api/jobs/'+job.name+'/resume')
                        response = conn.getresponse()
                        response.read()
                        return response.status
                    finally:
                        conn.close()
                with patch.object(server, 'JOBS', root), patch.object(server,'can_resume',return_value=True), patch.object(server,'budget_snapshot',return_value={'remaining_usd':0.98}), patch.object(server.POOL,'submit') as submit, ThreadPoolExecutor(max_workers=2) as clients:
                    self.assertEqual(sorted(clients.map(request,range(2))),[202,409])
                    submit.assert_called_once_with(server.process,job,job/'source.mov','full',True)
                    self.assertEqual(json.loads((job/'state.json').read_text())['status'],'queued')
            finally:
                httpd.shutdown()
                worker.join()
                httpd.server_close()
