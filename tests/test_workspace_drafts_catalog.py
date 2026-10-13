import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest import mock
import workspace_drafts
from tests.test_official_list_pagination import OfficialListPaginationTest
from tools.workspace_drafts_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import ROOT, load_manifest, sha256_text, transform_sql


class WorkspaceDraftCatalogTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""CREATE TABLE official_documents(id text,applicant_id text,company_id text,current_status text,source_type text,subject text,title text,updated_at text);
        CREATE TABLE official_document_compose_drafts(id text,applicant_id text,company_id text,archived int,snapshot_json text,updated_at text);""")
        self.user = {"id": "A", "company_id": "C"}
        self.api = SimpleNamespace(compose_draft_user=lambda session: self.user)

    def tearDown(self):
        self.conn.close()

    def cloud(self, key, linked="", actor="A", company="C", archived=0, date="2026-10-14"):
        snapshot = {"values": {"#subject": "測試 " + key}, "draftRequestId": linked}
        self.conn.execute("INSERT INTO official_document_compose_drafts VALUES (?,?,?,?,?,?)", (key, actor, company, archived, json.dumps(snapshot), date))

    def official(self, key, status="draft", actor="A", company="C"):
        self.conn.execute("INSERT INTO official_documents VALUES (?,?,?,?,?,?,?,?)", (key, actor, company, status, "uploaded_pdf", "測試文件", "", "2026-10-14"))

    def read(self, **query):
        return workspace_drafts.list_sqlite(self.api, self.conn, {k: [str(v)] for k, v in query.items()}, {})

    def test_full_count_keyset_exceeds_old_twenty_limit_and_no_snapshots(self):
        for i in range(81): self.cloud(f"C{i:03d}")
        summary = self.read(summary=1)
        self.assertEqual((81, []), (summary["total"], summary["items"]))
        rows, cursor = [], ""
        while True:
            page = self.read(page_size=25, cursor=cursor)
            rows.extend(page["items"])
            self.assertEqual(81, page["total"])
            if not page["has_more"]: break
            cursor = page["next_cursor"]
        self.assertEqual(81, len({row["key"] for row in rows}))
        self.assertTrue(all("snapshot" not in row and "snapshot_json" not in row for row in rows))

    def test_dedup_and_terminal_cases_do_not_resurface_from_stale_cloud(self):
        self.official("D"); self.cloud("old", "D", date="2026-10-13"); self.cloud("new", "D")
        self.official("R", "rejected"); self.cloud("returned", "R")
        for status in ("pending_approval", "declined", "closed", "cancelled"):
            self.official(status, status); self.cloud("cloud-" + status, status)
        self.official("pdf")
        result = self.read()
        self.assertEqual(3, result["total"])
        self.assertEqual({"new", "returned", "pdf"}, {row["id"] for row in result["items"]})

    def test_never_lists_another_user_company_private_cloud_or_archived(self):
        self.cloud("mine"); self.cloud("foreign-actor", actor="B"); self.cloud("foreign-company", company="D"); self.cloud("archived", archived=1)
        self.official("other-case", actor="B")
        self.assertEqual(["mine"], [row["id"] for row in self.read()["items"]])

    def test_search_cursor_bound_to_actor_and_query(self):
        for i in range(3): self.cloud(str(i))
        cursor = self.read(page_size=1)["next_cursor"]
        with self.assertRaisesRegex(ValueError, "cursor_invalid"): self.read(cursor=cursor, search="new query")
        self.user["id"] = "B"
        with self.assertRaisesRegex(ValueError, "cursor_invalid"): self.read(cursor=cursor)

    def test_mutation_changes_exact_count_and_permission_failure_propagates(self):
        self.official("D"); self.assertEqual(1, self.read(summary=1)["total"])
        self.conn.execute("UPDATE official_documents SET current_status='pending_approval'")
        self.assertEqual(0, self.read(summary=1)["total"])
        self.api.compose_draft_user = mock.Mock(side_effect=PermissionError("forbidden"))
        with self.assertRaises(PermissionError): self.read()

    def test_supabase_uses_single_scoped_metadata_rpc(self):
        self.api.supabase_request = mock.Mock(return_value={"items": [], "total": 812})
        result = workspace_drafts.list_supabase(self.api, {"summary": ["1"]}, {})
        self.assertEqual(812, result["total"])
        args = self.api.supabase_request.call_args.args
        self.assertEqual(("POST", "rpc/edoc_workspace_drafts"), args[:2])
        self.assertEqual("A", args[2]["p_request"]["actor_id"])
        self.assertTrue(args[2]["p_request"]["summary"])

    def test_exact_shared_forward_and_manifest(self):
        self.assertEqual(render_shared_forward(), (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text())
        self.assertIn(SOURCE, load_manifest())
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        self.assertIn("security invoker set search_path=''", source)
        self.assertIn("from public,anon,authenticated", source)
        self.assertIn("'return_previous','decline'", source)
        cutover = (ROOT / "supabase/verification/shared_project_cutover_checks.sql").read_text()
        self.assertIn("source_sha256='" + sha256_text(source) + "'", cutover)
        self.assertIn("transformed_sha256='" + sha256_text(transform_sql(source)) + "'", cutover)


class ApprovalWorkspaceViewsTest(OfficialListPaginationTest):
    def test_assigned_or_applicant_is_not_actual_decision(self):
        self.bundles = [self.bundles[0]]
        self.bundles[0]["steps"] = [{"id": "S", "status": "approved", "approver_user_id": "ACTOR", "step_key": "applicant_manager"}]
        self.assertEqual([], self.read({"view": ["acted"]}))
        self.assertEqual(1, len(self.read({"view": ["mine"]})))

    def test_actual_actor_all_generations_and_return_decline_logs(self):
        self.bundles = [self.bundles[0]]
        for action in ("approve", "reject", "add_sign", "return_previous", "decline"):
            self.bundles[0]["decision_logs"] = [{"actor_id": "ACTOR", "action": action}]
            self.assertEqual(1, len(self.read({"view": ["acted"]})), action)
        self.bundles[0]["decision_logs"] = [{"actor_id": "OTHER", "action": "approve"}]
        self.assertEqual([], self.read({"view": ["acted"]}))

    def test_pending_excludes_drafts_rejected_tab_keeps_both_kinds(self):
        self.bundles = self.bundles[:3]
        self.bundles[1]["document"]["current_status"] = "rejected"
        self.bundles[2]["document"]["current_status"] = "declined"
        self.assertEqual([], self.read({"view": ["pending"]}))
        self.assertEqual(2, len(self.read({"view": ["rejected"]})))

    def test_task_filter_cursor_cannot_be_reused_across_filters(self):
        page = self.read({"view": ["mine"], "page_size": ["1"]})
        with self.assertRaisesRegex(ValueError, "cursor_invalid"):
            self.read({"view": ["mine"], "page_size": ["1"], "cursor": [page["next_cursor"]], "task_filter": ["operations"]})
