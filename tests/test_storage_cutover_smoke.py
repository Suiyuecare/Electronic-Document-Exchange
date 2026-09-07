from __future__ import annotations

import io
import json
import types
import unittest
import urllib.error
from unittest.mock import Mock

from tools.storage_cutover_smoke import safe_failure_code, verify_owned_object_deleted


class StorageCutoverSmokeTest(unittest.TestCase):
    key = "smoke-tests/storage-cutover-0123456789abcdef.pdf"

    def backend(self, status: int, body: object):
        error = urllib.error.HTTPError(
            "https://test.invalid/private-object", status, "masked", {},
            io.BytesIO(json.dumps(body).encode()),
        )
        return types.SimpleNamespace(
            EDOC_STORAGE_BUCKET="edoc-private", EDOC_SEAL_STORAGE_BUCKET="edoc-seal-vault",
            supabase_storage_object_url=Mock(return_value="https://test.invalid/private-object"),
            supabase_storage_headers=Mock(return_value={"Authorization": "private-test-token"}),
            _urlopen_no_redirect=Mock(side_effect=error),
            _consume_http_error=lambda exc: exc.read(4096),
        )

    def test_legacy_http_400_with_explicit_object_404_is_verified(self):
        backend = self.backend(400, {"statusCode": "404", "code": "NoSuchKey", "error": "not_found"})
        self.assertEqual(verify_owned_object_deleted(backend, self.key), (True, 400, "NoSuchKey"))

    def test_current_http_404_object_missing_is_verified(self):
        self.assertEqual(verify_owned_object_deleted(self.backend(404, {"code": "NoSuchKey"}), self.key), (True, 404, "NoSuchKey"))

    def test_auth_bucket_generic_or_inconsistent_error_never_passes(self):
        for status, body in (
            (403, {"code": "AccessDenied"}),
            (404, {"code": "NoSuchBucket"}),
            (400, {"code": "InvalidRequest", "statusCode": "404"}),
            (400, {"code": "NoSuchKey"}),
            (403, {"code": "NoSuchKey", "statusCode": "404"}),
            (500, {"code": "NoSuchKey", "statusCode": "404"}),
            (404, ["NoSuchKey"]),
        ):
            with self.subTest(status=status, body=body):
                self.assertFalse(verify_owned_object_deleted(self.backend(status, body), self.key)[0])

    def test_probe_rejects_unowned_key_and_seal_bucket_before_request(self):
        backend = self.backend(404, {"code": "NoSuchKey"})
        with self.assertRaisesRegex(RuntimeError, "probe_key_forbidden"):
            verify_owned_object_deleted(backend, "seals/sensitive.pdf")
        backend.EDOC_STORAGE_BUCKET = backend.EDOC_SEAL_STORAGE_BUCKET
        with self.assertRaisesRegex(RuntimeError, "probe_bucket_forbidden"):
            verify_owned_object_deleted(backend, self.key)
        backend._urlopen_no_redirect.assert_not_called()

    def test_failure_output_never_echoes_signed_url_or_arbitrary_message(self):
        self.assertEqual(safe_failure_code(ValueError("supabase_storage_upload_failed:403")), "supabase_storage_upload_failed:403")
        self.assertEqual(safe_failure_code(RuntimeError("storage_cutover_delete_not_verified")), "storage_cutover_delete_not_verified")
        for message in ("https://test.invalid/file?token=private", "storage_cutover_error private-personal-data", "secret"):
            self.assertEqual(safe_failure_code(RuntimeError(message)), "storage_cutover_failed")


if __name__ == "__main__":
    unittest.main()
