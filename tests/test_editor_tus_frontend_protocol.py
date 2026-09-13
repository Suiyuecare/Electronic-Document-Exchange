"""Fast transport harness checks; the CI gate additionally uses real Storage."""
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import threading
import unittest

from tests.support.local_supabase_editor_filename_gate import pdf_bytes, run_frontend


class EditorTusFrontendProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uploaded = bytearray()
        cls.expected_path = ''
        cls.request_metadata = []
        cls.unsafe_headers = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                cls.unsafe_headers.append(bool(self.headers.get('Authorization') or self.headers.get('x-upsert')))
                metadata = dict(item.split(' ', 1) for item in self.headers['Upload-Metadata'].split(','))
                values = {key: base64.b64decode(value).decode('utf-8') for key, value in metadata.items()}
                cls.request_metadata.append(values)
                if not re.fullmatch(r"[A-Za-z0-9_/!.*'() &$=@;:+,?-]+", values['objectName']):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'Invalid key: synthetic-redacted')
                    return
                if values['objectName'] != cls.expected_path:
                    self.send_response(403)
                    self.end_headers()
                    return
                cls.uploaded.clear()
                self.send_response(201)
                self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/storage/v1/upload/resumable/sign/session')
                self.send_header('Upload-Offset', '0')
                self.end_headers()

            def do_PATCH(self):
                if int(self.headers['Upload-Offset']) != len(cls.uploaded):
                    self.send_response(409)
                    self.end_headers()
                    return
                cls.uploaded.extend(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(204)
                self.send_header('Upload-Offset', str(len(cls.uploaded)))
                self.end_headers()

            def do_HEAD(self):
                self.send_response(200)
                self.send_header('Upload-Offset', str(len(cls.uploaded)))
                self.end_headers()

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.uploaded.clear()
        self.request_metadata.clear()
        self.unsafe_headers.clear()

    def intent(self, object_name):
        return {
            'protocol': 'tus',
            'upload_url': f'{self.url}/storage/v1/upload/resumable/sign',
            'upload_token': 'ci-synthetic-object-signature',
            'storage_publishable_key': 'sb_publishable_ci_synthetic',
            'bucket': 'edoc-private', 'path': object_name,
            'content_type': 'application/pdf', 'cache_control': '0',
        }

    def test_actual_client_reproduces_plain_text_invalid_key_response(self):
        data = pdf_bytes()
        result = run_frontend(self.url, self.intent('editor/CI/驗收 [50%].pdf'), data,
                              '驗收 [50%].pdf', 'application/pdf')
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 400)
        self.assertEqual(result['code'], 'editor_tus_invalid_object_key')
        self.assertTrue(result['invalidKeyRejected'])
        self.assertEqual(result['trace'], [{'method': 'POST', 'status': 400}])
        self.assertEqual(len(self.uploaded), 0)

    def test_actual_client_preserves_unicode_name_with_opaque_key_and_resumes(self):
        data = pdf_bytes(large=True)
        type(self).expected_path = 'editor/CI/ASSET-123.pdf'
        result = run_frontend(self.url, self.intent(self.expected_path), data,
                              '驗收 📄 [50%].pdf', 'application/pdf', interrupt=True)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['fileNamePreserved'])
        self.assertTrue(result['interrupted'])
        self.assertTrue(result['progressComplete'])
        self.assertEqual(bytes(self.uploaded), data)
        self.assertTrue(any(row['method'] == 'HEAD' for row in result['trace']))
        self.assertGreaterEqual(sum(row['method'] == 'PATCH' for row in result['trace']), 2)
        self.assertFalse(any(self.unsafe_headers))
        self.assertEqual(self.request_metadata[0], {
            'bucketName': 'edoc-private', 'objectName': self.expected_path,
            'contentType': 'application/pdf', 'cacheControl': '0',
        })

    def test_transport_cannot_contact_hosted_storage(self):
        runner = Path(__file__).parent / 'support/editor_tus_frontend_runner.cjs'
        completed = subprocess.run(['node', str(runner)], input=json.dumps({
            'localOrigin': 'https://example.supabase.co',
        }), text=True, capture_output=True, check=False, timeout=10)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)['code'], 'isolated_client_runner_failed')


if __name__ == '__main__':
    unittest.main()
