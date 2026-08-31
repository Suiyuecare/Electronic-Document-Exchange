from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import backend


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_editor_storage_assets.py"
SPEC = importlib.util.spec_from_file_location("verify_editor_storage_assets", SCRIPT)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class EditorStorageVerifierTestCase(unittest.TestCase):
    @staticmethod
    def asset() -> dict:
        digest = backend.sha256_bytes(b"private-deidentified-fixture")
        return {
            "id": "ASSET-SECRET",
            "document_id": "OD-SECRET",
            "asset_kind": "source_pdf",
            "file_object_id": "FILE-SECRET",
            "size_bytes": len(b"private-deidentified-fixture"),
            "sha256": digest,
            "expected_sha256": digest,
            "storage_bucket": backend.EDOC_STORAGE_BUCKET,
            "storage_path": (
                f"editor-final/OD-SECRET/ASSET-SECRET/{digest}-private.pdf"
            ),
            "upload_status": "finalized",
        }

    def test_valid_inventory_emits_aggregate_evidence_only(self) -> None:
        asset = self.asset()
        data = b"private-deidentified-fixture"
        file_object = {
            "id": "FILE-SECRET",
            "document_id": "OD-SECRET",
            "bucket": backend.EDOC_STORAGE_BUCKET,
            "storage_key": asset["storage_path"],
            "storage_provider": "supabase",
            "sha256": asset["sha256"],
            "size_bytes": len(data),
        }
        with mock.patch.object(
            verifier,
            "finalized_asset_page",
            return_value=[asset],
        ), mock.patch.object(
            backend,
            "supabase_get",
            return_value=file_object,
        ), mock.patch.object(
            backend,
            "supabase_storage_download",
            return_value=data,
        ):
            result = verifier.verify_all()

        self.assertTrue(result["passed"])
        self.assertEqual(result["checkedAssetCount"], 1)
        self.assertEqual(result["invalidAssetCount"], 0)
        self.assertEqual(result["phase"], "pre-migration")
        self.assertFalse(result["storageJobBindingChecked"])
        rendered = json.dumps(result, sort_keys=True)
        for secret_value in (
            asset["id"],
            asset["document_id"],
            asset["storage_path"],
            asset["sha256"],
            "private.pdf",
        ):
            self.assertNotIn(secret_value, rendered)

    def test_invalid_inventory_returns_only_bounded_error_count(self) -> None:
        asset = {**self.asset(), "expected_sha256": "0" * 64}
        with mock.patch.object(
            verifier,
            "finalized_asset_page",
            return_value=[asset],
        ), mock.patch.object(
            backend,
            "supabase_storage_download",
        ) as download:
            result = verifier.verify_all()

        self.assertFalse(result["passed"])
        self.assertEqual(result["invalidAssetCount"], 1)
        self.assertEqual(
            result["errorCounts"],
            {"editor_asset_metadata_invalid": 1},
        )
        download.assert_not_called()
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn(asset["id"], rendered)
        self.assertNotIn(asset["storage_path"], rendered)

    def test_post_migration_inventory_requires_exact_storage_job_binding(self) -> None:
        asset = self.asset()
        data = b"private-deidentified-fixture"
        file_object = {
            "id": "FILE-SECRET",
            "document_id": "OD-SECRET",
            "bucket": backend.EDOC_STORAGE_BUCKET,
            "storage_key": asset["storage_path"],
            "storage_provider": "supabase",
            "sha256": asset["sha256"],
            "size_bytes": len(data),
        }
        job = {
            "status": "committed",
            "final_file_object_id": "FILE-SECRET",
            "final_bucket": backend.EDOC_STORAGE_BUCKET,
            "final_path": asset["storage_path"],
            "expected_sha256": asset["sha256"],
            "expected_size_bytes": len(data),
        }
        with mock.patch.object(
            verifier, "finalized_asset_page", return_value=[asset]
        ), mock.patch.object(
            backend, "supabase_get", return_value=file_object
        ), mock.patch.object(
            backend, "supabase_filter_rows", return_value=[job]
        ) as jobs, mock.patch.object(
            backend, "supabase_storage_download", return_value=data
        ):
            result = verifier.verify_all(post_migration=True)

        self.assertTrue(result["passed"])
        self.assertEqual(result["phase"], "post-migration")
        self.assertTrue(result["storageJobBindingChecked"])
        jobs.assert_called_once_with(
            "official_document_editor_storage_jobs",
            {"asset_id": asset["id"], "document_id": asset["document_id"]},
            limit=2,
        )

    def test_post_migration_inventory_fails_closed_without_storage_job(self) -> None:
        asset = self.asset()
        file_object = {
            "id": "FILE-SECRET",
            "document_id": "OD-SECRET",
            "bucket": backend.EDOC_STORAGE_BUCKET,
            "storage_key": asset["storage_path"],
            "storage_provider": "supabase",
            "sha256": asset["sha256"],
            "size_bytes": asset["size_bytes"],
        }
        with mock.patch.object(
            verifier, "finalized_asset_page", return_value=[asset]
        ), mock.patch.object(
            backend, "supabase_get", return_value=file_object
        ), mock.patch.object(
            backend, "supabase_filter_rows", return_value=[]
        ), mock.patch.object(
            backend, "supabase_storage_download"
        ) as download:
            result = verifier.verify_all(post_migration=True)

        self.assertFalse(result["passed"])
        self.assertEqual(result["errorCounts"], {"editor_storage_job_missing": 1})
        download.assert_not_called()

    def test_documented_post_migration_cli_flag_is_accepted(self) -> None:
        output = io.StringIO()
        result = {
            "gate": "editor_storage_asset_byte_inventory",
            "phase": "post-migration",
            "passed": True,
            "aggregateOnly": True,
            "storageJobBindingChecked": True,
        }
        with mock.patch.object(
            sys,
            "argv",
            [
                str(SCRIPT),
                "--acknowledge-private-document-download",
                "--post-migration",
            ],
        ), mock.patch.object(
            verifier, "require_configuration"
        ), mock.patch.object(
            verifier, "verify_all", return_value=result
        ) as verify, redirect_stdout(output):
            exit_code = verifier.main()

        self.assertEqual(exit_code, 0)
        verify.assert_called_once_with(post_migration=True)
        self.assertEqual(json.loads(output.getvalue()), result)


if __name__ == "__main__":
    unittest.main()
