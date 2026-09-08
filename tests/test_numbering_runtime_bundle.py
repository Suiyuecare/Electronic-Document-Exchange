from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NumberingRuntimeBundleTest(unittest.TestCase):
    def test_numbering_module_is_explicitly_packaged_and_not_upload_ignored(self):
        config = json.loads((ROOT / "vercel.json").read_text())
        build = next(row for row in config["builds"] if row.get("src") == "api/index.py")
        self.assertIn("edoc_numbering.py", build["config"]["includeFiles"])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            shutil.copy2(ROOT / ".vercelignore", target / ".gitignore")
            shutil.copy2(ROOT / "edoc_numbering.py", target / "edoc_numbering.py")
            subprocess.run(["git", "init", "--quiet"], cwd=target, check=True, capture_output=True)
            result = subprocess.run(["git", "check-ignore", "--no-index", "edoc_numbering.py"], cwd=target, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stdout.decode())

    def test_minimal_python_function_bundle_imports_numbering_without_repository_on_path(self):
        # Trace only local Python imports, then import the actual Function entrypoint
        # from that isolated bundle. No source-repository sys.path fallback is used.
        pending = [Path("api/index.py")]
        included = set()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            while pending:
                relative = pending.pop()
                if relative in included:
                    continue
                included.add(relative)
                source = ROOT / relative
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                for node in ast.walk(ast.parse(source.read_text())):
                    modules = [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
                    if isinstance(node, ast.Import):
                        modules = [item.name for item in node.names]
                    for module in modules:
                        local = Path(module.split(".")[0] + ".py")
                        if (ROOT / local).is_file():
                            pending.append(local)
            self.assertIn(Path("edoc_numbering.py"), included)
            environment = {
                key: value for key, value in os.environ.items()
                if not key.startswith(("SUPABASE", "EDOC_", "VERCEL", "PYTHONPATH"))
            }
            environment.update({"EDOC_DB_MODE": "supabase", "EDOC_DEPLOYMENT_ENV": "test"})
            result = subprocess.run(
                [sys.executable, "-I", "-c", "import runpy; result=runpy.run_path('api/index.py'); import edoc_numbering; assert result['handler']; assert callable(edoc_numbering.install_sqlite_numbering); print(edoc_numbering.__file__)"],
                cwd=target, env=environment, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()).resolve(), (target / "edoc_numbering.py").resolve())


if __name__ == "__main__":
    unittest.main()
