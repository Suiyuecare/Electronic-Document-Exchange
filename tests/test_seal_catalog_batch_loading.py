"""Read-only catalog performance must not turn slow I/O into absent stamps."""
import copy
import io
import unittest
import urllib.error
import urllib.parse
from contextlib import ExitStack
from unittest import mock

import backend
import seal_scan_exceptions as original200
import seal_scan_20261013 as native120


def registered_seal(values, policy):
    digest, company, seal_id, category, size, w, h, mw, mh, _page = values
    file = {"id": "FILE-" + seal_id, "seal_id": seal_id, "file_object_id": "OBJ-" + seal_id,
            "file_hash": digest, "version": 1, "is_current": True,
            "pixel_width": w, "pixel_height": h, "source_aspect_ratio": w / h,
            "render_width_mm": mw, "render_height_mm": mh,
            "dimension_policy_version": policy, "dimension_validated": True,
            "file_mime_type": "image/png", "file_size": 123,
            "file_storage_key": "private/" + seal_id + ".png"}
    file["backing"] = {"id": file["file_object_id"], "sha256": digest,
                       "size_bytes": 123, "mime_type": "image/png",
                       "storage_key": file["file_storage_key"],
                       "bucket": backend.EDOC_SEAL_STORAGE_BUCKET, "scan_status": "clean"}
    return {"id": seal_id, "company_id": company, "seal_category": category,
            "seal_size_type": size, "is_active": True, "files": [file]}


def ordinary_seal(index=0, company="CO-SYNTHETIC"):
    return registered_seal(("a" * 64, company, f"SEAL-{index}", "general_seal", "large_seal",
                            400, 400, 30, 30, 1), backend.EDOC_SEAL_DIMENSION_POLICY_VERSION)


class SealCatalogBatchTests(unittest.TestCase):
    def catalog(self, seals, owner="company", *, company_id=None, editor=True):
        company_id = company_id or (seals[0]["company_id"] if seals else "CO-SYNTHETIC")
        snapshot = [{"id": company_id, "name": "Synthetic", "tax_id": "",
                     "owner_policy": {"owner_kind": owner}, "seals": copy.deepcopy(seals)}]
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(backend, "assert_editor_seal_catalog_company"))
            stack.enter_context(mock.patch.object(backend, "supabase_official_session_user", return_value={"id": "synthetic"}))
            stack.enter_context(mock.patch.object(backend, "assert_supabase_seal_company_access"))
            request = stack.enter_context(mock.patch.object(backend, "supabase_request", return_value=snapshot))
            stack.enter_context(mock.patch.object(backend, "supabase_get", side_effect=AssertionError("N+1 read")))
            stack.enter_context(mock.patch.object(backend, "supabase_filter_rows", side_effect=AssertionError("N+1 filter")))
            probe = stack.enter_context(mock.patch.object(backend, "supabase_seal_backing_exists", side_effect=AssertionError("catalog private-byte fetch")))
            result = backend.supabase_list_company_seals(company_id, {"user": {"id": "synthetic"}}, editor=editor)
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args.args[1]).query)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(query["id"], ["eq." + company_id])
            self.assertEqual(query["seals.files.is_current"], ["eq.true"])
            self.assertEqual(query["seals.files.limit"], ["2"])
            probe.assert_not_called()
            return result

    def test_original200_co005_bank_rows_cannot_hide_later_official_stamp(self):
        seals = [registered_seal(r, original200.POLICY) for r in original200._ROWS if r[1] == "CO-005"]
        seals.sort(key=lambda r: r["seal_category"])
        token = backend._seal_storage_probe_budget.set(-1)
        try:
            result = self.catalog(seals, "institution")
        finally:
            backend._seal_storage_probe_budget.reset(token)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["seal_category"], "official_seal")
        self.assertTrue(result[0]["selectable"])
        self.assertTrue(result[0]["current_file"]["usable"])
        self.assertEqual(result[0]["availability_basis"], "registered_metadata")
        self.assertEqual(result[0]["storage_verification"], "required_on_use")
        self.assertNotIn("backing_storage_exists", str(result))
        self.assertNotIn("storage_key", str(result))

    def test_native120_all_three_units_keep_exact_locked_current_metadata(self):
        for company in sorted({r[1] for r in native120._ROWS}):
            seals = [registered_seal(r, native120.POLICY) for r in native120._ROWS if r[1] == company]
            result = self.catalog(seals, "company" if company == "CO-007" else "institution")
            self.assertEqual(len(result), 2)
            self.assertTrue(all(row["selectable"] for row in result))
            self.assertEqual({r["current_file"]["file_hash"] for r in result}, {r["files"][0]["file_hash"] for r in seals})
            self.assertTrue(all(r["current_file"]["dimension_policy_version"] == native120.POLICY for r in result))

    def test_roundtrips_remain_constant_for_empty_one_and_many_catalogs(self):
        for count in (0, 1, 30, 500):
            with self.subTest(count=count):
                result = self.catalog([ordinary_seal(i) for i in range(count)])
                self.assertEqual(len(result), count)
                self.assertTrue(all(r["selectable"] for r in result))

    def test_invalid_registration_is_never_enabled_by_catalog_fast_path(self):
        mutations = (
            lambda s: s["files"][0].update(backing=None),
            lambda s: s["files"][0]["backing"].update(sha256="b" * 64),
            lambda s: s["files"][0]["backing"].update(scan_status="quarantined"),
            lambda s: s["files"][0]["backing"].update(bucket="public"),
            lambda s: s["files"][0].update(dimension_validated=False),
            lambda s: s["files"][0].update(render_width_mm=55),
            lambda s: s.update(files=[]),
        )
        for mutate in mutations:
            seal = ordinary_seal()
            mutate(seal)
            result = self.catalog([seal])
            self.assertFalse(result[0]["selectable"])
            self.assertIsNone(result[0]["current_file"])

    def test_owner_classification_and_inactive_stamps_still_fail_closed(self):
        seal = registered_seal(native120._ROWS[0], native120.POLICY)
        for owner, reason in (("institution", "owner_policy_mismatch"), ("unclassified", "classification_required")):
            result = self.catalog([seal], owner)
            self.assertFalse(result[0]["selectable"])
            self.assertEqual(result[0]["availability_reason"], reason)
        seal["is_active"] = False
        self.assertEqual(self.catalog([seal]), [])

    def test_unknown_storage_state_is_not_claimed_as_present(self):
        seal = ordinary_seal()
        file = seal["files"][0]
        status = backend._supabase_seal_file_status_from_rows(file, seal, file["backing"], verify_storage=False)
        self.assertIsNone(status["backing_storage_exists"])
        self.assertEqual(status["storage_verification"], "required_on_use")
        self.assertTrue(status["usable"])

    def test_catalog_errors_propagate_instead_of_successful_empty_list(self):
        errors = [TimeoutError("synthetic timeout"), RuntimeError("supabase_request_failed:403")]
        for error in errors:
            with mock.patch.object(backend, "assert_editor_seal_catalog_company"), \
                    mock.patch.object(backend, "supabase_official_session_user", return_value={}), \
                    mock.patch.object(backend, "supabase_request", side_effect=error):
                with self.assertRaises(type(error)):
                    backend.supabase_list_company_seals("CO-SYNTHETIC", {}, editor=True)

    def test_bad_embedded_current_or_cross_company_response_is_not_partial_success(self):
        for mutate, expected in (
            (lambda s: s.update(company_id="CO-OTHER"), "response_invalid"),
            (lambda s: s.update(files=[*s["files"], *s["files"]]), "current_conflict"),
            (lambda s: s["files"][0].update(is_current=False), "response_invalid"),
            (lambda s: s["files"][0].update(seal_id="OTHER"), "response_invalid"),
        ):
            seal = ordinary_seal()
            mutate(seal)
            with self.assertRaisesRegex(RuntimeError, expected):
                self.catalog([seal], company_id="CO-SYNTHETIC")

    def test_strict_current_file_check_still_rejects_missing_timeout_and_forbidden_blob(self):
        seal = ordinary_seal()
        file = seal["files"][0]
        for failure in (TimeoutError("synthetic timeout"),
                        urllib.error.HTTPError("https://synthetic.invalid", 404, "missing", {}, io.BytesIO(b"")),
                        urllib.error.HTTPError("https://synthetic.invalid", 403, "forbidden", {}, io.BytesIO(b""))):
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(backend, "supabase_filter_rows", return_value=[file]), \
                    mock.patch.object(backend, "supabase_get", side_effect=lambda table, _id: file["backing"] if table == "file_objects" else seal), \
                    mock.patch.object(backend, "object_storage_endpoint", return_value="https://synthetic.invalid/storage/v1"), \
                    mock.patch.object(backend, "supabase_storage_headers", return_value={}), \
                    mock.patch.object(backend, "_urlopen_no_redirect", side_effect=failure) as probe:
                with self.assertRaisesRegex(ValueError, "current_seal_backing_unavailable"):
                    backend.supabase_require_current_company_seal_file(seal["id"])
                probe.assert_called_once()


if __name__ == "__main__":
    unittest.main()
