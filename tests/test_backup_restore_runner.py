import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("backup_restore_drill", Path(__file__).resolve().parents[1] / "scripts/backup_restore_drill.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class BackupRestoreRunnerTest(unittest.TestCase):
    def test_encrypted_archive_round_trip_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = runner.load_key(root / "key")
            source, encrypted, restored = (root / name for name in ("source", "encrypted", "restored"))
            source.write_bytes(b"synthetic document\x00" * 70000)
            runner.encrypt_file(source, encrypted, key)
            self.assertNotIn(b"synthetic document", encrypted.read_bytes())
            runner.decrypt_file(encrypted, restored, key)
            self.assertEqual(runner.digest_file(source), runner.digest_file(restored))
            data = bytearray(encrypted.read_bytes())
            data[len(data) // 2] ^= 1
            encrypted.write_bytes(data)
            with self.assertRaisesRegex(runner.DrillError, "authentication_failed"):
                runner.decrypt_file(encrypted, root / "tampered", key)
            self.assertFalse((root / "tampered").exists())

    def test_storage_restore_uses_bytes_and_rejects_same_count_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            object_id = "a" * 64
            (source / object_id).write_bytes(b"%PDF-1.4 synthetic fixture")
            objects = [{"archive_id": object_id, "sha256": runner.digest_file(source / object_id), "bytes": (source / object_id).stat().st_size}]
            report = runner.restore_storage(objects, source, root / "restored")
            self.assertEqual(report["object_count"], 1)
            self.assertTrue(report["hash_match"])
            (source / object_id).write_bytes(b"%PDF-1.4 corrupted fixture")
            with self.assertRaisesRegex(runner.DrillError, "backup_hash_mismatch"):
                runner.restore_storage(objects, source, root / "corrupted")

    def test_empty_storage_is_explicit_and_not_fabricated_sample_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = runner.restore_storage([], root, root / "restored")
            self.assertEqual(report["object_count"], 0)
            self.assertTrue(report["empty_source"])

    def test_refuses_shared_key_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_bytes(b"x" * 32)
            key.chmod(0o644)
            with self.assertRaisesRegex(runner.DrillError, "private_0600"):
                runner.load_key(key)

    def test_archive_path_traversal_is_rejected(self):
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with tarfile.open(root / "bad.tar", "w") as archive:
                info = tarfile.TarInfo("../escape")
                info.size = 4
                archive.addfile(info, io.BytesIO(b"nope"))
            with self.assertRaisesRegex(runner.DrillError, "member_invalid"):
                runner.unpack_archive(root / "bad.tar", root / "target")


@unittest.skipUnless(os.environ.get("EDOC_TEST_PG_BIN"), "isolated PostgreSQL runtime not configured")
class ActualPostgresRestoreTest(unittest.TestCase):
    def test_real_database_restore_preserves_rows_constraints_and_permissions(self):
        pg_bin = Path(os.environ["EDOC_TEST_PG_BIN"])
        with tempfile.TemporaryDirectory(prefix="edoc-pg-test-") as directory:
            root = Path(directory)
            source_dir, target_dir = root / "source", root / "target"
            source_dir.mkdir()
            target_dir.mkdir()
            dump = root / "fixture.dump"
            with runner.LocalPostgres(pg_bin, source_dir) as source:
                with runner.connect_from_environment(source.env) as conn:
                    conn.execute("CREATE ROLE fixture_reader NOLOGIN")
                    conn.execute("CREATE ROLE fixture_owner NOLOGIN")
                    conn.execute("CREATE SCHEMA edoc")
                    conn.execute("CREATE TABLE edoc.fixture (id integer PRIMARY KEY, value text NOT NULL)")
                    conn.execute("INSERT INTO edoc.fixture VALUES (1, 'synthetic-one'), (2, 'synthetic-two')")
                    conn.execute("ALTER TABLE edoc.fixture ENABLE ROW LEVEL SECURITY")
                    conn.execute("GRANT SELECT ON edoc.fixture TO fixture_reader")
                    conn.execute("CREATE POLICY fixture_policy ON edoc.fixture FOR SELECT TO fixture_reader USING (id > 0)")
                    conn.execute("ALTER TABLE edoc.fixture OWNER TO fixture_owner")
                with runner.connect_from_environment(source.env) as conn:
                    before = runner.table_evidence(conn)
                runner.checked_run([str(pg_bin / "pg_dump"), "--format=custom", "--no-owner", "--schema=edoc", "--file=" + str(dump)], env=source.env)
            with runner.LocalPostgres(pg_bin, target_dir) as target:
                target.prepare([("fixture_reader", False), ("fixture_owner", False)], [])
                runner.checked_run([str(pg_bin / "pg_restore"), "--exit-on-error", "--single-transaction", "--dbname=postgres", str(dump)], env=target.env)
                with runner.connect_from_environment(target.env) as conn:
                    after = runner.table_evidence(conn)
                    self.assertEqual(conn.execute("SHOW listen_addresses").fetchone()[0], "")
                self.assertEqual(runner.canonical(before), runner.canonical(after))
                self.assertEqual(before["tables"][0]["rows"], 2)


if __name__ == "__main__":
    unittest.main()
