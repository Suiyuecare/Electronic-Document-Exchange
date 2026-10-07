"""Execute candidate handover transactions in isolated PostgreSQL namespaces."""
import copy
import json
import unittest
import uuid
import os
import re
from concurrent.futures import ThreadPoolExecutor

import official_handover as policy
import backend
from tests import test_configurable_workflow_postgres as fixture
from tools.shared_supabase_bootstrap import ROOT, transform_sql
from tools.offboarding_handover_shared_forward import render_shared_forward

SOURCE = "20261007004716_offboarding_handover.sql"


class HandoverPostgresTest(fixture.ConfigurableWorkflowPostgresTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pg.execute("SET ROLE postgres")
        try:
            # Parent applies the full candidate inventory, including this
            # source. Shared forward is deliberately replayed twice to prove
            # ledger/hash idempotency without rerunning raw historical DDL.
            if cls.namespace != "public":
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.rollback()
            cls.pg.execute("RESET ROLE")
        # This reduced fixture omits the historical table-grant reset. Mirror
        # only the listing read dependencies already present in the immutable
        # baseline 20260827063824 grant matrix; shared bootstrap transforms
        # the same grants to edoc/edoc_backend. Do not elevate the RPC or grant
        # any browser capabilities to make this fixture pass.
        grant_source = (ROOT / "supabase/migrations/20260827063824_lock_runtime_table_data_api_grants.sql").read_text()
        baseline_reads = re.search(r"grant select on table\s+(.*?)\s+to service_role;", grant_source, re.S).group(1)
        listing_tables = ("users", "official_document_approval_steps", "approval_step_actor_snapshots",
                          "official_document_dispatch_records", "official_document_stamp_requests",
                          "official_document_approval_logs", "official_workflow_delegations", "official_document_files")
        for table in listing_tables:
            if not re.search(r"\bpublic\." + re.escape(table) + r"\b", baseline_reads):
                raise AssertionError("listing fixture grant is absent from the immutable baseline")
        cls.pg.execute("GRANT SELECT ON " + ",".join(f"{cls.namespace}.{table}" for table in listing_tables) + f" TO {cls.backend_role}")
        for actor, role in (("GAHANDOVER", "總務"), ("ADHANDOVER", "行政部主任"), ("NEWHANDOVER", "主任")):
            cls.pg.execute("INSERT INTO users(id,name,email,role,status,account_source,company_id,finance_tenant_id) VALUES (%s,%s,%s,%s,'啟用','finance','CO-SECOND',%s)", (actor, actor, actor.lower()+"@example.invalid", role, cls.tenant))

    def case_request(self, *, kind="pending_approver", approve_first=False):
        # All authority for handover is strict same-company, unlike the
        # separately supported cross-company editor applicant-selection flow.
        self.pg.execute("UPDATE users SET status='啟用',company_id='CO-SECOND',account_source='finance',finance_tenant_id=%s WHERE id IN ('REVIEWER','NEXT','APPLICANT','GAHANDOVER','ADHANDOVER','NEWHANDOVER')", (self.tenant,))
        self.pg.execute("UPDATE users SET role='主任' WHERE id='NEWHANDOVER'")
        doc, evidence = self.workflow()
        former_id = "REVIEWER"
        if approve_first:
            self.decide(doc, evidence)
            former_id = "NEXT"
        if kind == "followup_owner": former_id = "APPLICANT"
        self.pg.execute("UPDATE users SET status='停用' WHERE id=%s", (former_id,))
        document = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        company = self.pg.execute("SELECT to_jsonb(c) FROM companies c WHERE id='CO-SECOND'").fetchone()[0]
        actors = {name: self.pg.execute("SELECT to_jsonb(u) FROM users u WHERE id=%s", (name,)).fetchone()[0]
                  for name in ("GAHANDOVER", "ADHANDOVER", former_id, "NEWHANDOVER")}
        stamp = self.pg.execute("SELECT to_jsonb(s) FROM official_document_stamp_requests s WHERE document_id=%s", (doc,)).fetchone()[0]
        steps = self.rows(doc)
        payload = {"operation_id": "HANDOVER-PG-"+uuid.uuid4().hex, "kind": kind, "reason": "Synthetic offboarding handover",
                   "expected_fingerprint": policy.handover_fingerprint(document, steps, stamp)}
        record = policy.propose_handover(document, steps, company, actors["GAHANDOVER"], actors[former_id],
                                         actors["NEWHANDOVER"], payload, timestamp="2026-10-07 10:00:00", stamp=stamp)
        return {"action": "propose", "actor_id": "GAHANDOVER", "handover_id": record["id"],
                "document_id": doc, "record": record, "expected_snapshot": policy.handover_snapshot(document, steps, stamp)}

    def handover(self, request):
        return self.rpc("edoc_manage_official_handover", [json.dumps(request)], ["::jsonb"])

    def test_followup_receipt_has_original_principal_actual_owner_and_live_binding(self):
        request = self.case_request(kind="followup_owner")
        self.handover(request)
        self.handover(self.confirmation(request))
        doc = request["document_id"]
        self.pg.execute("UPDATE official_document_approval_steps SET status='approved' WHERE document_id=%s AND step_key<>'applicant_confirm'", (doc,))
        self.pg.execute("UPDATE official_documents SET current_status='stamped',current_step='applicant_confirm' WHERE id=%s", (doc,))
        receipt = {"document_id": doc, "actor_id": "NEWHANDOVER", "expected_step_id": "step-3-" + doc,
                   "workflow_generation": 1, "followup_handover_id": request["handover_id"]}
        with self.pg.transaction(force_rollback=True):
            with self.assertRaises(self.psycopg.Error):
                self.rpc("edoc_confirm_official_document", [json.dumps({**receipt, "followup_handover_id": "FORGED"})], ["::jsonb"])
        first = self.rpc("edoc_confirm_official_document", [json.dumps(receipt)], ["::jsonb"])
        second = self.rpc("edoc_confirm_official_document", [json.dumps(receipt)], ["::jsonb"])
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        step = self.pg.execute("SELECT approver_user_id,decision_actor_user_id,decision_evidence_json FROM official_document_approval_steps WHERE id=%s", (receipt["expected_step_id"],)).fetchone()
        self.assertEqual(("APPLICANT", "NEWHANDOVER"), step[:2])
        self.assertEqual("APPLICANT", step[2]["principal_actor_id"])
        self.assertEqual(request["handover_id"], step[2]["followup_handover_id"])
        self.assertEqual(("APPLICANT","NEWHANDOVER"), self.pg.execute("SELECT principal_actor_id,actor_id FROM official_document_approval_logs WHERE id=%s", (first["approval_log_id"],)).fetchone())
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("UPDATE users SET status='停用' WHERE id='NEWHANDOVER'")
            with self.assertRaises(self.psycopg.Error):
                self.rpc("edoc_confirm_official_document", [json.dumps(receipt)], ["::jsonb"])

    def confirmation(self, request, **changes):
        return {"action": "confirm", "actor_id": "ADHANDOVER", "handover_id": request["handover_id"],
                "document_id": request["document_id"], **changes}

    def test_linked_new_application_is_atomic_unapproved_empty_editor_and_idempotent(self):
        request = self.case_request(kind="followup_owner")
        self.handover(request)
        self.handover(self.confirmation(request))
        doc = request["document_id"]
        self.pg.execute("UPDATE official_documents SET current_status='rejected' WHERE id=%s", (doc,))
        before = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        stamp = self.pg.execute("SELECT to_jsonb(s) FROM official_document_stamp_requests s WHERE document_id=%s", (doc,)).fetchone()[0]
        state = backend.validate_editor_state({"schemaVersion": 2, "revisionNo": 1, "sourceFiles": [], "pages": [], "elements": [], "manifestSha256": ""})
        state["manifestSha256"] = backend.canonical_editor_manifest(state)
        self.assertRegex(state["manifestSha256"], r"^[A-F0-9]{64}$")
        binding = self.pg.execute("SELECT to_jsonb(f) FROM official_document_followup_owners f WHERE document_id=%s", (doc,)).fetchone()[0]
        payload = {"action": "linked_create", "actor_id": "NEWHANDOVER", "document_id": doc,
            "handover_id": request["handover_id"], "operation_id": "LINKED-PG-"+uuid.uuid4().hex,
            "expected_snapshot": policy.handover_snapshot(before, self.rows(doc), stamp, binding),
            "expected_fingerprint": policy.handover_fingerprint(before, self.rows(doc), stamp, binding),
            "department": {"id": "SYNTHETIC", "name": "Synthetic unit"},
            "editor_state": state, "renderer_version": backend.EDOC_EDITOR_RENDERER_VERSION}
        for invalid_digest in ("", "A" * 63, "A" * 65, "g" * 64, "A" * 64 + " "):
            with self.subTest(invalid_manifest=invalid_digest), self.pg.transaction(force_rollback=True):
                invalid_state = {**state, "manifestSha256": invalid_digest}
                with self.assertRaisesRegex(self.psycopg.Error, "handover_linked_editor_invalid"):
                    self.handover({**payload, "editor_state": invalid_state})
        with self.subTest(manifest_case="lowercase"), self.pg.transaction(force_rollback=True):
            lowercase_state = {**state, "manifestSha256": state["manifestSha256"].lower()}
            lowercase_result = self.handover({**payload, "editor_state": lowercase_state})
            self.assertFalse(lowercase_result["idempotent"])
        with self.pg.transaction(force_rollback=True):
            with self.assertRaises(self.psycopg.Error): self.handover({**payload, "actor_id": "NEXT"})
        with self.pg.transaction(force_rollback=True):
            with self.assertRaises(self.psycopg.Error): self.handover({**payload, "expected_snapshot": {"forged": True}})
        result = self.handover(payload)
        self.assertFalse(result["idempotent"])
        self.assertTrue(self.handover(payload)["idempotent"])
        linked = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (result["document_id"],)).fetchone()[0]
        self.assertEqual(("draft", "NEWHANDOVER", None), (linked["current_status"], linked["applicant_id"], linked["stamped_file_id"]))
        self.assertEqual(before, self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0])
        self.assertEqual([], self.rows(linked["id"]))
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_files WHERE document_id=%s", (linked["id"],)).fetchone()[0])
        revision = self.pg.execute("SELECT editor_state_json FROM official_document_editor_revisions WHERE document_id=%s", (linked["id"],)).fetchone()
        # The historical editor_state_json column is text in both baselines.
        # Decode the stored document before checking that no old pages/seals
        # were carried into the fresh linked application.
        revision_state = json.loads(revision[0]) if isinstance(revision[0], str) else revision[0]
        self.assertEqual([], revision_state["pages"])
        self.assertEqual([], revision_state["elements"])
        self.assertEqual(state["manifestSha256"], revision_state["manifestSha256"])
        with self.pg.transaction(force_rollback=True):
            with self.assertRaises(self.psycopg.Error): self.handover({**payload, "expected_fingerprint": "f"*64})

    def test_listing_includes_live_followup_binding_without_original_applicant_rewrite(self):
        request = self.case_request(kind="followup_owner")
        self.handover(request); self.handover(self.confirmation(request))
        data = self.rpc("edoc_list_official_document_candidates", [json.dumps({"actor_id": "NEWHANDOVER", "limit": 100})], ["::jsonb"])
        case = next(row for row in data["items"] if row["document"]["id"] == request["document_id"])
        self.assertEqual("NEWHANDOVER", case["followup_binding"]["process_owner_user_id"])
        self.assertEqual("APPLICANT", case["document"]["applicant_id"])
        mine = self.rpc("edoc_list_official_document_candidates", [json.dumps({"actor_id": "NEWHANDOVER", "scope": "mine", "limit": 100})], ["::jsonb"])
        self.assertNotIn(request["document_id"], [row["document"]["id"] for row in mine["items"]])

    def test_repeat_followup_succession_validates_chain_revokes_old_owner_and_keeps_original(self):
        first = self.case_request(kind="followup_owner")
        self.handover(first); self.handover(self.confirmation(first))
        doc = first["document_id"]
        original = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0]
        binding = self.pg.execute("SELECT to_jsonb(f) FROM official_document_followup_owners f WHERE document_id=%s", (doc,)).fetchone()[0]
        self.pg.execute("UPDATE users SET status='停用' WHERE id='NEWHANDOVER'")
        actors = {name: self.pg.execute("SELECT to_jsonb(u) FROM users u WHERE id=%s", (name,)).fetchone()[0] for name in ("GAHANDOVER", "NEWHANDOVER", "NEXT")}
        company = self.pg.execute("SELECT to_jsonb(c) FROM companies c WHERE id='CO-SECOND'").fetchone()[0]
        stamp = self.pg.execute("SELECT to_jsonb(s) FROM official_document_stamp_requests s WHERE document_id=%s", (doc,)).fetchone()[0]
        payload = {"operation_id": "HANDOVER-REPEAT-"+uuid.uuid4().hex, "kind": "followup_owner", "reason": "Synthetic repeated succession",
            "expected_fingerprint": policy.handover_fingerprint(original, self.rows(doc), stamp, binding)}
        record = policy.propose_handover(original, self.rows(doc), company, actors["GAHANDOVER"], actors["NEWHANDOVER"], actors["NEXT"], payload, timestamp="2026-10-07 11:00:00", stamp=stamp, binding=binding)
        second = {"action": "propose", "actor_id": "GAHANDOVER", "handover_id": record["id"], "document_id": doc,
            "record": record, "expected_snapshot": policy.handover_snapshot(original, self.rows(doc), stamp, binding)}
        self.handover(second)
        self.assertIsNone(self.pg.execute("SELECT edoc_private.official_followup_owner(%s,'NEWHANDOVER')", (doc,)).fetchone()[0])
        self.handover(self.confirmation(second))
        proof = self.pg.execute("SELECT edoc_private.official_followup_owner(%s,'NEXT')", (doc,)).fetchone()[0]
        self.assertEqual(second["handover_id"], proof["handover_id"])
        self.assertEqual("APPLICANT", proof["original_applicant_id"])
        self.assertEqual(original, self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (doc,)).fetchone()[0])
        self.assertEqual(2, self.pg.execute("SELECT count(*) FROM official_document_handovers WHERE document_id=%s AND status='approved'", (doc,)).fetchone()[0])
        self.assertTrue(self.handover(self.confirmation(second))["idempotent"])
        with self.pg.transaction(force_rollback=True):
            self.pg.execute("UPDATE official_document_handovers SET request_json=request_json||'{\"previous_handover_id\":\"MISSING-PARENT\"}'::jsonb WHERE id=%s", (second["handover_id"],))
            self.assertIsNone(self.pg.execute("SELECT edoc_private.official_followup_owner(%s,'NEXT')", (doc,)).fetchone()[0])

    def test_handover_atomic_current_reviewer_then_real_review_and_approval(self):
        request = self.case_request()
        self.assertFalse(self.handover(request)["idempotent"])
        self.assertTrue(self.handover(request)["idempotent"])
        result = self.handover(self.confirmation(request))
        self.assertEqual("approved", result["status"])
        rows = self.rows(request["document_id"], 2)
        self.assertEqual("NEWHANDOVER", rows[0]["approver_user_id"])
        self.assertIsNone(rows[0]["decision_actor_user_id"])
        self.assertEqual(request["handover_id"], rows[0]["decision_evidence_json"]["added_by_operation_id"])
        self.assertTrue(self.handover(self.confirmation(request))["idempotent"])
        self.assertEqual(1, self.pg.execute("SELECT count(*) FROM official_document_approval_logs WHERE id=%s", ("HLOG-"+request["handover_id"],)).fetchone()[0])
        evidence = self.review(request["document_id"], rows[0]["id"], "NEWHANDOVER")
        self.assertTrue(self.decide(request["document_id"], evidence)["claimed"])
        actual = self.rows(request["document_id"], 2)[0]
        self.assertEqual("NEWHANDOVER", actual["decision_actor_user_id"])
        self.assertEqual(request["handover_id"], actual["decision_evidence_json"]["added_by_operation_id"])

    def test_handover_completed_actual_actor_evidence_remain_immutable(self):
        request = self.case_request(approve_first=True)
        before = self.rows(request["document_id"], 1)[0]
        self.handover(request)
        self.handover(self.confirmation(request))
        self.assertEqual(before, self.rows(request["document_id"], 1)[0])
        fresh = self.rows(request["document_id"], 2)
        self.assertEqual(before["decision_actor_user_id"], fresh[0]["decision_actor_user_id"])
        self.assertEqual(before["approved_at"], fresh[0]["approved_at"])
        self.assertEqual("NEWHANDOVER", fresh[1]["approver_user_id"])

    def test_handover_forged_snapshot_does_not_get_accepted(self):
        request = self.case_request()
        request["expected_snapshot"]["document"]["content_revision"] += 1
        with self.assertRaisesRegex(self.psycopg.Error, "version_conflict"): self.handover(request)
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_handovers WHERE id=%s", (request["handover_id"],)).fetchone()[0])

    def test_handover_disable_successor_and_cross_company_fail_at_commit(self):
        for update in ("status='停用'", "company_id='CO-COMPOSE'", "role='員工'", "finance_tenant_id='00000000-0000-0000-0000-000000000009'"):
            request = self.case_request()
            self.handover(request)
            self.pg.execute("UPDATE users SET " + update + " WHERE id='NEWHANDOVER'")
            with self.subTest(update=update), self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.handover(self.confirmation(request))
            self.assertEqual(1, max(row["workflow_generation"] for row in self.rows(request["document_id"])))

    def test_handover_same_person_and_unauthorized_confirmers_denied(self):
        request = self.case_request()
        self.handover(request)
        for actor in ("GAHANDOVER", "NEWHANDOVER", "CONFIGADMIN", "APPLICANT"):
            with self.subTest(actor=actor), self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.handover(self.confirmation(request, actor_id=actor))

    def test_handover_late_stamp_claim_or_new_decision_requires_reload(self):
        request = self.case_request()
        self.handover(request)
        self.pg.execute("UPDATE official_document_stamp_requests SET claim_token='CLAIMED' WHERE document_id=%s", (request["document_id"],))
        with self.assertRaisesRegex(self.psycopg.Error, "version_conflict"):
            self.handover(self.confirmation(request))
        self.assertEqual(3, len(self.rows(request["document_id"])))

    def test_handover_reject_never_changes_workflow_and_is_idempotent(self):
        request = self.case_request()
        self.handover(request)
        before = self.rows(request["document_id"])
        reject = self.confirmation(request, action="reject", reason="Synthetic rejected handover")
        self.assertEqual("rejected", self.handover(reject)["status"])
        self.assertTrue(self.handover(reject)["idempotent"])
        self.assertEqual(before, self.rows(request["document_id"]))
        with self.assertRaisesRegex(self.psycopg.Error, "already_resolved"): self.handover(self.confirmation(request))

    def test_handover_followup_never_rewrites_original(self):
        request = self.case_request(kind="followup_owner")
        before = self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (request["document_id"],)).fetchone()[0]
        steps = self.rows(request["document_id"])
        self.handover(request)
        self.handover(self.confirmation(request))
        binding = self.pg.execute("SELECT original_applicant_id,process_owner_user_id,correction_policy FROM official_document_followup_owners WHERE document_id=%s", (request["document_id"],)).fetchone()
        self.assertEqual(("APPLICANT", "NEWHANDOVER", "linked_new_application"), binding)
        self.assertEqual(before, self.pg.execute("SELECT to_jsonb(d) FROM official_documents d WHERE id=%s", (request["document_id"],)).fetchone()[0])
        self.assertEqual(steps, self.rows(request["document_id"]))

    def test_handover_tables_and_rpc_deny_browser_and_direct_backend_mutations(self):
        for table in ("official_document_handovers", "official_document_followup_owners"):
            for role in ("anon", "authenticated", self.backend_role):
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    self.assertFalse(self.pg.execute("SELECT has_table_privilege(%s,%s,%s)", (role, self.namespace+"."+table, privilege)).fetchone()[0])
        for role in ("anon", "authenticated") + (("service_role",) if self.namespace == "edoc" else ()):
            self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, self.namespace+".edoc_manage_official_handover(jsonb)")).fetchone()[0])

    def test_handover_null_or_unknown_action_is_not_a_permission_bypass(self):
        request = self.case_request(kind="followup_owner")
        self.handover(request)
        for action in (None, "", "administrator_auto_confirm"):
            bad = self.confirmation(request, action=action, actor_id="NEWHANDOVER")
            with self.subTest(action=action), self.assertRaisesRegex(self.psycopg.Error, "action_invalid"):
                self.handover(bad)
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM official_document_followup_owners WHERE document_id=%s", (request["document_id"],)).fetchone()[0])

    def test_private_followup_proof_helpers_are_not_browser_capabilities(self):
        signatures = ("edoc_private.official_followup_lineage(text)", "edoc_private.official_followup_owner(text,text)")
        for signature in signatures:
            for role in ("anon", "authenticated"):
                with self.subTest(signature=signature, role=role):
                    self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)).fetchone()[0])
            role = "edoc_backend" if self.namespace == "edoc" else "service_role"
            self.assertTrue(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)).fetchone()[0])

    def test_handover_queue_is_readonly_live_scoped_and_paginated(self):
        request = self.case_request()
        query = {"action": "queue", "actor_id": "GAHANDOVER", "page": 1, "page_size": 50, "view": "needs"}
        result = self.handover(query)
        self.assertIn(request["document_id"], [row["id"] for row in result["items"]])
        self.assertEqual(set(result["items"][0]), {"id", "dispatch_no", "subject", "current_status", "updated_at"})
        self.assertNotIn(request["document_id"], [row["id"] for row in self.handover({**query, "view": "pending"})["items"]])
        self.assertEqual(1, len(self.handover({**query, "page_size": 1})["items"]))
        self.handover(request)
        self.assertIn(request["document_id"], [row["id"] for row in self.handover({**query, "view": "pending"})["items"]])
        for actor in ("APPLICANT", "NEWHANDOVER", "REVIEWER"):
            with self.subTest(actor=actor), self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.handover({**query, "actor_id": actor})
        with self.assertRaises(self.psycopg.Error): self.handover({**query, "page_size": 1000})
        self.pg.execute("UPDATE users SET finance_tenant_id='different-tenant' WHERE id='GAHANDOVER'")
        with self.assertRaises(self.psycopg.errors.InsufficientPrivilege): self.handover(query)

    def test_handover_confirm_and_reject_race_has_one_transaction_winner(self):
        request = self.case_request()
        self.handover(request)
        def resolve(action):
            with self.psycopg.connect(host="127.0.0.1", port=int(os.environ["EDOC_COMPOSE_TEST_PG_PORT"]),
                                      user=os.getenv("EDOC_TEST_PG_USER", "seniorlifepr"), dbname=self.dbname, autocommit=True) as pg:
                try:
                    with pg.transaction():
                        pg.execute(f"SET LOCAL ROLE {self.backend_role}")
                        return pg.execute(f"SELECT {self.namespace}.edoc_manage_official_handover(%s::jsonb)",
                            (json.dumps(self.confirmation(request, action=action, reason="Synthetic rejected handover")),)).fetchone()[0]["status"]
                except self.psycopg.Error as exc:
                    if exc.sqlstate != "PT409": raise
                    return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(resolve, ("confirm", "reject")))
        self.assertEqual(1, outcomes.count("conflict"))
        self.assertEqual(1, self.pg.execute("SELECT count(*) FROM audit_logs WHERE id IN (%s,%s)",
            ("AUD-HANDOVER-confirm-"+request["handover_id"], "AUD-HANDOVER-reject-"+request["handover_id"])).fetchone()[0])


class SharedHandoverPostgresTest(HandoverPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"


def load_tests(loader, standard_tests, pattern):
    # Parent fixtures supply setup/helpers. Their other flows have independent
    # suites; avoid claiming repeated inherited tests as new handover coverage.
    # Include EVERY test declared by this candidate, not just names beginning
    # test_handover_: receipt, linked-case, lineage and ACL tests count too.
    names = sorted(name for name, value in HandoverPostgresTest.__dict__.items()
                   if name.startswith("test_") and callable(value))
    return unittest.TestSuite(loader.loadTestsFromName(cls.__name__+"."+name, module=__import__(__name__, fromlist=["*"]))
        for cls in (HandoverPostgresTest, SharedHandoverPostgresTest)
        for name in names)
