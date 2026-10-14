"""Actual disposable PostgreSQL tests; no production or government access."""
import unittest

from tests import test_compose_output_postgres as fixture
from tests.test_compose_output_postgres import transform_sql

SOURCE = "20261012114854_explicit_seal_owner_policy_and_continuous_geometry.sql"


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL gate not enabled")
class ExplicitSealPolicyPostgresTest(unittest.TestCase):
    namespace = "public"
    backend_role = "service_role"
    cleanup = classmethod(fixture.ComposeOutputPostgresTest.cleanup.__func__)

    @classmethod
    def setUpClass(cls):
        fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute("CREATE UNIQUE INDEX fixture_seal_ref_unique ON seal_reference_options(option_type,code)")
        sql = (fixture.ROOT / "supabase/migrations" / SOURCE).read_text()
        cls.pg.execute(sql if cls.namespace == "public" else transform_sql(sql))
        cls.pg.execute("UPDATE companies SET status='active',source_system='finance',finance_entity_id='SYNTHETIC-ENTITY' WHERE id='CO-COMPOSE'")
        cls.pg.execute(f"GRANT INSERT ON {cls.namespace}.seal_usage_logs,{cls.namespace}.audit_logs TO {cls.backend_role}")
        cls.pg.execute(f"GRANT SELECT ON {cls.namespace}.company_seals TO {cls.backend_role}")

    def as_role(self, role, sql, args=()):
        with self.pg.transaction():
            previous = self.pg.execute("SELECT current_user").fetchone()[0]
            self.pg.execute(f"SET LOCAL ROLE {role}")
            cursor = self.pg.execute(sql, args)
            result = cursor.fetchall() if cursor.description else []
            self.pg.execute(f"SET LOCAL ROLE {previous}")
            return result

    def test_policy_rpc_is_invoker_and_browser_denied(self):
        signature = f"{self.namespace}.edoc_set_company_seal_policy(text,text,text)"
        self.assertFalse(self.pg.execute("SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (signature,)).fetchone()[0])
        for role in ("anon", "authenticated"):
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.as_role(role, f"SELECT {self.namespace}.edoc_set_company_seal_policy('CO-COMPOSE','company','SYNTHETIC')")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                self.as_role(role, f"SELECT * FROM {self.namespace}.company_seal_policies")
        self.as_role(self.backend_role, f"SELECT {self.namespace}.edoc_set_company_seal_policy('CO-COMPOSE','company','SYNTHETIC')")
        self.assertEqual("company", self.pg.execute("SELECT owner_kind FROM company_seal_policies WHERE company_id='CO-COMPOSE'").fetchone()[0])
        self.assertEqual(1, self.pg.execute("SELECT count(*) FROM audit_logs WHERE action='classify_seal_owner'").fetchone()[0])
        self.assertFalse(self.pg.execute("SELECT has_table_privilege(%s,%s,'DELETE')", (self.backend_role, f"{self.namespace}.company_seal_policies")).fetchone()[0])

    def test_rectangular_and_legacy_geometry_are_not_conflated(self):
        def valid(size, width, height, physical_w, physical_h, policy):
            return self.pg.execute(f"SELECT {self.namespace}.edoc_company_seal_dimensions_are_valid(%s::text,%s::integer,%s::integer,%s::numeric,%s::numeric,%s::numeric,%s::text,true)", (size,width,height,width/height,physical_w,physical_h,policy)).fetchone()[0]
        self.assertTrue(valid("large_seal", 400, 1200, 20, 60, "official-seal-v1-calibrated"))
        self.assertTrue(valid("single_seal", 1000, 240, 50, 12, "continuous-seal-v1-calibrated"))
        self.assertTrue(valid("large_seal", 320, 320, 30, 30, "institution-seal-v2-calibrated"))
        self.assertTrue(valid("small_seal", 200, 200, 18, 18, "institution-seal-v1"))
        self.assertFalse(valid("large_seal", 400, 1200, 20, 60, "institution-seal-v2-calibrated"))
        self.assertFalse(valid("large_seal", 1000, 240, 50, 12, "continuous-seal-v1-calibrated"))
        self.assertFalse(valid("single_seal", 100, 24, 50, 12, "continuous-seal-v1-calibrated"))
        self.assertFalse(self.pg.execute(f"SELECT {self.namespace}.edoc_company_seal_dimensions_are_valid('single_seal',1,0,0,0,0,'continuous-seal-v1-calibrated',true)").fetchone()[0])
        self.assertFalse(self.pg.execute(f"SELECT {self.namespace}.edoc_company_seal_dimensions_are_valid('single_seal',null,null,null,null,null,'continuous-seal-v1-calibrated',true)").fetchone()[0])

    def test_trigger_category_policy_pair_without_exposing_trigger_as_rpc(self):
        self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (self.backend_role, f"{self.namespace}.edoc_enforce_seal_category_geometry()")).fetchone()[0])
        with self.pg.transaction():
            self.pg.execute("INSERT INTO company_seals(id,company_id,seal_name,seal_category,seal_size_type,is_active) VALUES ('SYNTH-CORP','CO-COMPOSE','Synthetic','establishment_seal','large_seal',true),('SYNTH-RECT','CO-COMPOSE','Synthetic','official_seal','large_seal',true)")
            self.pg.execute(f"GRANT INSERT ON {self.namespace}.company_seal_files TO {self.backend_role}")
            for seal in ("SYNTH-CORP", "SYNTH-RECT"):
                if seal == "SYNTH-CORP":
                    with self.assertRaisesRegex(self.psycopg.Error, "category_dimension_policy_mismatch"):
                        self.as_role(self.backend_role, "INSERT INTO company_seal_files(id,seal_id,dimension_policy_version,is_current) VALUES (%s,%s,'official-seal-v1-calibrated',false)", ("F-"+seal,seal))
                else:
                    self.as_role(self.backend_role, "INSERT INTO company_seal_files(id,seal_id,dimension_policy_version,is_current) VALUES (%s,%s,'official-seal-v1-calibrated',false)", ("F-"+seal,seal))
            raise self.psycopg.Rollback()

    def test_atomic_version_rpcs_accept_rectangles_but_reject_wrong_category(self):
        with self.pg.transaction():
            self.pg.execute("INSERT INTO company_seals(id,company_id,seal_name,seal_category,seal_size_type,is_active) VALUES ('SYNTH-RPC-CORP','CO-COMPOSE','Synthetic','establishment_seal','large_seal',true),('SYNTH-RPC-RECT','CO-COMPOSE','Synthetic','official_seal','large_seal',true)")
            signature = f"{self.namespace}.edoc_create_company_seal_file_version"
            casts = "::text,::text,::text,::text,::text,::text,::bigint,::text,::integer,::integer,::numeric,::numeric,::numeric,::text,::text,::text,::text,::text,::text".split(",")
            params = ",".join("%s"+cast for cast in casts)
            for identity in ("SYNTH-RPC-CORP", "SYNTH-RPC-RECT"):
                values = ("OBJECT-"+identity,"FILE-"+identity,identity,f"seal-vault/seals/{identity}/SEAL-VAULT/synthetic.png","synthetic.png","image/png",100,"a"*64,400,1200,400/1200,20,60,"official-seal-v1-calibrated","SYNTHETIC","test-decoder","test-clean","LOG-"+identity,"AUD-"+identity)
                if identity.endswith("CORP"):
                    with self.assertRaisesRegex(self.psycopg.Error,"category_dimension_policy_mismatch"):
                        self.as_role(self.backend_role,f"SELECT {signature}({params})",values)
                    self.assertEqual(0,self.pg.execute("SELECT count(*) FROM file_objects WHERE id=%s",("OBJECT-"+identity,)).fetchone()[0])
                else:
                    result = self.as_role(self.backend_role,f"SELECT {signature}({params})",values)[0][0]
                    self.assertEqual(result["file"]["dimension_policy_version"],"official-seal-v1-calibrated")
                    self.assertEqual(result["file"]["render_height_mm"],60)
                    current = self.as_role(self.backend_role,f"SELECT {self.namespace}.edoc_set_current_company_seal_file(%s,%s,%s,%s)",("FILE-"+identity,"SYNTHETIC","LOG-SET-"+identity,"AUD-SET-"+identity))[0][0]
                    self.assertTrue(current["file"]["is_current"])
                    with self.assertRaisesRegex(self.psycopg.Error,"category_locked_after_upload"):
                        with self.pg.transaction():
                            self.pg.execute("UPDATE company_seals SET seal_category='general_seal' WHERE id=%s",(identity,))
            raise self.psycopg.Rollback()


class SharedExplicitSealPolicyPostgresTest(ExplicitSealPolicyPostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"


if __name__ == "__main__":
    unittest.main()
