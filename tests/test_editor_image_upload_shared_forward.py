"""Real atomic RPCs on an opt-in, disposable loopback PostgreSQL database."""
import copy
import json
import unittest
from unittest.mock import patch

import backend
from tools.editor_image_upload_shared_forward import ROOT, SOURCE, FORWARD_NAME, render_shared_forward
from tools.shared_supabase_bootstrap import sha256_text, transform_sql
from tests import test_compose_output_postgres as pg_fixture
from tests import test_editor_pdf_upload_shared_forward as pdf_fixture
from tests import test_editor_conflict_copy as local_fixture
from tests.test_editor_placeholder_image_policy import image_bytes


class EditorImageSharedForwardTest(unittest.TestCase):
    def test_generated_forward_and_inventory(self):
        source = (ROOT / "supabase/migrations" / SOURCE).read_text()
        shared = (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()
        self.assertEqual(shared, render_shared_forward())
        self.assertIn(sha256_text(source), shared)
        self.assertIn(sha256_text(transform_sql(source)), shared)
        self.assertNotIn("public.", shared)
        self.assertIn(SOURCE, json.loads((ROOT / "supabase/verification/migration_manifest.json").read_text())["migrations"])
        self.assertIn("file_name='" + SOURCE + "'", (ROOT / "supabase/verification/shared_project_cutover_checks.sql").read_text())


@unittest.skipUnless(pg_fixture.PORT, "isolated PostgreSQL image RPC gate not enabled")
class EditorImageSharedPostgresTest(unittest.TestCase):
    namespace = "edoc"
    backend_role = "edoc_backend"
    cleanup = classmethod(pg_fixture.ComposeOutputPostgresTest.cleanup.__func__)

    @classmethod
    def setUpClass(cls):
        pg_fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("SET ROLE postgres")
        try:
            cls.pg.execute("DROP TABLE edoc.official_document_editor_storage_jobs")
            for name in ("20260827194500_promote_editor_tus_staging_to_immutable.sql", "20260911133603_editor_conflict_copy_atomic.sql", "20260913130517_editor_storage_v2_opaque_paths.sql"):
                cls.pg.execute(transform_sql((ROOT / "supabase/migrations" / name).read_text()))
            cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES (%s),(%s) ON CONFLICT DO NOTHING", ("20260913130517_editor_storage_v2_opaque_paths.sql", "20260922074613_configurable_official_workflows.sql"))
            cls.pg.execute(pdf_fixture.render_shared_forward())
            cls.pg.execute(render_shared_forward())
            cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute("RESET ROLE")
        # Match the shared bootstrap grants in this disposable fixture only.
        cls.pg.execute("GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA edoc TO edoc_backend")
        cls.pg.execute("CREATE POLICY fixture_backend_rls ON edoc.official_document_editor_storage_jobs TO edoc_backend USING (true) WITH CHECK (true)")
        cls.types = pg_fixture.canonical_column_types()

    def clean(self, table, row):
        return {key: None if value == "" and self.types.get((table,key)) in {"timestamp with time zone", "timestamp without time zone", "timestamptz", "date"}
                else bool(value) if value is not None and self.types.get((table,key)) == "boolean" else value
                for key,value in row.items()}

    def insert(self, table, row):
        self.pg.execute(f"INSERT INTO edoc.{table} SELECT * FROM jsonb_populate_record(NULL::edoc.{table}, %s::jsonb) ON CONFLICT DO NOTHING", (json.dumps(self.clean(table,row)),))

    def fixture(self):
        f = local_fixture.EditorConflictCopyTest()
        f.setUp(); self.addCleanup(f.tearDown)
        return f

    def seed(self, f, session, document_id):
        self.insert("companies", backend.official_company_row(f.conn,"CO-001"))
        self.insert("users", dict(f.conn.execute("SELECT * FROM users WHERE id=?",(session["user"]["id"],)).fetchone()))
        self.insert("official_documents", backend.official_document_row(f.conn,document_id))

    def rpc(self, name, payload):
        return self.pg.execute(f"SELECT edoc.{name}(%s::jsonb)",(json.dumps(payload),)).fetchone()[0]

    def test_finalize_png_not_scanned_is_atomic_idempotent_and_fail_closed(self):
        f = self.fixture(); session = f._session_for_user_id(f.applicant_ids[0])
        doc = backend.create_official_editor_draft(f.conn,{"company_id":"CO-001","title":"Synthetic image","document_category":"合作意向書"},session)
        data = image_bytes(); digest = backend.sha256_bytes(data)
        intent = backend.create_official_editor_upload_intent(f.conn,doc["id"],{"asset_kind":"image","file_name":"synthetic.png","mime_type":"image/png","size_bytes":len(data),"sha256":digest},session)
        backend.store_official_editor_local_upload(f.conn,doc["id"],intent["upload_id"],data,session,"image/png")
        pending = dict(f.conn.execute("SELECT * FROM official_document_editor_assets WHERE id=?",(intent["upload_id"],)).fetchone())
        base = dict(f.conn.execute("SELECT * FROM official_document_editor_revisions WHERE document_id=? ORDER BY revision_no DESC LIMIT 1",(doc["id"],)).fetchone())
        result = backend.finalize_official_editor_upload(f.conn,doc["id"],intent["upload_id"],{},session)
        asset = dict(f.conn.execute("SELECT * FROM official_document_editor_assets WHERE id=?",(intent["upload_id"],)).fetchone())
        file = dict(f.conn.execute("SELECT * FROM file_objects WHERE id=?",(asset["file_object_id"],)).fetchone())
        revision = dict(f.conn.execute("SELECT * FROM official_document_editor_revisions WHERE document_id=? ORDER BY revision_no DESC LIMIT 1",(doc["id"],)).fetchone())
        self.seed(f,session,doc["id"])
        self.insert("official_document_editor_revisions",base)
        pending["metadata_json"] = json.dumps({**json.loads(pending["metadata_json"]),"storage_key_version":2})
        pending.update(storage_bucket="edoc-private",storage_path=backend._supabase_editor_staging_storage_path(doc["id"],asset["id"],"image/png"))
        self.insert("official_document_editor_assets",pending)
        final_path = backend._supabase_editor_immutable_storage_path(doc["id"],pending,digest)
        stamp = backend.now()
        self.pg.execute("INSERT INTO edoc.official_document_editor_storage_jobs(id,asset_id,document_id,staging_bucket,staging_path,final_bucket,final_path,expected_sha256,expected_size_bytes,created_at,updated_at,token_expires_at) VALUES (%s,%s,%s,'edoc-private',%s,'edoc-private',%s,%s,%s,%s,%s,'2099-01-01T00:00:00')",("JOB-IMAGE",asset["id"],doc["id"],pending["storage_path"],final_path,digest,len(data),stamp,stamp))
        self.pg.execute("UPDATE edoc.official_document_editor_storage_jobs SET status='promoting',lease_token=%s,lease_expires_at='2099-01-01T00:00:00',attempt_count=1 WHERE id='JOB-IMAGE'",("A"*32,))
        file.update(storage_provider="supabase",bucket="edoc-private",storage_key=final_path,created_by=session["user"]["id"])
        asset["metadata_json"] = pending["metadata_json"]
        request = {"operation_id":"IMAGE-FINALIZE","document_id":doc["id"],"company_id":"CO-001","applicant_id":session["user"]["id"],"asset_id":asset["id"],
                   "expected_asset_status":pending["upload_status"],"expected_asset_sha256":digest,"expected_asset_size_bytes":len(data),
                   "expected_base_revision_id":base["id"],"expected_base_revision_no":base["revision_no"],
                   "file_object":self.clean("file_objects",file),"official_file":None,"asset_patch":asset,"revision":revision,
                   "approval_log":{"id":"IMAGE-FINALIZE","document_id":doc["id"],"actor_id":session["user"]["id"],"action":"finalize_editor_upload","created_at":stamp},
                   "audit_log":{"id":"IMAGE-AUDIT","target_id":doc["id"],"request_id":"IMAGE-FINALIZE","created_at":stamp}}
        for role in ("anon","authenticated","service_role"):
            with self.pg.transaction():
                self.pg.execute(f"SET LOCAL ROLE {role}")
                with self.assertRaises(self.psycopg.errors.InsufficientPrivilege), self.pg.transaction(): self.rpc("edoc_finalize_editor_asset_v2",request)
        for label, mutate in (
            ("false scanned", lambda p: p["file_object"].update(scan_engine="fake")),
            ("wrong MIME", lambda p: p["file_object"].update(mime_type="image/svg+xml")),
            ("wrong purpose", lambda p: p["file_object"].update(purpose="attachment")),
            ("preflight pending", lambda p: p["asset_patch"].update(preflight_status="pending")),
            ("hash mismatch", lambda p: p["file_object"].update(sha256="0"*64)),
        ):
            attempt = copy.deepcopy(request); mutate(attempt)
            with self.subTest(label=label), self.pg.transaction():
                self.pg.execute("SET LOCAL ROLE edoc_backend")
                with self.assertRaises(self.psycopg.Error), self.pg.transaction(): self.rpc("edoc_finalize_editor_asset_v2",attempt)
            self.assertIsNone(self.pg.execute("SELECT id FROM edoc.file_objects WHERE id=%s",(file["id"],)).fetchone())
            self.assertEqual(self.pg.execute("SELECT status FROM edoc.official_document_editor_storage_jobs WHERE id='JOB-IMAGE'").fetchone()[0],"promoting")
        with self.pg.transaction():
            self.pg.execute("SET LOCAL ROLE edoc_backend")
            first = self.rpc("edoc_finalize_editor_asset_v2",request)
            repeat = self.rpc("edoc_finalize_editor_asset_v2",request)
        self.assertFalse(first["idempotent"]); self.assertTrue(repeat["idempotent"])
        self.assertEqual(self.pg.execute("SELECT scan_status,preflight_status FROM edoc.official_document_editor_assets WHERE id=%s",(asset["id"],)).fetchone(),("not_scanned","passed"))
        self.assertEqual(self.pg.execute("SELECT scan_status,scan_engine,last_scan_at FROM edoc.file_objects WHERE id=%s",(file["id"],)).fetchone(),("not_scanned","",None))
        self.assertEqual(self.pg.execute("SELECT status FROM edoc.official_document_editor_storage_jobs WHERE id='JOB-IMAGE'").fetchone()[0],"committed")
        with self.assertRaisesRegex(self.psycopg.Error,"immutable"), self.pg.transaction():
            self.pg.execute("UPDATE edoc.official_document_editor_assets SET sha256=%s WHERE id=%s",("0"*64,asset["id"]))

    def test_conflict_copy_preserves_decoded_image_and_rejects_metadata_forgery(self):
        f = self.fixture(); session, source_id, payload = f.source()
        data = image_bytes("JPEG")
        intent = backend.create_official_editor_upload_intent(f.conn,source_id,{"asset_kind":"image","file_name":"synthetic.jpg","mime_type":"image/jpeg","size_bytes":len(data),"sha256":backend.sha256_bytes(data)},session)
        backend.store_official_editor_local_upload(f.conn,source_id,intent["upload_id"],data,session,"image/jpeg")
        finalized = backend.finalize_official_editor_upload(f.conn,source_id,intent["upload_id"],{},session)
        payload["state"] = finalized["editor_state"]
        payload["state"]["elements"] = [{"id":"synthetic-image","kind":"image","pageId":payload["state"]["pages"][0]["pageId"],"x":20,"y":20,"width":62,"height":46,"rotation":0,"opacity":1,"zIndex":1,"properties":{"assetId":intent["upload_id"],"nativeAspectRatio":31/23}}]
        captured = []; original = backend._editor_conflict_copy_bundle
        def capture(*args,**kwargs):
            result=original(*args,**kwargs);captured.append(copy.deepcopy(result));return result
        with patch.object(backend,"_editor_conflict_copy_bundle",side_effect=capture): backend.copy_official_editor_conflict(f.conn,source_id,payload,session)
        bundle = captured[0]; self.seed(f,session,source_id)
        for index,item in enumerate(bundle["file_objects"]):
            item["storage_provider"]="supabase";bundle["file_objects"][index]=self.clean("file_objects",item)
        for field,value in (("scan_engine","fake"),("mime_type","image/svg+xml"),("purpose","attachment"),("sha256","0"*64)):
            attempt=copy.deepcopy(bundle)
            file=next(item for item in attempt["file_objects"] if item["mime_type"]=="image/jpeg")
            file[field]=value
            with self.subTest(field=field),self.pg.transaction():
                self.pg.execute("SET LOCAL ROLE edoc_backend")
                with self.assertRaises(self.psycopg.Error),self.pg.transaction(): self.rpc("edoc_copy_editor_conflict",attempt)
            self.assertIsNone(self.pg.execute("SELECT id FROM edoc.official_documents WHERE id=%s",(bundle["document"]["id"],)).fetchone())
        with self.pg.transaction():
            self.pg.execute("SET LOCAL ROLE edoc_backend")
            first=self.rpc("edoc_copy_editor_conflict",bundle);second=self.rpc("edoc_copy_editor_conflict",bundle)
        self.assertFalse(first["idempotent"]);self.assertTrue(second["idempotent"])
        self.assertEqual(self.pg.execute("SELECT scan_status,preflight_status FROM edoc.official_document_editor_assets WHERE document_id=%s AND asset_kind='image'",(first["document_id"],)).fetchone(),("not_scanned","passed"))
        self.assertEqual(self.pg.execute("SELECT count(*) FROM edoc.official_document_editor_storage_jobs WHERE document_id=%s AND status='committed'",(first["document_id"],)).fetchone()[0],2)


if __name__ == "__main__": unittest.main()
