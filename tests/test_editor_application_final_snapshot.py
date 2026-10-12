"""Deidentified SQLite and adapter checks for final application/PDF binding."""
from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

import backend
import editor_application
from tests import test_general_document_seal_workflow as general_fixture


class EditorApplicationFinalSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.fixture = general_fixture.GeneralDocumentSealWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn, self.session = self.fixture.conn, self.fixture.session
        self.tenant = "00000000-0000-0000-0000-000000000071"
        self.conn.execute("UPDATE companies SET finance_tenant_id=?,finance_entity_id=id,source_system='finance',status='active' WHERE id IN ('CO-001','CO-002')", (self.tenant,))
        self.conn.execute("UPDATE users SET finance_tenant_id=? WHERE id=?", (self.tenant, self.session["user"]["id"]))
        self.session["user"]["finance_tenant_id"] = self.tenant
        backend.EDOC_PDF_EDITOR_V2_COMPANY_IDS = "CO-001,CO-002"
        for company, code, name in (("CO-001", "APP-D1", "Synthetic first unit"), ("CO-002", "APP-D2", "Synthetic second unit")):
            company_name = self.conn.execute("SELECT name FROM companies WHERE id=?", (company,)).fetchone()[0]
            self.conn.execute("INSERT INTO department_registry(id,name,company_name,manager_role,status,created_at,updated_at) VALUES (?,?,?,'Synthetic role','active',?,?)", (code, name, company_name,backend.now(),backend.now()))

    def draft(self, with_seals=False):
        identity, revision, source = self.fixture._draft()
        if with_seals:
            state = self.fixture._combined_state(revision)
            state["elements"].append({"id": "APPLICATION-TEXT", "kind": "text", "pageId": state["pages"][0]["pageId"],
                "x": 50, "y": 50, "width": 100, "height": 25, "rotation": 0, "opacity": 1, "zIndex": 1,
                "properties": {"text": "Synthetic editable text"}})
            revision = self.fixture._save(identity, revision, state)
        return identity, revision, source

    def patch(self, identity, revision, **overrides):
        document = backend.official_document_row(self.conn, identity)
        payload = {"company_id": document["company_id"], "title": "Final synthetic title", "subject": "Final synthetic title",
            "description": "Final synthetic reason", "request_reason": "Final synthetic reason",
            "handler_name": self.session["user"]["name"], "dispatch_unit": "Synthetic first unit",
            "applicant_department_id": "APP-D1", "applicant_department_name": "Synthetic first unit",
            "document_category": "服務委託合約", "expected_content_revision": int(document.get("content_revision") or 0),
            "expected_editor_revision_id": revision["id"], "expected_editor_manifest_sha256": revision["manifestSha256"]}
        payload.update(overrides)
        return payload

    def test_company_switch_keeps_pdf_text_and_immutable_assets_removes_all_old_seam_members(self):
        identity, revision, source = self.draft(with_seals=True)
        assets_before = [tuple(row) for row in self.conn.execute("SELECT id,document_id,storage_path,sha256,file_object_id FROM official_document_editor_assets WHERE document_id=? ORDER BY id", (identity,))]
        original_actor = backend.official_document_row(self.conn, identity)["applicant_id"]
        result = backend.update_official_document_correction(self.conn, identity, self.patch(identity, revision,
            company_id="CO-002", applicant_department_id="APP-D2", applicant_department_name="Synthetic second unit", dispatch_unit="Synthetic second unit"), self.session)
        self.assertEqual(result["id"], identity)
        self.assertEqual(result["company_id"], "CO-002")
        self.assertEqual(result["applicant_id"], original_actor)
        self.assertEqual(result["content_revision"], 1)
        self.assertEqual(result["editor_revision"]["revisionNo"], revision["revisionNo"] + 1)
        self.assertEqual(result["editor_state"]["pages"], revision["state"]["pages"])
        self.assertEqual(result["editor_state"]["sourceFiles"], revision["state"]["sourceFiles"])
        self.assertEqual([item["id"] for item in result["editor_state"]["elements"]], ["APPLICATION-TEXT"])
        self.assertEqual(len(result["removed_seal_element_ids"]), 6)
        self.assertEqual(assets_before, [tuple(row) for row in self.conn.execute("SELECT id,document_id,storage_path,sha256,file_object_id FROM official_document_editor_assets WHERE document_id=? ORDER BY id", (identity,))])
        self.assertTrue(result["application_metadata_editable"])
        self.assertTrue(result["application_company_editable"])
        asset = self.conn.execute("SELECT file_object_id FROM official_document_editor_assets WHERE document_id=? AND asset_kind='source_pdf'", (identity,)).fetchone()
        self.assertEqual(backend.read_file_object_bytes(self.conn, asset[0])[1], source)
        self.assertEqual(self.session["user"]["company_id"], "CO-001")

    def test_stale_application_and_editor_tokens_do_not_mutate_anything(self):
        identity, revision, _ = self.draft()
        for overrides, error in (({"expected_content_revision": 99}, "compose_content_revision_conflict"),
                                 ({"expected_editor_manifest_sha256": "0" * 64}, "editor_revision_conflict"),
                                 ({"expected_content_revision": True}, "compose_content_revision_required")):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, error):
                backend.update_official_document_correction(self.conn, identity, self.patch(identity, revision, **overrides), self.session)
            self.assertEqual(backend.official_document_row(self.conn, identity)["content_revision"], 0)

    def test_denied_other_actor_permission_cross_tenant_inactive_company_are_zero_write(self):
        identity, revision, _ = self.draft()
        denied = copy.deepcopy(self.session)
        denied["user"]["id"] = "ANOTHER-SYNTHETIC"
        with self.assertRaises(PermissionError):
            backend.update_official_document_correction(self.conn, identity, self.patch(identity, revision), denied)
        denied = copy.deepcopy(self.session)
        denied["permissions"] = []
        with self.assertRaises(PermissionError):
            backend.update_official_document_correction(self.conn, identity, self.patch(identity, revision), denied)
        for column, value in (("finance_tenant_id", "another-tenant"), ("status", "inactive")):
            before = self.conn.execute(f"SELECT {column} FROM companies WHERE id='CO-002'").fetchone()[0]
            self.conn.execute(f"UPDATE companies SET {column}=? WHERE id='CO-002'", (value,))
            with self.assertRaises(PermissionError):
                backend.update_official_document_correction(self.conn, identity, self.patch(identity, revision, company_id="CO-002"), self.session)
            self.conn.execute(f"UPDATE companies SET {column}=? WHERE id='CO-002'", (before,))
        self.assertEqual(backend.official_document_row(self.conn, identity)["content_revision"], 0)

    def test_ever_submitted_and_numbered_company_switch_forbidden_same_company_correction_kept(self):
        identity, revision, _ = self.draft()
        backend.insert_official_log(self.conn, identity, "submit", self.session["user"], "Synthetic old submission")
        capabilities = backend.official_document_detail(self.conn, identity, self.session)
        self.assertTrue(capabilities["application_metadata_editable"])
        self.assertFalse(capabilities["application_company_editable"])
        with self.assertRaisesRegex(PermissionError, "official_document_company_forbidden"):
            backend.update_official_document_correction(self.conn, identity, self.patch(identity, revision, company_id="CO-002", applicant_department_id="APP-D2", applicant_department_name="Synthetic second unit", dispatch_unit="Synthetic second unit"), self.session)
        self.conn.execute("UPDATE official_documents SET current_status='rejected' WHERE id=?", (identity,))
        result = backend.update_official_document_correction(self.conn, identity, self.patch(identity, revision, document_category="採購合約"), self.session)
        self.assertEqual(result["document_category"], "採購合約")
        self.assertTrue(result["application_metadata_editable"])
        self.assertFalse(result["application_company_editable"])
        self.conn.execute("UPDATE official_documents SET current_status='declined' WHERE id=?", (identity,))
        with self.assertRaisesRegex(ValueError, "editor_locked_after_submit"):
            backend.update_official_document_correction(self.conn, identity, self.patch(identity, revision), self.session)

    def test_preflight_after_metadata_update_binds_final_application_and_invalidates_old_preview(self):
        identity, revision, _ = self.draft(with_seals=True)
        prepared = backend.preflight_official_editor(self.conn, identity, {"editorRevisionId": revision["id"], "manifestSha256": revision["manifestSha256"], "expected_content_revision": 0}, self.session)
        result = backend.update_official_document_correction(self.conn, identity, self.patch(identity, prepared["revision"], document_category="採購合約"), self.session)
        payload = {"editorRevisionId": prepared["editorRevisionId"], "manifestSha256": prepared["manifestSha256"], "preparedFileId": prepared["preparedFileId"], "preparedSha256": prepared["preparedSha256"]}
        with self.assertRaisesRegex(ValueError, "editor_preflight_not_completed"):
            backend.lock_official_editor_submission(self.conn, result, payload, self.session["user"])
        self.assertNotIn("preparedFileId",backend.get_official_editor_state(self.conn,identity,self.session))
        fresh = backend.preflight_official_editor(self.conn, identity, {"editorRevisionId": prepared["editorRevisionId"], "manifestSha256": prepared["manifestSha256"], "expected_content_revision": 1}, self.session)
        payload.update(preparedFileId=fresh["preparedFileId"], preparedSha256=fresh["preparedSha256"])
        backend.lock_official_editor_submission(self.conn, result, payload, self.session["user"])
        asset = self.conn.execute("SELECT metadata_json FROM official_document_editor_assets WHERE official_file_id=?", (fresh["preparedFileId"],)).fetchone()
        self.assertEqual(json.loads(asset[0])["application_snapshot"], editor_application.application_snapshot(result))

    def test_final_fields_category_seals_and_output_remain_the_submitted_snapshot(self):
        identity,revision,source=self.draft(with_seals=True)
        changed=backend.update_official_document_correction(self.conn,identity,self.patch(identity,revision,document_category="採購合約"),self.session)
        prepared=backend.preflight_official_editor(self.conn,identity,{"editorRevisionId":revision["id"],"manifestSha256":revision["manifestSha256"],"expected_content_revision":changed["content_revision"]},self.session)
        submitted=backend.submit_official_document(self.conn,identity,{**prepared,"expected_content_revision":changed["content_revision"]},self.session)
        self.assertEqual(submitted["title"],"Final synthetic title")
        self.assertEqual(submitted["request_reason"],"Final synthetic reason")
        self.assertEqual(submitted["document_category"],"採購合約")
        self.assertEqual(submitted["approval_route_code"],"D")
        self.assertEqual(submitted["metadata"]["editor_submission_application"]["snapshot_sha256"],backend.canonical_json_hash(editor_application.application_snapshot(changed)))
        completed=self.fixture.fixture._approve_and_stamp(submitted)
        self.assertEqual(completed["stamp_request"]["prepared_sha256"],prepared["preparedSha256"])
        final=next(item for item in completed["files"] if item["file_type"]=="stamped_pdf")
        _,_,pdf=backend.official_document_download_file(self.conn,identity,final["id"],self.session)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.fixture._assert_rendered_placements(pdf,{**revision["state"],"elements":[item for item in revision["state"]["elements"] if item["kind"]=="seal"]})
        self.assertEqual(backend.get_official_editor_state(self.conn,identity,self.session)["state"],revision["state"])

    def test_hosted_application_adapter_uses_only_atomic_rpc_and_fail_closed_response(self):
        identity, revision, _ = self.draft()
        document = backend.official_document_row(self.conn, identity)
        latest = backend._editor_latest_revision_row(self.conn, identity)
        company = backend.official_company_row(self.conn, "CO-001")
        payload = self.patch(identity, revision)
        committed = {**document, "title": payload["title"], "content_revision": 1}
        with mock.patch.object(backend, "require_production_editor_runtime_ready"), mock.patch.object(backend, "supabase_official_document_row", return_value=document), mock.patch.object(backend, "_supabase_editor_assert_document_access", return_value=self.session["user"]), mock.patch.object(backend, "official_editor_company", return_value=company), mock.patch.object(backend, "authoritative_editor_applicant_department", return_value={"id":"APP-D1","name":"Synthetic first unit"}), mock.patch.object(backend, "_supabase_editor_latest_revision", return_value=latest), mock.patch.object(backend, "supabase_filter_rows", return_value=[]), mock.patch.object(backend, "supabase_official_document_stamp_request", return_value=None), mock.patch.object(backend, "supabase_official_document_detail", return_value=committed), mock.patch.object(backend, "supabase_request", return_value={"document_id":identity,"content_revision":1,"editor_revision_id":latest["id"],"changed":True,"removed_seal_element_ids":[]}) as rpc, mock.patch.object(backend,"supabase_patch") as non_atomic:
            result = backend.supabase_update_official_editor_application(identity,payload,self.session)
            self.assertEqual(result["title"],payload["title"])
            self.assertEqual(rpc.call_args.args[1],"rpc/edoc_update_editor_application")
            self.assertEqual(rpc.call_args.args[2]["p_request"]["expected_editor_revision_id"],latest["id"])
            non_atomic.assert_not_called()

    def test_pure_prune_preserves_images_and_text_and_removes_entire_mixed_seam_group(self):
        state = {"elements":[{"id":"left","kind":"seal","properties":{"sealId":"OLD","seamGroupId":"GROUP"}},
          {"id":"right","kind":"seal","properties":{"sealId":"NEW","seamGroupId":"GROUP"}},
          {"id":"text","kind":"text","properties":{"text":"Synthetic"}}, {"id":"image","kind":"image","properties":{"assetId":"IMG"}}], "pages":[{"pageId":"P"}],"sourceFiles":[{"assetId":"PDF"}]}
        result,removed = editor_application.remove_foreign_seals(state,"NEW-COMPANY",lambda identity:{"company_id":"OLD-COMPANY" if identity=="OLD" else "NEW-COMPANY"})
        self.assertEqual(removed,["left","right"])
        self.assertEqual([item["id"] for item in result["elements"]],["text","image"])
        self.assertEqual(len(state["elements"]),4)


if __name__ == "__main__": unittest.main()
