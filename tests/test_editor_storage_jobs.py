from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

import backend


class EditorStorageJobTestCase(unittest.TestCase):
    @staticmethod
    def pending_asset() -> dict:
        return {
            "id": "ASSET-1",
            "document_id": "OD-1",
            "editor_revision_id": "REV-1",
            "asset_kind": "source_pdf",
            "file_object_id": None,
            "official_file_id": None,
            "file_name": "a4.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 128,
            "sha256": "",
            "expected_sha256": "A" * 64,
            "storage_bucket": backend.EDOC_STORAGE_BUCKET,
            "storage_path": "editor/OD-1/ASSET-1-a4.pdf",
            "upload_status": "pending",
            "scan_status": "pending",
            "preflight_status": "pending",
            "page_count": 0,
            "metadata_json": "{}",
            "created_by": "FIN-U1",
            "created_at": "2026-08-27T00:00:00",
            "finalized_at": None,
        }

    @staticmethod
    def storage_job(*, status: str = "pending") -> dict:
        return {
            "id": "EDOC-STORAGE-ASSET-1",
            "asset_id": "ASSET-1",
            "document_id": "OD-1",
            "staging_bucket": backend.EDOC_STORAGE_BUCKET,
            "staging_path": "editor/OD-1/ASSET-1-a4.pdf",
            "final_bucket": backend.EDOC_STORAGE_BUCKET,
            "final_path": f"editor-final/OD-1/ASSET-1/{'A' * 64}-a4.pdf",
            "expected_sha256": "A" * 64,
            "expected_size_bytes": 128,
            "token_expires_at": "2020-01-01T00:00:00",
            "status": status,
            "lease_token": "",
            "lease_expires_at": "",
            "final_file_object_id": "FILE-1" if status == "committed" else None,
            "attempt_count": 0,
            "last_error_code": "",
            "created_at": "2026-08-27T00:00:00",
            "updated_at": "2026-08-27T00:00:00",
            "cleaned_at": None,
        }

    def test_failure_compare_and_set_loses_to_finalize_without_downgrade(self) -> None:
        pending = self.pending_asset()
        finalized = {
            **pending,
            "file_object_id": "FILE-1",
            "sha256": "A" * 64,
            "storage_path": self.storage_job(status="committed")["final_path"],
            "upload_status": "finalized",
            "scan_status": "passed",
            "preflight_status": "passed",
            "finalized_at": "2026-08-27T01:00:00",
        }

        with mock.patch.object(
            backend,
            "supabase_official_document_row",
            return_value={"id": "OD-1", "company_id": "CO-1"},
        ), mock.patch.object(
            backend,
            "_supabase_editor_assert_document_access",
            return_value={"id": "FIN-U1"},
        ), mock.patch.object(
            backend,
            "supabase_filter_rows",
            side_effect=[[pending], [finalized]],
        ), mock.patch.object(
            backend,
            "supabase_update_many",
            return_value=[],
        ) as update_many, mock.patch.object(
            backend,
            "supabase_storage_delete",
        ) as storage_delete, mock.patch.object(
            backend,
            "supabase_insert_official_log",
        ) as insert_log:
            result = backend.supabase_fail_official_editor_upload(
                "OD-1",
                "ASSET-1",
                {"error_code": "editor_upload_incomplete"},
                {"user": {"id": "FIN-U1"}},
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["asset"]["sha256"], "A" * 64)
        update_many.assert_called_once()
        self.assertEqual(
            update_many.call_args.args[1],
            {"id": "ASSET-1", "upload_status": "pending"},
        )
        storage_delete.assert_not_called()
        insert_log.assert_not_called()

    def test_cleanup_committed_job_deletes_only_staging_object(self) -> None:
        job = self.storage_job(status="committed")
        cleaning_job = {
            **job,
            "status": "cleaning",
            "lease_token": "C" * 32,
            "lease_expires_at": "2099-01-01T00:00:00",
            "attempt_count": 1,
        }
        asset = {
            **self.pending_asset(),
            "file_object_id": "FILE-1",
            "sha256": "A" * 64,
            "storage_path": job["final_path"],
            "upload_status": "finalized",
            "scan_status": "passed",
            "preflight_status": "passed",
        }

        def filter_rows(table, filters, **_kwargs):
            if table == "official_document_editor_storage_jobs":
                return [job] if filters.get("status") == "committed" else []
            if table == "official_document_editor_assets":
                return [asset]
            self.fail(f"unexpected table lookup: {table}")

        def update_many(table, filters, payload):
            self.assertEqual(table, "official_document_editor_storage_jobs")
            self.assertEqual(
                filters,
                {
                    "id": job["id"],
                    "status": "cleaning",
                    "lease_token": "C" * 32,
                },
            )
            return [{**cleaning_job, **payload}]

        with mock.patch.object(
            backend,
            "supabase_filter_rows",
            side_effect=filter_rows,
        ), mock.patch.object(
            backend,
            "_supabase_assert_finalized_editor_asset_immutable",
            return_value={"id": "FILE-1"},
        ), mock.patch.object(
            backend,
            "supabase_storage_delete",
        ) as storage_delete, mock.patch.object(
            backend,
            "supabase_update_many",
            side_effect=update_many,
        ), mock.patch.object(
            backend,
            "_supabase_claim_editor_storage_job",
            return_value=cleaning_job,
        ):
            result = backend.supabase_cleanup_stale_official_editor_uploads(
                document_id="OD-1"
            )

        self.assertEqual(result["asset_ids"], ["ASSET-1"])
        self.assertEqual(result["failure_count"], 0)
        storage_delete.assert_called_once_with(
            job["staging_path"],
            job["staging_bucket"],
        )
        self.assertNotIn(
            mock.call(job["final_path"], job["final_bucket"]),
            storage_delete.call_args_list,
        )

    def test_cleanup_pending_orphan_deletes_staging_and_final_without_reference(self) -> None:
        job = self.storage_job(status="pending")
        cleaning_job = {
            **job,
            "status": "cleaning",
            "lease_token": "C" * 32,
            "lease_expires_at": "2099-01-01T00:00:00",
            "attempt_count": 1,
        }

        def filter_rows(table, filters, **_kwargs):
            if table == "official_document_editor_storage_jobs":
                return [job] if filters.get("status") == "pending" else []
            if table in {"official_document_editor_assets", "file_objects"}:
                return []
            self.fail(f"unexpected table lookup: {table}")

        with mock.patch.object(
            backend,
            "supabase_filter_rows",
            side_effect=filter_rows,
        ), mock.patch.object(
            backend,
            "supabase_storage_delete",
        ) as storage_delete, mock.patch.object(
            backend,
            "supabase_update_many",
            side_effect=lambda _table, _filters, payload: [{**cleaning_job, **payload}],
        ), mock.patch.object(
            backend,
            "_supabase_claim_editor_storage_job",
            return_value=cleaning_job,
        ):
            result = backend.supabase_cleanup_stale_official_editor_uploads(
                document_id="OD-1"
            )

        self.assertEqual(result["asset_ids"], ["ASSET-1"])
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(
            storage_delete.call_args_list,
            [
                mock.call(job["staging_path"], job["staging_bucket"]),
                mock.call(job["final_path"], job["final_bucket"]),
            ],
        )

    def test_cleanup_pending_orphan_never_deletes_referenced_final_object(self) -> None:
        job = self.storage_job(status="pending")
        cleaning_job = {
            **job,
            "status": "cleaning",
            "lease_token": "C" * 32,
            "lease_expires_at": "2099-01-01T00:00:00",
            "attempt_count": 1,
        }

        def filter_rows(table, filters, **_kwargs):
            if table == "official_document_editor_storage_jobs":
                return [job] if filters.get("status") == "pending" else []
            if table == "official_document_editor_assets":
                return []
            if table == "file_objects":
                self.assertEqual(filters, {"storage_key": job["final_path"]})
                return [{"id": "FILE-REFERENCING-FINAL"}]
            self.fail(f"unexpected table lookup: {table}")

        with mock.patch.object(
            backend,
            "supabase_filter_rows",
            side_effect=filter_rows,
        ), mock.patch.object(
            backend,
            "supabase_storage_delete",
        ) as storage_delete, mock.patch.object(
            backend,
            "supabase_update_many",
            side_effect=lambda _table, _filters, payload: [{**cleaning_job, **payload}],
        ), mock.patch.object(
            backend,
            "_supabase_claim_editor_storage_job",
            return_value=cleaning_job,
        ), mock.patch.object(
            backend,
            "log_structured",
        ):
            result = backend.supabase_cleanup_stale_official_editor_uploads(
                document_id="OD-1"
            )

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["failed_asset_ids"], ["ASSET-1"])
        self.assertNotIn(
            mock.call(job["final_path"], job["final_bucket"]),
            storage_delete.call_args_list,
        )

    def test_cleanup_never_touches_paths_under_active_promotion_lease(self) -> None:
        job = {
            **self.storage_job(status="promoting"),
            "lease_token": "A" * 32,
            "lease_expires_at": "2099-01-01T00:00:00",
            "attempt_count": 1,
        }

        def filter_rows(table, filters, **_kwargs):
            if table == "official_document_editor_storage_jobs":
                return [job] if filters.get("status") == "promoting" else []
            self.fail(f"unexpected table lookup: {table}")

        with mock.patch.object(
            backend,
            "supabase_filter_rows",
            side_effect=filter_rows,
        ), mock.patch.object(
            backend,
            "_supabase_claim_editor_storage_job",
        ) as claim, mock.patch.object(
            backend,
            "supabase_storage_delete",
        ) as storage_delete:
            result = backend.supabase_cleanup_stale_official_editor_uploads(
                document_id="OD-1"
            )

        self.assertEqual(result["count"], 0)
        claim.assert_not_called()
        storage_delete.assert_not_called()

    def test_create_upload_intent_persists_storage_job_before_returning_token(self) -> None:
        inserted: list[tuple[str, dict]] = []

        def insert(table, row):
            copied = dict(row)
            inserted.append((table, copied))
            return copied

        with mock.patch.object(
            backend,
            "supabase_official_document_row",
            return_value={"id": "OD-1", "company_id": "CO-1"},
        ), mock.patch.object(
            backend,
            "_supabase_editor_assert_document_access",
            return_value={"id": "FIN-U1"},
        ), mock.patch.object(
            backend,
            "supabase_cleanup_stale_official_editor_uploads",
            return_value={"count": 0, "asset_ids": []},
        ), mock.patch.object(
            backend,
            "_supabase_editor_latest_revision",
            return_value={"id": "REV-1", "revision_no": 1},
        ), mock.patch.object(
            backend,
            "_supabase_storage_direct_tus_url",
            return_value="https://storage.example.test/storage/v1/upload/resumable/sign",
        ), mock.patch.object(
            backend,
            "_supabase_storage_public_upload_key",
            return_value="sb_publishable_test",
        ), mock.patch.object(
            backend,
            "_supabase_create_signed_upload_token",
            return_value="short-lived-signature",
        ), mock.patch.object(
            backend,
            "supabase_insert",
            side_effect=insert,
        ):
            intent = backend.supabase_create_official_editor_upload_intent(
                "OD-1",
                {
                    "file_name": "a4.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 128,
                    "sha256": "A" * 64,
                },
                {"user": {"id": "FIN-U1"}},
            )

        self.assertEqual(
            [table for table, _row in inserted],
            [
                "official_document_editor_assets",
                "official_document_editor_storage_jobs",
            ],
        )
        asset = inserted[0][1]
        job = inserted[1][1]
        self.assertEqual(job["asset_id"], asset["id"])
        self.assertEqual(job["document_id"], "OD-1")
        self.assertEqual(job["staging_path"], asset["storage_path"])
        self.assertEqual(job["staging_path"], intent["path"])
        self.assertEqual(job["expected_sha256"], "A" * 64)
        self.assertEqual(job["expected_size_bytes"], 128)
        self.assertEqual(job["token_expires_at"], intent["expires_at"])
        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["lease_token"], "")
        self.assertEqual(job["lease_expires_at"], "")
        self.assertEqual(
            job["final_path"],
            backend._supabase_editor_immutable_storage_path(
                "OD-1",
                asset,
                "A" * 64,
            ),
        )

    def test_sqlite_finalized_source_asset_rejects_all_evidence_updates(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(backend.SCHEMA)
        # This unit isolates the evidence trigger itself.  Parent rows and
        # file-object foreign keys are covered by the workflow integration
        # tests, so avoid constructing unrelated document fixtures here.
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            INSERT INTO official_document_editor_assets (
              id, document_id, asset_kind, file_object_id, file_name,
              mime_type, size_bytes, sha256, expected_sha256, storage_bucket,
              storage_path, upload_status, scan_status, preflight_status,
              metadata_json, created_by, created_at, finalized_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ASSET-SQLITE-1",
                "OD-SQLITE-1",
                "source_pdf",
                "FILE-SQLITE-1",
                "a4.pdf",
                "application/pdf",
                128,
                "A" * 64,
                "A" * 64,
                backend.EDOC_STORAGE_BUCKET,
                f"editor-final/OD-SQLITE-1/ASSET-SQLITE-1/{'A' * 64}-a4.pdf",
                "pending",
                "passed",
                "passed",
                "{}",
                "FIN-U1",
                "2026-08-27T00:00:00",
                "2026-08-27T01:00:00",
            ),
        )
        conn.execute(
            "UPDATE official_document_editor_assets SET upload_status = 'finalized' WHERE id = ?",
            ("ASSET-SQLITE-1",),
        )
        conn.commit()

        with self.assertRaisesRegex(
            sqlite3.IntegrityError,
            "editor_finalized_asset_insert_forbidden",
        ):
            conn.execute(
                """
                INSERT INTO official_document_editor_assets (
                  id, document_id, asset_kind, file_name, mime_type,
                  size_bytes, sha256, expected_sha256, storage_bucket,
                  storage_path, upload_status, scan_status, preflight_status,
                  metadata_json, created_by, created_at
                ) VALUES (?, ?, 'source_pdf', 'direct.pdf', 'application/pdf',
                          128, ?, ?, ?, ?, 'finalized', 'passed', 'passed',
                          '{}', 'FIN-U1', '2026-08-27T00:00:00')
                """,
                (
                    "ASSET-SQLITE-DIRECT",
                    "OD-SQLITE-1",
                    "A" * 64,
                    "A" * 64,
                    backend.EDOC_STORAGE_BUCKET,
                    f"editor-final/OD-SQLITE-1/ASSET-SQLITE-DIRECT/{'A' * 64}-direct.pdf",
                ),
            )
        conn.rollback()

        mutations = {
            "upload_status": "failed",
            "storage_path": "editor-final/OD-SQLITE-1/ASSET-SQLITE-1/other.pdf",
            "sha256": "B" * 64,
            "size_bytes": 256,
            "file_object_id": "FILE-SQLITE-2",
        }
        for column, value in mutations.items():
            with self.subTest(column=column):
                with self.assertRaisesRegex(
                    sqlite3.IntegrityError,
                    "editor_finalized_asset_immutable",
                ):
                    conn.execute(
                        f"UPDATE official_document_editor_assets SET {column} = ? WHERE id = ?",
                        (value, "ASSET-SQLITE-1"),
                    )
                conn.rollback()

        with self.assertRaisesRegex(
            sqlite3.IntegrityError,
            "editor_finalized_asset_immutable",
        ):
            conn.execute(
                "DELETE FROM official_document_editor_assets WHERE id = ?",
                ("ASSET-SQLITE-1",),
            )
        conn.rollback()

        unchanged = conn.execute(
            """
            SELECT upload_status, storage_path, sha256, size_bytes, file_object_id
            FROM official_document_editor_assets WHERE id = ?
            """,
            ("ASSET-SQLITE-1",),
        ).fetchone()
        self.assertEqual(unchanged["upload_status"], "finalized")
        self.assertIn("editor-final/OD-SQLITE-1/ASSET-SQLITE-1/", unchanged["storage_path"])
        self.assertEqual(unchanged["sha256"], "A" * 64)
        self.assertEqual(unchanged["size_bytes"], 128)
        self.assertEqual(unchanged["file_object_id"], "FILE-SQLITE-1")
        conn.close()


if __name__ == "__main__":
    unittest.main()
