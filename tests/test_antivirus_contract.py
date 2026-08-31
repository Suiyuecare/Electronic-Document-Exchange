import socketserver
import struct
import threading
import unittest
import hashlib
import hmac
import json
import os
import time
import types
from unittest import mock

import backend


class _ClamdHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        command = b""
        while not command.endswith(b"\0"):
            block = self.request.recv(1)
            if not block:
                return
            command += block
        if command != b"zINSTREAM\0":
            return

        payload = bytearray()
        while True:
            raw_size = self._read_exact(4)
            if raw_size is None:
                return
            size = struct.unpack("!I", raw_size)[0]
            if size == 0:
                break
            chunk = self._read_exact(size)
            if chunk is None:
                return
            payload.extend(chunk)

        self.server.received_payloads.append(bytes(payload))
        self.request.sendall(self.server.response)

    def _read_exact(self, size: int):
        result = bytearray()
        while len(result) < size:
            block = self.request.recv(size - len(result))
            if not block:
                return None
            result.extend(block)
        return bytes(result)


class _ClamdServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, response: bytes):
        super().__init__(("127.0.0.1", 0), _ClamdHandler)
        self.response = response
        self.received_payloads = []


class ProductionAntivirusContractTestCase(unittest.TestCase):
    def run_scanner(self, response: bytes, payload: bytes = b"safe pdf bytes"):
        server = _ClamdServer(response)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"tcp://127.0.0.1:{server.server_address[1]}"
        try:
            with (
                mock.patch.object(backend, "is_production", return_value=True),
                mock.patch.object(backend, "EDOC_AV_ENDPOINT", endpoint),
                mock.patch.object(backend, "EDOC_AV_TIMEOUT_SECONDS", 2),
            ):
                result = backend.editor_scan_bytes_for_threats(payload, "document.pdf")
            return result, server.received_payloads
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_clean_file_uses_clamd_instream_and_passes_exact_bytes(self) -> None:
        result, received = self.run_scanner(b"stream: OK\0", b"%PDF clean")
        self.assertEqual(result, ("已通過", "ClamAV-Clean"))
        self.assertEqual(received, [b"%PDF clean"])

    def test_malware_signature_is_quarantined_and_safely_normalized(self) -> None:
        result, _ = self.run_scanner(b"stream: Eicar Test Signature FOUND\0")
        self.assertEqual(result, ("已隔離", "Eicar-Test-Signature"))

    def test_unknown_or_malformed_scanner_response_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "editor_antivirus_scan_failed"):
            self.run_scanner(b"stream: UNKNOWN\0")

    def test_production_without_supported_private_endpoint_fails_closed(self) -> None:
        with (
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "EDOC_AV_ENDPOINT", "https://scanner.example.invalid"),
        ):
            with self.assertRaisesRegex(ValueError, "editor_antivirus_not_ready"):
                backend.editor_scan_bytes_for_threats(b"%PDF", "document.pdf")

    def test_vercel_sandbox_provider_needs_no_public_endpoint_or_api_key(self) -> None:
        payload = b"%PDF isolated sandbox"
        result = types.SimpleNamespace(status="clean", signature="ClamAV-Clean")
        with (
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "RUNNING_ON_VERCEL", True),
            mock.patch.object(backend, "EDOC_AV_PROVIDER", backend.VERCEL_SANDBOX_AV_PROVIDER_ID),
            mock.patch.object(backend, "EDOC_AV_ENDPOINT", ""),
            mock.patch.object(backend, "EDOC_AV_SANDBOX_SNAPSHOT_ID", "snap_1234567890abcdefghijklmnop"),
            mock.patch.object(backend, "scan_bytes_in_vercel_sandbox", return_value=result) as scan,
            mock.patch.dict(os.environ, {
                "EDOC_SCAN_ENGINE": "ClamAV",
                "EDOC_AV_PROVIDER": backend.VERCEL_SANDBOX_AV_PROVIDER_ID,
                "EDOC_AV_SANDBOX_SNAPSHOT_ID": "snap_1234567890abcdefghijklmnop",
            }),
        ):
            self.assertEqual(
                backend.editor_scan_bytes_for_threats(payload, "private-name.pdf"),
                ("已通過", "ClamAV-Clean"),
            )
            readiness = backend.internal_antivirus_readiness()
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["contract"], backend.VERCEL_SANDBOX_AV_PROVIDER_ID)
        self.assertFalse(readiness["endpointConfigured"])
        self.assertTrue(readiness["transportConfigured"])
        self.assertNotIn("EDOC_AV_ENDPOINT", readiness["missingEnvironment"])
        self.assertNotIn("EDOC_AV_API_KEY", readiness["missingEnvironment"])
        self.assertEqual(scan.call_args.kwargs["expected_sha256"].lower(), hashlib.sha256(payload).hexdigest())

    def test_vercel_sandbox_provider_fails_closed_without_snapshot(self) -> None:
        with (
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "RUNNING_ON_VERCEL", True),
            mock.patch.object(backend, "EDOC_AV_PROVIDER", backend.VERCEL_SANDBOX_AV_PROVIDER_ID),
            mock.patch.object(backend, "EDOC_AV_ENDPOINT", ""),
            mock.patch.object(backend, "EDOC_AV_SANDBOX_SNAPSHOT_ID", ""),
        ):
            with self.assertRaisesRegex(ValueError, "editor_antivirus_not_ready"):
                backend.editor_scan_bytes_for_threats(b"%PDF", "document.pdf")

    def test_runtime_smoke_requires_clean_acceptance_and_malware_rejection(self) -> None:
        calls = []

        def fake_scan(data, file_name, **_kwargs):
            calls.append((data, file_name))
            return ("已通過", "ClamAV-Clean") if file_name.endswith(".pdf") else ("已隔離", "Fixture")

        with mock.patch.object(backend, "editor_scan_bytes_for_threats", side_effect=fake_scan):
            result = backend.antivirus_runtime_smoke()
        self.assertTrue(result["ok"])
        self.assertTrue(result["cleanAccepted"])
        self.assertTrue(result["malwareRejected"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("signature", result)
        self.assertNotIn("content", result)

    def test_https_hmac_clean_response_is_bound_to_nonce_hash_and_size(self) -> None:
        secret = "s" * 48
        data = b"%PDF clean over https"

        class Response:
            def __init__(self, body, headers):
                self.body = body
                self.headers = headers

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return self.body

        def fake_urlopen(request, timeout):
            self.assertGreaterEqual(timeout, 2)
            body = bytes(request.data)
            timestamp = request.headers["X-edoc-av-timestamp"]
            nonce = request.headers["X-edoc-av-nonce"]
            body_sha256 = hashlib.sha256(body).hexdigest()
            expected_request_signature = "v1=" + hmac.new(
                secret.encode(),
                backend._av_request_signing_message(timestamp, nonce, body_sha256),
                hashlib.sha256,
            ).hexdigest()
            self.assertEqual(request.headers["X-edoc-av-signature"], expected_request_signature)
            response_payload = {
                "schemaVersion": 1,
                "status": "clean",
                "engine": "ClamAV",
                "signature": "",
                "sha256": hashlib.sha256(data).hexdigest(),
                "sizeBytes": len(data),
                "scannedAt": "2026-08-24T00:00:00+00:00",
            }
            raw = json.dumps(response_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
            response_timestamp = str(int(time.time()))
            response_signature = "v1=" + hmac.new(
                secret.encode(),
                backend._av_response_signing_message(
                    response_timestamp,
                    nonce,
                    hashlib.sha256(raw).hexdigest(),
                ),
                hashlib.sha256,
            ).hexdigest()
            return Response(raw, {
                "X-EDOC-AV-Response-Timestamp": response_timestamp,
                "X-EDOC-AV-Response-Signature": response_signature,
            })

        with (
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "EDOC_AV_ENDPOINT", "https://scanner.example.test"),
            mock.patch.object(backend, "EDOC_AV_PROVIDER", "edoc-clamav-https-v1"),
            mock.patch.dict(os.environ, {"EDOC_AV_API_KEY": secret}),
            mock.patch.object(backend, "_urlopen_no_redirect", side_effect=fake_urlopen),
        ):
            self.assertEqual(
                backend.editor_scan_bytes_for_threats(data, "private-name.pdf"),
                ("已通過", "ClamAV-Clean"),
            )

    def test_https_hmac_rejects_forged_response(self) -> None:
        secret = "k" * 48

        class Response:
            headers = {
                "X-EDOC-AV-Response-Timestamp": str(int(time.time())),
                "X-EDOC-AV-Response-Signature": "v1=" + "0" * 64,
            }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{}'

        with (
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "EDOC_AV_ENDPOINT", "https://scanner.example.test/v1/scan"),
            mock.patch.object(backend, "EDOC_AV_PROVIDER", "edoc-clamav-https-v1"),
            mock.patch.dict(os.environ, {"EDOC_AV_API_KEY": secret}),
            mock.patch.object(backend, "_urlopen_no_redirect", return_value=Response()),
        ):
            with self.assertRaisesRegex(ValueError, "editor_antivirus_response_invalid"):
                backend.editor_scan_bytes_for_threats(b"%PDF", "document.pdf")

    def test_https_hmac_large_file_requires_private_storage_source(self) -> None:
        secret = "z" * 48
        with (
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "EDOC_AV_ENDPOINT", "https://scanner.example.test"),
            mock.patch.object(backend, "EDOC_AV_PROVIDER", "edoc-clamav-https-v1"),
            mock.patch.object(backend, "EDOC_AV_HTTP_INLINE_MAX_BYTES", 3),
            mock.patch.dict(os.environ, {"EDOC_AV_API_KEY": secret}),
        ):
            with self.assertRaisesRegex(ValueError, "editor_antivirus_storage_source_required"):
                backend.editor_scan_bytes_for_threats(b"1234", "document.pdf")

    def test_https_timeout_fails_closed(self) -> None:
        secret = "t" * 48
        with (
            mock.patch.object(backend, "is_production", return_value=True),
            mock.patch.object(backend, "EDOC_AV_ENDPOINT", "https://scanner.example.test"),
            mock.patch.object(backend, "EDOC_AV_PROVIDER", "edoc-clamav-https-v1"),
            mock.patch.dict(os.environ, {"EDOC_AV_API_KEY": secret}),
            mock.patch.object(backend, "_urlopen_no_redirect", side_effect=TimeoutError()),
        ):
            with self.assertRaisesRegex(ValueError, "editor_antivirus_scan_failed"):
                backend.editor_scan_bytes_for_threats(b"%PDF", "document.pdf")

    def test_internal_scan_url_is_short_lived_origin_pinned_and_not_a_browser_url(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return json.dumps({
                    "signedURL": "/object/sign/edoc-private/private/path.pdf?token=short"
                }).encode()

        with (
            mock.patch.dict(os.environ, {"EDOC_OBJECT_STORAGE_URL": ""}, clear=False),
            mock.patch.object(backend, "EDOC_STORAGE_PROVIDER", "supabase"),
            mock.patch.object(backend, "EDOC_STORAGE_SUPABASE_URL", "https://project-ref.supabase.co"),
            mock.patch.object(backend, "EDOC_OBJECT_STORAGE_URL", "https://project-ref.supabase.co/storage/v1"),
            mock.patch.object(backend, "EDOC_STORAGE_SERVICE_ROLE_KEY", "sb_secret_test_storage"),
            mock.patch.object(backend, "EDOC_STORAGE_BUCKET", "edoc-private"),
            mock.patch.object(backend, "EDOC_SEAL_STORAGE_BUCKET", "edoc-seal-vault"),
            mock.patch.object(backend, "_urlopen_no_redirect", return_value=Response()),
        ):
            signed = backend.supabase_storage_create_signed_scan_url(
                "private/path.pdf", "edoc-private", ttl_seconds=60
            )
        self.assertEqual(signed["expires_in"], 60)
        self.assertEqual(
            signed["url"],
            "https://project-ref.supabase.co/storage/v1/object/sign/edoc-private/private/path.pdf?token=short",
        )
        self.assertNotIn("download=", signed["url"])

    def test_internal_scan_url_rejects_unknown_bucket_and_mixed_seal_path(self) -> None:
        with (
            mock.patch.object(backend, "EDOC_STORAGE_BUCKET", "edoc-private"),
            mock.patch.object(backend, "EDOC_SEAL_STORAGE_BUCKET", "edoc-seal-vault"),
        ):
            with self.assertRaisesRegex(PermissionError, "supabase_scan_url_bucket_forbidden"):
                backend.supabase_storage_create_signed_scan_url("private/a.pdf", "public")
            with self.assertRaisesRegex(PermissionError, "supabase_scan_url_bucket_path_mismatch"):
                backend.supabase_storage_create_signed_scan_url("seal-vault/seals/a.png", "edoc-private")
            with self.assertRaisesRegex(PermissionError, "supabase_scan_url_seal_path_forbidden"):
                backend.supabase_storage_create_signed_scan_url("official-documents/a.pdf", "edoc-seal-vault")


if __name__ == "__main__":
    unittest.main()
