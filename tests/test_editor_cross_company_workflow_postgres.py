"""Real privileged workflow RPCs for selected-company V2 cases; local PG only."""
import hashlib
import json
import unittest
import uuid

from tests import test_editor_applicant_selection_postgres as selection
from tools.shared_supabase_bootstrap import transform_sql


MIGRATION = "20260913060040_editor_cross_company_workflow_scope.sql"


@unittest.skipUnless(selection.resilience.fixture.PORT, "isolated PostgreSQL workflow gate not enabled")
class EditorCrossCompanyWorkflowPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(selection.EditorApplicantSelectionPostgresTest.cleanup.__func__)
    create = selection.EditorApplicantSelectionPostgresTest.create
    case = selection.EditorApplicantSelectionPostgresTest.case

    @classmethod
    def setUpClass(cls):
        selection.EditorApplicantSelectionPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            sql = (selection.resilience.fixture.ROOT / "supabase/migrations" / MIGRATION).read_text()
            cls.pg.execute(sql if cls.namespace == "public" else transform_sql(sql))
        finally:
            cls.pg.execute("RESET ROLE")
        for actor in ("REVIEWER", "NEXT", "STRANGER", "DELEGATE", "OUTSIDER"):
            tenant = cls.tenant if actor != "OUTSIDER" else "00000000-0000-0000-0000-000000000009"
            cls.pg.execute("INSERT INTO users(id,name,status,company_id,finance_tenant_id,email,role) VALUES (%s,%s,'啟用','CO-COMPOSE',%s,%s,'主任')", (actor, actor, tenant, actor.lower() + "@example.invalid"))

    def insert(self, table, **values):
        self.pg.execute(f"INSERT INTO {table}({','.join(values)}) VALUES ({','.join('%s' for _ in values)})", tuple(values.values()))

    def file(self, doc, kind, digest):
        file_id = kind + "-" + doc
        object_id = "object-" + file_id
        self.insert("file_objects", id=object_id, document_id=doc, sha256=digest, size_bytes=123, scan_status="passed")
        self.insert("official_document_files", id=file_id, document_id=doc, file_object_id=object_id, file_type=kind, file_hash=digest, file_size=123, version=1)
        return {"id": file_id, "type": kind, "sha256": digest, "size": 123, "version": 1}

    def workflow(self, *, actor="REVIEWER", principal="REVIEWER", decision="approve"):
        doc = self.case()
        source = self.file(doc, "original_pdf", "A" * 64)
        prepared = self.file(doc, "prepared_pdf", "B" * 64)
        revision = "revision-" + doc
        self.insert("official_document_editor_revisions", id=revision, document_id=doc, revision_no=1, manifest_sha256="D" * 64)
        self.insert("official_document_editor_assets", id="asset-" + doc, document_id=doc, editor_revision_id=revision, asset_kind="prepared_pdf", official_file_id=prepared["id"], sha256="B" * 64, preflight_status="passed")
        self.insert("official_document_stamp_requests", id="request-" + doc, document_id=doc, locked_editor_revision_id=revision, locked_source_sha256="C" * 64, prepared_file_id=prepared["id"], prepared_sha256="B" * 64, editor_manifest_sha256="D" * 64, editor_schema_version=2, renderer_version="fixture-renderer")
        for order, key, approver in ((1, "applicant_manager", principal), (2, "department_head", "NEXT"), (3, "applicant_confirm", "APPLICANT")):
            self.insert("official_document_approval_steps", id=f"step-{order}-{doc}", document_id=doc, step_key=key, step_name=key, step_order=order, workflow_generation=1, approver_user_id=approver, status="pending", review_started_at="2026-09-08 13:01:00")
        self.pg.execute("UPDATE official_documents SET current_status='pending_applicant_manager',current_step='applicant_manager' WHERE id=%s", (doc,))
        access = []
        for file in (source, prepared):
            log = "access-" + file["id"]
            self.insert("official_document_approval_logs", id=log, document_id=doc, actor_id=actor, file_id=file["id"], action="download_file", created_at="2026-09-08 13:02:00")
            access.append({"file_id": file["id"], "access_log_id": log, "action": "download_file", "accessed_at": "2026-09-08 13:02:00"})
        evidence = {
            "schema_version": 2, "decision_type": decision, "expected_step_id": "step-1-" + doc,
            "principal_actor_id": principal, "decision_actor_user_id": actor,
            "review_acknowledgements": {"original_reviewed": True, "edited_version_reviewed": True, "attachments_reviewed": True},
            "source_file": source, "prepared_file": prepared, "legacy_renderer": False,
            "source_bundle_sha256": "C" * 64, "prepared_sha256": "B" * 64, "manifest_sha256": "D" * 64,
            "editor_revision_id": revision, "editor_schema_version": 2, "renderer_version": "fixture-renderer",
            "attachments": [], "attachments_manifest_sha256": hashlib.sha256(b"").hexdigest(),
            "review_access": {"server_verified": True, "step_started_at": "2026-09-08 13:01:00", "required_file_ids": [source["id"], prepared["id"]], "access_logs": access},
            "reason_category": "fixture", "missing_items": [],
        }
        return doc, evidence

    def rpc(self, name, values, casts=None):
        casts = casts or [""] * len(values)
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            return self.pg.execute(f"SELECT {self.namespace}.{name}({','.join('%s' + cast for cast in casts)})", values).fetchone()[0]

    def decide(self, doc, evidence):
        name = "approval" if evidence["decision_type"] == "approve" else "rejection"
        return self.rpc(f"edoc_claim_official_document_{name}_v3", [doc, evidence["expected_step_id"], evidence["principal_actor_id"], evidence["decision_actor_user_id"], "Fixture reviewed", json.dumps(evidence)], ["", "", "", "", "", "::jsonb"])

    def test_approval_advances_real_actor_and_private_next_recipient_company(self):
        doc, evidence = self.workflow()
        self.assertTrue(self.decide(doc, evidence)["claimed"])
        self.assertEqual(("CO-SECOND", "pending_department_head", "department_head"), self.pg.execute("SELECT company_id,current_status,current_step FROM official_documents WHERE id=%s", (doc,)).fetchone())
        self.assertEqual(("NEXT", "CO-COMPOSE"), self.pg.execute("SELECT target_user_id,target_company_id FROM notifications WHERE source=%s", (doc,)).fetchone())
        self.assertEqual(("REVIEWER", "approved"), self.pg.execute("SELECT decision_actor_user_id,status FROM official_document_approval_steps WHERE id=%s", (evidence["expected_step_id"],)).fetchone())
        self.assertFalse(self.decide(doc, evidence)["claimed"])
        self.assertEqual(1, self.pg.execute("SELECT count(*) FROM notifications WHERE source=%s", (doc,)).fetchone()[0])

    def test_reject_returns_to_real_applicant_and_enqueues_locked_revision_copy(self):
        doc, evidence = self.workflow(decision="reject")
        self.assertTrue(self.decide(doc, evidence)["claimed"])
        self.assertEqual(("APPLICANT", "CO-COMPOSE"), self.pg.execute("SELECT target_user_id,target_company_id FROM notifications WHERE source=%s", (doc,)).fetchone())
        self.assertEqual((evidence["editor_revision_id"], "pending"), self.pg.execute("SELECT source_revision_id,status FROM official_document_rejection_jobs WHERE document_id=%s", (doc,)).fetchone())

    def test_outsider_stranger_self_approval_and_unassigned_principal_refused(self):
        for actor, principal in (("OUTSIDER", "REVIEWER"), ("STRANGER", "REVIEWER"), ("APPLICANT", "APPLICANT")):
            doc, evidence = self.workflow(actor=actor, principal=principal)
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.decide(doc, evidence)
            self.assertEqual("pending", self.pg.execute("SELECT status FROM official_document_approval_steps WHERE id=%s", (evidence["expected_step_id"],)).fetchone()[0])
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM notifications WHERE source=%s", (doc,)).fetchone()[0])
        doc, evidence = self.workflow()
        evidence["principal_actor_id"] = "STRANGER"
        evidence["decision_actor_user_id"] = "STRANGER"
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
            self.decide(doc, evidence)

    def test_next_actor_other_tenant_rolls_back_entire_decision(self):
        doc, evidence = self.workflow()
        self.pg.execute("UPDATE official_document_approval_steps SET approver_user_id='OUTSIDER' WHERE id=%s", ("step-2-" + doc,))
        with self.assertRaisesRegex(self.psycopg.Error, "notification_exact_target_required"):
            self.decide(doc, evidence)
        self.assertEqual("pending_applicant_manager", self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (doc,)).fetchone()[0])
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_approval_logs WHERE document_id=%s AND action='approve'", (doc,)).fetchone()[0])

    def test_stale_company_and_non_v2_scope_cannot_bypass_boundary(self):
        for mutation in ("UPDATE companies SET status='inactive' WHERE id='CO-SECOND'", "UPDATE companies SET finance_tenant_id='00000000-0000-0000-0000-000000000009' WHERE id='CO-SECOND'", "UPDATE official_documents SET metadata_json='{}' WHERE id=%s"):
            doc, evidence = self.workflow()
            with self.pg.transaction(force_rollback=True):
                self.pg.execute(mutation, (doc,) if "%s" in mutation else None)
                with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                    self.decide(doc, evidence)

    def test_archive_allows_only_actual_cross_company_participants(self):
        doc, evidence = self.workflow()
        self.decide(doc, evidence)
        for actor in ("APPLICANT", "REVIEWER", "NEXT"):
            result = self.archive(doc, actor)
            self.assertEqual(actor, result["requested_by"])
        for actor in ("STRANGER", "OUTSIDER"):
            with self.assertRaisesRegex(self.psycopg.Error, "official_archive_export_company_forbidden"):
                self.archive(doc, actor)

    def archive(self, doc, actor):
        export_id = "export-" + uuid.uuid4().hex
        return self.rpc("edoc_register_official_archive_export", [export_id, doc, actor, "A" * 64, "B" * 64, 1, 123, "fixture", "private-test", "isolated/" + export_id + ".zip"], ["", "", "", "", "", "::integer", "::bigint", "", "", ""])

    def test_dispatch_owner_and_applicant_can_complete_selected_company_case(self):
        doc, _ = self.workflow()
        self.pg.execute("UPDATE official_documents SET dispatch_method='return_to_applicant_for_manual_send',current_status='returned_to_applicant_for_send',current_step='applicant_dispatch' WHERE id=%s", (doc,))
        with self.assertRaisesRegex(self.psycopg.Error, "official_dispatch_actor_forbidden"):
            self.rpc("edoc_create_official_document_dispatch_record", [doc, "STRANGER"])
        created = self.rpc("edoc_create_official_document_dispatch_record", [doc, "APPLICANT"])
        record = created["dispatch_record_id"]
        proof = self.file(doc, "dispatch_proof", "E" * 64)
        self.pg.execute("UPDATE official_document_dispatch_records SET proof_file_id=%s WHERE id=%s", (proof["id"], record))
        args = [doc, record, "REVIEWER", "", "2026-09-13", "Synthetic recipient", "", "Fixture dispatch", "", ""]
        with self.assertRaisesRegex(self.psycopg.Error, "official_dispatch_complete_forbidden"):
            self.rpc("edoc_complete_official_document_dispatch", args)
        args[2] = "APPLICANT"
        self.assertTrue(self.rpc("edoc_complete_official_document_dispatch", args)["completed"])
        self.assertEqual(("APPLICANT", "CO-COMPOSE"), self.pg.execute("SELECT target_user_id,target_company_id FROM notifications WHERE source=%s", (doc,)).fetchone())

    def test_private_helpers_and_public_rpcs_retain_acl_search_path_and_locks(self):
        for name, arguments in (("editor_v2_actor_in_company_scope", "text,text"), ("editor_v2_case_participant", "text,text"), ("assert_official_document_decision_actor", "text,text,text,text")):
            signature = f"edoc_private.{name}({arguments})"
            definition, config, definer = self.pg.execute("SELECT pg_get_functiondef(oid),proconfig,prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (signature,)).fetchone()
            self.assertIn('search_path=""', config)
            self.assertFalse(definer)
            for role in ("anon", "authenticated", self.backend_role):
                self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)).fetchone()[0])
        for kind in ("approval", "rejection"):
            signature = f"{self.namespace}.edoc_claim_official_document_{kind}_v2(text,text,text,text,text,jsonb)"
            definition, config = self.pg.execute("SELECT pg_get_functiondef(oid),proconfig FROM pg_proc WHERE oid=%s::regprocedure", (signature,)).fetchone()
            self.assertIn("for update", definition.lower())
            self.assertIn('search_path=""', config)
            self.assertIn("lock_timeout=5s", config)
            self.assertIn("v_step.approver_user_id is distinct from", definition)
            public_signature = signature.replace("_v2(", "_v3(")
            for role in ("anon", "authenticated"):
                self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, public_signature)).fetchone()[0])
            self.assertTrue(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (self.backend_role, public_signature)).fetchone()[0])


@unittest.skipUnless(selection.resilience.fixture.PORT, "isolated PostgreSQL workflow gate not enabled")
class SharedEditorCrossCompanyWorkflowPostgresTest(EditorCrossCompanyWorkflowPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"
