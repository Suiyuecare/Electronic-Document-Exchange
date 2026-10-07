"""Keep readiness claims scoped to actual evidence, never simulated human SSO."""
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader
from tools.editor_latency_browser_acceptance import CASES, make_pdf

ROOT = Path(__file__).resolve().parents[1]


class ReadinessEvidenceContractTest(unittest.TestCase):
    def test_shared_touch_target_preserves_larger_finance_navigation(self):
        css = (ROOT / "styles.css").read_text()
        self.assertIn("--action-hit-size: 44px", css)
        self.assertIn("#appShell button:not(.nav-item)", css)
        self.assertIn("min-width: var(--action-hit-size)", css)
        self.assertIn("min-height: var(--action-hit-size)", css)
        acceptance = (ROOT / "tools/fluid_experience_browser_acceptance.py").read_text()
        self.assertIn('if row.get("shortTargets"):failures.append', acceptance)

    def test_pdf_matrix_includes_large_scan_and_page_limit_without_real_documents(self):
        self.assertEqual({case[0] for case in CASES},
                         {"vector-1", "vector-25", "vector-300", "scan-1", "scan-4", "non-a4"})
        for name, pages, size, scanned in CASES:
            if name not in {"vector-1", "non-a4"}:
                continue
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "synthetic.pdf"
                make_pdf(path, name, pages, size, scanned)
                reader = PdfReader(path)
                self.assertEqual(len(reader.pages), pages)
                self.assertIn("SYNTHETIC LATENCY", reader.pages[0].extract_text())
                self.assertAlmostEqual(float(reader.pages[0].mediabox.width), size[0], places=2)

    def test_latency_measures_painted_canvas_and_actual_saved_edit(self):
        source = (ROOT / "tools/editor_latency_browser_acceptance.py").read_text()
        self.assertIn("await original(...args)", source)
        self.assertIn("await new Promise(requestAnimationFrame)", source)
        self.assertIn('row["firstPagePaintMs"]', source)
        self.assertIn('row["serverSavedText"]', source)
        self.assertIn('"humanSSOVerified": False', source)
        self.assertIn('"physicalMobileVerified": False', source)
        self.assertIn('"hostedUploadMeasured": False', source)
        self.assertIn("require_local_origin(Fixture.origin)", source)

    def test_ci_executes_opt_in_database_restore_numbering_and_tus(self):
        source = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("postgresql-client postgresql", source)
        self.assertIn("tests.test_official_numbering_postgres", source)
        self.assertIn("tests.test_backup_restore_runner.ActualPostgresRestoreTest", source)
        self.assertIn("EDOC_ACCEPTANCE_UPLOAD_PROTOCOL=local_supabase_tus", source)
        self.assertIn("tests.test_official_handover_postgres", source)


if __name__ == "__main__":
    unittest.main()
