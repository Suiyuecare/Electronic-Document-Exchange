"""Execute the selectable-applicant correction RPC in isolated PostgreSQL only."""
import json
import unittest
import uuid

from tests import test_compose_resilience_postgres as resilience
from tools.shared_supabase_bootstrap import transform_sql


MIGRATION = "20260913055452_editor_applicant_selection_scope.sql"


@unittest.skipUnless(resilience.fixture.PORT, "isolated PostgreSQL editor applicant gate not enabled")
class EditorApplicantSelectionPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(resilience.fixture.ComposeOutputPostgresTest.cleanup.__func__)
    create = resilience.fixture.ComposeOutputPostgresTest.create

    @classmethod
    def setUpClass(cls):
        resilience.ComposeResiliencePostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            # The lightweight fixture predates the released 20260827101636
            # correction special-form repair. Apply that exact syntax-only
            # normalization here (no actor, scope, lock or state bypass).
            signature = f"{cls.namespace}.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)"
            definition = cls.pg.execute("SELECT pg_get_functiondef(%s::regprocedure)", (signature,)).fetchone()[0]
            if definition.count("pg_catalog.coalesce(") != 15 or definition.count("pg_catalog.nullif(") != 1:
                raise AssertionError("released_correction_special_form_fixture_drift")
            cls.pg.execute(definition.replace("pg_catalog.coalesce(", "coalesce(").replace("pg_catalog.nullif(", "nullif("))
            sql = (resilience.fixture.ROOT / "supabase/migrations" / MIGRATION).read_text()
            cls.pg.execute(sql if cls.namespace == "public" else transform_sql(sql))
        finally:
            cls.pg.execute("RESET ROLE")
        cls.tenant = "00000000-0000-0000-0000-000000000001"
        cls.pg.execute("UPDATE companies SET finance_tenant_id=%s,finance_entity_id='E1',source_system='finance',status='active' WHERE id='CO-COMPOSE'", (cls.tenant,))
        cls.pg.execute("INSERT INTO companies(id,name,finance_tenant_id,finance_entity_id,source_system,status) VALUES ('CO-SECOND','Isolated second',%s,'E2','finance','active')", (cls.tenant,))
        cls.pg.execute("UPDATE users SET finance_tenant_id=%s WHERE id='APPLICANT'", (cls.tenant,))
        cls.pg.execute("INSERT INTO finance_organization_units(id,finance_tenant_id,finance_unit_id,code,name,unit_type,status,entity_scope_mode,entity_codes) VALUES ('UNIT-SECOND',%s,'00000000-0000-0000-0000-000000000002','D2','Isolated department','department','active','explicit','[\"E2\"]')", (cls.tenant,))

    def case(self):
        doc_id = "editor-selection-" + uuid.uuid4().hex
        self.create(doc_id, company_id="CO-SECOND", source_type="uploaded_pdf", document_type="electronic_seal_pdf_editor_v2", output_mode="physical", requires_stamp=True,
                    metadata_json=json.dumps({"pdf_editor_v2": True}), applicant_department_id="D2", applicant_department_name="Isolated department")
        return doc_id

    def correct(self, doc_id, *, actor="APPLICANT", revision=0, name="Isolated department"):
        patch = {"workflow_template_key": "fixture", "metadata_json": json.dumps({"pdf_editor_v2": True}), "_expected_content_revision": revision,
                 "applicant_department_id": "D2", "applicant_department_name": name, "dispatch_unit": name, "title": "Isolated edited title"}
        suffix = uuid.uuid4().hex
        arguments = [doc_id, actor, "CO-SECOND", json.dumps(patch), "", "[]", "[]", "", "[]", "[]", "", "", "", "Fixture", "LOG-" + suffix, "AUD-" + suffix, '["applicant_department_id"]', "", ""]
        sql = f"SELECT {self.namespace}.edoc_apply_official_document_correction(%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)"
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            return self.pg.execute(sql, arguments).fetchone()[0]

    def test_correction_other_company_persists_unit_and_revision_without_pdf(self):
        doc_id = self.case()
        self.correct(doc_id)
        row = self.pg.execute("SELECT company_id,applicant_id,applicant_department_id,applicant_department_name,dispatch_unit,content_revision FROM official_documents WHERE id=%s", (doc_id,)).fetchone()
        self.assertEqual(row, ("CO-SECOND", "APPLICANT", "D2", "Isolated department", "Isolated department", 1))
        self.assertEqual(self.pg.execute("SELECT company_id FROM users WHERE id='APPLICANT'").fetchone()[0], "CO-COMPOSE")

    def test_cross_tenant_and_inactive_company_rejected_atomically(self):
        for statement, values in (("UPDATE companies SET finance_tenant_id=%s WHERE id='CO-SECOND'", ("00000000-0000-0000-0000-000000000009",)), ("UPDATE companies SET status='inactive' WHERE id='CO-SECOND'", ())):
            doc_id = self.case()
            with self.pg.transaction(force_rollback=True):
                self.pg.execute(statement, values)
                with self.assertRaises(self.psycopg.Error):
                    self.correct(doc_id)
                self.assertEqual(self.pg.execute("SELECT content_revision FROM official_documents WHERE id=%s", (doc_id,)).fetchone()[0], 0)

    def test_other_applicant_submitted_revision_and_stale_unit_rejected(self):
        doc_id = self.case()
        with self.assertRaisesRegex(self.psycopg.Error, "only_applicant_can_correct"):
            self.correct(doc_id, actor="ANOTHER")
        with self.assertRaisesRegex(self.psycopg.Error, "compose_content_revision_conflict"):
            self.correct(doc_id, revision=9)
        with self.assertRaisesRegex(self.psycopg.Error, "finance_unit_projection_unavailable"):
            self.correct(doc_id, name="FORGED")
        self.pg.execute("UPDATE official_documents SET current_status='pending_applicant_manager' WHERE id=%s", (doc_id,))
        with self.assertRaisesRegex(self.psycopg.Error, "official_document_correction_locked"):
            self.correct(doc_id)

    def test_non_editor_document_cannot_use_selected_department_extension(self):
        doc_id = "non-editor-" + uuid.uuid4().hex
        self.create(doc_id, company_id="CO-SECOND")
        with self.assertRaisesRegex(self.psycopg.Error, "finance_unit_payload_mismatch"):
            self.correct(doc_id)

    def test_rpc_stays_private_and_retains_row_lock(self):
        definition, security_definer = self.pg.execute("SELECT pg_get_functiondef(p.oid),p.prosecdef FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=%s AND proname='edoc_apply_official_document_correction'", (self.namespace,)).fetchone()
        self.assertIn("for update", definition.lower())
        self.assertIn("_expected_content_revision", definition)
        self.assertTrue(security_definer)
        for role in ("anon", "authenticated"):
            self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, f"{self.namespace}.edoc_apply_official_document_correction(text,text,text,jsonb,text,jsonb,jsonb,text,jsonb,jsonb,text,text,text,text,text,text,jsonb,text,text)")).fetchone()[0])


@unittest.skipUnless(resilience.fixture.PORT, "isolated PostgreSQL editor applicant gate not enabled")
class SharedEditorApplicantSelectionPostgresTest(EditorApplicantSelectionPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"
