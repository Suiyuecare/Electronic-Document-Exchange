"""QA retention may not overwrite workspace/user artifacts or call live paths."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import capture_isolated_pdf_output as capture


class CaptureOutputBoundaryTest(unittest.TestCase):
    def test_unknown_profile_fails_before_any_fixture_runs(self):
        with mock.patch.object(capture, "_capture_uploaded_output") as run, self.assertRaisesRegex(ValueError, "profile_invalid"):
            capture.capture(Path("/unused"), profile="production")
        run.assert_not_called()

    def test_repo_destination_is_rejected_before_authoring_or_fixture(self):
        with mock.patch.object(capture, "_capture_uploaded_output") as run, self.assertRaisesRegex(ValueError, "outside_repository"):
            capture.capture(capture.ROOT / "output" / "qa")
        run.assert_not_called()

    def test_existing_product_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-stamped-two-page.pdf"
            path.write_bytes(b"existing-user-bytes")
            with mock.patch.object(capture, "_capture_uploaded_output") as run, self.assertRaisesRegex(ValueError, "already_exists"):
                capture.capture(Path(directory))
            run.assert_not_called()
            self.assertEqual(b"existing-user-bytes", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
