"""Actual public/edoc RPCs in disposable loopback databases; never hosted."""
import json
import unittest
import uuid
from tests import test_compose_output_postgres as fixture
from tests import test_compose_resilience_postgres as resilience
from tools.private_draft_archive_shared_forward import SOURCE, render_shared_forward, render_cutover_gate


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL private draft gate not enabled")
class PrivateDraftArchivePostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(fixture.ComposeOutputPostgresTest.cleanup.__func__)
    save = resilience.ComposeResiliencePostgresTest.save

    @classmethod
    def setUpClass(cls):
        resilience.ComposeResiliencePostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            if cls.namespace == "public":
                sql = (fixture.ROOT / "supabase/migrations" / SOURCE).read_text()
                cls.pg.execute(sql)
                cls.pg.execute(sql)
            else:
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")

    def archive(self, key, revision, archived=True, actor="APPLICANT", company="CO-COMPOSE"):
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            return self.pg.execute(f"SELECT {self.namespace}.edoc_archive_private_compose_draft(%s,%s,%s,%s,%s)", (key, actor, company, revision, archived)).fetchone()[0]

    def catalog(self, archived=False):
        with self.pg.transaction():
            self.pg.execute(f"SET LOCAL ROLE {self.backend_role}")
            return self.pg.execute(f"SELECT {self.namespace}.edoc_workspace_drafts(%s::jsonb)", (json.dumps({"actor_id": "APPLICANT", "company_id": "CO-COMPOSE", "archived": archived}),)).fetchone()[0]

    def test_cutover_gate_accepts_exact_backend_only_live_functions(self):
        self.pg.execute(render_cutover_gate(self.namespace))

    def test_cutover_gate_rejects_grant_code_and_autosave_guard_drift(self):
        signature = f"{self.namespace}.edoc_archive_private_compose_draft(text,text,text,integer,boolean)"
        mutations = (
            (f"GRANT EXECUTE ON FUNCTION {signature} TO anon", "rpc_browser_grant"),
            (f"GRANT EXECUTE ON FUNCTION {signature} TO PUBLIC", "rpc_browser_grant"),
            (f"REVOKE EXECUTE ON FUNCTION {signature} FROM {self.backend_role}", "rpc_security_mismatch"),
            (f"ALTER FUNCTION {signature} SECURITY DEFINER", "rpc_security_mismatch"),
        )
        for mutation, code in mutations:
            with self.subTest(mutation=mutation), self.pg.transaction(force_rollback=True):
                self.pg.execute(mutation)
                with self.assertRaisesRegex(self.psycopg.Error, code):
                    with self.pg.transaction(): self.pg.execute(render_cutover_gate(self.namespace))
        for target, before, after, code in (
            (signature, "if v_row.revision<>p_expected_revision", "if false", "rpc_source_mismatch"),
            (f"{self.namespace}.edoc_save_compose_draft(text,text,text,integer,jsonb,text,boolean)",
             "if v_row.archived and not p_archived", "if false", "autosave_guard_missing"),
        ):
            with self.subTest(code=code), self.pg.transaction(force_rollback=True):
                definition = self.pg.execute("SELECT pg_get_functiondef(%s::regprocedure)", (target,)).fetchone()[0]
                self.assertIn(before, definition)
                self.pg.execute(definition.replace(before, after))
                with self.assertRaisesRegex(self.psycopg.Error, code):
                    with self.pg.transaction(): self.pg.execute(render_cutover_gate(self.namespace))

    def test_archive_restore_preserves_original_snapshot_and_exact_identity(self):
        key = "OD-" + str(uuid.uuid4())
        original = self.save(key, 0, "Synthetic private draft")
        archived = self.archive(key, 1)
        self.assertEqual((True, 2), (archived["archived"], archived["revision"]))
        self.assertEqual(original["snapshot_json"], archived["snapshot_json"])
        self.assertNotIn(key, [r["id"] for r in self.catalog()["items"]])
        self.assertIn(key, [r["id"] for r in self.catalog(True)["items"]])
        restored = self.archive(key, 2, False)
        self.assertEqual((False, 3), (restored["archived"], restored["revision"]))
        self.assertIn(key, [r["id"] for r in self.catalog()["items"]])

    def test_old_autosave_and_stale_restore_cannot_unarchive(self):
        key = "OD-" + str(uuid.uuid4()); self.save(key, 0, "Synthetic CAS")
        self.archive(key, 1)
        for revision in (1, 2):
            with self.assertRaisesRegex(self.psycopg.Error, "revision_conflict"): self.save(key, revision, "late edit")
        with self.assertRaisesRegex(self.psycopg.Error, "revision_conflict"): self.archive(key, 1, False)
        self.assertTrue(self.pg.execute("SELECT archived FROM official_document_compose_drafts WHERE id=%s", (key,)).fetchone()[0])

    def test_owner_company_active_actor_and_client_roles_fail_closed(self):
        key = "OD-" + str(uuid.uuid4()); self.save(key, 0, "Synthetic ACL")
        for actor, company in (("OTHER", "CO-COMPOSE"), ("APPLICANT", "FOREIGN")):
            with self.assertRaisesRegex(self.psycopg.Error, "scope_forbidden"): self.archive(key, 1, actor=actor, company=company)
        for role in ("anon", "authenticated"):
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                with self.pg.transaction():
                    self.pg.execute(f"SET LOCAL ROLE {role}")
                    self.pg.execute(f"SELECT {self.namespace}.edoc_archive_private_compose_draft(%s,'APPLICANT','CO-COMPOSE',1,true)", (key,))
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("UPDATE users SET status='停用' WHERE id='APPLICANT'")
            with self.assertRaisesRegex(self.psycopg.Error, "scope_forbidden"): self.archive(key, 1)

    def test_stored_formal_links_or_numbers_cannot_hide_or_restore_case(self):
        formal = "FORMAL-" + uuid.uuid4().hex
        self.pg.execute("INSERT INTO official_documents(id,company_id,applicant_id,source_type,title,subject,requires_stamp,output_mode,dispatch_date,current_status,current_step,created_at,updated_at) VALUES (%s,'CO-COMPOSE','APPLICANT','blank_editor','Synthetic','Synthetic',false,'electronic','2026-10-18','pending_applicant_manager','','now','now')", (formal,))
        for extra in ({"officialDocumentId": formal}, {"draftRequestId": formal}, {"currentComposeDraftId": "OUT-123"}, {"values": {"#dispatchNo": "Synthetic number"}}):
            key = "OD-" + str(uuid.uuid4()); self.save(key, 0, "Synthetic protected")
            self.pg.execute("UPDATE official_document_compose_drafts SET snapshot_json=snapshot_json||%s::jsonb WHERE id=%s", (json.dumps(extra), key))
            with self.assertRaisesRegex(self.psycopg.Error, "archive_private_only"): self.archive(key, 1)
            self.pg.execute("UPDATE official_document_compose_drafts SET archived=true WHERE id=%s", (key,))
            with self.assertRaisesRegex(self.psycopg.Error, "archive_private_only"): self.archive(key, 1, False)
            self.assertNotIn(key, [r["id"] for r in self.catalog(True)["items"]])
        self.assertEqual("pending_applicant_manager", self.pg.execute("SELECT current_status FROM official_documents WHERE id=%s", (formal,)).fetchone()[0])

    def test_formal_creation_on_either_side_of_archive_never_hides_official(self):
        for archive_first in (True, False):
            key = "OD-" + str(uuid.uuid4()); self.save(key, 0, "Synthetic create race")
            if archive_first: self.archive(key, 1)
            self.pg.execute("INSERT INTO official_documents(id,company_id,applicant_id,source_type,title,subject,requires_stamp,output_mode,dispatch_date,current_status,current_step,created_at,updated_at) VALUES (%s,'CO-COMPOSE','APPLICANT','blank_editor','Synthetic formal','Synthetic formal',false,'electronic','2026-10-18','draft','','now','now')", (key,))
            if not archive_first:
                with self.assertRaisesRegex(self.psycopg.Error, "archive_private_only"): self.archive(key, 1)
            else:
                with self.assertRaisesRegex(self.psycopg.Error, "archive_private_only"): self.archive(key, 2, False)
            rows = self.catalog()["items"]
            self.assertIn(key, [r["id"] for r in rows])
            self.assertIn("official", [r["kind"] for r in rows if r["id"] == key])
            self.assertNotIn(key, [r["id"] for r in self.catalog(True)["items"]])


class SharedPrivateDraftArchivePostgresTest(PrivateDraftArchivePostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"


if __name__ == "__main__": unittest.main()
