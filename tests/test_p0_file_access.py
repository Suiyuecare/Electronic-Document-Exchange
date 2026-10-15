"""Deidentified file-boundary audit. No hosted services or real identities.

Supabase tests replace only persistence/transport with the SQLite fixture;
authorization functions remain real. HTTP routing is executed synchronously
against an uninitialized handler, with no server or production session.
"""
from contextlib import ExitStack, nullcontext
import copy
import io
import time
import unittest
from unittest import mock

from PIL import Image
import backend
from tests import test_five_account_editor_workflow as fixture_module


class P0FileAccessTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.FiveAccountEditorWorkflowTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.conn = self.fixture.conn
        self.owner = self.fixture._session_for_user_id(self.fixture.applicant_ids[0])
        self.outsider = self.fixture._session_for_user_id(self.fixture.applicant_ids[1])
        self.foreign = copy.deepcopy(self.outsider)
        self.foreign["user"].update(company_id="CO-002", finance_tenant_id="OTHER-TENANT")
        self.draft = backend.create_official_editor_draft(self.conn, {
            "company_id": "CO-001", "title": "Isolated file access audit",
            "document_category": "合作意向書", "request_reason": "Synthetic audit",
            "dispatch_method": "no_dispatch_required",
        }, self.owner)
        self.doc_id = self.draft["document_id"]
        self.pdf = self.fixture._a4_pdf_bytes(701)
        self.source = self.upload(self.pdf, "source_pdf", "application/pdf", "synthetic.pdf")
        stream = io.BytesIO()
        Image.new("RGB", (32, 24), (20, 120, 60)).save(stream, format="PNG")
        self.image_bytes = stream.getvalue()
        self.image = self.upload(self.image_bytes, "image", "image/png", "synthetic.png")

    def upload(self, data, kind, mime, filename):
        digest = backend.sha256_bytes(data)
        intent = backend.create_official_editor_upload_intent(self.conn, self.doc_id, {
            "asset_kind": kind, "file_name": filename, "mime_type": mime,
            "size_bytes": len(data), "sha256": digest,
        }, self.owner)
        backend.store_official_editor_local_upload(self.conn, self.doc_id, intent["upload_id"], data, self.owner, mime)
        return backend.finalize_official_editor_upload(self.conn, self.doc_id, intent["upload_id"], {"sha256": digest}, self.owner)

    def asset_row(self, finalized):
        return dict(self.conn.execute("SELECT * FROM official_document_editor_assets WHERE id=?", (finalized["asset"]["id"],)).fetchone())

    def signed_asset_args(self, finalized, document_id=None):
        doc_id = document_id or self.doc_id
        asset_id = finalized["asset"]["id"]
        expires = int(time.time()) + 300
        return doc_id, asset_id, expires, backend._editor_asset_access_token(doc_id, asset_id, expires)

    def complete_case(self):
        revision = self.image["editor_revision"]
        saved = backend.save_official_editor_state(self.conn, self.doc_id, {
            "revisionNo": revision["revisionNo"], "baseManifestSha256": revision["manifestSha256"],
            "state": self.fixture._add_editor_elements(revision, 701),
        }, self.owner)
        prepared = backend.preflight_official_editor(self.conn, self.doc_id, {
            "editorRevisionId": saved["id"], "manifestSha256": saved["manifestSha256"],
        }, self.owner)
        submitted = backend.submit_official_document(self.conn, self.doc_id, {
            **{key: prepared[key] for key in ("editorRevisionId", "manifestSha256", "preparedFileId", "preparedSha256")},
            "expected_content_revision": backend.official_document_row(self.conn, self.doc_id)["content_revision"],
        }, self.owner)
        return self.fixture._approve_and_stamp(submitted)

    def supabase_fixture(self):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(backend, "supabase_official_document_row", side_effect=lambda doc: backend.official_document_row(self.conn, doc)))
        stack.enter_context(mock.patch.object(backend, "supabase_official_document_steps", side_effect=lambda doc: backend.official_document_steps(self.conn, doc)))
        stack.enter_context(mock.patch.object(backend, "supabase_official_document_actor_snapshots", side_effect=lambda doc: backend.official_document_actor_snapshots(self.conn, doc)))
        def rows(table, filters, **kwargs):
            where = " AND ".join(f'"{key}"=?' for key in filters)
            return [dict(row) for row in self.conn.execute(f'SELECT * FROM "{table}" WHERE {where}', tuple(filters.values()))]
        stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", side_effect=rows))
        stack.enter_context(mock.patch.object(backend, "supabase_get", side_effect=lambda table, key: next(iter(rows(table, {"id": key})), None)))
        return stack

    def route(self, method, path, *, supabase=False, payload=None, actor=None):
        handler = object.__new__(backend.Handler)
        handler.path = path
        handler.headers = {}
        handler.wfile = io.BytesIO()
        handler.client_address = ("127.0.0.1", 0)
        handler.send_json = mock.Mock()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler.read_json = mock.Mock(return_value=payload or {})
        with mock.patch.object(backend, "USE_SUPABASE", supabase), mock.patch.object(backend, "connect", return_value=nullcontext(self.conn)), mock.patch.object(backend, "current_session", return_value=actor), mock.patch.object(backend, "supabase_current_session", return_value=actor):
            backend.Handler.handle_api(handler, method, path.split("?", 1)[0], {})
        return handler

    def test_official_original_prepared_stamped_reject_anonymous_and_outsiders(self):
        detail = self.complete_case()
        kinds = {item["file_type"] for item in detail["files"]}
        self.assertTrue({"original_pdf", "prepared_pdf", "stamped_pdf"} <= kinds)
        for item in detail["files"]:
            if item["file_type"] not in {"original_pdf", "prepared_pdf", "stamped_pdf"}:
                continue
            _, _, data = backend.official_document_download_file(self.conn, self.doc_id, item["id"], self.owner)
            self.assertEqual(backend.sha256_bytes(data), item["file_hash"])
            for actor in (None, self.outsider, self.foreign):
                with self.subTest(kind=item["file_type"], actor=(actor or {}).get("user", {}).get("id")), mock.patch.object(backend, "read_file_object_bytes") as read:
                    with self.assertRaises(PermissionError):
                        backend.official_document_download_file(self.conn, self.doc_id, item["id"], actor)
                    read.assert_not_called()

    def test_editor_pdf_and_image_reject_anonymous_same_company_outsider_and_foreign(self):
        for finalized, expected in ((self.source, self.pdf), (self.image, self.image_bytes)):
            args = self.signed_asset_args(finalized)
            self.assertEqual(backend.local_editor_asset_download(self.conn, *args, self.owner)[1], expected)
            for actor in (None, self.outsider, self.foreign):
                with self.subTest(kind=self.asset_row(finalized)["asset_kind"], actor=actor is None), mock.patch.object(backend, "read_file_object_bytes") as read:
                    with self.assertRaises(PermissionError):
                        backend.local_editor_asset_download(self.conn, *args, actor)
                    read.assert_not_called()

    def test_editor_asset_tokens_expire_and_bind_exact_document_and_asset(self):
        args = self.signed_asset_args(self.image)
        for changed in ((args[0], args[1], int(time.time())-1, args[3]),
                        (args[0], args[1], args[2], "0"*64),
                        (args[0]+"-other", args[1], args[2], args[3]),
                        (args[0], args[1]+"-other", args[2], args[3])):
            with self.subTest(changed=changed[:2]), mock.patch.object(backend, "read_file_object_bytes") as read:
                with self.assertRaises(PermissionError):
                    backend.local_editor_asset_download(self.conn, *changed, self.owner)
                read.assert_not_called()

    def test_foreign_asset_under_owned_document_is_not_found_even_with_valid_test_signature(self):
        second = backend.create_official_editor_draft(self.conn, {"company_id": "CO-001", "title": "Other isolated case", "document_category": "合作意向書"}, self.outsider)
        with self.assertRaisesRegex(ValueError, "editor_asset_not_found"):
            backend.local_editor_asset_download(self.conn, *self.signed_asset_args(self.image, second["document_id"]), self.outsider)

    def test_official_file_id_cannot_be_swapped_into_own_other_case(self):
        detail = self.complete_case()
        second = backend.create_official_editor_draft(self.conn, {"company_id": "CO-001", "title": "Other isolated case", "document_category": "合作意向書"}, self.outsider)
        old_id, old_owner = self.doc_id, self.owner
        self.doc_id, self.owner = second["document_id"], self.outsider
        try:
            self.upload(self.pdf, "source_pdf", "application/pdf", "second-synthetic.pdf")
        finally:
            self.doc_id, self.owner = old_id, old_owner
        file_id = next(item["id"] for item in detail["files"] if item["file_type"] == "stamped_pdf")
        with self.assertRaisesRegex(ValueError, "official_document_file_not_found"):
            backend.official_document_download_file(self.conn, second["document_id"], file_id, self.outsider)

    def test_supabase_download_denies_before_presigning_any_file_or_asset(self):
        detail = self.complete_case()
        with self.supabase_fixture(), mock.patch.object(backend, "supabase_storage_create_signed_download_url") as sign, mock.patch.object(backend, "supabase_storage_download") as read:
            for actor in (None, self.outsider, self.foreign):
                for item in detail["files"]:
                    with self.subTest(kind=item["file_type"]), self.assertRaises(PermissionError):
                        backend.supabase_official_document_download_file(self.doc_id, item["id"], actor)
                for asset in (self.source, self.image):
                    with self.assertRaises(PermissionError):
                        backend.supabase_editor_asset_download(*self.signed_asset_args(asset), actor)
            sign.assert_not_called()
            read.assert_not_called()

    def test_raw_seal_never_gets_generic_signed_url_or_generic_bytes(self):
        seal_file = backend.require_current_company_seal_file(self.conn, self.fixture.seal_id)
        object_id = seal_file["file_object_id"]
        self.assertEqual(backend.create_file_signed_url(self.conn, object_id)["error"], "seal_vault_download_forbidden")
        for actor in (None, self.owner, self.outsider, self.foreign):
            handler = self.route("GET", f"/api/files/{object_id}/download?token=forged", actor=actor)
            self.assertIn(handler.send_json.call_args.args[1], (401, 403))
            self.assertEqual(handler.wfile.getvalue(), b"")

    def test_generic_signed_download_blocks_private_vault_unknown_buckets_and_bad_ttl(self):
        with mock.patch.object(backend, "_urlopen_no_redirect") as http:
            for key, bucket in (("synthetic.png", backend.EDOC_SEAL_STORAGE_BUCKET), ("seal-vault/seals/synthetic.png", backend.EDOC_STORAGE_BUCKET), ("private/seals/synthetic.png", backend.EDOC_STORAGE_BUCKET), ("synthetic.pdf", "unknown-bucket")):
                with self.subTest(key=key), self.assertRaises(PermissionError):
                    backend.supabase_storage_create_signed_download_url(key, bucket)
            for ttl in (-1, 0, 901, 999999):
                with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                    backend.supabase_storage_create_signed_download_url("synthetic.pdf", ttl_seconds=ttl)
            http.assert_not_called()

    def test_preview_is_placeholder_and_never_reads_raw_seal_even_for_owner(self):
        file = backend.require_current_company_seal_file(self.conn, self.fixture.seal_id)
        with mock.patch.object(backend, "read_file_object_bytes", side_effect=AssertionError("raw seal read")) as read:
            preview = backend.local_editor_seal_preview(self.conn, self.fixture.seal_id, self.owner, file_id=file["id"], file_sha256=file["file_hash"])
            self.assertTrue(preview.startswith(b"\x89PNG"))
            self.assertNotEqual(backend.sha256_bytes(preview), file["file_hash"])
            with self.assertRaises(PermissionError):
                backend.local_editor_seal_preview(self.conn, self.fixture.seal_id, None)
            with self.assertRaises(PermissionError):
                backend.local_editor_seal_preview(self.conn, self.fixture.seal_id, self.foreign)
            read.assert_not_called()

    def test_supabase_public_route_does_not_offer_generic_signed_urls(self):
        object_id = self.asset_row(self.image)["file_object_id"]
        for method, path in (("POST", f"/api/files/{object_id}/signed-url"), ("GET", f"/api/files/{object_id}/download?token=forged")):
            for actor, expected in ((None, 401), (self.outsider, 404)):
                handler = self.route(method, path, supabase=True, actor=actor)
                self.assertEqual(handler.send_json.call_args.args[1], expected)
                self.assertEqual(handler.wfile.getvalue(), b"")

    def test_local_generic_image_signed_url_requires_authorization(self):
        """Regression expectation: editor images must not bypass case authorization."""
        object_id = self.asset_row(self.image)["file_object_id"]
        for actor in (None, self.outsider, self.foreign):
            handler = self.route("POST", f"/api/files/{object_id}/signed-url", actor=actor)
            self.assertIn(handler.send_json.call_args.args[1], (401, 403), "nonparticipant obtained editor image download token")

    def old_token(self, file_id):
        token = "synthetic-old-token-" + file_id
        self.conn.execute("INSERT INTO file_download_tokens(id,file_object_id,token_hash,actor,purpose,expires_at,created_at) VALUES (?,?,?,?,?,?,?)",
                          ("TEST-TOKEN-"+file_id, file_id, backend.hash_token(token), "synthetic", "download", backend.signed_url_expiry(300), backend.now()))
        return token

    def test_editor_image_existing_valid_generic_token_is_blocked_for_every_actor(self):
        file_id = self.asset_row(self.image)["file_object_id"]
        token = self.old_token(file_id)
        self.assertTrue(backend.validate_file_download_token(self.conn, file_id, token)[0])
        for actor in (self.owner, self.outsider, self.foreign):
            # Permission to manage ordinary files never overrides case checks.
            actor = {**actor, "permissions": ["files.manage", "official_documents.all_records"]}
            response = self.route("GET", f"/api/files/{file_id}/download?token={token}", actor=actor)
            self.assertEqual(response.send_json.call_args.args[1], 403)
            self.assertEqual(response.wfile.getvalue(), b"")
        self.assertEqual(backend.create_file_signed_url(self.conn, file_id)["error"], "official_document_file_requires_participant_endpoint")

    def test_inbound_and_dispatch_reply_references_never_allow_generic_download(self):
        now = backend.now()
        self.conn.execute("INSERT INTO inbound_documents(id,receive_no,sender_name,subject,created_at,updated_at) VALUES ('TEST-IN','TEST-IN','Synthetic','Synthetic',?,?)", (now, now))
        self.conn.execute("INSERT INTO internal_dispatches(id,title,subject,created_at,updated_at) VALUES ('TEST-DISPATCH','Synthetic','Synthetic',?,?)", (now, now))
        for kind in ("inbound", "reply"):
            # Deliberately use a different file_objects.document_id: protection
            # must follow the actual persisted attachment/reply reference.
            item = backend.store_file_object(self.conn, "TEST-UNRELATED", kind+".pdf", self.pdf, "synthetic", "1", "synthetic")
            if kind == "inbound":
                self.conn.execute("INSERT INTO inbound_document_attachments(id,inbound_document_id,file_object_id,file_name,file_mime_type,file_size,file_hash,created_at) VALUES ('TEST-ATT','TEST-IN',?,'synthetic.pdf','application/pdf',?,?,?)", (item["id"], len(self.pdf), backend.sha256_bytes(self.pdf), now))
            else:
                self.conn.execute("INSERT INTO internal_dispatch_replies(id,dispatch_id,attachment_file_id,created_at) VALUES ('TEST-REPLY','TEST-DISPATCH',?,?)", (item["id"], now))
            self.assertEqual(backend.create_file_signed_url(self.conn, item["id"])["error"], "official_document_file_requires_participant_endpoint")
            token = self.old_token(item["id"])
            response = self.route("GET", f"/api/files/{item['id']}/download?token={token}", actor={**self.owner, "permissions": ["files.manage"]})
            self.assertEqual(response.send_json.call_args.args[1], 403)
            self.assertEqual(response.wfile.getvalue(), b"")

    def legacy_file(self):
        now = backend.now()
        company = self.conn.execute("SELECT name FROM companies WHERE id='CO-001'").fetchone()["name"]
        self.conn.execute("INSERT INTO documents(id,doc_no,direction,company_name,agency_name,subject,status,owner,department,created_at,updated_at) VALUES ('TEST-LEGACY','TEST-LEGACY','發文',?,'Synthetic','Synthetic','draft',?,'Private isolated department',?,?)",
                          (company, self.owner["user"]["name"], now, now))
        return backend.store_file_object(self.conn, "TEST-LEGACY", "synthetic-legacy.pdf", self.pdf, "documents", "1", "synthetic")

    def test_legal_same_company_legacy_download_requires_permission_acl_and_current_scope(self):
        file = self.legacy_file()
        authorized = self.owner
        response = self.route("POST", f"/api/files/{file['id']}/signed-url", actor=authorized)
        payload, status = response.send_json.call_args.args[:2]
        self.assertEqual(status, 201)
        downloaded = self.route("GET", payload["download_url"], actor=authorized)
        self.assertEqual(downloaded.send_response.call_args.args[0], 200)
        self.assertEqual(downloaded.wfile.getvalue(), self.pdf)
        headers = dict(call.args for call in downloaded.send_header.call_args_list)
        self.assertEqual(headers.get("Cache-Control"), "private, no-store, max-age=0")
        self.assertEqual(headers.get("Pragma"), "no-cache")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        other_manager = {**self.outsider, "permissions": ["files.manage"]}
        foreign_owner = {"user": {**authorized["user"], "company_id": "CO-002"}, "permissions": ["files.manage"]}
        foreign_ceo = {"user": {**foreign_owner["user"], "role": "執行長"}, "permissions": ["files.manage"]}
        for actor in ({**authorized, "permissions": []}, other_manager, foreign_owner, foreign_ceo):
            with self.subTest(actor=actor["user"]["role"]):
                denied = self.route("POST", f"/api/files/{file['id']}/signed-url", actor=actor)
                self.assertEqual(denied.send_json.call_args.args[1], 403)
                denied = self.route("GET", payload["download_url"], actor=actor)
                self.assertEqual(denied.send_json.call_args.args[1], 403)
                self.assertEqual(denied.wfile.getvalue(), b"")

    def test_legacy_empty_unknown_company_or_missing_document_is_not_guessed(self):
        file = self.legacy_file()
        authorized = {**self.owner, "permissions": ["files.manage"]}
        for company in ("", "Unknown synthetic company", self.owner["user"]["company_name"]+" "):
            self.conn.execute("UPDATE documents SET company_name=? WHERE id='TEST-LEGACY'", (company,))
            with self.subTest(company=company), self.assertRaises(PermissionError):
                backend.require_generic_file_document_access(self.conn, file["id"], authorized)
        self.conn.execute("UPDATE file_objects SET document_id='MISSING-DOCUMENT' WHERE id=?", (file["id"],))
        with self.assertRaises(PermissionError):
            backend.require_generic_file_document_access(self.conn, file["id"], authorized)

    def test_legacy_existing_acl_grant_is_preserved_and_rechecked_after_revocation(self):
        file = self.legacy_file()
        actor = self.outsider
        self.conn.execute("INSERT INTO document_acl(id,document_id,principal_type,principal_id,can_view,created_at,updated_at) VALUES ('TEST-ACL','TEST-LEGACY','user',?,1,?,?)", (actor["user"]["name"], backend.now(), backend.now()))
        allowed = self.route("POST", f"/api/files/{file['id']}/signed-url", actor={**self.owner, "permissions": ["files.manage"]})
        payload, status = allowed.send_json.call_args.args[:2]
        self.assertEqual(status, 201)
        downloaded = self.route("GET", payload["download_url"], actor=actor)
        self.assertEqual(downloaded.wfile.getvalue(), self.pdf)
        log = dict(self.conn.execute("SELECT actor,detail FROM file_access_logs WHERE file_object_id=? AND result='成功' ORDER BY rowid DESC LIMIT 1", (file["id"],)).fetchone())
        self.assertEqual(log["actor"], backend.official_actor_name(actor["user"]))
        self.assertIn("issued_by="+backend.official_actor_name(self.owner["user"]), log["detail"])
        self.conn.execute("DELETE FROM document_acl WHERE id='TEST-ACL'")
        denied = self.route("GET", payload["download_url"], actor=actor)
        self.assertEqual(denied.send_json.call_args.args[1], 403)
        self.assertEqual(denied.wfile.getvalue(), b"")
        failed = dict(self.conn.execute("SELECT actor,detail FROM file_access_logs WHERE file_object_id=? AND result='失敗' ORDER BY rowid DESC LIMIT 1", (file["id"],)).fetchone())
        self.assertEqual(failed["actor"], backend.official_actor_name(actor["user"]))
        self.assertEqual(failed["detail"], "generic_file_document_forbidden")

    def test_legacy_company_metadata_malformed_conflicting_inactive_or_foreign_tenant_fails_closed(self):
        file = self.legacy_file()
        actor = {**self.owner, "permissions": ["files.manage"]}
        for metadata in ('[]', '"scalar"', '3', 'null', '{broken', '{"company_id":"CO-002"}', '{"companyId":"CO-002"}', '{"company_id":"CO-001","companyId":"CO-002"}'):
            self.conn.execute("UPDATE documents SET metadata_json=? WHERE id='TEST-LEGACY'", (metadata,))
            with self.subTest(metadata=metadata), self.assertRaises(PermissionError):
                backend.require_generic_file_document_access(self.conn, file["id"], actor)
        self.conn.execute("UPDATE documents SET metadata_json='{}' WHERE id='TEST-LEGACY'")
        self.conn.execute("UPDATE companies SET status='inactive' WHERE id='CO-001'")
        with self.assertRaises(PermissionError):
            backend.require_generic_file_document_access(self.conn, file["id"], actor)
        self.conn.execute("UPDATE companies SET status='active',finance_tenant_id='OTHER-TENANT' WHERE id='CO-001'")
        with self.assertRaises(PermissionError):
            backend.require_generic_file_document_access(self.conn, file["id"], actor)

    def test_legacy_real_readonly_role_permissions_preserve_explicit_acl_download(self):
        file = self.legacy_file()
        for role in ("外部檢核單位", "董事會", "股東"):
            actor = {"user": {**self.outsider["user"], "role": role},
                     "permissions": backend.role_permission_codes(self.conn, role)}
            self.assertNotIn("files.manage", actor["permissions"])
            self.assertNotIn("files.download", actor["permissions"])
            self.conn.execute("INSERT OR REPLACE INTO document_acl(id,document_id,principal_type,principal_id,can_view,created_at,updated_at) VALUES ('TEST-READONLY-ACL','TEST-LEGACY','user',?,1,?,?)", (actor["user"]["name"], backend.now(), backend.now()))
            with self.subTest(role=role):
                self.assertTrue(backend.can_read_document(self.conn, "TEST-LEGACY", actor))
                response = self.route("POST", f"/api/files/{file['id']}/signed-url", actor=actor)
                payload, status = response.send_json.call_args.args[:2]
                self.assertEqual(status, 201)
                downloaded = self.route("GET", payload["download_url"], actor=actor)
                self.assertEqual(downloaded.wfile.getvalue(), self.pdf)
                foreign = {**actor, "user": {**actor["user"], "company_id": "CO-002"}}
                denied = self.route("GET", payload["download_url"], actor=foreign)
                self.assertEqual(denied.send_json.call_args.args[1], 403)
                self.assertEqual(denied.wfile.getvalue(), b"")
                without_read = {**actor, "permissions": ["audit_logs.view"]}
                denied = self.route("GET", payload["download_url"], actor=without_read)
                self.assertEqual(denied.send_json.call_args.args[1], 403)
                self.assertEqual(denied.wfile.getvalue(), b"")
                if role == "外部檢核單位":
                    self.conn.execute("DELETE FROM document_acl WHERE id='TEST-READONLY-ACL'")
                    self.assertFalse(backend.can_read_document(self.conn, "TEST-LEGACY", actor))
                    denied = self.route("GET", payload["download_url"], actor=actor)
                    self.assertEqual(denied.send_json.call_args.args[1], 403)
                    self.assertEqual(denied.wfile.getvalue(), b"")


if __name__ == "__main__":
    unittest.main()
