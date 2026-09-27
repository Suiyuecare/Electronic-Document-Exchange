"""Synthetic-only prepared-file locking and application CAS regressions."""
import copy
import unittest
from contextlib import ExitStack
from unittest import mock

import backend
from compose_resilience import require_content_revision
from tests import test_general_document_seal_workflow as workflow_fixture


class EditorRevisionRaceTest(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow_fixture.GeneralDocumentSealWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn, self.session = self.fixture.conn, self.fixture.session

    def prepared_twice(self):
        document_id, revision, _ = self.fixture._draft()
        self.fixture._save(document_id, revision, self.fixture._combined_state(revision))
        first = backend.preflight_official_editor(self.conn, document_id, {}, self.session)
        second = backend.preflight_official_editor(self.conn, document_id, {}, self.session)
        self.assertEqual(first["editorRevisionId"], second["editorRevisionId"])
        self.assertNotEqual(first["preparedFileId"], second["preparedFileId"])
        return document_id, first, second

    def submit_first(self):
        document_id, first, second = self.prepared_twice()
        payload = {key: first[key] for key in ("editorRevisionId", "manifestSha256", "preparedFileId", "preparedSha256")}
        payload["expected_content_revision"] = backend.official_document_row(self.conn, document_id)["content_revision"]
        detail = backend.submit_official_document(self.conn, document_id, payload, self.session)
        return document_id, first, second, detail

    def remote_state(self, document_id):
        def rows(table, filters, **options):
            where = " AND ".join(f"{key}=?" for key in filters)
            result = [dict(row) for row in self.conn.execute(f"SELECT * FROM {table} WHERE {where}", tuple(filters.values()))]
            if options.get("order") == "created_at.desc,id.desc":
                result.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return result[:options["limit"]] if options.get("limit") else result
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(backend, "supabase_official_document_row", side_effect=lambda _: backend.official_document_row(self.conn, document_id)))
            stack.enter_context(mock.patch.object(backend, "_supabase_editor_assert_document_access"))
            stack.enter_context(mock.patch.object(backend, "_supabase_editor_latest_revision", side_effect=lambda _: backend._editor_latest_revision_row(self.conn, document_id)))
            stack.enter_context(mock.patch.object(backend, "supabase_official_document_stamp_request", side_effect=lambda _: backend.official_document_stamp_request(self.conn, document_id)))
            stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", side_effect=rows))
            stack.enter_context(mock.patch.object(backend, "editor_asset_access_manifest", return_value=[]))
            return backend.supabase_get_official_editor_state(document_id, self.session)

    def test_locked_prepared_identity_hash_and_url_never_follow_newest_file(self):
        document_id, first, second, _ = self.submit_first()
        for result in (backend.get_official_editor_state(self.conn, document_id, self.session), self.remote_state(document_id)):
            self.assertEqual(result["preparedFileId"], first["preparedFileId"])
            self.assertEqual(result["preparedSha256"], first["preparedSha256"])
            self.assertEqual(result["preparedUrl"], backend.official_editor_file_authorized_url(document_id, first["preparedFileId"]))
            self.assertEqual(result["authorizedUrl"], result["preparedUrl"])
            self.assertNotEqual(result["preparedFileId"], second["preparedFileId"])
            _, _, downloaded = backend.official_document_download_file(self.conn, document_id, result["preparedFileId"], self.session)
            self.assertEqual(backend.sha256_bytes(downloaded), result["preparedSha256"])

    def test_submitted_state_reads_exact_locked_revision_even_after_valid_late_child(self):
        document_id, first, _, detail = self.submit_first()
        locked = backend.get_official_editor_state(self.conn, document_id, self.session)
        child = backend._insert_editor_revision(self.conn, document_id, copy.deepcopy(locked["state"]), self.session["user"], locked["id"])
        self.assertNotEqual(child["id"], locked["id"])
        self.assertEqual(backend._editor_latest_revision_row(self.conn, document_id)["id"], child["id"])
        for result in (backend.get_official_editor_state(self.conn, document_id, self.session), self.remote_state(document_id)):
            self.assertEqual(result["id"], detail["stamp_request"]["locked_editor_revision_id"])
            self.assertEqual(result["state"], locked["state"])
            self.assertEqual(result["status"], "locked")
            self.assertEqual(result["preparedFileId"], first["preparedFileId"])
            self.assertEqual(result["preparedSha256"], first["preparedSha256"])
            self.assertEqual(result["preparedUrl"], locked["preparedUrl"])
        # Correction cases intentionally open the newest editable revision.
        self.conn.execute("UPDATE official_documents SET current_status='rejected' WHERE id=?", (document_id,))
        for result in (backend.get_official_editor_state(self.conn, document_id, self.session), self.remote_state(document_id)):
            self.assertEqual(result["id"], child["id"])
            self.assertEqual(result["status"], "draft")

    def test_incomplete_or_missing_locked_prepared_file_fails_closed(self):
        document_id, first, _, detail = self.submit_first()
        request = detail["stamp_request"]
        request_id = request["id"]
        for field, value in (("prepared_file_id", ""), ("prepared_sha256", ""), ("prepared_file_id", "MISSING-FILE"), ("prepared_sha256", "F" * 64), ("locked_editor_revision_id", ""), ("locked_editor_revision_id", "MISSING-REVISION")):
            with self.subTest(field=field, value=value):
                self.conn.execute(f"UPDATE official_document_stamp_requests SET {field}=? WHERE id=?", (value, request_id))
                for operation in (lambda: backend.get_official_editor_state(self.conn, document_id, self.session), lambda: self.remote_state(document_id)):
                    with self.assertRaisesRegex(ValueError, "editor_(locked_prepared|locked_revision|prepared)"):
                        operation()
                self.conn.execute(f"UPDATE official_document_stamp_requests SET {field}=? WHERE id=?", (request[field], request_id))

    def test_draft_without_submission_lock_still_uses_latest_prepared_file(self):
        document_id, _, second = self.prepared_twice()
        for result in (backend.get_official_editor_state(self.conn, document_id, self.session), self.remote_state(document_id)):
            self.assertEqual(result["preparedFileId"], second["preparedFileId"])

    def test_locked_prepared_asset_must_match_submission_revision_hash_and_object(self):
        document_id, first, _, _ = self.submit_first()
        asset = dict(self.conn.execute("SELECT * FROM official_document_editor_assets WHERE official_file_id=?", (first["preparedFileId"],)).fetchone())
        other_revision = self.conn.execute("SELECT id FROM official_document_editor_revisions WHERE document_id=? AND id<>? ORDER BY revision_no LIMIT 1", (document_id, asset["editor_revision_id"])).fetchone()[0]
        other_object = self.conn.execute("SELECT file_object_id FROM official_document_files WHERE document_id=? AND file_type='original_pdf'", (document_id,)).fetchone()[0]
        for field, value in (("editor_revision_id", other_revision), ("sha256", "F" * 64), ("file_object_id", other_object), ("preflight_status", "failed")):
            with self.subTest(field=field):
                self.conn.execute(f"UPDATE official_document_editor_assets SET {field}=? WHERE id=?", (value, asset["id"]))
                for operation in (lambda: backend.get_official_editor_state(self.conn, document_id, self.session), lambda: self.remote_state(document_id)):
                    with self.assertRaisesRegex(ValueError, "editor_locked_prepared_asset_missing"):
                        operation()
                self.conn.execute(f"UPDATE official_document_editor_assets SET {field}=? WHERE id=?", (asset[field], asset["id"]))

    def test_pdf_v2_metadata_patch_requires_client_revision_and_preserves_winner(self):
        document_id, _, _ = self.fixture._draft()
        before = copy.deepcopy(backend.official_document_row(self.conn, document_id))
        with self.assertRaisesRegex(ValueError, "content_revision_required"):
            backend.update_official_document_correction(self.conn, document_id, {"title": "No revision"}, self.session)
        self.assertEqual(backend.official_document_row(self.conn, document_id), before)
        updated = backend.update_official_document_correction(self.conn, document_id, {"title": "Winning device", "expected_content_revision": before["content_revision"]}, self.session)
        self.assertEqual(updated["content_revision"], before["content_revision"] + 1)
        for operation in (backend.update_official_document_correction, backend.submit_official_document):
            with self.assertRaisesRegex(ValueError, "content_revision_conflict"):
                operation(self.conn, document_id, {"title": "Stale device", "expected_content_revision": before["content_revision"]}, self.session)
        self.assertEqual(backend.official_document_row(self.conn, document_id)["title"], "Winning device")

    def test_pdf_v2_submit_missing_revision_has_no_workflow_or_lock_effect(self):
        document_id, first, _ = self.prepared_twice()
        before = copy.deepcopy(backend.official_document_stamp_request(self.conn, document_id))
        with self.assertRaisesRegex(ValueError, "content_revision_required"):
            backend.submit_official_document(self.conn, document_id, first, self.session)
        self.assertEqual(backend.official_document_stamp_request(self.conn, document_id), before)
        self.assertFalse(backend.official_document_steps(self.conn, document_id))
        self.assertEqual(backend.official_document_row(self.conn, document_id)["current_status"], "draft")

    def test_supabase_missing_and_stale_client_revision_reject_before_rpc(self):
        document_id, _, _ = self.fixture._draft()
        document = backend.official_document_row(self.conn, document_id)
        document["content_revision"] = 3
        with mock.patch.object(backend, "supabase_official_session_user", return_value=self.session["user"]), mock.patch.object(backend, "supabase_official_document_row", return_value=document), mock.patch.object(backend, "supabase_request") as request:
            for operation in (backend.supabase_update_official_document_correction, backend.supabase_submit_official_document):
                for payload, error in (({}, "content_revision_required"), ({"expected_content_revision": 2}, "content_revision_conflict")):
                    with self.subTest(operation=operation.__name__, payload=payload), self.assertRaisesRegex(ValueError, error):
                        operation(document_id, payload, self.session)
            request.assert_not_called()


class ContentRevisionGuardTest(unittest.TestCase):
    def test_pdf_v2_requires_exact_nonnegative_integer_and_keeps_legacy_compatibility(self):
        document = {"source_type": "uploaded_pdf", "metadata_json": '{"pdf_editor_v2":true}', "content_revision": 4}
        for expected in (None, True, False, "4", 4.0, -1):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, "content_revision_required"):
                require_content_revision(document, {"expected_content_revision": expected})
        with self.assertRaisesRegex(ValueError, "content_revision_conflict"):
            require_content_revision(document, {"expected_content_revision": 3})
        require_content_revision(document, {"expected_content_revision": 4})
        require_content_revision({"source_type": "uploaded_pdf", "metadata_json": "{}", "content_revision": 4}, {})


if __name__ == "__main__":
    unittest.main()
