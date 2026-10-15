"""Public HTTP assets must never expose repository or neighbouring files."""
from __future__ import annotations

import http.client
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import backend


class HttpStaticBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="edoc-static-boundary-")
        self.addCleanup(self.temp.cleanup)
        parent = Path(self.temp.name)
        self.root = parent / "site"
        self.root.mkdir()
        for name, contents in {
            "index.html": b"<title>isolated EDOC</title>",
            "app.js": b"window.isolated = true;",
            "styles.css": b"body { margin: 0; }",
            ".env": b"SYNTHETIC_PRIVATE_SENTINEL=not-a-real-secret",
            "backend.py": b"synthetic private source",
            "data/edoc.sqlite3": b"synthetic private database",
            "storage/private.pdf": b"synthetic private document",
            "assets/private.pdf": b"synthetic unlisted asset",
        }.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        (parent / "outside.txt").write_bytes(b"synthetic outside-root sentinel")
        self.root_patch = mock.patch.object(backend, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

        class QuietHandler(backend.Handler):
            def log_message(self, *_args):
                pass

        self.server = backend.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, method="GET", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def test_public_assets_and_cache_busting_still_work(self):
        for path in ("/", "/index.html", "/app.js?v=isolated", "/styles.css"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
        status, headers, body = self.request("/app.js", "HEAD")
        self.assertEqual(status, 200)
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertEqual(body, b"")

    def test_repository_and_unlisted_assets_are_not_public(self):
        for path in ("/.env", "/backend.py", "/data/edoc.sqlite3", "/storage/private.pdf", "/assets/private.pdf"):
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    status, _, body = self.request(path, method)
                    self.assertEqual(status, 404)
                    self.assertNotIn(b"synthetic", body)

    def test_traversal_and_directory_listing_are_denied(self):
        for path in ("/../outside.txt", "/%2e%2e/outside.txt", "/assets/../../outside.txt", "/assets/%2e%2e/backend.py", "/data/", "/assets/", "/app.js/"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"synthetic", body)
                self.assertNotIn(b"Directory listing", body)

    def test_allowlisted_symlinks_cannot_expose_private_files(self):
        (self.root / "app.js").unlink()
        for target in (self.root / ".env", self.root.parent / "outside.txt"):
            with self.subTest(target=target.name):
                link = self.root / "app.js"
                link.symlink_to(target)
                try:
                    self.assertEqual(self.request("/app.js")[0], 404)
                finally:
                    link.unlink()

    def test_api_head_does_not_fall_through_to_filesystem(self):
        for path in ("/api/../backend.py", "/api/%2e%2e/backend.py", "/api/health"):
            with self.subTest(path=path):
                status, _, body = self.request(path, "HEAD")
                self.assertEqual(status, 405)
                self.assertEqual(body, b"")

    def test_encoded_private_paths_and_noncanonical_separators_are_denied(self):
        # Exercise the HTTP parser as well as translate_path. All targets are
        # synthetic private fixtures; no production credentials are present.
        paths = (
            "/%2eenv", "/%62ackend.py", "/%252eenv", "/%2562ackend.py",
            "/%2e%2e%2foutside.txt", "/%252e%252e%252foutside.txt",
            "/assets%2f..%2fbackend.py", "/assets//../backend.py",
            "/assets/./../backend.py", "/assets%5c..%5cbackend.py",
            "/..%5coutside.txt", "/.%2e/outside.txt", "/%2e./outside.txt",
            "/%2e%2e%252foutside.txt", "/assets/%00/../backend.py",
            "/backend.py%00.js", "/app.js%00/../backend.py",
            "/app.js%2f..%2fbackend.py", "/app.js%3f/../backend.py",
            "/app.js%23/../backend.py", "/app.js%3b/../backend.py",
            "/backend.py?public=app.js", "/backend.py;app.js",
            "/vendor/tom-select/../../../backend.py", "/vendor/",
            "/assets/fonts/", "/assets/fonts/%2e%2e/%2e%2e/.env",
            "/app.js/", "/app.js%2f", "/%2fbackend.py", "/%5cbackend.py",
            "/%2e%2e/%2e%2e/outside.txt", "/%ef%bc%8e%ef%bc%8e/outside.txt",
            "//backend.py", "///backend.py", "/%2f../outside.txt",
            "http://untrusted.invalid/backend.py", "file:///backend.py",
            "/%61pi/../backend.py", "/%61pi/%2e%2e/backend.py",
        )
        for path in paths:
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    status, _, body = self.request(path, method)
                    self.assertEqual(status, 404)
                    self.assertNotIn(b"synthetic", body)
                    self.assertNotIn(b"Directory listing", body)

    def test_allowlisted_symlink_ancestor_cannot_expose_private_files(self):
        private_dir = self.root.parent / "private-fonts"
        private_dir.mkdir()
        (private_dir / "edukai-5.1_20251208.ttf").write_bytes(b"synthetic private font-path target")
        (self.root / "assets" / "fonts").symlink_to(private_dir, target_is_directory=True)
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                status, _, body = self.request("/assets/fonts/edukai-5.1_20251208.ttf", method)
                self.assertEqual(status, 404)
                self.assertNotIn(b"synthetic", body)

    def test_allowlisted_filename_cannot_turn_into_directory_listing(self):
        target = self.root / "app.js"
        target.unlink()
        target.mkdir()
        (target / "private.txt").write_bytes(b"synthetic private nested file")
        for path in ("/app.js", "/app.js/", "/app.js/private.txt"):
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    status, _, body = self.request(path, method)
                    self.assertEqual(status, 404)
                    self.assertNotIn(b"synthetic", body)
                    self.assertNotIn(b"Directory listing", body)

    def test_public_conditional_get_and_encoded_asset_path_still_work(self):
        status, headers, expected = self.request("/app.js")
        self.assertEqual(status, 200)
        for path in ("/%61pp.js", "/app.js?v=1&retry=2"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(body, expected)
        status, _, body = self.request("/app.js", headers={"If-Modified-Since": headers["Last-Modified"]})
        self.assertEqual(status, 304)
        self.assertEqual(body, b"")

    def test_every_deployed_public_asset_serves_real_bytes_for_get_and_head(self):
        repo = Path(__file__).resolve().parents[1]
        config = json.loads((repo / "vercel.json").read_text())
        public_assets = sorted(item["src"] for item in config["builds"] if item["use"] == "@vercel/static")
        with mock.patch.object(backend, "ROOT", repo):
            for name in public_assets:
                expected = (repo / name).read_bytes()
                for method in ("GET", "HEAD"):
                    with self.subTest(asset=name, method=method):
                        status, headers, body = self.request("/" + name + "?v=isolated-smoke", method)
                        self.assertEqual(status, 200)
                        self.assertEqual(int(headers["Content-Length"]), len(expected))
                        if method == "GET":
                            self.assertEqual(hashlib.sha256(body).digest(), hashlib.sha256(expected).digest())
                        else:
                            self.assertEqual(body, b"")
                        if name.endswith((".mjs", ".js")):
                            self.assertIn("javascript", headers["Content-Type"])
                        elif name.endswith(".css"):
                            self.assertEqual(headers["Content-Type"], "text/css")
                        elif name.endswith(".png"):
                            self.assertEqual(headers["Content-Type"], "image/png")

    def test_public_allowlist_matches_deployment_manifest(self):
        repo = Path(__file__).resolve().parents[1]
        config = json.loads((repo / "vercel.json").read_text())
        expected = {item["src"] for item in config["builds"] if item["use"] == "@vercel/static"}
        self.assertEqual(set(backend.PUBLIC_STATIC_FILES), expected)


if __name__ == "__main__":
    unittest.main()
