import hashlib
import hmac
import importlib.util
import json
import os
import socketserver
import struct
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "services" / "clamav-scanner" / "scanner.py"
SERVICE_DIR = MODULE_PATH.parent
SPEC = importlib.util.spec_from_file_location("edoc_cloud_run_scanner", MODULE_PATH)
scanner = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(scanner)


class _ClamdHandler(socketserver.BaseRequestHandler):
    def handle(self):
        command = self._read_until_null()
        if command == b"zPING\0":
            self.request.sendall(b"PONG\0")
            return
        if command != b"zINSTREAM\0":
            return
        payload = bytearray()
        while True:
            size = struct.unpack("!I", self._read_exact(4))[0]
            if size == 0:
                break
            payload.extend(self._read_exact(size))
        self.server.payloads.append(bytes(payload))
        response = b"stream: Eicar-Test-Signature FOUND\0" if b"infected" in payload else b"stream: OK\0"
        self.request.sendall(response)

    def _read_until_null(self):
        result = bytearray()
        while not result.endswith(b"\0"):
            result.extend(self.request.recv(1))
        return bytes(result)

    def _read_exact(self, size):
        result = bytearray()
        while len(result) < size:
            result.extend(self.request.recv(size - len(result)))
        return bytes(result)


class _ClamdServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _ClamdHandler)
        self.payloads = []


class CloudRunScannerContractTestCase(unittest.TestCase):
    def setUp(self):
        self.secret = "private-av-test-secret-" + "x" * 32
        self.clamd = _ClamdServer()
        self.clamd_thread = threading.Thread(target=self.clamd.serve_forever, daemon=True)
        self.clamd_thread.start()
        self.env = mock.patch.dict(os.environ, {
            "EDOC_AV_SHARED_SECRET": self.secret,
            "EDOC_AV_ALLOWED_SOURCE_HOSTS": "project-ref.supabase.co",
            "CLAMD_HOST": "127.0.0.1",
            "CLAMD_PORT": str(self.clamd.server_address[1]),
            "EDOC_AV_MAX_FILE_SIZE_MB": "50",
            "EDOC_AV_INLINE_MAX_MB": "4",
        })
        self.env.start()
        scanner.REPLAY_CACHE = scanner.ReplayCache()
        self.http = scanner.ThreadingHTTPServer(("127.0.0.1", 0), scanner.Handler)
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.http_thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.http_thread.join(timeout=2)
        self.clamd.shutdown()
        self.clamd.server_close()
        self.clamd_thread.join(timeout=2)
        self.env.stop()

    def signed_request(self, payload: bytes, nonce: str, *, signature_override: str = ""):
        timestamp = str(int(time.time()))
        body_sha256 = hashlib.sha256(payload).hexdigest()
        signature = "v1=" + hmac.new(
            self.secret.encode(),
            scanner.request_signing_message(timestamp, nonce, body_sha256),
            hashlib.sha256,
        ).hexdigest()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.http.server_address[1]}/v1/scan",
            data=payload,
            headers={
                "Content-Type": "application/octet-stream",
                "X-EDOC-AV-Timestamp": timestamp,
                "X-EDOC-AV-Nonce": nonce,
                "X-EDOC-AV-Body-SHA256": body_sha256,
                "X-EDOC-AV-Content-SHA256": body_sha256,
                "X-EDOC-AV-Content-Length": str(len(payload)),
                "X-EDOC-AV-Signature": signature_override or signature,
            },
            method="POST",
        )
        return request

    def test_clean_and_infected_results_are_hmac_signed(self):
        for payload, expected_status in ((b"clean pdf", "clean"), (b"infected pdf", "infected")):
            nonce = hashlib.sha256(payload).hexdigest()[:32]
            with urllib.request.urlopen(self.signed_request(payload, nonce), timeout=2) as response:
                raw = response.read()
                result = json.loads(raw)
                self.assertEqual(result["status"], expected_status)
                response_timestamp = response.headers["X-EDOC-AV-Response-Timestamp"]
                expected_signature = "v1=" + hmac.new(
                    self.secret.encode(),
                    scanner.response_signing_message(
                        response_timestamp,
                        nonce,
                        hashlib.sha256(raw).hexdigest(),
                    ),
                    hashlib.sha256,
                ).hexdigest()
                self.assertEqual(response.headers["X-EDOC-AV-Response-Signature"], expected_signature)
        self.assertEqual(self.clamd.payloads, [b"clean pdf", b"infected pdf"])

    def test_forged_signature_never_reaches_clamd(self):
        request = self.signed_request(b"private bytes", "1" * 32, signature_override="v1=" + "0" * 64)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 401)
        self.assertEqual(self.clamd.payloads, [])

    def test_replayed_nonce_is_rejected(self):
        request = self.signed_request(b"same bytes", "2" * 32)
        with urllib.request.urlopen(request, timeout=2):
            pass
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.signed_request(b"same bytes", "2" * 32), timeout=2)
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(self.clamd.payloads, [b"same bytes"])

    def test_content_hash_mismatch_is_rejected_after_scan(self):
        request = self.signed_request(b"actual bytes", "3" * 32)
        request.headers["X-edoc-av-content-sha256"] = hashlib.sha256(b"different").hexdigest()
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 422)
        self.assertEqual(self.clamd.payloads, [b"actual bytes"])

    def test_expired_envelope_is_rejected_before_scan(self):
        payload = b"private bytes"
        nonce = "4" * 32
        timestamp = str(int(time.time()) - 120)
        body_sha256 = hashlib.sha256(payload).hexdigest()
        signature = "v1=" + hmac.new(
            self.secret.encode(),
            scanner.request_signing_message(timestamp, nonce, body_sha256),
            hashlib.sha256,
        ).hexdigest()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.http.server_address[1]}/v1/scan",
            data=payload,
            headers={
                "Content-Type": "application/octet-stream",
                "X-EDOC-AV-Timestamp": timestamp,
                "X-EDOC-AV-Nonce": nonce,
                "X-EDOC-AV-Body-SHA256": body_sha256,
                "X-EDOC-AV-Content-SHA256": body_sha256,
                "X-EDOC-AV-Content-Length": str(len(payload)),
                "X-EDOC-AV-Signature": signature,
            },
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 401)
        self.assertEqual(self.clamd.payloads, [])

    def test_source_url_allowlist_blocks_ssrf_shapes(self):
        self.assertEqual(
            scanner.validate_source_url(
                "https://project-ref.supabase.co/storage/v1/object/sign/edoc-private/path?token=short"
            ),
            "https://project-ref.supabase.co/storage/v1/object/sign/edoc-private/path?token=short",
        )
        for value in (
            "http://project-ref.supabase.co/storage/v1/object/sign/x?token=x",
            "https://127.0.0.1/storage/v1/object/sign/x?token=x",
            "https://project-ref.supabase.co.evil.test/storage/v1/object/sign/x?token=x",
            "https://project-ref.supabase.co/rest/v1/users?token=x",
            "https://user@project-ref.supabase.co/storage/v1/object/sign/x?token=x",
        ):
            with self.assertRaises(scanner.ScanContractError):
                scanner.validate_source_url(value)

    def test_deployment_uses_pinned_official_image_and_secret_manager(self):
        dockerfile = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")
        deploy = (SERVICE_DIR / "deploy-cloud-run.sh").read_text(encoding="utf-8")
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("FROM clamav/clamav:1.4", dockerfile)
        self.assertNotIn("clamav:latest", dockerfile)
        self.assertIn("--set-secrets", deploy)
        self.assertNotIn("--set-env-vars EDOC_AV_SHARED_SECRET", deploy)
        self.assertIn("--min-instances 1", deploy)
        self.assertIn("def log_message", source)
        self.assertNotIn("print(self.path", source)


if __name__ == "__main__":
    unittest.main()
