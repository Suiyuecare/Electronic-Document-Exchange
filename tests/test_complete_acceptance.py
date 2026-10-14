"""Combined gate contract; individual validators have independent test suites."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import complete_acceptance as complete


class CompleteAcceptanceTest(unittest.TestCase):
    def evaluate(self, *, human=True, latency=True, backup=True):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(complete.readiness_acceptance, "validate", return_value={"checklist_complete": human}), \
                mock.patch.object(complete.service_level_acceptance, "assess", return_value={"hosted_physical_evidence_ready_for_review": latency}), \
                mock.patch.object(complete.backup_continuity_acceptance, "assess", return_value={"operator_evidence_ready_for_review": backup}):
            root = Path(temporary).resolve()
            root.chmod(0o700)
            return complete.assess({}, {}, {}, candidate="a"*40, source_project_ref_sha256="b"*64,
                                   evidence_root=root, backup_evidence_root=root)

    def test_every_independent_record_must_be_ready(self):
        for key in ("human", "latency", "backup"):
            with self.subTest(key=key):
                result = self.evaluate(**{key: False})
                self.assertEqual("PENDING_OR_FAILED_ACCEPTANCE", result["status"])
                self.assertFalse(result["promotion_authorized"])

    def test_ready_record_is_not_independent_proof_or_release_authority(self):
        result = self.evaluate()
        self.assertEqual("READY_FOR_INDEPENDENT_REVIEW", result["status"])
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["independent_human_oauth_verified"])
        self.assertFalse(result["independent_offsite_permissions_and_custody_verified"])
        self.assertEqual("DISABLED", result["government_exchange"])

    def test_truthy_text_is_not_a_pass(self):
        result = self.evaluate(human="true", latency=1, backup="PASS")
        self.assertEqual("PENDING_OR_FAILED_ACCEPTANCE", result["status"])

    def test_combined_entry_cannot_bypass_private_backup_root_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            root.chmod(0o755)
            with mock.patch.object(complete.readiness_acceptance, "validate", return_value={"checklist_complete": True}), \
                    mock.patch.object(complete.service_level_acceptance, "assess", return_value={"hosted_physical_evidence_ready_for_review": True}), \
                    mock.patch.object(complete.backup_continuity_acceptance, "assess", return_value={"operator_evidence_ready_for_review": True}) as child:
                with self.assertRaisesRegex(ValueError, "private_evidence_root"):
                    complete.assess({}, {}, {}, candidate="a"*40, source_project_ref_sha256="b"*64,
                                    evidence_root=root, backup_evidence_root=root)
                child.assert_not_called()

    def test_combined_evidence_hardlink_denied_before_human_validator(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); root.chmod(0o700)
            file = root/"evidence.json"; file.write_bytes(b"{}"); file.chmod(0o600)
            os.link(file, root/"alias.json")
            with mock.patch.object(complete.readiness_acceptance, "validate") as human:
                with self.assertRaisesRegex(ValueError, "private_file"):
                    complete.assess({"evidence": [{"path": "alias.json"}]}, {}, {}, candidate="a"*40,
                                    source_project_ref_sha256="b"*64, evidence_root=root, backup_evidence_root=root)
                human.assert_not_called()

    def test_record_reader_is_private_no_link_and_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); root.chmod(0o700)
            file = root/"record.json"; file.write_bytes(b'{"status":1}'); file.chmod(0o600)
            self.assertEqual({"status": 1}, complete.read_record(file, 1024))
            link = root/"link.json"; link.symlink_to(file)
            with self.assertRaises(ValueError):
                complete.read_record(link, 1024)
            file.write_bytes(b'{"status":1,"status":2}')
            with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
                complete.read_record(file, 1024)


if __name__ == "__main__":
    unittest.main()
