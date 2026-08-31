from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend


ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_DIR = ROOT / "supabase" / "verification"
PACKAGED_SUPABASE_FILES = {
    "supabase/verification/production_cutover_checks.sql",
    "supabase/verification/migration_manifest.json",
}


class VercelPackagingTestCase(unittest.TestCase):
    def test_production_env_template_includes_dedicated_app_secret(self) -> None:
        values = {}
        template = (ROOT / ".env.production.example").read_text(encoding="utf-8")
        for line in template.splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name] = value

        self.assertTrue(values.get("APP_SECRET"))
        self.assertNotEqual(values["APP_SECRET"], values.get("CRON_SECRET"))
        self.assertNotEqual(values["APP_SECRET"], values.get("EDOC_FILE_ENCRYPTION_KEY"))

    def test_vercel_function_includes_only_safe_supabase_artifacts(self) -> None:
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        python_build = next(item for item in config["builds"] if item.get("src") == "api/index.py")
        include_files = set(python_build["config"]["includeFiles"])

        self.assertTrue(PACKAGED_SUPABASE_FILES.issubset(include_files))
        supabase_includes = {item for item in include_files if item.startswith("supabase/")}
        self.assertEqual(supabase_includes, PACKAGED_SUPABASE_FILES)
        self.assertFalse(any("*" in item for item in supabase_includes))

    def test_vercelignore_uploads_verification_but_excludes_supabase_runtime(self) -> None:
        rules = {
            line.strip()
            for line in (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertNotIn("supabase", rules)
        self.assertNotIn("supabase/*", rules)
        self.assertIn("supabase/migrations/", rules)
        self.assertIn("supabase/seed.sql", rules)
        self.assertIn("supabase/.temp/", rules)
        self.assertIn("supabase/.DS_Store", rules)

        # Vercel's ignore parser follows gitignore semantics. Exercise those
        # semantics in an isolated repository so a future parent-directory
        # rule (the regression that removed verification/ before includeFiles)
        # is caught rather than merely asserting text patterns.
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copy2(ROOT / ".vercelignore", temp_root / ".gitignore")
            paths = [
                *sorted(PACKAGED_SUPABASE_FILES),
                "supabase/migrations/202601010000_example.sql",
                "supabase/seed.sql",
                "supabase/.temp/project-ref",
                "supabase/.DS_Store",
            ]
            for relative in paths:
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=temp_root,
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                ["git", "check-ignore", "--no-index", "--stdin"],
                cwd=temp_root,
                input="\n".join(paths) + "\n",
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertIn(result.returncode, {0, 1})
            ignored = set(result.stdout.splitlines())

        self.assertTrue(PACKAGED_SUPABASE_FILES.isdisjoint(ignored))
        self.assertIn("supabase/migrations/202601010000_example.sql", ignored)
        self.assertIn("supabase/seed.sql", ignored)
        self.assertIn("supabase/.temp/project-ref", ignored)
        self.assertIn("supabase/.DS_Store", ignored)

    def test_migration_manifest_matches_repository_without_sql_content(self) -> None:
        manifest_raw = (VERIFICATION_DIR / "migration_manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        actual = sorted(path.name for path in (ROOT / "supabase" / "migrations").glob("*.sql"))

        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["directory"], "supabase/migrations")
        self.assertEqual(manifest["migrations"], actual)
        self.assertTrue(all(re.fullmatch(r"[0-9]{12,20}_[a-z0-9_]+\.sql", name) for name in actual))
        self.assertNotIn("create table", manifest_raw.decode("utf-8").lower())
        self.assertNotRegex(manifest_raw.decode("utf-8"), r"(?i)(service_role_key|sk-proj-|private key)")

    def test_artifact_endpoints_work_from_minimal_function_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            target = bundle_root / "supabase" / "verification"
            target.mkdir(parents=True)
            for name in ("production_cutover_checks.sql", "migration_manifest.json"):
                shutil.copy2(VERIFICATION_DIR / name, target / name)

            with mock.patch.object(backend, "ROOT", bundle_root):
                sql_artifact = backend.production_cutover_sql_artifact()
                checklist_artifact = backend.production_supabase_bootstrap_checklist_artifact()

        self.assertGreater(len(sql_artifact["data"]), 100)
        self.assertEqual(
            sql_artifact["sha256"],
            hashlib.sha256(sql_artifact["data"]).hexdigest().upper(),
        )
        checklist = json.loads(checklist_artifact["content"])
        manifest = json.loads((VERIFICATION_DIR / "migration_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(checklist["migrationPlan"]["files"], manifest["migrations"])
        self.assertEqual(checklist["migrationPlan"]["count"], len(manifest["migrations"]))
        self.assertTrue(checklist["migrationPlan"]["manifest"]["containsSecrets"] is False)

    def test_cutover_sql_is_read_only_and_metadata_only(self) -> None:
        sql = (VERIFICATION_DIR / "production_cutover_checks.sql").read_text(encoding="utf-8")
        executable = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        ).lower()
        self.assertNotRegex(executable, r"\b(insert|update|delete|alter|drop|truncate|grant|revoke|create)\b")
        self.assertNotRegex(sql, r"(?i)(service_role_key|sk-proj-|begin (rsa |ec |openssh )?private key)")
        self.assertNotRegex(executable, r"storage\.objects\s")


if __name__ == "__main__":
    unittest.main()
