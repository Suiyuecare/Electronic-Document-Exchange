import json
import unittest
import uuid
from unittest import mock

import backend
import workspace_drafts
from tests.test_compose_resilience import ComposeResilienceTest
from tools.private_draft_archive_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward, render_cutover_gate
from tools.shared_supabase_bootstrap import ROOT, load_manifest, sha256_text, transform_sql


class PrivateDraftArchiveTest(ComposeResilienceTest):
    def private(self, **snapshot_changes):
        key = "OD-" + str(uuid.uuid4())
        payload = {"snapshot": {**self.snapshot(), **snapshot_changes}, "expected_revision": 0}
        return backend.save_compose_draft(self.conn, key, payload, self.session)

    def archive(self, draft, archived=True, revision=None):
        return backend.archive_compose_draft(draft["id"], {"archived": archived, "expected_revision": draft["revision"] if revision is None else revision}, self.session, self.conn)

    def catalog(self, **kwargs):
        return workspace_drafts.list_sqlite(backend, self.conn, {k: [str(v)] for k, v in kwargs.items()}, self.session)

    def test_private_archive_restore_preserves_snapshot_and_counts(self):
        draft = self.private()
        self.assertEqual(1, self.catalog()["total"])
        self.assertTrue(self.catalog()["items"][0]["can_archive"])
        archived = self.archive(draft)
        self.assertEqual(2, archived["revision"])
        self.assertEqual(draft["snapshot"], archived["snapshot"])
        self.assertEqual(0, self.catalog()["total"])
        self.assertEqual(1, self.catalog(archived=1)["total"])
        with self.assertRaises(PermissionError): backend.get_compose_draft(draft["id"], self.session, self.conn)
        restored = self.archive(archived, False)
        self.assertEqual(3, restored["revision"])
        self.assertFalse(restored["archived"])
        self.assertEqual(draft["snapshot"], backend.get_compose_draft(draft["id"], self.session, self.conn)["snapshot"])
        self.assertEqual(1, self.catalog()["total"])
        self.assertEqual(0, self.catalog(archived=1)["total"])

    def test_stale_revision_and_ordinary_autosave_cannot_restore(self):
        draft = self.private()
        archived = self.archive(draft)
        for revision in (draft["revision"], archived["revision"]):
            with self.assertRaisesRegex(ValueError, "revision_conflict"):
                backend.save_compose_draft(self.conn, draft["id"], {"snapshot": draft["snapshot"], "expected_revision": revision}, self.session)
        with self.assertRaisesRegex(ValueError, "revision_conflict"):
            self.archive(archived, False, draft["revision"])
        self.assertEqual(1, self.catalog(archived=1)["total"])

    def test_formal_link_and_number_cannot_be_archived_or_restored(self):
        formal = self.create()
        for changes in ({"officialDocumentId": formal["id"]}, {"draftRequestId": formal["id"]}, {"currentComposeDraftId": "OUT-123"}, {"values": {"#dispatchNo": "已配號"}}):
            draft = self.private(**changes)
            with self.assertRaisesRegex(ValueError, "archive_private_only"): self.archive(draft)
            # Even an old auto-archived submitted snapshot is not a personal restore target.
            self.conn.execute("UPDATE official_document_compose_drafts SET archived=1 WHERE id=?", (draft["id"],))
            with self.assertRaisesRegex(ValueError, "archive_private_only"): self.archive(draft, False)
            self.assertNotIn(draft["id"], [r["id"] for r in self.catalog(archived=1)["items"]])
        self.assertEqual("draft", backend.official_document_row(self.conn, formal["id"])["current_status"])

    def test_owner_company_permissions_and_invalid_payload(self):
        draft = self.private()
        other = self.conn.execute("SELECT id FROM users WHERE id<>? LIMIT 1", (backend.compose_draft_user(self.session)["id"],)).fetchone()[0]
        for field, value in (("applicant_id", other), ("company_id", "CO-002")):
            self.conn.execute(f"UPDATE official_document_compose_drafts SET {field}=? WHERE id=?", (value, draft["id"]))
            with self.assertRaisesRegex(PermissionError, "scope_forbidden"): self.archive(draft)
            user = backend.compose_draft_user(self.session)
            self.conn.execute(f"UPDATE official_document_compose_drafts SET {field}=? WHERE id=?", (user["id"] if field == "applicant_id" else user["company_id"], draft["id"]))
        for payload in ({"archived": "true", "expected_revision": 1}, {"archived": True, "expected_revision": 0}, {"archived": True, "expected_revision": True}):
            with self.assertRaisesRegex(ValueError, "archive_request_invalid"): backend.archive_compose_draft(draft["id"], payload, self.session, self.conn)

    def test_formal_created_after_archive_remains_visible_and_cannot_restore_cloud(self):
        draft = self.private()
        archived = self.archive(draft)
        formal = self.create(id=draft["id"])
        rows = self.catalog()["items"]
        self.assertIn(formal["id"], [r["id"] for r in rows])
        self.assertFalse(next(r for r in rows if r["id"] == formal["id"])["can_archive"])
        self.assertEqual(0, self.catalog(archived=1)["total"])
        with self.assertRaisesRegex(ValueError, "archive_private_only"): self.archive(archived, False)
        self.assertEqual(formal["dispatch_no"], backend.official_document_row(self.conn, formal["id"])["dispatch_no"])

    def test_archived_cursor_is_scoped_and_private_paging_is_bounded(self):
        for _ in range(4): self.archive(self.private())
        page = self.catalog(archived=1, page_size=2)
        self.assertEqual(4, page["total"])
        self.assertEqual(2, len(page["items"]))
        with self.assertRaisesRegex(ValueError, "cursor_invalid"): self.catalog(cursor=page["next_cursor"])
        self.assertEqual(2, len(self.catalog(archived=1, page_size=2, cursor=page["next_cursor"])["items"]))

    def test_hosted_route_uses_only_server_actor_and_exact_rpc(self):
        draft = self.private()
        with mock.patch.object(backend, "supabase_request", return_value={"id": draft["id"], "revision": 2, "snapshot_json": draft["snapshot"], "updated_at": "now", "archived": True}) as request:
            backend.archive_compose_draft(draft["id"], {"expected_revision": 1, "archived": True, "applicant_id": "OTHER"}, self.session)
        self.assertEqual("rpc/edoc_archive_private_compose_draft", request.call_args.args[1])
        self.assertEqual(backend.compose_draft_user(self.session)["id"], request.call_args.args[2]["p_applicant_id"])

    def test_shared_forward_matches_and_is_backend_only(self):
        self.assertIn("edoc_archive_private_compose_draft", backend.EDOC_READINESS_REQUIRED_RPC_NAMES)
        self.assertEqual(render_shared_forward().rstrip(), (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text().rstrip())
        self.assertIn(SOURCE, load_manifest())
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        self.assertIn("security invoker set search_path=''", source)
        self.assertIn("for update", source)
        self.assertIn("from public,anon,authenticated", source)

    def test_cutover_inventory_and_exact_guards_include_private_archive(self):
        verification = ROOT / "supabase/verification"
        for name, schema in (("fresh_bootstrap_smoke.sql", "public"), ("shared_project_cutover_checks.sql", "edoc")):
            self.assertIn(render_cutover_gate(schema), (verification / name).read_text())
        shared = (verification / "shared_project_cutover_checks.sql").read_text()
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        names = sorted(load_manifest() + ["roles.sql"])
        self.assertIn(f"migration_ledger) = {len(names)}", shared)
        self.assertIn(sha256_text("\n".join(names)), shared)
        self.assertIn(f"file_name='{SOURCE}'", shared)
        self.assertIn(f"source_sha256='{sha256_text(source)}'", shared)
        self.assertIn(f"transformed_sha256='{sha256_text(transform_sql(source))}'", shared)
        signature = "('public.edoc_archive_private_compose_draft(text,text,text,integer,boolean)')"
        self.assertEqual(3, (verification / "production_cutover_checks.sql").read_text().count(signature))
        self.assertEqual(2, (verification / "service_role_data_api_grant_smoke.sql").read_text().count(signature))


if __name__ == "__main__": unittest.main()
