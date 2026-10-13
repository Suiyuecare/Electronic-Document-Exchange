"""Native120 database behavior in disposable loopback-only PostgreSQL databases."""
import concurrent.futures
import os
import re
import unittest

import seal_scan_20261013 as native
import seal_scan_exceptions as original
from tests import test_seal_scan_exceptions_postgres as previous_fixture
from tests import test_compose_output_postgres as fixture
from tools import seal_native120_forward as forward

ENTITIES = {"CO-007": "E7", "FINCO-AE264D87483E": "E9", "FINCO-D7FAD93DE9AE": "E8"}


@unittest.skipUnless(fixture.PORT, "isolated PostgreSQL gate not enabled")
class Native120PostgresTest(previous_fixture.ApprovedScanPostgresTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Seed only de-identified directory metadata; no staff JWT or artwork.
        for company, entity in ENTITIES.items():
            cls.pg.execute("INSERT INTO companies(id,name,status,source_system,finance_entity_id) VALUES (%s,'Synthetic native120 owner','active','finance',%s)", (company, entity))
        for row in native._ROWS:
            if row[3:5] == ("official_seal", "small_seal"):
                continue  # The migration must create these two exact slots.
            cls.pg.execute("INSERT INTO company_seals(id,company_id,seal_name,seal_category,seal_size_type,is_active) VALUES (%s,%s,'Synthetic native120 slot',%s,%s,true)", (row[2], row[1], row[3], row[4]))
        cls.pg.execute(f"DROP TABLE {cls.namespace}.approved_native120_scan_import_batches")
        migration = fixture.ROOT / ("supabase/shared-project-migrations" if cls.namespace == "edoc" else "supabase/migrations") / (forward.SHARED if cls.namespace == "edoc" else forward.SOURCE)
        cls.pg.execute("SET ROLE postgres")
        try:
            cls.pg.execute(migration.read_text())
        finally:
            cls.pg.execute("RESET ROLE")
        # The generic fixture builds historical functions as the local cluster
        # user. Match hosted migration ownership explicitly before strict gates;
        # never weaken the production postgres-owner assertion for a fixture.
        for signature in (
            f"edoc_company_seal_file_dimensions_are_valid({forward.SIGNATURE})",
            "edoc_create_company_seal_file_version(text,text,text,text,text,text,bigint,text,integer,integer,numeric,numeric,numeric,text,text,text,text,text,text)",
            "edoc_set_current_company_seal_file(text,text,text,text)",
            "edoc_enforce_company_seal_position_dimensions()",
        ):
            cls.pg.execute(f"ALTER FUNCTION {cls.namespace}.{signature} OWNER TO postgres")
        cls.new_migration = migration

    def native_args(self, row, *, key="b" * 64, **overrides):
        digest = row[0]
        object_id = "FILE-APPROVED-" + digest
        values = dict(seal=row[2], object=object_id, file="SFILE-APPROVED-" + digest,
                      path=f"seal-vault/seals/{row[2]}/SEAL-VAULT/{object_id}.png",
                      name=digest + ".png", size=100, sha=digest, pw=row[5], ph=row[6],
                      ratio=row[5] / row[6], mw=row[7], mh=row[8],
                      engine="synthetic-fixture-engine", signature="synthetic-fixture-clean",
                      source=native.SOURCE_SHA256, key=key)
        values.update(overrides)
        return tuple(values[name] for name in ("seal", "object", "file", "path", "name", "size", "sha", "pw", "ph", "ratio", "mw", "mh", "engine", "signature", "source", "key"))

    def native_call(self, row, *, key="b" * 64, **overrides):
        casts = forward.RPC_SIGNATURE.split(",")
        query = f"SELECT {self.namespace}.edoc_import_approved_native120_scan_file(" + ",".join("%s::" + cast for cast in casts) + ")"
        return self.as_role(self.backend_role, query, self.native_args(row, key=key, **overrides))[0][0]

    def open_native(self, *, key="b" * 64, until=600, since=-1):
        self.pg.execute("INSERT INTO approved_native120_scan_import_batches(batch_id,source_pdf_sha256,key_sha256,started_at_epoch,expires_at_epoch,status) VALUES (%s,%s,%s,floor(extract(epoch from clock_timestamp()))::bigint+%s,floor(extract(epoch from clock_timestamp()))::bigint+%s,'open')", (native.POLICY, native.SOURCE_SHA256, key, since, until))

    def dimension_check(self, row, *, helper="edoc_approved_native120_scan_dimensions_are_valid", **overrides):
        values = [row[2], row[1], row[3], row[4], row[0], row[5], row[6], row[5] / row[6], row[7], row[8], native.POLICY, True]
        fields = ("seal", "company", "category", "size", "sha", "pw", "ph", "ratio", "mw", "mh", "policy", "valid")
        for name, value in overrides.items():
            values[fields.index(name)] = value
        query = f"SELECT {self.namespace}.{helper}(" + ",".join("%s::" + cast for cast in forward.SIGNATURE.split(",")) + ")"
        return self.as_role(self.backend_role, query, values)[0][0]

    def test_native_exact_source_fails_every_cross_owner_and_rescale_attempt(self):
        for row in native._ROWS:
            self.assertTrue(self.dimension_check(row))
            self.assertTrue(self.dimension_check(row, sha=row[0].upper()))
            self.assertTrue(self.dimension_check(row, helper="edoc_company_seal_file_dimensions_are_valid"))
            for overrides in ({"company": "CO-008"}, {"seal": "OTHER"}, {"category": "general_seal"},
                              {"size": "single_seal"}, {"sha": "f" * 64}, {"pw": row[5] + 1},
                              {"ph": row[6] + 1}, {"ratio": 2}, {"mw": row[7] + .001},
                              {"mh": row[8] + .001}, {"valid": False}, {"policy": original.POLICY}):
                self.assertFalse(self.dimension_check(row, **overrides))
                self.assertFalse(self.dimension_check(row, helper="edoc_company_seal_file_dimensions_are_valid", **overrides))
            self.assertFalse(self.pg.execute(f"SELECT {self.namespace}.edoc_company_seal_dimensions_are_valid(%s::text,%s::integer,%s::integer,%s::numeric,%s::numeric,%s::numeric,%s::text,true)", (row[4], row[5], row[6], row[5] / row[6], row[7], row[8], native.POLICY)).fetchone()[0])
        # An exception-policy string cannot be attached to generic 250-DPI bytes.
        self.assertFalse(self.dimension_check(native._ROWS[0], helper="edoc_company_seal_file_dimensions_are_valid", sha="a" * 64, pw=320, ph=320, ratio=1, mw=30, mh=30))

    def test_small_slots_exact_and_no_permit_or_policy_created_by_migration(self):
        for row in native._ROWS:
            slot = self.pg.execute("SELECT company_id,seal_category,seal_size_type,is_active FROM company_seals WHERE id=%s", (row[2],)).fetchone()
            self.assertEqual(slot, (row[1], row[3], row[4], True))
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM approved_native120_scan_import_batches").fetchone()[0])
        self.assertEqual(0, self.pg.execute("SELECT count(*) FROM company_seal_policies WHERE company_id=ANY(%s)", (list(ENTITIES),)).fetchone()[0])

    def test_six_imports_system_receipts_preserve_old_completed_permit_and_close(self):
        with self.pg.transaction():
            self.pg.execute("INSERT INTO approved_original_scan_import_batches(batch_id,source_pdf_sha256,key_sha256,started_at_epoch,expires_at_epoch,status,completed_file_count) VALUES (%s,%s,%s,1,100,'completed',22)", (original.POLICY, original.SOURCE_SHA256, "a" * 64))
            old = self.pg.execute("SELECT * FROM approved_original_scan_import_batches").fetchone()
            self.open_native()
            for index, row in enumerate(native._ROWS):
                result = self.native_call(row)
                self.assertEqual(index + 1, result["completed_file_count"])
                self.assertEqual(result["file"]["uploaded_by"], "system:codex-operator-import")
                self.assertEqual(result["file"]["dimension_policy_version"], native.POLICY)
                self.assertEqual((row[7], row[8]), (result["file"]["render_width_mm"], result["file"]["render_height_mm"]))
                audit = self.pg.execute("SELECT actor,action,target_id FROM audit_logs WHERE id=%s", ("AUD-IMPORT-" + "b" * 64 + "-" + row[0],)).fetchone()
                self.assertEqual(audit, ("system:codex-operator-import", "operator_import_native120_scan", result["file"]["id"]))
                if index == 0:
                    self.assertEqual(self.native_call(row)["import_status"], "already_registered")
                    self.assertEqual(1, self.pg.execute("SELECT count(*) FROM company_seal_files WHERE seal_id=%s", (row[2],)).fetchone()[0])
                self.pg.execute("INSERT INTO official_document_stamp_positions(id,request_id,seal_id,width,height,locked_seal_file_id,locked_seal_sha256,locked_render_width_pt,locked_render_height_pt,locked_dimension_policy_version) VALUES (%s,'SYNTHETIC',%s,%s,%s,%s,%s,%s,%s,%s)", (f"POS-NATIVE-{index}", row[2], row[7] * 72 / 25.4, row[8] * 72 / 25.4, result["file"]["id"], row[0], row[7] * 72 / 25.4, row[8] * 72 / 25.4, native.POLICY))
            self.assertEqual(("completed", 6), self.pg.execute("SELECT status,completed_file_count FROM approved_native120_scan_import_batches").fetchone())
            self.assertEqual(old, self.pg.execute("SELECT * FROM approved_original_scan_import_batches").fetchone())
            with self.assertRaisesRegex(self.psycopg.Error, "permit_closed"):
                self.native_call(native._ROWS[0])
            raise self.psycopg.Rollback()

    def test_native_roles_closed_and_permit_backend_read_only(self):
        signature = f"{self.namespace}.edoc_import_approved_native120_scan_file({forward.RPC_SIGNATURE})"
        row = self.pg.execute("SELECT prosecdef,provolatile,proconfig,pg_get_userbyid(proowner) FROM pg_proc WHERE oid=%s::regprocedure", (signature,)).fetchone()
        self.assertEqual(row[:2], (True, "v"))
        self.assertIn('search_path=""', row[2])
        self.assertIn("lock_timeout=5s", row[2])
        self.assertEqual(row[3], "postgres")
        table = f"{self.namespace}.approved_native120_scan_import_batches"
        for role in ("anon", "authenticated", "authenticator", *(('service_role',) if self.namespace == "edoc" else ())):
            self.assertFalse(self.pg.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)).fetchone()[0])
            self.assertFalse(self.pg.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')", (role, table)).fetchone()[0])
        self.assertTrue(self.pg.execute("SELECT has_table_privilege(%s,%s,'SELECT')", (self.backend_role, table)).fetchone()[0])
        self.assertFalse(self.pg.execute("SELECT has_table_privilege(%s,%s,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')", (self.backend_role, table)).fetchone()[0])
        for operation in (f"INSERT INTO {table}(batch_id) VALUES ('NO')", f"UPDATE {table} SET status='open'", f"DELETE FROM {table}"):
            with self.assertRaises(self.psycopg.Error):
                self.as_role(self.backend_role, operation)

    def test_native_strict_cutover_gate_rejects_permission_source_constraint_and_trigger_drift(self):
        gate = forward.gate_sql(self.namespace)
        self.pg.execute(gate)
        table = f"{self.namespace}.approved_native120_scan_import_batches"
        signature = f"{self.namespace}.edoc_import_approved_native120_scan_file({forward.RPC_SIGNATURE})"
        helper = f"{self.namespace}.edoc_approved_native120_scan_dimensions_are_valid({forward.SIGNATURE})"
        changes = (
            f"GRANT UPDATE ON {table} TO {self.backend_role}",
            f"GRANT SELECT ON {table} TO anon",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY unexpected_native_policy ON {table} FOR SELECT TO authenticated USING (true)",
            f"ALTER TABLE {table} DROP CONSTRAINT approved_native120_scan_import_batches_check",
            f"GRANT EXECUTE ON FUNCTION {signature} TO authenticated",
            f"ALTER FUNCTION {signature} RESET lock_timeout",
            f"ALTER FUNCTION {signature} SECURITY INVOKER",
            f"ALTER FUNCTION {helper} VOLATILE",
            f"ALTER TABLE {self.namespace}.company_seal_files DISABLE TRIGGER edoc_approved_native120_scan_file",
            f"CREATE OR REPLACE FUNCTION {helper.replace(forward.SIGNATURE,forward.PARAMS)} RETURNS boolean LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path='' AS 'SELECT true'",
        )
        for change in changes:
            with self.subTest(change=change), self.pg.transaction():
                self.pg.execute(change)
                with self.assertRaisesRegex(self.psycopg.Error, "native120_scan_import"):
                    with self.pg.transaction():
                        self.pg.execute(gate)
                raise self.psycopg.Rollback()
        self.pg.execute(gate)

    def test_small_slot_seed_conflicts_and_partial_changes_roll_back(self):
        slots = re.search(r"do \$native120_small_slots\$.*?end \$native120_small_slots\$;", forward.source_sql(), re.S).group(0)
        if self.namespace == "edoc":
            slots = forward.transform_sql(slots)
        row = native._ROWS[3]
        for field, value in (("company_id", "CO-007"), ("seal_category", "general_seal"), ("seal_size_type", "large_seal"), ("is_active", False)):
            with self.subTest(field=field), self.pg.transaction():
                self.pg.execute(f"UPDATE company_seals SET {field}=%s WHERE id=%s", (value, row[2]))
                with self.assertRaisesRegex(self.psycopg.Error, "small_slot_conflict"):
                    with self.pg.transaction():
                        self.pg.execute(slots)
                raise self.psycopg.Rollback()
        for field, value in (("status", "inactive"), ("source_system", "legacy_superseded"), ("finance_entity_id", "E8")):
            with self.subTest(owner_field=field), self.pg.transaction():
                self.pg.execute(f"UPDATE companies SET {field}=%s WHERE id=%s", (value, row[1]))
                with self.assertRaisesRegex(self.psycopg.Error, "small_slot_owner_mismatch"):
                    with self.pg.transaction():
                        self.pg.execute(slots)
                raise self.psycopg.Rollback()
        with self.pg.transaction():
            first, second = native._ROWS[3], native._ROWS[5]
            self.pg.execute("DELETE FROM company_seals WHERE id=%s", (first[2],))
            self.pg.execute("UPDATE company_seals SET is_active=false WHERE id=%s", (second[2],))
            with self.assertRaisesRegex(self.psycopg.Error, "small_slot_conflict"):
                with self.pg.transaction():
                    self.pg.execute(slots)
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM company_seals WHERE id=%s", (first[2],)).fetchone()[0])
            raise self.psycopg.Rollback()

    def test_completed_count_requires_all_three_explicit_canonical_owner_policies(self):
        with self.pg.transaction():
            casts = ("text", "text", "text", "text", "text", "text", "bigint", "text", "integer", "integer", "numeric", "numeric", "numeric", "text", "text", "text", "text", "text", "text")
            query = f"SELECT {self.namespace}.edoc_create_company_seal_file_version(" + ",".join("%s::" + cast for cast in casts) + ")"
            for index, row in enumerate(native._ROWS):
                args = (f"NATIVE-CUST-OBJ-{index}", f"NATIVE-CUST-VER-{index}", row[2], f"seal-vault/seals/{row[2]}/SEAL-VAULT/synthetic.png", "synthetic.png", "image/png", 100, row[0], row[5], row[6], row[5] / row[6], row[7], row[8], native.POLICY, "synthetic-custodian", "synthetic-fixture-engine", "synthetic-fixture-clean", f"NATIVE-CUST-LOG-{index}", f"NATIVE-CUST-AUD-{index}")
                self.as_role(self.backend_role, query, args)
            self.open_native()
            for index, row in enumerate((native._ROWS[0], native._ROWS[2], native._ROWS[4])):
                result = self.native_call(row)
                self.assertEqual((index + 1) * 2, result["completed_file_count"])
                self.assertEqual("open" if index < 2 else "completed", result["batch_status"])
                self.assertEqual("synthetic-custodian", result["file"]["uploaded_by"])
                self.assertEqual(f"NATIVE-CUST-VER-{index * 2}", result["file"]["id"])
            raise self.psycopg.Rollback()

    def test_new_permit_future_expired_revoked_and_max_duration_deny(self):
        for since, until, status in ((50, 600, "open"), (-600, -1, "open"), (-1, 600, "revoked")):
            with self.subTest(status=status, until=until), self.pg.transaction():
                self.open_native(since=since, until=until)
                self.pg.execute("UPDATE approved_native120_scan_import_batches SET status=%s", (status,))
                with self.assertRaisesRegex(self.psycopg.Error, "permit_closed"):
                    self.native_call(native._ROWS[0])
                raise self.psycopg.Rollback()
        with self.assertRaises(self.psycopg.Error), self.pg.transaction():
            self.open_native(since=-1, until=3601)

    def test_shared_forward_exact_ledger_replay_and_prerequisite_drift_fail_closed(self):
        if self.namespace != "edoc":
            return
        source = forward.source_sql()
        shared = forward.shared_sql(source)
        before = self.pg.execute("SELECT source_sha256,transformed_sha256 FROM edoc_private.shared_project_migration_ledger WHERE file_name=%s", (forward.SOURCE,)).fetchone()
        self.pg.execute(shared)
        self.assertEqual(before, self.pg.execute("SELECT source_sha256,transformed_sha256 FROM edoc_private.shared_project_migration_ledger WHERE file_name=%s", (forward.SOURCE,)).fetchone())
        # Exercise the actual DO block without its explicit transaction wrapper,
        # inside rollback-only fixture transactions; no hosted ledger writes.
        body = re.search(r"do \$native120_scan_forward\$.*?end \$native120_scan_forward\$;", shared, re.S).group(0)
        for name, column, error in ((forward.SOURCE, "source_sha256", "hash_mismatch"), (forward.SOURCE, "transformed_sha256", "hash_mismatch"), (forward.PREREQUISITE, "source_sha256", "prerequisite_missing"), (forward.PREREQUISITE, "transformed_sha256", "prerequisite_missing")):
            with self.subTest(column=column, file=name), self.pg.transaction():
                self.pg.execute(f"UPDATE edoc_private.shared_project_migration_ledger SET {column}=%s WHERE file_name=%s", ("f" * 64, name))
                with self.assertRaisesRegex(self.psycopg.Error, error):
                    with self.pg.transaction():
                        self.pg.execute(body)
                raise self.psycopg.Rollback()

    def test_bad_metadata_source_av_and_noncanonical_owner_fail_atomically(self):
        with self.pg.transaction():
            self.open_native()
            row = native._ROWS[0]
            for overrides in ({"source": original.SOURCE_SHA256}, {"key": "c" * 64},
                              {"sha": "a" * 64}, {"pw": row[5] + 1}, {"mw": row[7] + .001},
                              {"file": "OTHER"}, {"object": "OTHER"}, {"path": "public/OTHER"},
                              {"name": "other.png"}, {"engine": ""}, {"signature": ""}):
                with self.assertRaises(self.psycopg.Error):
                    self.native_call(row, **overrides)
            for field, value in (("status", "inactive"), ("source_system", "legacy_superseded"), ("finance_entity_id", "E8")):
                with self.pg.transaction():
                    self.pg.execute(f"UPDATE companies SET {field}=%s WHERE id=%s", (value, row[1]))
                    with self.assertRaisesRegex(self.psycopg.Error, "finance_linked"):
                        self.native_call(row)
                    raise self.psycopg.Rollback()
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM company_seal_files WHERE seal_id=%s", (row[2],)).fetchone()[0])
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM company_seal_policies WHERE company_id=ANY(%s)", (list(ENTITIES),)).fetchone()[0])
            raise self.psycopg.Rollback()

    def test_policy_conflict_and_different_current_are_never_overwritten(self):
        with self.pg.transaction():
            self.open_native()
            row = native._ROWS[0]
            self.as_role(self.backend_role, f"SELECT {self.namespace}.edoc_set_company_seal_policy(%s,'institution','synthetic-custodian')", (row[1],))
            with self.assertRaisesRegex(self.psycopg.Error, "owner_policy_conflict"):
                self.native_call(row)
            self.pg.execute("DELETE FROM company_seal_policies WHERE company_id=%s", (row[1],))
            self.pg.execute("INSERT INTO file_objects(id,sha256,size_bytes,mime_type,storage_key,bucket,scan_status) VALUES ('OTHER-OBJECT',%s,100,'image/png','private/other','edoc-seal-vault','clean')", ("f" * 64,))
            self.pg.execute("INSERT INTO company_seal_files(id,seal_id,file_object_id,file_storage_key,file_name,file_mime_type,file_size,file_hash,pixel_width,pixel_height,source_aspect_ratio,render_width_mm,render_height_mm,dimension_policy_version,dimension_validated,version,is_current,uploaded_by) VALUES ('OTHER-VERSION',%s,'OTHER-OBJECT','private/other','other.png','image/png',100,%s,320,320,1,30,30,'institution-seal-v2-calibrated',true,1,true,'synthetic-custodian')", (row[2], "f" * 64))
            with self.assertRaisesRegex(self.psycopg.Error, "current_conflict"):
                self.native_call(row)
            self.assertEqual([("OTHER-VERSION", True, "synthetic-custodian")], self.pg.execute("SELECT id,is_current,uploaded_by FROM company_seal_files WHERE seal_id=%s", (row[2],)).fetchall())
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM company_seal_policies WHERE company_id=%s", (row[1],)).fetchone()[0])
            raise self.psycopg.Rollback()

    def test_same_current_requires_clean_backing_and_keeps_original_actor(self):
        with self.pg.transaction():
            self.open_native()
            row = native._ROWS[0]
            result = self.native_call(row)
            self.pg.execute("UPDATE company_seal_files SET uploaded_by='synthetic-custodian' WHERE id=%s", (result["file"]["id"],))
            self.pg.execute("UPDATE company_seal_policies SET owner_kind='unclassified' WHERE company_id=%s", (row[1],))
            again = self.native_call(row)
            self.assertEqual(again["file"]["uploaded_by"], "synthetic-custodian")
            self.assertEqual(again["file"]["id"], result["file"]["id"])
            self.assertEqual("company", self.pg.execute("SELECT owner_kind FROM company_seal_policies WHERE company_id=%s", (row[1],)).fetchone()[0])
            for field, value in (("scan_status", "pending"), ("sha256", "a" * 64), ("bucket", "public"), ("storage_key", "other"), ("mime_type", "image/jpeg"), ("size_bytes", 101)):
                with self.pg.transaction():
                    self.pg.execute(f"UPDATE file_objects SET {field}=%s WHERE id=%s", (value, result["file"]["file_object_id"]))
                    with self.assertRaisesRegex(self.psycopg.Error, "current_conflict"):
                        self.native_call(row)
                    raise self.psycopg.Rollback()
            raise self.psycopg.Rollback()

    def test_native_expiry_mid_audit_rolls_back_file_policy_and_receipt(self):
        with self.pg.transaction():
            self.open_native(until=1)
            row = native._ROWS[0]
            self.pg.execute(f"CREATE FUNCTION {self.namespace}.fixture_slow_native_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='operator_import_native120_scan' THEN PERFORM pg_sleep(2); END IF; RETURN NEW; END $$")
            self.pg.execute(f"CREATE TRIGGER fixture_slow_native_audit BEFORE INSERT ON {self.namespace}.audit_logs FOR EACH ROW EXECUTE FUNCTION {self.namespace}.fixture_slow_native_audit()")
            with self.assertRaisesRegex(self.psycopg.Error, "permit_closed"):
                self.native_call(row)
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM company_seal_files WHERE seal_id=%s", (row[2],)).fetchone()[0])
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM company_seal_policies WHERE company_id=%s", (row[1],)).fetchone()[0])
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM audit_logs WHERE action='operator_import_native120_scan'").fetchone()[0])
            raise self.psycopg.Rollback()

    def test_native_batch_lock_wait_uses_actual_clock(self):
        row = native._ROWS[0]
        self.open_native(until=1)
        query = f"SELECT {self.namespace}.edoc_import_approved_native120_scan_file(" + ",".join("%s::" + cast for cast in forward.RPC_SIGNATURE.split(",")) + ")"
        def waiting_request():
            with self.psycopg.connect(host="127.0.0.1", port=int(fixture.PORT), user=os.getenv("EDOC_TEST_PG_USER", "seniorlifepr"), dbname=self.dbname, autocommit=True) as conn:
                conn.execute(f"SET ROLE {self.backend_role}")
                try:
                    conn.execute(query, self.native_args(row))
                except self.psycopg.Error as error:
                    return str(error)
                return "unexpected_success"
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with self.pg.transaction():
                    self.pg.execute("SELECT * FROM approved_native120_scan_import_batches FOR UPDATE")
                    future = pool.submit(waiting_request)
                    self.pg.execute("SELECT pg_sleep(2)")
                self.assertIn("permit_closed", future.result(timeout=5))
            self.assertEqual(0, self.pg.execute("SELECT count(*) FROM company_seal_files WHERE seal_id=%s", (row[2],)).fetchone()[0])
        finally:
            self.pg.execute("DELETE FROM approved_native120_scan_import_batches")


class SharedNative120PostgresTest(Native120PostgresTest):
    namespace = "edoc"
    backend_role = "edoc_backend"


if __name__ == "__main__":
    unittest.main()
