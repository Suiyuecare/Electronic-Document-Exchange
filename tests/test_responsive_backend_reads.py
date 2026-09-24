"""Bounded I/O reductions; synthetic records only and no network access."""
from datetime import datetime, timedelta
from pathlib import Path
import re
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

import backend


class OfficialListReadBudgetTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.rows = [
            {"id": f"SYNTHETIC-{index:03d}", "company_id": "COMPANY-A",
             "applicant_id": "ACTOR" if index == 0 else "OTHER",
             "current_status": "draft", "current_step": "", "metadata_json": "{}",
             "created_at": "2026-09-24 10:00:00"}
            for index in range(100)
        ]
        self.session = {"user": {"id": "ACTOR", "company_id": "COMPANY-A"},
                        "permissions": ["official_documents.all_records"]}

    def request(self, method, path, payload, **_kwargs):
        self.assertEqual((method, path), ("POST", "rpc/edoc_list_official_document_candidates"))
        query = payload["p_request"]
        self.calls.append((path, query))
        rows = sorted(self.rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)
        if query["scope"] == "mine":
            rows = [r for r in rows if r["applicant_id"] == query["actor_id"]]
        for source, key in (("status", "current_status"), ("company_id", "company_id"), ("applicant_id", "applicant_id")):
            if query[source]:
                rows = [r for r in rows if r[key] == query[source]]
        if query["after_id"]:
            rows = [r for r in rows if (r["created_at"], r["id"]) < (query["after_created_at"], query["after_id"])]
        return {"items": [{"document": dict(r), "steps": [], "snapshots": []} for r in rows[:query["limit"]]]}

    def test_mine_reads_only_its_one_case_not_all_100_child_resources(self):
        with mock.patch.object(backend, "supabase_request", side_effect=self.request):
            rows = backend.supabase_list_official_documents({"scope": ["mine"]}, self.session)
        self.assertEqual([row["id"] for row in rows], ["SYNTHETIC-000"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]["actor_id"], "ACTOR")
        self.assertEqual(self.calls[0][1]["scope"], "mine")

    def test_conflicting_mine_applicant_filter_does_not_query_or_expand_access(self):
        with mock.patch.object(backend, "supabase_request", side_effect=self.request):
            result = backend.supabase_list_official_documents({"scope": ["mine"], "applicant_id": ["OTHER"]}, self.session)
        self.assertEqual(result, [])
        self.assertEqual(self.calls, [])

    def test_explicit_filters_are_applied_server_side_and_still_checked_locally(self):
        query = {"status": ["draft"], "company_id": ["COMPANY-A"], "applicant_id": ["ACTOR"]}
        with mock.patch.object(backend, "supabase_request", side_effect=self.request):
            result = backend.supabase_list_official_documents(query, self.session)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual({key: self.calls[0][1][key] for key in ("status", "company_id", "applicant_id")},
                         {"status": "draft", "company_id": "COMPANY-A", "applicant_id": "ACTOR"})

    def test_unknown_scope_still_cannot_bypass_participant_access(self):
        self.session["permissions"] = []
        with mock.patch.object(backend, "supabase_request", side_effect=self.request):
            rows = backend.supabase_list_official_documents({"scope": ["arbitrary"]}, self.session)
        self.assertEqual([row["id"] for row in rows], ["SYNTHETIC-000"])

    def test_all_100_records_are_batched_instead_of_401_sequential_requests(self):
        with mock.patch.object(backend, "supabase_request", side_effect=self.request):
            rows = backend.supabase_list_official_documents({"scope": ["all"]}, self.session)
        self.assertEqual(len(rows), 100)
        self.assertEqual(len(self.calls), 2)  # One full batch plus end-of-list probe.

    def test_first_page_uses_one_batched_read_and_exposes_cursor(self):
        with mock.patch.object(backend, "supabase_request", side_effect=self.request):
            result = backend.supabase_list_official_documents({"scope": ["all"], "page_size": ["50"]}, self.session)
        self.assertEqual(len(result["items"]), 50)
        self.assertTrue(result["has_more"])
        self.assertTrue(result["next_cursor"])
        self.assertEqual(len(self.calls), 1)


class UploadCleanupReadBudgetTest(unittest.TestCase):
    def test_public_and_shared_schema_require_the_same_sortable_expiry_format(self):
        root = Path(__file__).resolve().parents[1]
        paths = (
            "supabase/migrations/20260827194500_promote_editor_tus_staging_to_immutable.sql",
            "supabase/migrations/20260913130517_editor_storage_v2_opaque_paths.sql",
            "supabase/shared-project-migrations/20260913130517_shared_editor_storage_v2_opaque_paths.sql",
        )
        for path in paths:
            with self.subTest(path=path):
                source = (root / path).read_text()
                pattern = re.search(r"token_expires_at\s*~\s*'([^']+)'", source).group(1)
                self.assertTrue(re.fullmatch(pattern, "2026-09-22T10:20:30"))
                for invalid in ("2026-09-22 10:20:30", "2026-09-22T10:20:30+08:00", "2026-09-22T10:20:30Z"):
                    self.assertIsNone(re.fullmatch(pattern, invalid))
                self.assertIn("timestamp without time zone", source)

    def test_empty_cleanup_uses_one_bounded_scoped_due_query(self):
        with mock.patch.object(backend, "supabase_request", return_value=[]) as request:
            result = backend.supabase_cleanup_stale_official_editor_uploads(document_id="SYNTHETIC-DOC")
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "GET")
        query = parse_qs(urlparse(request.call_args.args[1]).query)
        self.assertEqual(query["document_id"], ["eq.SYNTHETIC-DOC"])
        self.assertEqual(query["limit"], ["500"])
        self.assertEqual(query["order"], ["token_expires_at.asc,id.asc"])
        self.assertEqual(query["status"], ["in.(pending,promoting,committed,cleaning,cleanup_failed)"])
        cutoff = datetime.fromisoformat(query["token_expires_at"][0].removeprefix("lt."))
        self.assertAlmostEqual((datetime.now() - cutoff).total_seconds(), 300, delta=2)
        self.assertEqual(result["count"], 0)

    def test_foreign_or_malformed_due_rows_fail_before_cleanup_side_effects(self):
        for response in ([{"document_id": "OTHER"}], [None], {"error": "unexpected"}):
            with self.subTest(response=response), mock.patch.object(backend, "supabase_request", return_value=response), \
                    mock.patch.object(backend, "_supabase_claim_editor_storage_job") as claim, \
                    mock.patch.object(backend, "supabase_storage_delete") as delete:
                with self.assertRaisesRegex(RuntimeError, "cleanup_scope_invalid"):
                    backend.supabase_cleanup_stale_official_editor_uploads(document_id="SYNTHETIC-DOC")
                claim.assert_not_called()
                delete.assert_not_called()

    def test_local_expiry_and_active_lease_checks_remain_authoritative(self):
        for job in (
            {"status": "pending", "token_expires_at": (datetime.now() + timedelta(hours=1)).isoformat()},
            {"status": "promoting", "token_expires_at": "2020-01-01T00:00:00", "lease_expires_at": "2099-01-01T00:00:00"},
            {"status": "cleaning", "token_expires_at": "2020-01-01T00:00:00", "lease_expires_at": "2099-01-01T00:00:00"},
        ):
            with self.subTest(job=job), mock.patch.object(backend, "supabase_request", return_value=[{**job, "document_id": "SYNTHETIC-DOC"}]), \
                    mock.patch.object(backend, "_supabase_claim_editor_storage_job") as claim, \
                    mock.patch.object(backend, "supabase_storage_delete") as delete:
                self.assertEqual(backend.supabase_cleanup_stale_official_editor_uploads(document_id="SYNTHETIC-DOC")["count"], 0)
                claim.assert_not_called()
                delete.assert_not_called()


class ImmutableReadbackBudgetTest(unittest.TestCase):
    def promote(self, upload_error=None, readback=b"synthetic PDF bytes"):
        data = b"synthetic PDF bytes"
        digest = backend.sha256_bytes(data)
        job = {"id": "JOB", "final_bucket": "synthetic-private", "final_path": "editor-final/DOC/ASSET/hash.pdf", "lease_token": "LEASE"}
        with mock.patch.object(backend, "_supabase_editor_storage_job", return_value=job), \
                mock.patch.object(backend, "_supabase_claim_editor_storage_job", return_value=job), \
                mock.patch.object(backend, "supabase_storage_upload", side_effect=upload_error), \
                mock.patch.object(backend, "supabase_storage_download", return_value=readback) as download, \
                mock.patch.object(backend, "_supabase_release_editor_storage_promotion") as release:
            if readback != data:
                expected = "immutable_asset_conflict" if upload_error else "immutable_asset_verification_failed"
                with self.assertRaisesRegex(ValueError, expected):
                    backend._supabase_promote_editor_asset_to_immutable_storage("DOC", {"mime_type": "application/pdf"}, data, digest)
                release.assert_called_once()
            else:
                self.assertEqual(backend._supabase_promote_editor_asset_to_immutable_storage("DOC", {"mime_type": "application/pdf"}, data, digest), (job["final_path"], "JOB", "LEASE"))
                release.assert_not_called()
            download.assert_called_once_with(job["final_path"], job["final_bucket"])

    def test_successful_create_still_reads_and_verifies_storage_bytes(self):
        self.promote()

    def test_conflict_retry_uses_one_verified_readback_not_two(self):
        self.promote(RuntimeError("supabase_storage_upload_failed:409"))

    def test_changed_readback_is_rejected_on_create_and_retry(self):
        self.promote(readback=b"tampered")
        self.promote(RuntimeError("supabase_storage_upload_failed:409"), readback=b"tampered")


if __name__ == "__main__":
    unittest.main()
