"""Read-only measurement safety; browser evidence remains a separate run."""
import unittest
from unittest.mock import patch

from tools import editor_latency_browser_acceptance as acceptance


class EditorLatencyBrowserAcceptanceContractTest(unittest.TestCase):
    def test_supplied_candidate_must_match_actual_head_before_generating_files(self):
        with patch.object(acceptance.subprocess, "run") as command:
            command.return_value.stdout = "a" * 40 + "\n"
            self.assertEqual(acceptance.verified_candidate_commit("a" * 40), "a" * 40)
            self.assertEqual(acceptance.verified_candidate_commit(), "a" * 40)
            with self.assertRaisesRegex(ValueError, "candidate_commit_mismatch"):
                acceptance.verified_candidate_commit("b" * 40)
        source = acceptance.Path(acceptance.__file__).read_text()
        self.assertLess(source.index("candidate = verified_candidate_commit(candidate)"), source.index("output = output.resolve()"))

    def test_waits_for_current_nonblank_frame_not_truthy_paint_return(self):
        source = acceptance.Path(acceptance.__file__).read_text()
        self.assertIn("window.__latencyProbe.firstFrame!==null", source)
        self.assertNotIn("window.__latencyPaintMs!==null", source)
        self.assertIn("state:()=>uploadedSealEditorState", acceptance.INSTALL_PAINT_PROBE)
        self.assertIn("row[\"serverSavedText\"]", source)
        self.assertIn("row[\"serverPageCount\"] == pages", source)
        self.assertIn("row[\"noLocalAssetsSaved\"]", source)

    def test_hashes_product_sources_before_after_without_hosted_claim(self):
        self.assertTrue({"app.js", "index.html", "styles.css", "backend.py", "api/index.py"}.issubset(acceptance.RUNTIME_SOURCES))
        source = acceptance.Path(acceptance.__file__).read_text()
        self.assertIn('"runtimeSourceUnchanged"', source)
        self.assertIn('"instrumentationWorktreeChanges"', source)
        self.assertIn('"governmentExchange": "DISABLED"', source)
        self.assertIn('"hostedUploadMeasured": False', source)
        self.assertIn('"physicalMobileVerified": False', source)


if __name__ == "__main__":
    unittest.main()
