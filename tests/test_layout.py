"""The repository layout: the demo runs over HTTP and every default resource path resolves."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest import TestCase
from unittest.mock import patch

import brand_golden
import full_edit
import prepare_libraries
import server
import source_assets

REPO = Path(__file__).resolve().parent.parent


class DemoOverHttpTests(TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.pool = ThreadPoolExecutor(max_workers=1)
        for patcher in (patch.object(server, "JOBS", Path(temp.name)), patch.object(server, "POOL", self.pool)):
            patcher.start()
            self.addCleanup(patcher.stop)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = httpd.server_port
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

    def request(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_pages_and_demo_clip_go_through_local_editing(self) -> None:
        self.assertEqual(self.request("GET", "/"), (200, (REPO / "index.html").read_bytes()))
        self.assertEqual(self.request("GET", "/pipeline"), (200, (REPO / "pipeline.html").read_bytes()))
        status, clip = self.request("GET", "/demo.mp4")
        self.assertEqual((status, clip), (200, (REPO / "assets/demo.mp4").read_bytes()))

        status, body = self.request("POST", "/api/jobs?mode=local&speed=1.3&filename=demo.mp4", clip)
        self.assertEqual(status, 202, body)
        job = json.loads(body)["id"]
        self.pool.shutdown(wait=True)

        state = json.loads(self.request("GET", f"/api/jobs/{job}")[1])
        self.assertEqual(state["status"], "ready", state)
        self.assertLess(state["result"]["output_seconds"], state["result"]["original_seconds"])
        status, movie = self.request("GET", f"/api/jobs/{job}/download")
        self.assertEqual((status, movie[4:8]), (200, b"ftyp"))


class DefaultPathTests(TestCase):
    def test_full_mode_defaults_point_at_repository_resources(self) -> None:
        with patch.dict(os.environ):
            for name in ("REEL_SKILL", "REEL_REFERENCE_DIR", "REEL_LIBRARIES"):
                os.environ.pop(name, None)
            skill, _, refs = full_edit.settings()
            self.assertEqual(full_edit.libraries(), REPO.parent / "reel-libraries")
        self.assertTrue((skill / "scripts/reel.py").is_file())
        self.assertEqual(refs, [REPO / "references" / f"{name}.mp4" for name in "ABC"])
        self.assertTrue(full_edit.RUBRIC.is_file())
        for name in ("source_scene.py", "local_transcript.py", "render_qa.py", "article_capture.cjs"):
            self.assertTrue((full_edit.HERE / name).is_file(), name)
        self.assertIn("official:claude", brand_golden.pinned_assets())
        self.assertTrue((prepare_libraries.OFFICIAL_MEDIA / "ai-brands/catalog.json").is_file())
        # The optional amoCRM bundle is written next to its preparation script.
        self.assertTrue((source_assets.AMO_BUNDLE.parent / "prepare-amocrm.py").is_file())
