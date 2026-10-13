"""Disposable PostgreSQL tests; no production, artwork or government access."""
import unittest
import concurrent.futures
import os
import seal_scan_exceptions as scan
from tests.test_explicit_seal_policy_postgres import ExplicitSealPolicyPostgresTest
from tests import test_compose_output_postgres as fixture
from tools.seal_scan_exception_forward import SOURCE, SHARED, PREREQUISITE


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL gate not enabled")
class ApprovedScanPostgresTest(ExplicitSealPolicyPostgresTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The generic fixture inventories every migration's table columns;
        # remove only its unconfigured placeholder so this DDL is exercised.
        cls.pg.execute(f"DROP TABLE {cls.namespace}.approved_original_scan_import_batches")
        if cls.namespace == "edoc":
            cls.pg.execute("INSERT INTO edoc_private.shared_project_migration_ledger(file_name) VALUES (%s) ON CONFLICT DO NOTHING",(PREREQUISITE,))
            cls.pg.execute((fixture.ROOT/"supabase/shared-project-migrations"/SHARED).read_text())
        else:
            cls.pg.execute((fixture.ROOT/"supabase/migrations"/SOURCE).read_text())

    def check(self, values, *, digest=None, seal_id=None, company=None, category=None, width=None, mm=None):
        r=values
        args=(seal_id or r[2],company or r[1],category or r[3],r[4],digest or r[0],width or r[5],r[6],r[5]/r[6],mm or r[7],r[8],scan.POLICY,True)
        casts=("text","text","text","text","text","integer","integer","numeric","numeric","numeric","text","boolean")
        query=f"SELECT {self.namespace}.edoc_approved_original_scan_dimensions_are_valid("+",".join("%s::"+t for t in casts)+")"
        return self.as_role(self.backend_role,query,args)[0][0]

    def test_approved_exact_metadata_and_unmodified_generic_250dpi_contract(self):
        for r in scan._ROWS:
            self.assertTrue(self.check(r))
            self.assertTrue(self.check(r,digest=r[0].upper()))
            for override in ({"digest":"f"*64},{"seal_id":"OTHER"},{"company":"OTHER"},{"category":"general_seal"},{"width":r[5]+1},{"mm":r[7]+.001}):
                self.assertFalse(self.check(r,**override))
            self.assertFalse(self.pg.execute(f"SELECT {self.namespace}.edoc_company_seal_dimensions_are_valid(%s::text,%s::integer,%s::integer,%s::numeric,%s::numeric,%s::numeric,%s::text,true)",(r[4],r[5],r[6],r[5]/r[6],r[7],r[8],scan.POLICY)).fetchone()[0])

    def test_helper_is_invoker_and_anonymous_cannot_execute(self):
        signature=f"{self.namespace}.edoc_approved_original_scan_dimensions_are_valid(text,text,text,text,text,integer,integer,numeric,numeric,numeric,text,boolean)"
        self.assertFalse(self.pg.execute("SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure",(signature,)).fetchone()[0])
        for role in ("anon","authenticated","authenticator"):
            self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')",(role,signature)).fetchone()[0])

    def test_atomic_rpc_current_and_file_trigger_bind_hash_slot_geometry(self):
        with self.pg.transaction():
            for index,r in enumerate(scan._ROWS):
                self.pg.execute("INSERT INTO companies(id,name,status,source_system,finance_entity_id) VALUES (%s,'Synthetic approved scan owner','active','finance','SYNTHETIC') ON CONFLICT DO NOTHING",(r[1],))
                self.pg.execute("INSERT INTO company_seals(id,company_id,seal_name,seal_category,seal_size_type,is_active) VALUES (%s,%s,'Synthetic approved slot',%s,%s,true)",(r[2],r[1],r[3],r[4]))
                casts=("text","text","text","text","text","text","bigint","text","integer","integer","numeric","numeric","numeric","text","text","text","text","text","text")
                query=f"SELECT {self.namespace}.edoc_create_company_seal_file_version("+",".join("%s::"+t for t in casts)+")"
                args=(f"OBJ-{index}",f"VER-{index}",r[2],f"seal-vault/seals/{r[2]}/SEAL-VAULT/synthetic.png","synthetic.png","image/png",100,r[0].upper(),r[5],r[6],r[5]/r[6],r[7],r[8],scan.POLICY,"system:isolated-policy-test","synthetic-test-engine","synthetic-clean",f"LOG-{index}",f"AUD-{index}")
                bad=(*args[:7],"0"*64,*args[8:])
                with self.assertRaisesRegex(self.psycopg.Error,"dimension_metadata_invalid"):
                    self.as_role(self.backend_role,query,bad)
                self.assertEqual(0,self.pg.execute("SELECT count(*) FROM file_objects WHERE id=%s",(args[0],)).fetchone()[0])
                result=self.as_role(self.backend_role,query,args)[0][0]
                self.assertEqual(result["file"]["render_width_mm"],r[7])
                self.assertEqual(result["file"]["render_height_mm"],r[8])
                self.assertTrue(result["file"]["is_current"])
                current=self.as_role(self.backend_role,f"SELECT {self.namespace}.edoc_set_current_company_seal_file(%s,%s,%s,%s)",(args[1],args[14],f"SET-{index}",f"SET-AUD-{index}"))[0][0]
                self.assertTrue(current["file"]["is_current"])
                with self.assertRaisesRegex(self.psycopg.Error,"approved_original_scan_metadata_invalid"):
                    with self.pg.transaction():
                        self.pg.execute("UPDATE company_seal_files SET render_width_mm=render_width_mm+0.01 WHERE id=%s",(args[1],))
            raise self.psycopg.Rollback()

    def operator_call(self,r,key="b"*64):
        digest=r[0]
        object_id="FILE-APPROVED-"+digest
        args=(r[2],object_id,"SFILE-APPROVED-"+digest,f"seal-vault/seals/{r[2]}/SEAL-VAULT/{object_id}.png",digest+".png",100,digest.upper(),r[5],r[6],r[5]/r[6],r[7],r[8],"synthetic-fixture-engine","synthetic-fixture-clean",scan.SOURCE_SHA256,key)
        casts=("text","text","text","text","text","bigint","text","integer","integer","numeric","numeric","numeric","text","text","text","text")
        query=f"SELECT {self.namespace}.edoc_import_approved_original_scan_file("+",".join("%s::"+t for t in casts)+")"
        return self.as_role(self.backend_role,query,args)[0][0]

    def seed_operator_slot(self,r):
        self.pg.execute("INSERT INTO companies(id,name,status,source_system,finance_entity_id) VALUES (%s,'Synthetic permit owner','active','finance','SYNTHETIC') ON CONFLICT DO NOTHING",(r[1],))
        self.pg.execute("INSERT INTO company_seals(id,company_id,seal_name,seal_category,seal_size_type,is_active) VALUES (%s,%s,'Synthetic permit slot',%s,%s,true)",(r[2],r[1],r[3],r[4]))

    def test_operator_rpc_is_system_audited_idempotent_and_closes_all_22(self):
        with self.pg.transaction():
            first=scan._ROWS[0]
            self.seed_operator_slot(first)
            with self.assertRaisesRegex(self.psycopg.Error,"permit_closed"):
                self.operator_call(first)
            self.pg.execute("INSERT INTO approved_original_scan_import_batches(batch_id,source_pdf_sha256,key_sha256,started_at_epoch,expires_at_epoch,status) VALUES (%s,%s,%s,floor(extract(epoch from clock_timestamp()))::bigint-1,floor(extract(epoch from clock_timestamp()))::bigint+600,'open')",(scan.POLICY,scan.SOURCE_SHA256,"b"*64))
            for index,r in enumerate(scan._ROWS):
                if index: self.seed_operator_slot(r)
                result=self.operator_call(r)
                self.assertEqual(result["file"]["uploaded_by"],"system:codex-operator-import")
                self.assertEqual(result["completed_file_count"],index+1)
                audit=self.pg.execute("SELECT actor,action,target_id FROM audit_logs WHERE id=%s",("AUD-IMPORT-"+"b"*64+"-"+r[0],)).fetchone()
                self.assertEqual(audit,("system:codex-operator-import","operator_import_original_scan",result["file"]["id"]))
                if index==0:
                    original_actor=result["file"]["uploaded_by"]
                    self.pg.execute("UPDATE company_seal_policies SET owner_kind='unclassified' WHERE company_id=%s",(r[1],))
                    again=self.operator_call(r)
                    self.assertEqual(again["import_status"],"already_registered")
                    self.assertEqual(again["file"]["version"],1)
                    self.assertEqual(again["file"]["uploaded_by"],original_actor)
                    self.assertEqual(self.pg.execute("SELECT owner_kind FROM company_seal_policies WHERE company_id=%s",(r[1],)).fetchone()[0],"company")
                    self.assertEqual(self.pg.execute("SELECT count(*) FROM company_seal_files WHERE seal_id=%s",(r[2],)).fetchone()[0],1)
                self.pg.execute("INSERT INTO official_document_stamp_positions(id,request_id,seal_id,width,height,locked_seal_file_id,locked_seal_sha256,locked_render_width_pt,locked_render_height_pt,locked_dimension_policy_version) VALUES (%s,'SYNTHETIC',%s,%s,%s,%s,%s,%s,%s,%s)",(f"POS-APPROVED-{index}",r[2],r[7]*72/25.4,r[8]*72/25.4,result["file"]["id"],r[0].upper(),r[7]*72/25.4,r[8]*72/25.4,scan.POLICY))
            self.assertEqual(result["batch_status"],"completed")
            with self.assertRaisesRegex(self.psycopg.Error,"permit_closed"):
                self.operator_call(first)
            self.assertEqual(self.pg.execute("SELECT status,completed_file_count FROM approved_original_scan_import_batches").fetchone(),("completed",22))
            raise self.psycopg.Rollback()

    def test_operator_permit_wrong_key_expiry_and_revocation_are_rejected(self):
        with self.pg.transaction():
            r=scan._ROWS[0]; self.seed_operator_slot(r)
            self.pg.execute("INSERT INTO approved_original_scan_import_batches(batch_id,source_pdf_sha256,key_sha256,started_at_epoch,expires_at_epoch,status) VALUES (%s,%s,%s,floor(extract(epoch from clock_timestamp()))::bigint-600,floor(extract(epoch from clock_timestamp()))::bigint+600,'open')",(scan.POLICY,scan.SOURCE_SHA256,"b"*64))
            with self.assertRaisesRegex(self.psycopg.Error,"permit_closed"): self.operator_call(r,"c"*64)
            self.pg.execute("UPDATE approved_original_scan_import_batches SET expires_at_epoch=floor(extract(epoch from clock_timestamp()))::bigint-1")
            with self.assertRaisesRegex(self.psycopg.Error,"permit_closed"): self.operator_call(r)
            self.pg.execute("UPDATE approved_original_scan_import_batches SET expires_at_epoch=floor(extract(epoch from clock_timestamp()))::bigint+600,status='revoked'")
            with self.assertRaisesRegex(self.psycopg.Error,"permit_closed"): self.operator_call(r)
            self.assertEqual(0,self.pg.execute("SELECT count(*) FROM company_seal_files WHERE seal_id=%s",(r[2],)).fetchone()[0])
            raise self.psycopg.Rollback()

    def test_expiry_during_internal_commit_rolls_back_files_policy_and_audit(self):
        with self.pg.transaction():
            r=scan._ROWS[0]; self.seed_operator_slot(r)
            self.pg.execute("INSERT INTO approved_original_scan_import_batches(batch_id,source_pdf_sha256,key_sha256,started_at_epoch,expires_at_epoch,status) VALUES (%s,%s,%s,floor(extract(epoch from clock_timestamp()))::bigint-1,floor(extract(epoch from clock_timestamp()))::bigint+1,'open')",(scan.POLICY,scan.SOURCE_SHA256,"b"*64))
            self.pg.execute(f"CREATE FUNCTION {self.namespace}.fixture_slow_operator_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='operator_import_original_scan' THEN PERFORM pg_sleep(2); END IF; RETURN NEW; END $$")
            self.pg.execute(f"CREATE TRIGGER fixture_slow_operator_audit BEFORE INSERT ON {self.namespace}.audit_logs FOR EACH ROW EXECUTE FUNCTION {self.namespace}.fixture_slow_operator_audit()")
            with self.assertRaisesRegex(self.psycopg.Error,"permit_closed"): self.operator_call(r)
            self.assertEqual(0,self.pg.execute("SELECT count(*) FROM company_seal_files WHERE seal_id=%s",(r[2],)).fetchone()[0])
            self.assertEqual(0,self.pg.execute("SELECT count(*) FROM company_seal_policies WHERE company_id=%s",(r[1],)).fetchone()[0])
            self.assertEqual(0,self.pg.execute("SELECT count(*) FROM audit_logs WHERE action='operator_import_original_scan'").fetchone()[0])
            raise self.psycopg.Rollback()

    def test_all_existing_custodian_files_do_not_close_until_all_six_owners_classified(self):
        with self.pg.transaction():
            casts=("text","text","text","text","text","text","bigint","text","integer","integer","numeric","numeric","numeric","text","text","text","text","text","text")
            query=f"SELECT {self.namespace}.edoc_create_company_seal_file_version("+",".join("%s::"+t for t in casts)+")"
            for index,r in enumerate(scan._ROWS):
                self.seed_operator_slot(r)
                args=(f"ORD-OBJ-{index}",f"ORD-VER-{index}",r[2],f"seal-vault/seals/{r[2]}/SEAL-VAULT/synthetic.png","synthetic.png","image/png",100,r[0].upper(),r[5],r[6],r[5]/r[6],r[7],r[8],scan.POLICY,"synthetic-custodian","synthetic-fixture-engine","synthetic-fixture-clean",f"ORD-LOG-{index}",f"ORD-AUD-{index}")
                self.as_role(self.backend_role,query,args)
                self.pg.execute("INSERT INTO company_seal_policies(id,company_id,owner_kind,updated_by) VALUES (%s,%s,'unclassified','synthetic-custodian') ON CONFLICT DO NOTHING",(r[1],r[1]))
            self.pg.execute("INSERT INTO approved_original_scan_import_batches(batch_id,source_pdf_sha256,key_sha256,started_at_epoch,expires_at_epoch,status) VALUES (%s,%s,%s,floor(extract(epoch from clock_timestamp()))::bigint-1,floor(extract(epoch from clock_timestamp()))::bigint+600,'open')",(scan.POLICY,scan.SOURCE_SHA256,"b"*64))
            for index,r in enumerate(scan._ROWS):
                result=self.operator_call(r)
                self.assertEqual(result["file"]["id"],f"ORD-VER-{index}")
                self.assertEqual(result["file"]["uploaded_by"],"synthetic-custodian")
                if index==0:
                    self.assertEqual(result["completed_file_count"],4)
                    self.assertEqual(result["batch_status"],"open")
                if result["batch_status"]=="completed": break
            self.assertEqual(result["completed_file_count"],22)
            self.assertEqual(self.pg.execute("SELECT count(*) FROM company_seal_policies WHERE owner_kind in ('company','institution')").fetchone()[0],6)
            raise self.psycopg.Rollback()

    def test_batch_lock_wait_rechecks_real_clock_and_refuses_expired_commit(self):
        r=scan._ROWS[0]
        self.seed_operator_slot(r)
        self.pg.execute("INSERT INTO approved_original_scan_import_batches(batch_id,source_pdf_sha256,key_sha256,started_at_epoch,expires_at_epoch,status) VALUES (%s,%s,%s,floor(extract(epoch from clock_timestamp()))::bigint-1,floor(extract(epoch from clock_timestamp()))::bigint+1,'open')",(scan.POLICY,scan.SOURCE_SHA256,"b"*64))
        digest=r[0]; object_id="FILE-APPROVED-"+digest
        args=(r[2],object_id,"SFILE-APPROVED-"+digest,f"seal-vault/seals/{r[2]}/SEAL-VAULT/{object_id}.png",digest+".png",100,digest.upper(),r[5],r[6],r[5]/r[6],r[7],r[8],"synthetic-fixture-engine","synthetic-fixture-clean",scan.SOURCE_SHA256,"b"*64)
        casts=("text","text","text","text","text","bigint","text","integer","integer","numeric","numeric","numeric","text","text","text","text")
        query=f"SELECT {self.namespace}.edoc_import_approved_original_scan_file("+",".join("%s::"+t for t in casts)+")"
        def waiting_request():
            with self.psycopg.connect(host="127.0.0.1",port=int(fixture.PORT),user=os.getenv("EDOC_TEST_PG_USER","seniorlifepr"),dbname=self.dbname,autocommit=True) as conn:
                conn.execute(f"SET ROLE {self.backend_role}")
                try: conn.execute(query,args)
                except self.psycopg.Error as error: return str(error)
                return "unexpected_success"
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with self.pg.transaction():
                    self.pg.execute("SELECT * FROM approved_original_scan_import_batches FOR UPDATE")
                    future=pool.submit(waiting_request)
                    self.pg.execute("SELECT pg_sleep(2)")
                self.assertIn("permit_closed",future.result(timeout=5))
            self.assertEqual(0,self.pg.execute("SELECT count(*) FROM company_seal_files WHERE seal_id=%s",(r[2],)).fetchone()[0])
        finally:
            self.pg.execute("DELETE FROM approved_original_scan_import_batches")
            self.pg.execute("DELETE FROM company_seals WHERE id=%s",(r[2],))

    def test_different_custodian_current_is_preserved_and_never_classified_or_replaced(self):
        with self.pg.transaction():
            r=scan._ROWS[0]; self.seed_operator_slot(r)
            casts=("text","text","text","text","text","text","bigint","text","integer","integer","numeric","numeric","numeric","text","text","text","text","text","text")
            query=f"SELECT {self.namespace}.edoc_create_company_seal_file_version("+",".join("%s::"+t for t in casts)+")"
            args=("DIFF-OBJ","DIFF-VER",r[2],f"seal-vault/seals/{r[2]}/SEAL-VAULT/different.png","different.png","image/png",100,"f"*64,320,320,1,30,30,"institution-seal-v2-calibrated","synthetic-custodian","synthetic-fixture-engine","synthetic-fixture-clean","DIFF-LOG","DIFF-AUD")
            self.as_role(self.backend_role,query,args)
            self.pg.execute("INSERT INTO approved_original_scan_import_batches(batch_id,source_pdf_sha256,key_sha256,started_at_epoch,expires_at_epoch,status) VALUES (%s,%s,%s,floor(extract(epoch from clock_timestamp()))::bigint-1,floor(extract(epoch from clock_timestamp()))::bigint+600,'open')",(scan.POLICY,scan.SOURCE_SHA256,"b"*64))
            with self.assertRaisesRegex(self.psycopg.Error,"current_conflict"): self.operator_call(r)
            self.assertEqual(self.pg.execute("SELECT id,is_current,uploaded_by FROM company_seal_files WHERE seal_id=%s",(r[2],)).fetchall(),[("DIFF-VER",True,"synthetic-custodian")])
            self.assertEqual(0,self.pg.execute("SELECT count(*) FROM company_seal_policies WHERE company_id=%s",(r[1],)).fetchone()[0])
            raise self.psycopg.Rollback()


class SharedApprovedScanPostgresTest(ApprovedScanPostgresTest):
    namespace="edoc"
    backend_role="edoc_backend"


if __name__ == "__main__": unittest.main()
