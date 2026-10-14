"""Production submit payloads against strict, disposable PostgreSQL tables.

The workflow rows, actor snapshots, logs and audit rows come from the real
backend submit/planner. Only storage/SSO/notification I/O uses synthetic
witnesses. Both fresh-public and shared-edoc namespaces are exercised.
"""
from __future__ import annotations

import copy
import concurrent.futures
import json
import os
import threading
import unittest
from contextlib import ExitStack
from unittest import mock

import backend
from tests import test_compose_output_postgres as base
from tests import test_editor_application_final_snapshot_postgres as editor


@unittest.skipUnless(base.PORT, "isolated PostgreSQL submission gate not enabled")
class SubmissionConstraintsPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(editor.EditorApplicationFinalSnapshotPostgresTest.cleanup.__func__)
    create = editor.EditorApplicationFinalSnapshotPostgresTest.create
    row = editor.EditorApplicationFinalSnapshotPostgresTest.row
    insert = editor.EditorApplicationFinalSnapshotPostgresTest.insert
    seed = editor.EditorApplicationFinalSnapshotPostgresTest.seed
    prepared_request = editor.EditorApplicationFinalSnapshotPostgresTest.prepared_request
    rpc = editor.EditorApplicationFinalSnapshotPostgresTest.rpc
    timestamp = "2026-10-14 12:01:00"

    @classmethod
    def setUpClass(cls):
        editor.EditorApplicationFinalSnapshotPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute((base.ROOT / "tests/support/submission_production_constraints.sql").read_text())
        cls.before_forward = cls.pg.execute(
            "SELECT pg_get_functiondef(%s::regprocedure)",
            (f"{cls.namespace}.edoc_commit_official_document_submission(jsonb)",),
        ).fetchone()[0]
        from tools.submission_evidence_shared_forward import SOURCE, FORWARD_NAME
        cls.pg.execute("SET ROLE postgres")
        try:
            if cls.namespace == "public":
                cls.pg.execute((base.ROOT / "supabase/migrations" / SOURCE).read_text())
            else:
                # The earlier fixture applies the application migration directly;
                # record its already-applied prerequisite in this isolated ledger.
                cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES (%s) ON CONFLICT DO NOTHING", (editor.SOURCE,))
                cls.pg.execute((base.ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
        finally:
            cls.pg.execute("RESET ROLE")
        cls.after_forward = cls.pg.execute("SELECT pg_get_functiondef(%s::regprocedure)",
            (f"{cls.namespace}.edoc_commit_official_document_submission(jsonb)",)).fetchone()[0]

    def plan(self, *, kind="pdf", rejected=False):
        """Capture the real HTTP-to-RPC builder, not a handwritten step fixture."""
        identity, revision = self.seed(with_seals=True)
        prepared = self.prepared_request(identity, revision)
        self.rpc("edoc_commit_editor_preflight", prepared)
        witness = editor.EditorApplicationFinalSnapshotPostgresTest.submit_request(self, identity, revision, prepared)
        if kind == "compose":
            self.pg.execute("UPDATE official_documents SET source_type='blank_editor',document_type='outgoing_official_document',output_mode='electronic',requires_stamp=false,metadata_json='{}' WHERE id=%s", (identity,))
            obj, file_id = "SOURCEOBJ-" + identity, "SOURCEFILE-" + identity
            self.insert("file_objects", {"id":obj,"document_id":identity,"mime_type":"application/pdf","sha256":"D"*64,"size_bytes":128})
            self.insert("official_document_files", {"id":file_id,"document_id":identity,"file_object_id":obj,"file_type":"generated_pdf","file_hash":"D"*64,"file_size":128,"version":1})
            generated_source = {"id":file_id,"file_hash":"D"*64,"file_type":"generated_pdf"}
        else:
            generated_source = None
        if rejected:
            self.pg.execute("UPDATE official_documents SET current_status='rejected',correction_requested_at='2026-10-14 11:00:00' WHERE id=%s", (identity,))
            self.insert("official_document_approval_steps", {"id":"OLD-"+identity,"document_id":identity,"step_order":1,"step_key":"department_head","step_name":"Synthetic rejected step","status":"rejected","workflow_generation":1,"approver_user_id":"REVIEWER"})
            self.insert("official_document_approval_steps", {"id":"OLD-PENDING-"+identity,"document_id":identity,"step_order":2,"step_key":"general_affairs_review","step_name":"Synthetic unvisited step","status":"pending","workflow_generation":1,"approver_user_id":"REVIEWER"})
        document = self.row("official_documents", identity)
        user = {"id":"APPLICANT","company_id":"CO-COMPOSE","name":"Synthetic applicant","status":"啟用","role":"員工","email":"applicant@example.invalid"}
        reviewer = {"id":"REVIEWER","company_id":"CO-COMPOSE","name":"Synthetic reviewer","status":"啟用","role":"主管","email":"reviewer@example.invalid"}
        selected = [{"key":"department_head","name":"部門主任","order":1,"role":"主任"}, {"key":"general_affairs_review","name":"總務","order":2,"role":"總務"}]
        editor_plan = None if kind == "compose" else {
            "request_row":{**witness["stamp_request"],"claim_attempt_count":0,"created_at":self.timestamp,"updated_at":self.timestamp},
            "position_rows":[{**position,"created_at":self.timestamp,"updated_at":self.timestamp} for position in witness["stamp_positions"]],
            "revision_id":revision["id"],"manifest_sha256":revision["manifest_sha256"],"source_sha256":"A"*64,
            "prepared_file_id":prepared["asset"]["official_file_id"],"prepared_sha256":"C"*64,"seal_positions":witness["stamp_positions"],
        }
        cursor = self.pg.execute("SELECT * FROM official_document_approval_steps WHERE document_id=%s", (identity,))
        existing = [dict(zip((column.name for column in cursor.description), values)) for values in cursor.fetchall()]
        captured = {}

        def capture(method, endpoint, body):
            self.assertEqual((method,endpoint), ("POST","rpc/edoc_commit_official_document_submission"))
            captured.update(copy.deepcopy(body["p_request"]))
            return {"committed":True,"document_id":identity,"operation_id":captured["operation_id"],"first_step_id":captured["first_step_id"],"current_status":captured["first_status"],"current_step":captured["first_step_key"],"workflow_generation":captured["workflow_generation"]}

        with ExitStack() as stack:
            stubs = {
                "supabase_official_session_user":user,"supabase_official_document_row":document,
                "official_seal_context_from_document":backend.require_official_seal_classification({"document_category":"採購合約"}),
                "is_production":False,"supabase_official_workflow_config":backend.normalize_official_workflow_config(),
                "configured_official_workflow_steps":selected,"supabase_official_document_steps":existing,
                "supabase_official_company_row":{"id":"CO-COMPOSE","name":"Synthetic company"},
                "supabase_resolve_official_step_approver":reviewer,
                "supabase_lock_official_editor_submission":editor_plan,"supabase_ensure_official_generated_pdf":generated_source,
                "supabase_assert_official_document_uploads_av_clean":None,"supabase_official_document_detail":document,
                "supabase_create_and_deliver_notification":None,"now":self.timestamp,
            }
            for name,value in stubs.items():
                stack.enter_context(mock.patch.object(backend,name,return_value=value))
            stack.enter_context(mock.patch.object(backend,"supabase_user_by_id",side_effect=lambda key: user if key=="APPLICANT" else reviewer))
            stack.enter_context(mock.patch.object(backend,"supabase_request",side_effect=capture))
            backend.supabase_submit_official_document(identity,{
                "expected_content_revision":document["content_revision"],
                "editorRevisionId":revision["id"],"manifestSha256":revision["manifest_sha256"],
                "preparedFileId":prepared["asset"]["official_file_id"],"preparedSha256":"C"*64,
            }, {"user":user})
        self.assertTrue(captured)
        self.assertEqual(len(captured["actor_snapshots"]),len(captured["steps"]))
        return captured

    def submit(self, payload):
        return self.rpc("edoc_commit_official_document_submission",payload)

    def assert_not_committed(self,payload):
        document = self.row("official_documents",payload["document_id"])
        self.assertEqual(document["current_status"],payload["expected_status"])
        self.assertEqual(document["content_revision"],payload["expected_content_revision"])
        for table, predicate, value in (
            ("official_document_approval_steps","document_id=%s AND workflow_generation="+str(payload["workflow_generation"]),payload["document_id"]),
            ("official_document_approval_logs","id=%s",payload["operation_id"]),
            ("audit_logs","id=%s",payload["submit_audit"]["id"]),
        ):
            self.assertEqual(0,self.pg.execute(f"SELECT count(*) FROM {table} WHERE {predicate}",(value,)).fetchone()[0])
        if payload["stamp_request"].get("id"):
            self.assertIsNone(self.row("official_document_stamp_requests",payload["stamp_request"]["id"]))

    def test_real_builder_pdf_compose_draft_and_resubmission_commit(self):
        for kind in ("pdf","compose"):
            for rejected in (False,True):
                with self.subTest(kind=kind,rejected=rejected):
                    payload = self.plan(kind=kind,rejected=rejected)
                    self.assertTrue(all(row.get("decision_evidence_json")=={} for row in payload["steps"]))
                    result = self.submit(payload)
                    self.assertTrue(result["committed"])
                    self.assertEqual(self.row("official_documents",payload["document_id"])["current_step"],"department_head")
                    self.assertEqual([({},),({},)],self.pg.execute("SELECT decision_evidence_json FROM official_document_approval_steps WHERE document_id=%s AND workflow_generation=%s ORDER BY step_order",(payload["document_id"],payload["workflow_generation"])).fetchall())
                    self.assertTrue(self.submit(payload)["idempotent"])
                    self.assertEqual(1,self.pg.execute("SELECT count(*) FROM official_document_approval_logs WHERE id=%s",(payload["operation_id"],)).fetchone()[0])
                    if rejected:
                        self.assertEqual("rejected",self.row("official_document_approval_steps","OLD-"+payload["document_id"])["status"])
                        self.assertEqual("skipped",self.row("official_document_approval_steps","OLD-PENDING-"+payload["document_id"])["status"])
                        self.assertIsNone(self.row("official_documents",payload["document_id"])["correction_requested_at"])
                        self.assertEqual(2,payload["workflow_generation"])

    def test_old_rpc_reproduces_missing_column_failure_and_rolls_back(self):
        payload = self.plan()
        for step in payload["steps"]: step.pop("decision_evidence_json",None)
        column = self.pg.execute("SELECT is_nullable,column_default FROM information_schema.columns WHERE table_schema=%s AND table_name='official_document_approval_steps' AND column_name='decision_evidence_json'",(self.namespace,)).fetchone()
        self.assertEqual(column,("NO","'{}'::jsonb"))
        # Pin the actual violation hidden by the old RPC's generic catch.
        # jsonb_populate_record(null::rowtype, ...) supplies SQL NULL, not the
        # table default, even though the omitted column has DEFAULT '{}'.
        with self.assertRaises(self.psycopg.errors.NotNullViolation) as raw:
            with self.pg.transaction():
                self.pg.execute(f"INSERT INTO {self.namespace}.official_document_approval_steps SELECT * FROM jsonb_populate_record(null::{self.namespace}.official_document_approval_steps,%s::jsonb)",(json.dumps(payload["steps"][0]),))
        self.assertEqual(raw.exception.diag.column_name,"decision_evidence_json")
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("SET LOCAL ROLE postgres")
            self.pg.execute(self.before_forward)
            with self.assertRaisesRegex(self.psycopg.Error,"official_submission_invalid_payload"):
                self.submit(payload)
            self.assert_not_committed(payload)

    def test_legacy_missing_evidence_gets_empty_object_but_explicit_invalid_fails(self):
        payload = self.plan()
        for step in payload["steps"]: step.pop("decision_evidence_json",None)
        self.assertTrue(self.submit(payload)["committed"])
        self.assertEqual([({},),({},)],self.pg.execute("SELECT decision_evidence_json FROM official_document_approval_steps WHERE document_id=%s ORDER BY step_order",(payload["document_id"],)).fetchall())
        for invalid in (None,[],"{}",0,False):
            with self.subTest(invalid=invalid):
                bad = self.plan()
                bad["steps"][1]["decision_evidence_json"] = invalid
                with self.assertRaisesRegex(self.psycopg.Error,"official_submission_invalid_payload"): self.submit(bad)
                self.assert_not_committed(bad)
                # A submitted operation must not bypass payload validation via
                # the idempotent-return branch.
                retry = copy.deepcopy(payload)
                retry["steps"][0]["decision_evidence_json"] = invalid
                with self.assertRaisesRegex(self.psycopg.Error,"official_submission_invalid_payload"): self.submit(retry)

    def test_late_snapshot_failure_rolls_back_workflow_stamp_and_status(self):
        payload = self.plan()
        payload["actor_snapshots"][1]["approver_user_id"] = "NOT-THE-REVIEWER"
        with self.assertRaisesRegex(self.psycopg.Error,"official_submission_invalid_payload"): self.submit(payload)
        self.assert_not_committed(payload)

    def test_two_simultaneous_retries_commit_one_generation_and_audit(self):
        payload = self.plan()
        barrier = threading.Barrier(2)
        def send(_):
            with self.psycopg.connect(host="127.0.0.1",port=int(base.PORT),
                    user=os.getenv("EDOC_TEST_PG_USER","seniorlifepr"),dbname=self.dbname,autocommit=True) as connection:
                barrier.wait(timeout=5)
                return self.rpc("edoc_commit_official_document_submission",payload,conn=connection)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(send,range(2)))
        self.assertEqual([False,True],sorted(result["idempotent"] for result in results))
        self.assertEqual(2,self.pg.execute("SELECT count(*) FROM official_document_approval_steps WHERE document_id=%s",(payload["document_id"],)).fetchone()[0])
        self.assertEqual(1,self.pg.execute("SELECT count(*) FROM audit_logs WHERE id=%s",(payload["submit_audit"]["id"],)).fetchone()[0])

    def test_stale_application_and_wrong_actor_remain_zero_write(self):
        for key,value,code in (("expected_content_revision",99,"compose_content_revision_conflict"),
                ("applicant_id","OTHER-APPLICANT","official_document_submit_forbidden"),
                ("company_id","CO-OTHER","official_document_submit_forbidden")):
            with self.subTest(key=key):
                payload = self.plan()
                bad = {**payload,key:value}
                with self.assertRaisesRegex(self.psycopg.Error,code): self.submit(bad)
                self.assert_not_committed(payload)

    def test_future_defaulted_step_column_does_not_break_submission(self):
        payload = self.plan()
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("ALTER TABLE official_document_approval_steps ADD COLUMN future_audit_marker text NOT NULL DEFAULT 'preserved-default'")
            self.assertTrue(self.submit(payload)["committed"])
            self.assertEqual([("preserved-default",),("preserved-default",)],self.pg.execute("SELECT future_audit_marker FROM official_document_approval_steps WHERE document_id=%s",(payload["document_id"],)).fetchall())
        # A rolled-back test-only composite-type change can leave a cached
        # PL/pgSQL row descriptor. Recompile after restoring the fixture schema.
        self.pg.execute("SET ROLE postgres")
        try:
            self.pg.execute(self.after_forward)
        finally:
            self.pg.execute("RESET ROLE")

    def test_browser_roles_cannot_execute_submit_and_hr_is_untouched(self):
        payload = self.plan()
        for role in ("anon","authenticated"):
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.rpc("edoc_commit_official_document_submission",payload,role=role)
        self.assert_not_committed(payload)
        if self.namespace=="edoc":
            self.assertEqual([("HR","unchanged")],self.pg.execute("SELECT * FROM public.hr_untouched").fetchall())


class SubmissionConstraintsSharedPostgresTest(SubmissionConstraintsPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"


if __name__ == "__main__":
    unittest.main()
