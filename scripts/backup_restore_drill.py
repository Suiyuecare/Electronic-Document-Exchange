#!/usr/bin/env python3
"""Operator-only encrypted backup and actual isolated PostgreSQL restore.

The source connection is read-only. The restore target is always a new local
PostgreSQL cluster with TCP disabled; a source or remote restore URL is never
accepted. Output is aggregate evidence only, never rows, object names or keys.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import time
from urllib import parse, request

ROOT = Path(__file__).resolve().parents[1]
MAGIC = b"EDOCBK01"
SCHEMAS = ("edoc", "edoc_private")


class DrillError(RuntimeError):
    """Messages are fixed error codes safe for operator logs."""


class SourceLock:
    """One cooperative operator process per source, independent of output path.

    The lock inode is never deleted: unlinking it could admit a second lock.
    No credentials or personal data are stored in the lock file.
    """

    def __init__(self, source_ref, directory=None):
        if not re.fullmatch(r"[a-z0-9]{20}", str(source_ref)):
            raise DrillError("source_project_ref_invalid")
        root = directory or Path.home() / ".local/state/edoc-backup/locks"
        self.directory = private_directory(root)
        self.path = self.directory / (hashlib.sha256(source_ref.encode()).hexdigest() + ".lock")
        self.fd = None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        metadata = os.fstat(self.fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077 or metadata.st_uid != os.getuid():
            os.close(self.fd)
            self.fd = None
            raise DrillError("source_lock_permissions_invalid")
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise DrillError("source_backup_already_running") from None
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


@contextmanager
def bounded_operation(timeout_seconds):
    """Bound the whole operation and unwind private temporary files on signals.

    Requires the main thread on a POSIX host. SIGKILL/power loss cannot be
    handled; those cases must remain visible in the operator's stale status.
    """
    if not 1 <= timeout_seconds <= 7200:
        raise DrillError("backup_timeout_invalid")
    old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def interrupted(signum, frame):
        raise DrillError("backup_operation_timed_out" if signum == signal.SIGALRM else "backup_operation_interrupted")

    try:
        for sig in old_handlers:
            signal.signal(sig, interrupted)
        signal.setitimer(signal.ITIMER_REAL, min(timeout_seconds, old_timer[0]) if old_timer[0] else timeout_seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, old_timer[0] - (time.monotonic() - started)), old_timer[1])


def atomic_private_json(path, data, *, replace=True):
    """Publish complete safe evidence atomically; never follow a destination link."""
    path = Path(path)
    parent = private_directory(path.parent)
    if path.is_symlink() or (path.exists() and not replace):
        raise DrillError("evidence_path_conflict")
    fd, temporary = tempfile.mkstemp(prefix=".evidence-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(data))
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # Atomic fail-if-present; no immutable overwrite.
            os.unlink(temporary)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_operator_environment(path):
    """Read an existing ignored env file in-process; never run shell contents."""
    if not path:
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise DrillError("operator_environment_key_invalid")
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                raise DrillError("operator_environment_value_invalid") from None
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if value:
            os.environ[key] = value


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def private_directory(path):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise DrillError("backup_directory_symlink_forbidden")
    path = path.resolve()
    if path == ROOT or ROOT in path.parents:
        raise DrillError("backup_path_must_be_outside_repository")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise DrillError("backup_directory_must_be_private_0700")
    return path


def load_key(path, *, require_existing=False):
    path = Path(path).expanduser().absolute()
    if path.is_symlink() or path.resolve() == ROOT or ROOT in path.resolve().parents:
        raise DrillError("encryption_key_path_invalid")
    if require_existing and not path.exists():
        raise DrillError("scheduled_encryption_key_missing")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    if path.stat().st_mode & 0o077 or not stat.S_ISREG(path.stat().st_mode):
        raise DrillError("encryption_key_must_be_private_0600")
    key = path.read_bytes()
    if len(key) != 32:
        raise DrillError("encryption_key_must_be_32_bytes")
    return key


def encrypt_file(source, target, key):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    nonce = secrets.token_bytes(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    with open(source, "rb") as src, open(target, "xb") as dst:
        os.chmod(target, 0o600)
        dst.write(MAGIC + nonce)
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(encryptor.update(chunk))
        dst.write(encryptor.finalize())
        dst.write(encryptor.tag)


def decrypt_file(source, target, key):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    with open(source, "rb") as src:
        if src.read(len(MAGIC)) != MAGIC:
            raise DrillError("encrypted_backup_header_invalid")
        nonce = src.read(12)
        src.seek(-16, 2)
        tag = src.read(16)
        remaining = src.tell() - len(MAGIC) - 12 - 16
        src.seek(len(MAGIC) + 12)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(MAGIC)
        try:
            with open(target, "xb") as dst:
                os.chmod(target, 0o600)
                while remaining:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise DrillError("encrypted_backup_truncated")
                    remaining -= len(chunk)
                    dst.write(decryptor.update(chunk))
                dst.write(decryptor.finalize())
        except Exception:
            Path(target).unlink(missing_ok=True)
            raise DrillError("encrypted_backup_authentication_failed") from None


def unpack_archive(archive, destination):
    destination = Path(destination).resolve()
    destination.mkdir(mode=0o700)
    with tarfile.open(archive, "r") as tar:
        members = tar.getmembers()
        for item in members:
            name = Path(item.name)
            if name.is_absolute() or ".." in name.parts or not (item.isfile() or item.isdir()):
                raise DrillError("backup_archive_member_invalid")
        tar.extractall(destination, members=members, filter="data")


def checked_run(args, *, env=None, cwd=None, timeout=900, code="operator_command_failed"):
    # No shell, no inherited pipes and no stdout/stderr logging. On timeout or
    # cancellation terminate the command's process group before unwinding files.
    child = subprocess.Popen(args, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    completed = False
    try:
        stdout, _ = child.communicate(timeout=timeout)
        completed = True
        if child.returncode:
            raise DrillError(code)
        return stdout
    except subprocess.TimeoutExpired:
        raise DrillError(code + "_timeout") from None
    finally:
        if not completed:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.communicate(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate(timeout=3)


def linked_source_environment(workdir):
    # The CLI obtains a short-lived login role. Never execute its shell output,
    # save it, print it, or put credentials in process arguments.
    data = checked_run(
        ["supabase", "db", "dump", "--linked", "--dry-run", "--schema", "edoc"],
        cwd=workdir, code="supabase_linked_database_credentials_unavailable",
    ).decode()
    values = {}
    for line in data.splitlines():
        match = re.match(r"^\s*(?:export\s+)?(PGHOST|PGPORT|PGUSER|PGPASSWORD|PGDATABASE)=(.+)$", line)
        if match:
            tokens = shlex.split(match.group(2))
            if len(tokens) == 1:
                values[match.group(1)] = tokens[0]
    if set(values) != {"PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"}:
        raise DrillError("supabase_linked_database_credentials_invalid")
    if not values["PGHOST"].endswith(".supabase.com") and not values["PGHOST"].endswith(".supabase.co"):
        raise DrillError("supabase_linked_database_host_invalid")
    return {**os.environ, **values, "PGSSLMODE": "require", "PGOPTIONS": "-c default_transaction_read_only=on"}


def configure_storage_from_cli(project_ref, workdir):
    if not re.fullmatch(r"[a-z0-9]{20}", project_ref):
        raise DrillError("storage_project_ref_invalid")
    raw = checked_run(["supabase", "projects", "api-keys", "--project-ref", project_ref, "--output", "json"], cwd=workdir, code="storage_operator_credentials_unavailable")
    values = json.loads(raw)
    if isinstance(values, dict):
        values = values.get("api_keys", values.get("rows", []))
    selected = next((item for item in values if item.get("name") == "service_role"), None)
    if not selected or not selected.get("api_key"):
        raise DrillError("storage_service_role_not_available")
    os.environ["EDOC_STORAGE_SUPABASE_URL"] = "https://" + project_ref + ".supabase.co"
    os.environ["EDOC_STORAGE_SERVICE_ROLE_KEY"] = selected["api_key"]
    os.environ["EDOC_STORAGE_BUCKET"] = "edoc-private"
    os.environ["EDOC_SEAL_STORAGE_BUCKET"] = "edoc-seal-vault"


def connect_from_environment(env):
    import psycopg
    return psycopg.connect(
        host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
        password=env.get("PGPASSWORD", ""), dbname=env["PGDATABASE"],
        sslmode=env.get("PGSSLMODE", "disable"), connect_timeout=20,
    )


def table_evidence(conn):
    from psycopg import sql
    conn.execute("SET TIME ZONE 'UTC'")
    conn.execute("SET DateStyle TO 'ISO, YMD'")
    rows = conn.execute("""
        SELECT n.nspname,c.relname,c.relrowsecurity,c.relforcerowsecurity,
          coalesce(array_to_string(coalesce(c.relacl,acldefault('r',c.relowner)), ','),'')
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p')
        ORDER BY n.nspname,c.relname
    """, (list(SCHEMAS),)).fetchall()
    evidence = []
    for schema, table, rls, force_rls, acl in rows:
        digest = hashlib.sha256()
        count = 0
        # A deterministic, length-delimited full-row hash catches value changes
        # even when counts stay equal. Rows never leave the private process.
        query = sql.SQL("SELECT row_to_json(t)::text FROM {}.{} t ORDER BY row_to_json(t)::text COLLATE \"C\"").format(sql.Identifier(schema), sql.Identifier(table))
        with conn.cursor(name="hash_" + secrets.token_hex(6)) as cursor:
            cursor.execute(query)
            for (value,) in cursor:
                data = value.encode()
                digest.update(len(data).to_bytes(8, "big"))
                digest.update(data)
                count += 1
        evidence.append({"schema": schema, "table": table, "rows": count, "sha256": digest.hexdigest(), "rls": rls, "force_rls": force_rls, "acl": sorted(acl.split(",")) if acl else []})
    policies = conn.execute("""
        SELECT schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check
        FROM pg_policies WHERE schemaname=ANY(%s)
        ORDER BY schemaname,tablename,policyname
    """, (list(SCHEMAS),)).fetchall()
    return {"tables": evidence, "policies": policies}


def external_dependencies(conn):
    """Keep only referenced identity IDs, never the shared Auth/HR records."""
    from psycopg import sql
    rows = conn.execute("""
        SELECT n.nspname,t.relname,a.attname,nf.nspname,tf.relname,af.attname,
               cardinality(c.conkey),cardinality(c.confkey)
        FROM pg_constraint c
        JOIN pg_class t ON t.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        JOIN pg_class tf ON tf.oid=c.confrelid
        JOIN pg_namespace nf ON nf.oid=tf.relnamespace
        JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=c.conkey[1]
        JOIN pg_attribute af ON af.attrelid=tf.oid AND af.attnum=c.confkey[1]
        WHERE c.contype='f' AND n.nspname=ANY(%s) AND nf.nspname<>ALL(%s)
    """, (list(SCHEMAS), list(SCHEMAS))).fetchall()
    identities = set()
    for schema, table, column, target_schema, target_table, target_column, source_columns, target_columns in rows:
        if (target_schema, target_table, target_column, source_columns, target_columns) != ("auth", "users", "id", 1, 1):
            raise DrillError("unhandled_external_schema_dependency")
        query = sql.SQL("SELECT DISTINCT {}::text FROM {}.{} WHERE {} IS NOT NULL").format(sql.Identifier(column), sql.Identifier(schema), sql.Identifier(table), sql.Identifier(column))
        identities.update(row[0] for row in conn.execute(query))
    functions = conn.execute("""
        SELECT pg_get_functiondef(p.oid) FROM pg_proc p
        JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='auth' AND p.proname IN ('uid','role','jwt')
        AND p.pronargs=0 ORDER BY p.proname
    """).fetchall()
    return {"auth_user_ids": sorted(identities), "auth_functions": [row[0] for row in functions]}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StorageSource:
    def __init__(self):
        self.origin = os.environ.get("EDOC_STORAGE_SUPABASE_URL", "").rstrip("/")
        self.key = os.environ.get("EDOC_STORAGE_SERVICE_ROLE_KEY", "")
        if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", self.origin) or not self.key:
            raise DrillError("private_storage_credentials_missing")
        self.buckets = tuple(dict.fromkeys((
            os.environ.get("EDOC_STORAGE_BUCKET", "edoc-private"),
            os.environ.get("EDOC_SEAL_STORAGE_BUCKET", "edoc-seal-vault"),
        )))
        if any(not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", name) for name in self.buckets):
            raise DrillError("private_storage_bucket_invalid")
        self.opener = request.build_opener(NoRedirect())

    def fetch(self, path, payload=None):
        req = request.Request(self.origin + "/storage/v1/" + path,
            data=None if payload is None else canonical(payload),
            headers={"Authorization": "Bearer " + self.key, "apikey": self.key,
                     "Content-Type": "application/json"})
        try:
            return self.opener.open(req, timeout=60)
        except Exception:
            raise DrillError("private_storage_read_failed") from None

    def inventory(self):
        output = []
        for bucket in self.buckets:
            with self.fetch("bucket/" + bucket) as response:
                metadata = json.load(response)
            if metadata.get("public") is not False:
                raise DrillError("source_storage_bucket_not_private")
            prefixes = [""]
            while prefixes:
                prefix = prefixes.pop()
                offset = 0
                while True:
                    with self.fetch("object/list/" + bucket, {"prefix": prefix, "limit": 1000, "offset": offset, "sortBy": {"column": "name", "order": "asc"}}) as response:
                        rows = json.load(response)
                    if not isinstance(rows, list):
                        raise DrillError("storage_inventory_invalid")
                    for row in rows:
                        name = str(row.get("name", ""))
                        if not name or "/" in name or name in {".", ".."}:
                            raise DrillError("storage_inventory_path_invalid")
                        path = prefix + name
                        if row.get("id") is None:
                            prefixes.append(path + "/")
                        else:
                            output.append({"bucket": bucket, "path": path, "id": row["id"], "updated_at": row.get("updated_at"), "metadata": row.get("metadata")})
                    if len(rows) < 1000:
                        break
                    offset += len(rows)
        return sorted(output, key=lambda item: (item["bucket"], item["path"]))

    def backup(self, folder):
        folder.mkdir(mode=0o700)
        before = self.inventory()
        objects = []
        for item in before:
            object_id = hashlib.sha256(canonical([item["bucket"], item["path"]])).hexdigest()
            target = folder / object_id
            with self.fetch("object/" + item["bucket"] + "/" + parse.quote(item["path"], safe="/")) as response, target.open("xb") as dst:
                shutil.copyfileobj(response, dst, 1024 * 1024)
            objects.append({**item, "archive_id": object_id, "sha256": digest_file(target), "bytes": target.stat().st_size})
        if before != self.inventory():
            raise DrillError("storage_changed_during_backup_retry_required")
        return objects


def restore_storage(objects, source, target):
    target.mkdir(mode=0o700)
    for item in objects:
        object_id = item["archive_id"]
        if not re.fullmatch(r"[0-9a-f]{64}", object_id):
            raise DrillError("storage_archive_id_invalid")
        src = source / object_id
        if not src.is_file() or digest_file(src) != item["sha256"] or src.stat().st_size != item["bytes"]:
            raise DrillError("storage_backup_hash_mismatch")
        dst = target / object_id
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o600)
        if digest_file(dst) != item["sha256"]:
            raise DrillError("storage_restore_hash_mismatch")
    if len(list(target.iterdir())) != len(objects):
        raise DrillError("storage_restore_count_mismatch")
    return {"restored": True, "hash_match": True, "counts_match": True,
            "object_count": len(objects), "bytes": sum(x["bytes"] for x in objects),
            "target_type": "private_local_filesystem", "private": True,
            "empty_source": not bool(objects)}


class LocalPostgres:
    def __init__(self, bin_dir, work):
        self.bin = Path(bin_dir).resolve()
        self.data = work / "postgres"
        # macOS Unix-domain sockets have a small path limit.
        self.socket = Path(tempfile.mkdtemp(prefix="edoc-pg-", dir="/tmp"))
        os.chmod(self.socket, 0o700)
        self.env = {**os.environ, "PGHOST": str(self.socket), "PGPORT": "5432", "PGUSER": "postgres", "PGDATABASE": "postgres", "PGPASSWORD": "", "PGSSLMODE": "disable", "PGOPTIONS": ""}

    def __enter__(self):
        try:
            checked_run([str(self.bin / "initdb"), "-D", str(self.data), "-U", "postgres", "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--locale=C"], timeout=60, code="isolated_postgres_init_failed")
            checked_run([str(self.bin / "pg_ctl"), "-D", str(self.data), "-l", str(self.data / "private-startup.log"), "-o", "-c listen_addresses='' -c unix_socket_directories=" + str(self.socket), "-w", "start"], timeout=60, code="isolated_postgres_start_failed")
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if (self.data / "postmaster.pid").exists():
                checked_run([str(self.bin / "pg_ctl"), "-D", str(self.data), "-m", "immediate", "-w", "stop"], timeout=20, code="isolated_postgres_stop_failed")
        finally:
            shutil.rmtree(self.socket)

    def prepare(self, roles, extensions, dependencies=None):
        from psycopg import sql
        with connect_from_environment(self.env) as conn:
            conn.autocommit = True
            if conn.execute("SHOW listen_addresses").fetchone()[0]:
                raise DrillError("restore_target_network_not_isolated")
            for name, bypass in roles:
                if name == "postgres" or name.startswith("pg_"):
                    continue
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN {}").format(sql.Identifier(name), sql.SQL("BYPASSRLS" if bypass else "NOBYPASSRLS")))
            conn.execute("CREATE SCHEMA IF NOT EXISTS extensions")
            available = {row[0] for row in conn.execute("SELECT name FROM pg_available_extensions")}
            for name, schema in extensions:
                if name in available and name != "plpgsql":
                    conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
                    conn.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {} WITH SCHEMA {}").format(sql.Identifier(name), sql.Identifier(schema)))
            if dependencies is not None:
                conn.execute("CREATE SCHEMA auth")
                conn.execute("CREATE TABLE auth.users (id uuid PRIMARY KEY)")
                for user_id in dependencies["auth_user_ids"]:
                    conn.execute("INSERT INTO auth.users(id) VALUES (%s)", (user_id,))
                for definition in dependencies["auth_functions"]:
                    conn.execute(definition)


def restore_recovered(manifest, recovered, work, pg_bin_dir):
    if tuple(manifest.get("schemas", [])) != SCHEMAS:
        raise DrillError("backup_schema_scope_mismatch")
    if digest_file(recovered / "database.dump") != manifest["database_sha256"]:
        raise DrillError("backup_manifest_hash_mismatch")
    with LocalPostgres(pg_bin_dir, work) as target:
        target.prepare(manifest["roles"], manifest["extensions"], manifest["external_dependencies"])
        checked_run([str(Path(pg_bin_dir) / "pg_restore"), "--exit-on-error", "--single-transaction", "--dbname=postgres", str(recovered / "database.dump")], env=target.env, code="isolated_database_restore_failed")
        with connect_from_environment(target.env) as conn:
            restored = table_evidence(conn)
        if canonical(restored) != canonical(manifest["database"]):
            raise DrillError("database_restore_rows_or_permissions_mismatch")
        return restore_storage(manifest["objects"], recovered / "storage", work / "restored-storage")


def save_receipt(manifest, encrypted, storage, duration, drill_id, args, output):
    source = manifest["database"]
    rto = max(1, math.ceil(duration / 60))
    snapshot_at = datetime.fromisoformat(manifest.get("source_snapshot_at", manifest["created_at"]).replace("Z", "+00:00"))
    rpo = max(0, math.ceil((datetime.now(timezone.utc) - snapshot_at).total_seconds() / 60))
    ok = rto <= args.rto_target_minutes and rpo <= args.rpo_target_minutes
    report = {
        "schema_version": 1, "receipt_id": drill_id, "ok": ok,
        "result": "通過" if ok else "recovery_time_or_age_target_exceeded",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_project_ref": manifest["source_project_ref"],
        "target_project_ref": "local-postgres-" + secrets.token_hex(8),
        "target_type": "isolated_local_postgresql", "target_isolated": True,
        "database": {"restored": True, "integrity": True, "counts_match": True,
            "row_hashes_match": True, "permissions_match": True,
            "table_count": len(source["tables"]),
            "row_count": sum(x["rows"] for x in source["tables"]),
            "policy_count": len(source["policies"]), "schemas": list(SCHEMAS)},
        "storage": storage,
        "backup": {"encrypted": True, "algorithm": "AES-256-GCM",
            "sha256": digest_file(encrypted), "bytes": encrypted.stat().st_size,
            "file": encrypted.name, "snapshot_at": snapshot_at.isoformat()},
        "rto_minutes": rto, "rpo_minutes": rpo, "duration_seconds": duration,
        "limitations": [
            "local isolated restore; does not validate managed Supabase platform recovery",
            "on-demand backup age; does not prove scheduled-backup RPO",
            "private filesystem object restore; does not validate destination Storage API",
            "empty source storage is explicitly reported",
            "shared Auth identity UUID dependencies only; shared HR/Auth data is excluded",
        ],
    }
    report["receipt_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    atomic_private_json(output / (drill_id + ".receipt.json"), report, replace=False)
    return report


def restore_existing_backup(args):
    """Works offline, including when the source project is unavailable."""
    started = time.monotonic()
    os.umask(0o077)
    output = private_directory(args.output_dir)
    key = load_key(args.encryption_key_file, require_existing=getattr(args, "require_existing_key", False))
    encrypted = Path(args.restore_backup).resolve()
    with tempfile.TemporaryDirectory(prefix="edoc-restore-offline-") as temporary:
        work = Path(temporary)
        decrypt_file(encrypted, work / "recovered.tar", key)
        recovered = work / "recovered"
        unpack_archive(work / "recovered.tar", recovered)
        manifest = json.loads((recovered / "manifest.json").read_bytes())
        if manifest["source_project_ref"] != args.source_project_ref:
            raise DrillError("source_project_backup_mismatch")
        storage = restore_recovered(manifest, recovered, work, args.pg_bin_dir)
        drill_id = "RESTORE-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
        return save_receipt(manifest, encrypted, storage, math.ceil(time.monotonic() - started), drill_id, args, output)


def run_drill(args):
    started = time.monotonic()
    os.umask(0o077)
    output = private_directory(args.output_dir)
    key = load_key(args.encryption_key_file, require_existing=getattr(args, "require_existing_key", False))
    for command in ("pg_dump", "pg_restore", "pg_ctl", "initdb"):
        if not (Path(args.pg_bin_dir) / command).is_file():
            raise DrillError("postgres_tools_missing")
    source_ref = (Path(args.supabase_workdir) / "supabase/.temp/project-ref").read_text().strip()
    expected_ref = args.source_project_ref
    if not re.fullmatch(r"[a-z0-9]{20}", expected_ref) or source_ref != expected_ref:
        raise DrillError("source_project_link_mismatch")
    source_env = linked_source_environment(args.supabase_workdir)
    drill_id = "DRILL-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    with tempfile.TemporaryDirectory(prefix="edoc-restore-") as temporary:
        work = Path(temporary)
        os.chmod(work, 0o700)
        bundle = work / "bundle"
        bundle.mkdir(mode=0o700)
        dump = bundle / "database.dump"
        with connect_from_environment(source_env) as source:
            source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            source.execute("SET ROLE postgres")
            snapshot = source.execute("SELECT pg_export_snapshot()").fetchone()[0]
            snapshot_at = datetime.now(timezone.utc).isoformat()
            # Start the second connection while the CLI login is still fresh.
            checked_run([str(Path(args.pg_bin_dir) / "pg_dump"), "--format=custom", "--role=postgres", "--no-owner", "--no-comments", "--no-security-labels", "--snapshot=" + snapshot, *["--schema=" + name for name in SCHEMAS], "--file=" + str(dump)], env=source_env, code="source_pg_dump_failed")
            source_evidence = table_evidence(source)
            roles = source.execute("SELECT rolname,rolbypassrls FROM pg_roles WHERE rolname NOT LIKE 'pg_%' ORDER BY rolname").fetchall()
            extensions = source.execute("SELECT e.extname,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname").fetchall()
            dependencies = external_dependencies(source)
        objects = StorageSource().backup(bundle / "storage")
        manifest = {"schema_version": 1, "source_project_ref": source_ref, "source_snapshot_at": snapshot_at, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "schemas": SCHEMAS, "database_sha256": digest_file(dump), "database": source_evidence, "roles": roles, "extensions": extensions, "external_dependencies": dependencies, "objects": objects}
        (bundle / "manifest.json").write_bytes(canonical(manifest))
        archive = work / "backup.tar"
        with tarfile.open(archive, "w") as tar:
            for item in sorted(bundle.rglob("*")):
                tar.add(item, arcname=str(item.relative_to(bundle)), recursive=False)
        encrypted = output / (drill_id + ".tar.aesgcm")
        encrypt_file(archive, encrypted, key)
        archive.unlink()
        # Restore only bytes recovered from the authenticated encrypted backup.
        decrypted = work / "recovered.tar"
        decrypt_file(encrypted, decrypted, key)
        recovered = work / "recovered"
        unpack_archive(decrypted, recovered)
        recovered_manifest = json.loads((recovered / "manifest.json").read_bytes())
        if canonical(recovered_manifest) != canonical(manifest) or digest_file(recovered / "database.dump") != manifest["database_sha256"]:
            raise DrillError("backup_manifest_hash_mismatch")
        storage = restore_recovered(manifest, recovered, work, args.pg_bin_dir)
        duration = math.ceil(time.monotonic() - started)
        return save_receipt(manifest, encrypted, storage, duration, drill_id, args, output)


def execute(args, *, held_lock=None):
    """Shared guarded entry point for interactive and scheduled host runs."""
    os.umask(0o077)
    if held_lock is None:
        with SourceLock(args.source_project_ref) as lock:
            return execute(args, held_lock=lock)
    expected_lock_name = hashlib.sha256(args.source_project_ref.encode()).hexdigest() + ".lock"
    if not isinstance(held_lock, SourceLock) or held_lock.fd is None or held_lock.path.name != expected_lock_name:
        raise DrillError("source_lock_required")
    with bounded_operation(getattr(args, "timeout_seconds", 900)):
        load_operator_environment(args.env_file)
        if args.storage_project_ref and not args.restore_backup:
            configure_storage_from_cli(args.storage_project_ref, args.supabase_workdir)
        return restore_existing_backup(args) if args.restore_backup else run_drill(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin-dir", required=True)
    parser.add_argument("--supabase-workdir", default=str(ROOT))
    parser.add_argument("--source-project-ref", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--encryption-key-file", required=True)
    parser.add_argument("--rto-target-minutes", type=int, default=30)
    parser.add_argument("--rpo-target-minutes", type=int, default=15)
    parser.add_argument("--restore-backup", help="Restore an existing encrypted archive completely offline, without accessing the source")
    parser.add_argument("--env-file", help="Existing private/ignored operator env file; values are never printed")
    parser.add_argument("--storage-project-ref", help="Obtain storage service role in-process from the operator's existing Supabase CLI authorization")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Whole-operation deadline, including network reads and isolated restore")
    parser.add_argument("--require-existing-key", action="store_true", help="Fail closed when the operator key is missing; never silently rotate a scheduled key")
    args = parser.parse_args()
    try:
        result = execute(args)
    except DrillError as exc:
        result = {"ok": False, "blocked": True, "error_code": str(exc)}
    except Exception as exc:
        import traceback
        frames = traceback.extract_tb(exc.__traceback__)
        step = next((frame.name for frame in reversed(frames) if frame.filename == __file__), "main")
        result = {"ok": False, "blocked": True, "error_code": "backup_restore_unexpected_failure", "error_type": type(exc).__name__, "failed_step": step}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
