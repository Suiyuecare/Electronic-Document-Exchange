"""Synthetic taxonomy, backing-store and rectangular seal acceptance."""
import base64
from contextlib import ExitStack
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from PIL import Image
import backend
import seal_policy


class SealTaxonomyTest(unittest.TestCase):
    def test_company_and_institution_have_exact_five_slots(self):
        company = seal_policy.required_slots("company")
        institution = seal_policy.required_slots("institution")
        self.assertEqual(len(company), 5)
        self.assertEqual(len(institution), 5)
        self.assertEqual({row["category"] for row in company}, {"establishment_seal", "general_seal", "continuous_seal"})
        self.assertEqual({row["category"] for row in institution}, {"official_seal", "general_seal", "continuous_seal"})
        self.assertTrue(all(row["applicability"] == "required" for row in company + institution))

    def test_unclassified_never_guesses_primary_or_physical_inventory(self):
        result = seal_policy.inventory("SYNTHETIC", "unclassified", [])
        self.assertTrue(result["classification_required"])
        self.assertFalse(result["physical_inventory_verified"])
        self.assertEqual(len(result["conditional_slots"]), 4)
        self.assertEqual(len(result["missing_slots"]), 3)
        self.assertFalse(result["ready"])

    def test_one_primary_size_never_satisfies_the_other(self):
        result = seal_policy.inventory("A", "company", [{"id": "L", "seal_category": "establishment_seal", "seal_size_type": "large_seal", "is_active": True, "selectable": True, "current_file": {"id": "F", "usable": True}}])
        slots = {(row["category"], row["size_type"]): row["digital_status"] for row in result["required_slots"]}
        self.assertEqual(slots[("establishment_seal", "large_seal")], "ready")
        self.assertEqual(slots[("establishment_seal", "small_seal")], "missing_record")

    def test_continuous_has_no_invented_size_default_and_requires_calibration(self):
        with self.assertRaisesRegex(ValueError, "manual_calibration_required"):
            seal_policy.rectangular_geometry("single_seal")
        result = seal_policy.rectangular_geometry("single_seal", 55, 12)
        self.assertIsNone(result["default_width_mm"])
        self.assertEqual((result["width_mm"], result["height_mm"]), (55, 12))

    def test_category_and_size_pair_is_explicit(self):
        seal_policy.validate_category_size("continuous_seal", "single_seal")
        for category, size in [("continuous_seal", "large_seal"), ("general_seal", "single_seal")]:
            with self.assertRaisesRegex(ValueError, "category_size_mismatch"):
                seal_policy.validate_category_size(category, size)

    def test_rectangular_source_geometry_and_per_axis_resolution_are_checked(self):
        metadata = backend.validate_company_seal_raster_dimensions("large_seal", {"width": 400, "height": 800}, 20, 40, "official_seal")
        self.assertEqual(metadata["dimension_policy_version"], seal_policy.OFFICIAL_POLICY)
        self.assertTrue(backend.company_seal_file_dimension_is_valid(metadata, "large_seal"))
        self.assertFalse(seal_policy.category_policy_valid("establishment_seal", "large_seal", metadata))
        self.assertTrue(seal_policy.category_policy_valid("official_seal", "large_seal", metadata))
        with self.assertRaisesRegex(ValueError, "aspect_ratio"):
            backend.validate_company_seal_raster_dimensions("large_seal", {"width": 400, "height": 400}, 20, 40, "official_seal")
        with self.assertRaisesRegex(ValueError, "resolution"):
            backend.validate_company_seal_raster_dimensions("single_seal", {"width": 100, "height": 200}, 20, 40, "continuous_seal")
        with self.assertRaisesRegex(ValueError, "not_square"):
            backend.validate_company_seal_raster_dimensions("large_seal", {"width": 500, "height": 700}, 25, 35, "establishment_seal")

    def test_explicit_owner_kind_restricts_new_primary_choices_not_legacy_codes(self):
        self.assertFalse(seal_policy.application_category_allowed("unclassified", "official_seal"))
        with self.assertRaisesRegex(ValueError, "classification_required"):
            seal_policy.require_application_category("unclassified", "general_seal")
        self.assertFalse(seal_policy.application_category_allowed("company", "official_seal"))
        self.assertFalse(seal_policy.application_category_allowed("institution", "establishment_seal"))
        self.assertFalse(seal_policy.application_category_allowed("company", "bank_seal"))
        with self.assertRaisesRegex(ValueError, "owner_policy_mismatch"):
            seal_policy.require_application_category("company", "official_seal")


class SealPolicyBackendTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        self.stack.enter_context(mock.patch.object(backend, "STORAGE_DIR", Path(self.temp.name) / "storage"))
        self.stack.enter_context(mock.patch.object(backend, "PRIVATE_SEAL_STORAGE_DIR", Path(self.temp.name) / "storage" / "seal-vault" / "seals"))
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(backend.SCHEMA)
        backend.seed(self.conn)
        backend.seed_auth(self.conn)
        backend.seed_persistent_registries(self.conn)
        backend.seed_company_seal_module(self.conn)
        backend.register_sqlite_functions(self.conn)
        backend.ensure_local_company_seal_file_integrity(self.conn)
        self.company = "CO-001"

    def tearDown(self):
        self.conn.close()
        self.stack.close()
        self.temp.cleanup()

    def create(self, category, size="large_seal"):
        return backend.create_company_seal(self.conn, self.company, {"seal_name": "合成測試章", "seal_category": category, "seal_size_type": size})["id"]

    def upload(self, identity, width=30, height=30):
        output = io.BytesIO()
        Image.new("RGBA", (round(width * 15), round(height * 15)), (180, 0, 0, 180)).save(output, "PNG")
        return backend.upload_company_seal_file(self.conn, identity, {"file_name": "synthetic.png", "file_mime_type": "image/png", "content_base64": base64.b64encode(output.getvalue()).decode(), "render_width_mm": width, "render_height_mm": height})

    def test_manual_classification_is_separate_and_invalid_values_are_rejected(self):
        before = backend.company_seal_policy_report(self.conn, self.company)
        self.assertEqual(before["owner_kind"], "unclassified")
        result = backend.patch_company_seal_policy(self.conn, self.company, {"owner_kind": "company"})
        self.assertEqual(result["owner_kind"], "company")
        self.assertEqual(len(result["required_slots"]), 5)
        self.assertFalse(result["physical_inventory_verified"])
        with self.assertRaisesRegex(ValueError, "invalid_seal_owner_kind"):
            backend.patch_company_seal_policy(self.conn, self.company, {"owner_kind": "infer-from-name"})
        with self.assertRaisesRegex(ValueError, "invalid_seal_policy_fields"):
            backend.patch_company_seal_policy(self.conn, self.company, {"owner_kind": "company", "name": "new name"})

    def test_five_current_slots_make_only_the_digital_seal_inventory_ready(self):
        backend.patch_company_seal_policy(self.conn,self.company,{"owner_kind":"company"})
        for category,size,width,height in [("establishment_seal","large_seal",30,30),("establishment_seal","small_seal",18,18),("general_seal","large_seal",30,30),("general_seal","small_seal",18,18),("continuous_seal","single_seal",50,12)]:
            self.upload(self.create(category,size),width,height)
        report=backend.company_seal_policy_report(self.conn,self.company)
        self.assertTrue(report["ready"])
        self.assertEqual(len(report["required_slots"]),5)
        self.assertEqual(report["missing_slots"],[])
        self.assertFalse(report["physical_inventory_verified"])
        legacy,blockers=seal_policy.launch_inventory(self.company,"Synthetic company","company",backend.list_company_seals(self.conn,self.company))
        self.assertEqual(len(legacy["requiredSeals"]),5)
        self.assertEqual(blockers,[])
        audit={"dataReadiness":{"checks":{"companySeals":[legacy]}},"internalReadiness":{"checks":{}}}
        with mock.patch.object(backend,"current_go_live_audit_report",return_value=audit):
            ready=backend.current_seal_vault_readiness_report(self.conn)
        self.assertEqual(ready["requiredSealCount"],5)
        self.assertEqual(ready["currentSealCount"],5)
        self.assertFalse(ready["companyGroups"][0]["physical_inventory_verified"])

    def test_unclassified_inventory_is_blocked_even_with_all_common_digital_files(self):
        for category,size,width,height in [("general_seal","large_seal",30,30),("general_seal","small_seal",18,18),("continuous_seal","single_seal",50,12)]:
            self.upload(self.create(category,size),width,height)
        report,blockers=seal_policy.launch_inventory(self.company,"Synthetic company","unclassified",backend.list_company_seals(self.conn,self.company))
        self.assertEqual(len(report["requiredSeals"]),3)
        self.assertTrue(all(slot["currentFile"] for slot in report["requiredSeals"]))
        self.assertEqual(len(report["conditional_slots"]),4)
        self.assertEqual(len(blockers),1)
        audit={"dataReadiness":{"checks":{"companySeals":[report]}},"internalReadiness":{"checks":{}}}
        with mock.patch.object(backend,"current_go_live_audit_report",return_value=audit):
            ready=backend.current_seal_vault_readiness_report(self.conn)
        self.assertEqual(ready["decision"],"BLOCKED")
        self.assertEqual(ready["missingCount"],0)
        self.assertTrue(ready["companyGroups"][0]["classification_required"])

    def test_only_custodian_with_manage_permission_can_classify(self):
        employee = {"user": {"id": "EMPLOYEE", "company_id": self.company, "account_source": "finance", "status": "active", "role": "員工"}, "permissions": ["seals.manage"]}
        with self.assertRaises(PermissionError):
            backend.patch_company_seal_policy(self.conn, self.company, {"owner_kind": "company"}, employee)
        ceo = {"user": {**employee["user"], "role": "執行長"}, "permissions": []}
        with self.assertRaisesRegex(PermissionError, "manage_required"):
            backend.patch_company_seal_policy(self.conn, self.company, {"owner_kind": "company"}, ceo)

    def test_continuous_and_tall_official_uploads_keep_manual_dimensions(self):
        for category, size, width, height in [("continuous_seal", "single_seal", 50, 12), ("official_seal", "large_seal", 20, 60)]:
            with self.subTest(category=category):
                identity = self.create(category, size)
                backend.patch_company_seal_policy(self.conn, self.company, {"owner_kind": "institution" if category == "official_seal" else "company"})
                missing = backend.company_seal_row(self.conn, identity)
                self.assertIsNone(missing["render_width_mm"])
                self.assertIsNone(missing["render_height_mm"])
                result = self.upload(identity, width, height)["seal"]
                self.assertTrue(result["selectable"])
                self.assertEqual((result["render_width_mm"], result["render_height_mm"]), (width, height))
                current = result["current_file"]
                self.assertTrue(current["backing_metadata_valid"])
                self.assertTrue(current["backing_storage_exists"])
                self.assertNotIn("file_storage_key", current)
                self.assertNotIn("storage_key", current)

    def test_missing_or_mismatched_backing_cannot_be_selected(self):
        identity = self.create("general_seal")
        self.upload(identity)
        row = self.conn.execute("SELECT * FROM company_seal_files WHERE seal_id=?", (identity,)).fetchone()
        self.conn.execute("UPDATE file_objects SET sha256=? WHERE id=?", ("0" * 64, row["file_object_id"]))
        self.assertIsNone(backend.company_seal_row(self.conn, identity)["current_file"])
        with self.assertRaisesRegex(ValueError, "backing_unavailable"):
            backend.require_current_company_seal_file(self.conn, identity)
        self.conn.execute("UPDATE file_objects SET sha256=? WHERE id=?", (row["file_hash"], row["file_object_id"]))
        (backend.STORAGE_DIR / row["file_storage_key"]).unlink()
        self.assertFalse(backend.company_seal_row(self.conn, identity)["selectable"])

    def test_owner_policy_change_hides_new_choice_without_deleting_current_or_history(self):
        identity = self.create("official_seal")
        backend.patch_company_seal_policy(self.conn, self.company, {"owner_kind": "institution"})
        self.upload(identity, 20, 40)
        self.assertTrue(backend.company_seal_row(self.conn, identity)["selectable"])
        backend.patch_company_seal_policy(self.conn, self.company, {"owner_kind": "company"})
        row = backend.company_seal_row(self.conn, identity)
        self.assertFalse(row["selectable"])
        self.assertIsNotNone(row["current_file"])
        self.assertEqual(row["availability_reason"], "owner_policy_mismatch")
        with self.assertRaisesRegex(ValueError, "owner_policy_mismatch"):
            backend.validate_official_document_seal(self.conn, identity, self.company, require_current=True)

    def test_uploaded_seal_category_cannot_be_relabelled_into_a_different_family(self):
        identity = self.create("general_seal")
        self.upload(identity)
        with self.assertRaisesRegex(ValueError,"category_locked_after_upload"):
            backend.patch_company_seal(self.conn,identity,{"seal_category":"establishment_seal"})
        with self.assertRaisesRegex(sqlite3.IntegrityError,"category_locked_after_upload"):
            self.conn.execute("UPDATE company_seals SET seal_category='establishment_seal' WHERE id=?",(identity,))
        self.assertEqual(backend.company_seal_row(self.conn,identity)["seal_category"],"general_seal")

    def test_legacy_noncurrent_square_file_remains_valid_for_locked_replay(self):
        identity = self.create("general_seal")
        self.upload(identity)
        first = dict(self.conn.execute("SELECT * FROM company_seal_files WHERE seal_id=?", (identity,)).fetchone())
        self.upload(identity)
        historical = dict(self.conn.execute("SELECT * FROM company_seal_files WHERE id=?", (first["id"],)).fetchone())
        self.assertFalse(historical["is_current"])
        result = backend.require_seal_file_av_clean(self.conn, historical)
        self.assertEqual(result["id"], first["id"])
        self.assertEqual(backend.company_seal_file_dimension_profile("large_seal", result)["width_mm"], 30)

    def test_supabase_storage_probe_reads_only_one_private_range_byte(self):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 206
        response.__enter__.return_value.headers = {"Content-Range": "bytes 0-0/100"}
        response.__enter__.return_value.read.return_value = b"x"
        with mock.patch.object(backend, "object_storage_endpoint", return_value="https://synthetic.invalid/storage/v1"), mock.patch.object(backend, "supabase_storage_headers", side_effect=lambda extra: extra), mock.patch.object(backend, "_urlopen_no_redirect", return_value=response) as open_call:
            self.assertTrue(backend.supabase_seal_backing_exists({"bucket": backend.EDOC_SEAL_STORAGE_BUCKET, "storage_key": "seal-vault/seals/SYNTHETIC.png", "size_bytes": 100}))
            self.assertEqual(open_call.call_args.args[0].method, "GET")
            self.assertEqual(open_call.call_args.args[0].headers["Range"], "bytes=0-0")
            response.__enter__.return_value.read.assert_called_once_with(2)
            self.assertLessEqual(open_call.call_args.kwargs["timeout"], 2.0)

    def test_storage_metadata_is_not_blob_evidence_and_bad_ranges_are_rejected(self):
        file = {"bucket": backend.EDOC_SEAL_STORAGE_BUCKET, "storage_key": "seal-vault/seals/SYNTHETIC.png", "size_bytes": 100}
        for status, content_range, body in [(200,"",b"full object"),(404,"",b"not found"),(302,"",b"redirect"),(206,"bytes 0-2/100",b"xx"),(206,"bytes 0-0/0",b"x"),(206,"bytes 0-0/101",b"x"),(206,"bytes 0-0/100",b""),(206,"bytes 0-0/100",b"xx")]:
            with self.subTest(status=status,range=content_range,body_length=len(body)):
                response = mock.MagicMock()
                response.__enter__.return_value.status = status
                response.__enter__.return_value.headers = {"Content-Range": content_range}
                response.__enter__.return_value.read.return_value = body
                with mock.patch.object(backend,"object_storage_endpoint",return_value="https://synthetic.invalid/storage/v1"),mock.patch.object(backend,"supabase_storage_headers",return_value={}),mock.patch.object(backend,"_urlopen_no_redirect",return_value=response):
                    self.assertFalse(backend.supabase_seal_backing_exists(file))
                if status != 206 or content_range != "bytes 0-0/100":
                    response.__enter__.return_value.read.assert_not_called()

    def test_storage_probe_timeout_and_exhausted_budget_fail_closed(self):
        file = {"bucket": backend.EDOC_SEAL_STORAGE_BUCKET, "storage_key": "seal-vault/seals/SYNTHETIC.png", "size_bytes": 100}
        with mock.patch.object(backend,"object_storage_endpoint",return_value="https://synthetic.invalid/storage/v1"),mock.patch.object(backend,"supabase_storage_headers",return_value={}),mock.patch.object(backend,"_urlopen_no_redirect",side_effect=TimeoutError):
            self.assertFalse(backend.supabase_seal_backing_exists(file))
        token = backend._seal_storage_probe_budget.set(backend.time.monotonic()-1)
        try:
            with mock.patch.object(backend,"object_storage_endpoint",return_value="https://synthetic.invalid/storage/v1"),mock.patch.object(backend,"_urlopen_no_redirect") as opened:
                self.assertFalse(backend.supabase_seal_backing_exists(file))
                opened.assert_not_called()
        finally:
            backend._seal_storage_probe_budget.reset(token)


if __name__ == "__main__":
    unittest.main()
