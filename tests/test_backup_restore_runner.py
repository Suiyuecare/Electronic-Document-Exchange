import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


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

    def test_scheduled_missing_key_never_silently_creates_a_new_key(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "missing-parent/key"
            with self.assertRaisesRegex(runner.DrillError, "scheduled_encryption_key_missing"):
                runner.load_key(key, require_existing=True)
            self.assertFalse(key.parent.exists())

    def test_source_lock_is_cross_process_and_survives_release_without_unlink(self):
        with tempfile.TemporaryDirectory() as directory:
            source = "a" * 20
            code = """import importlib.util,sys
from pathlib import Path
s=importlib.util.spec_from_file_location('runner',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
try:
    with m.SourceLock('a'*20,Path(sys.argv[2])): pass
except m.DrillError as exc:
    sys.exit(42 if str(exc)=='source_backup_already_running' else 43)
"""
            with runner.SourceLock(source, directory) as lock:
                result = subprocess.run([sys.executable, "-c", code, str(Path(runner.__file__)), directory], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 42)
                inode = lock.path.stat().st_ino
            self.assertTrue(lock.path.exists())
            with runner.SourceLock(source, directory) as later:
                self.assertEqual(later.path.stat().st_ino, inode)

    def test_command_timeout_is_fixed_code_and_reaps_child(self):
        children = []
        original = subprocess.Popen
        def capture(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        with mock.patch.object(runner.subprocess, "Popen", side_effect=capture):
            with self.assertRaisesRegex(runner.DrillError, "fixture_timeout") as error:
                runner.checked_run([sys.executable, "-c", "import time; print('private-fixture-secret',flush=True);time.sleep(20)"], timeout=0.1, code="fixture")
        self.assertNotIn("private-fixture-secret", str(error.exception))
        self.assertIsNotNone(children[0].returncode)

    def test_whole_operation_deadline_cleans_private_scratch(self):
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            with self.assertRaisesRegex(runner.DrillError, "backup_operation_timed_out"):
                with runner.bounded_operation(1):
                    with tempfile.TemporaryDirectory(dir=directory) as scratch:
                        Path(scratch, "plaintext-fixture").write_bytes(b"synthetic fixture")
                        runner.checked_run([sys.executable, "-c", "import time;time.sleep(20)"], timeout=30)
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_atomic_evidence_never_overwrites_immutable_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "receipt.json"
            runner.atomic_private_json(target, {"version": 1}, replace=False)
            with self.assertRaisesRegex(runner.DrillError, "evidence_path_conflict"):
                runner.atomic_private_json(target, {"version": 2}, replace=False)
            self.assertEqual(json.loads(target.read_bytes()), {"version": 1})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(Path(directory).glob(".evidence-*")))

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
    def test_timeout_stops_isolated_postgres_and_cleans_scratch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(runner.DrillError, "backup_operation_timed_out"):
                with runner.bounded_operation(2):
                    with tempfile.TemporaryDirectory(dir=root) as private:
                        with runner.LocalPostgres(os.environ["EDOC_TEST_PG_BIN"], Path(private)) as database:
                            socket = database.socket
                            time.sleep(5)
            self.assertFalse(socket.exists())
            self.assertEqual(list(root.iterdir()), [])

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
