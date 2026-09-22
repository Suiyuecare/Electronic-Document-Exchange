"""Pre-launch authorization regressions using deidentified, isolated records.

No hosted database, real employee, mail delivery, or exchange provider is used.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import unittest
from unittest import mock

import backend
from tests import test_role_compose_http_journeys as journeys


class SupabaseListScopeRegressionTest(unittest.TestCase):
    def list_records(self, scope, *, privileged=False):
        user = {"id": "staff", "company_id": "company-a"}
        rows = [
            {"id": "own", "company_id": "company-a", "applicant_id": "staff", "current_status": "draft"},
            {"id": "unrelated", "company_id": "company-a", "applicant_id": "other", "current_status": "draft"},
            {"id": "foreign", "company_id": "company-b", "applicant_id": "foreign-user", "current_status": "draft"},
        ]
        session = {"user": user, "permissions": ["official_documents.all_records"] if privileged else []}
        with (
            mock.patch.object(backend, "supabase_official_session_user", return_value=user),
            mock.patch.object(backend, "supabase_filter_rows", return_value=copy.deepcopy(rows)),
            mock.patch.object(backend, "supabase_official_document_steps", return_value=[]),
            mock.patch.object(backend, "supabase_official_document_actor_snapshots", return_value=[]),
            mock.patch.object(backend, "supabase_official_dispatch_record", return_value=None),
            mock.patch.object(backend, "supabase_official_document_stamp_request", return_value=None),
        ):
            return backend.supabase_list_official_documents({"scope": [scope]}, session)

    def test_unknown_scope_does_not_expand_staff_visibility(self):
        for scope in ("", "all", "records", "arbitrary", "MINE", " "):
            with self.subTest(scope=scope):
                self.assertEqual([row["id"] for row in self.list_records(scope)], ["own"])

    def test_mine_todo_and_privileged_company_boundaries_are_preserved(self):
        self.assertEqual([row["id"] for row in self.list_records("mine")], ["own"])
        self.assertEqual(self.list_records("todo"), [])
        self.assertEqual([row["id"] for row in self.list_records("all", privileged=True)], ["own", "unrelated"])


class DelegatedReadGuardParityTest(unittest.TestCase):
    def setUp(self):
        profile = backend.LOGGING_ROLE_TO_EDOC_PROFILE["section_chief"]
        self.user = {
            "id": "delegate", "company_id": "company-a", "status": "啟用",
            "account_source": "finance", "auth_user_id": "isolated-auth", "finance_employee_id": "isolated-employee",
            "logging_role_key": "section_chief", "role": profile["role"], "job_level": profile["job_level"], "title": "隔離課長",
        }
        self.document = {
            "id": "isolated-v2", "company_id": "company-a", "applicant_id": "applicant",
            "current_status": "pending_applicant_manager", "current_step": "applicant_manager",
            "metadata_json": '{"pdf_editor_v2":true}',
        }
        self.step = {
            "id": "step-2", "document_id": self.document["id"], "workflow_generation": 2,
            "step_key": "applicant_manager", "status": "pending", "approver_user_id": "principal",
        }
        current = datetime.now()
        self.delegation = {
            "id": "isolated-delegation", "company_id": "company-a", "principal_user_id": "principal",
            "delegate_user_id": "delegate", "status": "active",
            "starts_at": (current - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "ends_at": (current + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.session = {"user": self.user, "permissions": []}

    def supabase_read_patches(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(mock.patch.object(backend, "supabase_official_session_user", return_value=self.user))
        stack.enter_context(mock.patch.object(backend, "supabase_official_document_steps", return_value=[self.step]))
        stack.enter_context(mock.patch.object(backend, "supabase_official_document_actor_snapshots", return_value=[]))
        stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", return_value=[self.delegation]))
        stack.enter_context(mock.patch.object(backend, "supabase_user_by_id", side_effect=lambda uid: {**self.user, "id": uid}))
        return stack

    def test_v2_delegate_can_read_comparison_but_cannot_edit(self):
        with self.supabase_read_patches():
            self.assertEqual(backend._supabase_editor_assert_document_access(self.document, self.session), self.user)
            with (
                mock.patch.object(backend, "require_official_document_application_company"),
                mock.patch.object(backend, "pdf_editor_v2_enabled_for_company", return_value=True),
                self.assertRaisesRegex(PermissionError, "official_editor_write_forbidden"),
            ):
                backend._supabase_editor_assert_document_access(self.document, self.session, write=True)

    def test_expired_revoked_and_foreign_delegate_remain_blocked(self):
        mutations = (
            {"status": "revoked"},
            {"ends_at": (datetime.now() - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")},
            {"starts_at": (datetime.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                original = self.delegation.copy()
                self.delegation.update(mutation)
                with self.supabase_read_patches(), self.assertRaises(PermissionError):
                    backend._supabase_editor_assert_document_access(self.document, self.session)
                self.delegation = original
        self.user["company_id"] = "foreign-company"
        with self.supabase_read_patches(), self.assertRaisesRegex(PermissionError, "company_forbidden"):
            backend._supabase_editor_assert_document_access(self.document, self.session)

    def test_read_delegation_never_uses_superseded_or_noncurrent_step(self):
        old_step = {**self.step, "workflow_generation": 1}
        scenarios = (
            ({**self.document, "current_status": "closed"}, [self.step]),
            (self.document, [{**self.step, "status": "approved"}]),
            ({**self.document, "current_step": "department_head", "current_status": "pending_department_head"}, [self.step]),
            (self.document, [old_step, {**self.step, "step_key": "department_head"}]),
            ({**self.document, "current_step": "applicant_confirm", "current_status": "stamped"}, [{**self.step, "step_key": "applicant_confirm"}]),
        )
        for document, steps in scenarios:
            with self.subTest(status=document["current_status"], steps=steps):
                with mock.patch.object(backend, "supabase_active_official_workflow_delegation") as lookup:
                    self.assertIsNone(backend.official_document_active_read_delegation(document, steps, self.user, supabase_mode=True))
                    lookup.assert_not_called()

    def test_role_or_company_changes_invalidate_supabase_delegation(self):
        valid = self.user.copy()
        mutations = ({"logging_role_key": "staff"}, {"company_id": ""}, {"job_level": "invalid"})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.user.update(mutation)
                with (
                    self.supabase_read_patches(),
                    mock.patch.object(backend, "supabase_user_by_id", side_effect=lambda uid: {**(valid if uid == "principal" else self.user), "id": uid}),
                    self.assertRaises(PermissionError),
                ):
                    backend._supabase_editor_assert_document_access(self.document, self.session)
                self.user.clear()
                self.user.update(valid)

    def test_stale_delegation_is_denied_without_masking_unexpected_failures(self):
        for error in (
            PermissionError("official_workflow_delegation_actor_inactive"),
            PermissionError("official_workflow_delegation_company_forbidden"),
            ValueError("official_workflow_delegation_ambiguous"),
        ):
            with self.subTest(error=str(error)):
                with mock.patch.object(backend, "supabase_active_official_workflow_delegation", side_effect=error):
                    self.assertIsNone(backend.official_document_active_read_delegation(self.document, [self.step], self.user, supabase_mode=True))
        with (
            mock.patch.object(backend, "supabase_active_official_workflow_delegation", side_effect=ValueError("unexpected_backend_failure")),
            self.assertRaisesRegex(ValueError, "unexpected_backend_failure"),
        ):
            backend.official_document_active_read_delegation(self.document, [self.step], self.user, supabase_mode=True)

    def test_supabase_delegate_download_is_scoped_before_storage_is_signed(self):
        file = {"id": "file-1", "document_id": self.document["id"], "file_object_id": "object-1", "file_type": "prepared_pdf", "file_name": "isolated.pdf"}
        object_row = {"id": "object-1", "storage_key": "isolated/key", "bucket": "isolated-private"}
        def rows(table, filters, **_):
            return [self.delegation] if table == "official_workflow_delegations" else [file]
        with (
            self.supabase_read_patches(),
            mock.patch.object(backend, "supabase_filter_rows", side_effect=rows),
            mock.patch.object(backend, "supabase_official_document_row", return_value=self.document),
            mock.patch.object(backend, "supabase_assert_official_document_uploads_av_clean"),
            mock.patch.object(backend, "supabase_get", return_value=object_row),
            mock.patch.object(backend, "require_official_file_av_clean", return_value=object_row),
            mock.patch.object(backend, "verify_private_storage_file_metadata"),
            mock.patch.object(backend, "supabase_storage_create_signed_download_url", return_value={"url": "isolated-capability"}) as signer,
            mock.patch.object(backend, "supabase_insert_official_log") as log,
            mock.patch.object(backend, "supabase_insert"),
        ):
            _, _, signed = backend.supabase_official_document_download_file(self.document["id"], file["id"], self.session)
            self.assertEqual(signed, {"url": "isolated-capability"})
            self.assertEqual(log.call_args.args[2]["id"], "delegate")
            signer.reset_mock()
            self.delegation["status"] = "revoked"
            with self.assertRaisesRegex(PermissionError, "official_document_download_forbidden"):
                backend.supabase_official_document_download_file(self.document["id"], file["id"], self.session)
            signer.assert_not_called()


class DelegatedReviewHttpRegressionTest(unittest.TestCase):
    setUpClass = classmethod(journeys.RoleComposeHttpJourneysTest.setUpClass.__func__)
    tearDownClass = classmethod(journeys.RoleComposeHttpJourneysTest.tearDownClass.__func__)
    api = journeys.RoleComposeHttpJourneysTest.api
    create = journeys.RoleComposeHttpJourneysTest.create
    approve_to_dispatch = journeys.RoleComposeHttpJourneysTest.approve_to_dispatch
    review = journeys.RoleComposeHttpJourneysTest.review
    complete_and_confirm = journeys.RoleComposeHttpJourneysTest.complete_and_confirm

    def create_editor(self, case):
        owner = self.tokens[case["ordinal"]]
        draft = self.api("POST", "/api/official-documents/editor-drafts", owner, {
            "company_id": case["company_id"], "title": "隔離代理 PDF 編輯驗收",
            "subject": "隔離代理 PDF 編輯驗收", "request_reason": "檢驗代理唯讀比較權限",
            "document_category": case["category"], "dispatch_method": "no_dispatch_required",
        }, 201)
        document_id = draft["document_id"]
        source = self.fixture._make_a4_pdf(case)
        digest = backend.sha256_bytes(source)
        intent = self.api("POST", f"/api/official-documents/{document_id}/editor-uploads", owner, {
            "asset_kind": "source_pdf", "file_name": "isolated-delegation.pdf", "mime_type": "application/pdf",
            "size_bytes": len(source), "sha256": digest,
        }, 201)
        if self.fixture.upload_protocol == "local_supabase_tus":
            self.fixture._perform_tus_upload(intent, source)
        else:
            result = self.fixture._request("PUT", intent["upload_url"], token=owner, raw_body=source, headers={"Content-Type": "application/pdf"})
            self.assertEqual(result.status, 201)
        finalized = self.api("POST", f"/api/official-documents/{document_id}/editor-uploads/{intent['upload_id']}/finalize", owner, {"sha256": digest})
        revision = finalized["editor_revision"]
        saved = self.api("PUT", f"/api/official-documents/{document_id}/editor-state", owner, {
            "revisionNo": revision["revisionNo"], "baseManifestSha256": revision["manifestSha256"],
            "state": self.fixture._editor_state(revision, case),
        })
        prepared = self.api("POST", f"/api/official-documents/{document_id}/editor-preflight", owner, {
            "editorRevisionId": saved["id"], "manifestSha256": saved["manifestSha256"],
        }, 201)
        return self.api("POST", f"/api/official-documents/{document_id}/submit", owner, {
            key: prepared[key] for key in ("editorRevisionId", "manifestSha256", "preparedFileId", "preparedSha256")
        })

    def delegated_document(self, *, editor=False):
        case = next(case for case in self.fixture.case_definitions if case["ordinal"] == 1)
        delegate_case = next(case for case in self.fixture.case_definitions if case["role"] == "section_chief")
        owner = self.tokens[case["ordinal"]]
        if editor:
            document = self.create_editor(case)
        else:
            document = self.create(case, "electronic")
            document = self.api("POST", f"/api/official-documents/{document['id']}/submit", owner, {})
        step = next(step for step in document["approval_steps"] if step["step_key"] == document["current_step"])
        principal = self.fixture._token_for_user_id(step["approver_user_id"])
        delegate = self.tokens[delegate_case["ordinal"]]
        with backend.connect() as conn:
            delegate_row = conn.execute("SELECT id FROM users WHERE email = ?", (delegate_case["email"],)).fetchone()
        current = datetime.now()
        delegation = self.api("POST", "/api/workflow-delegations", principal, {
            "delegate_user_id": delegate_row["id"],
            "starts_at": (current - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "ends_at": (current + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
            "reason": "隔離測試職務代理",
        }, 201)
        return document, owner, principal, delegate, delegation

    def revoke(self, delegation, principal):
        return self.api("POST", f"/api/workflow-delegations/{delegation['id']}/revoke", principal, {})

    def test_active_delegate_can_review_files_and_complete_real_approval(self):
        document, owner, principal, delegate, delegation = self.delegated_document()
        try:
            detail = self.api("GET", f"/api/official-documents/{document['id']}", delegate)
            self.assertTrue(detail["can_act"])
            self.assertTrue(detail["can_download"], "A current delegate must be able to review the files they are required to approve")
            todo = self.api("GET", "/api/official-documents?scope=todo", delegate)
            row = next(row for row in todo if row["id"] == document["id"])
            self.assertTrue(row["can_download"])
            for file in detail["files"]:
                if file["file_type"] in {"generated_pdf", "original_pdf", "prepared_pdf", "attachment"}:
                    result = self.fixture._request("GET", f"/api/official-documents/{document['id']}/files/{file['id']}/download", token=delegate)
                    self.assertEqual(result.status, 200)
                    self.assertTrue(result.body.startswith(b"%PDF"))
            step = next(step for step in detail["approval_steps"] if step["step_key"] == detail["current_step"])
            detail = self.api("POST", f"/api/official-documents/{document['id']}/approve", delegate, {
                "expected_step_id": step["id"], "comment": "代理人已檢閱去識別測試文件。",
                "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True},
            })
            approved = next(item for item in detail["approval_step_history"] if item["id"] == step["id"])
            self.assertNotEqual(approved["decision_actor_user_id"], approved["approver_user_id"])
            self.revoke(delegation, principal)
            delegation = None
            detail = self.approve_to_dispatch(detail)
            detail, _ = self.complete_and_confirm(detail, owner)
            records = self.api("GET", "/api/official-documents", delegate)
            self.assertIn(document["id"], {item["id"] for item in records}, "An actual decision actor must retain their approval record after delegation ends")
            final = self.fixture._request("GET", f"/api/official-documents/{document['id']}/files/{detail['stamped_file_id']}/download", token=delegate)
            self.assertEqual(final.status, 200)
        finally:
            if delegation:
                self.revoke(delegation, principal)

    def test_revoked_delegate_without_decision_cannot_download_or_approve(self):
        document, _, principal, delegate, delegation = self.delegated_document()
        self.revoke(delegation, principal)
        file = next(file for file in document["files"] if file["file_type"] == "generated_pdf")
        denied = self.fixture._request("GET", f"/api/official-documents/{document['id']}/files/{file['id']}/download", token=delegate)
        self.assertEqual(denied.status, 403)
        step = next(step for step in document["approval_steps"] if step["step_key"] == document["current_step"])
        denied = self.fixture._request("POST", f"/api/official-documents/{document['id']}/approve", token=delegate, json_body={"expected_step_id": step["id"], "comment": "不得接受已撤销代理"})
        self.assertEqual(denied.status, 403)
        todo = self.api("GET", "/api/official-documents?scope=todo", delegate)
        self.assertNotIn(document["id"], {item["id"] for item in todo})

    def test_v2_delegate_can_compare_but_cannot_edit_and_revocation_closes_asset_access(self):
        document, _, principal, delegate, delegation = self.delegated_document(editor=True)
        try:
            state = self.api("GET", f"/api/official-documents/{document['id']}/editor-state", delegate)
            self.assertEqual(state["id"], document["stamp_request"]["locked_editor_revision_id"])
            asset_url = state["assets"][0]["url"]
            source = self.fixture._request("GET", asset_url, token=delegate)
            self.assertEqual(source.status, 200)
            self.assertTrue(source.body.startswith(b"%PDF"))
            summary = self.api("GET", f"/api/official-documents/{document['id']}/editor-change-summary", delegate)
            self.assertTrue(summary)
            prepared = next(file for file in document["files"] if file["file_type"] == "prepared_pdf")
            download = self.fixture._request("GET", f"/api/official-documents/{document['id']}/files/{prepared['id']}/download", token=delegate)
            self.assertEqual(download.status, 200)
            rejected_edit = self.fixture._request("PUT", f"/api/official-documents/{document['id']}/editor-state", token=delegate, json_body={})
            self.assertEqual(rejected_edit.status, 403)
            self.revoke(delegation, principal)
            delegation = None
            for path in (asset_url, f"/api/official-documents/{document['id']}/editor-state"):
                self.assertEqual(self.fixture._request("GET", path, token=delegate).status, 403)
        finally:
            if delegation:
                self.revoke(delegation, principal)

    def test_lists_do_not_expose_noncurrent_or_superseded_delegation(self):
        for scenario in ("closed", "superseded"):
            with self.subTest(scenario=scenario):
                document, _, principal, delegate, delegation = self.delegated_document()
                try:
                    with backend.connect() as conn:
                        if scenario == "closed":
                            conn.execute("UPDATE official_documents SET current_status='closed' WHERE id=?", (document["id"],))
                        else:
                            # Detail rows also carry read-only audit display
                            # fields; a new generation must copy persisted data.
                            persisted_steps = backend.current_official_document_steps(conn, document["id"])
                            for step in persisted_steps:
                                newer = {**step, "id": step["id"] + "-GEN2", "workflow_generation": 2}
                                if newer["step_key"] == "applicant_manager":
                                    newer["approver_user_id"] = next(item["approver_user_id"] for item in persisted_steps if item["step_key"] == "department_head")
                                backend.insert_row(conn, "official_document_approval_steps", newer)
                    for scope in ("", "all", "todo"):
                        records = self.api("GET", "/api/official-documents?scope=" + scope, delegate)
                        self.assertNotIn(document["id"], {item["id"] for item in records})
                finally:
                    self.revoke(delegation, principal)

    def test_finance_role_change_removes_delegated_read_and_decision_rights(self):
        document, _, principal, _, delegation = self.delegated_document()
        original = None
        try:
            with backend.connect() as conn:
                original = dict(conn.execute("SELECT * FROM users WHERE id=?", (delegation["delegate_user_id"],)).fetchone())
                staff = conn.execute("SELECT * FROM users WHERE id=?", (document["applicant_id"],)).fetchone()
                conn.execute("UPDATE users SET role=?, logging_role_key=?, job_level=?, title=? WHERE id=?", (
                    staff["role"], staff["logging_role_key"], staff["job_level"], staff["title"], delegation["delegate_user_id"],
                ))
                user = dict(conn.execute("SELECT * FROM users WHERE id=?", (delegation["delegate_user_id"],)).fetchone())
                session = {"user": user, "permissions": []}
                for scope in ("", "all", "todo"):
                    records = backend.list_official_documents(conn, {"scope": [scope]}, session)
                    self.assertNotIn(document["id"], {item["id"] for item in records})
                step = next(step for step in document["approval_steps"] if step["step_key"] == document["current_step"])
                with self.assertRaisesRegex(PermissionError, "not_current_official_document_approver"):
                    backend.assert_official_step_actor(user, step, document, conn=conn)
                file = next(file for file in document["files"] if file["file_type"] == "generated_pdf")
                with self.assertRaisesRegex(PermissionError, "official_document_download_forbidden"):
                    backend.official_document_download_file(conn, document["id"], file["id"], session)
        finally:
            if original:
                with backend.connect() as conn:
                    conn.execute("UPDATE users SET role=?, logging_role_key=?, job_level=?, title=? WHERE id=?", (
                        original["role"], original["logging_role_key"], original["job_level"], original["title"], original["id"],
                    ))
            self.revoke(delegation, principal)

    def test_inactive_principal_does_not_break_the_delegates_other_records(self):
        own_case = next(case for case in self.fixture.case_definitions if case["role"] == "section_chief")
        own_document = self.create(own_case, "electronic")
        document, _, principal, _, delegation = self.delegated_document()
        try:
            with backend.connect() as conn:
                user = dict(conn.execute("SELECT * FROM users WHERE id=?", (delegation["delegate_user_id"],)).fetchone())
                conn.execute("UPDATE users SET status='停用' WHERE id=?", (delegation["principal_user_id"],))
                session = {"user": user, "permissions": []}
                for scope in ("", "all", "todo"):
                    records = backend.list_official_documents(conn, {"scope": [scope]}, session)
                    self.assertNotIn(document["id"], {item["id"] for item in records})
                    if scope != "todo":
                        self.assertIn(own_document["id"], {item["id"] for item in records})
                step = next(step for step in document["approval_steps"] if step["step_key"] == document["current_step"])
                with self.assertRaisesRegex(PermissionError, "official_workflow_delegation_actor_inactive"):
                    backend.assert_official_step_actor(user, step, document, conn=conn)
        finally:
            with backend.connect() as conn:
                conn.execute("UPDATE users SET status='啟用' WHERE id=?", (delegation["principal_user_id"],))
            self.revoke(delegation, principal)


if __name__ == "__main__":
    unittest.main()
