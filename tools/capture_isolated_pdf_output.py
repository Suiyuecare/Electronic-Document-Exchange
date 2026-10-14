"""Retain an existing product-download response for read-only PDF visual QA.

This executes the deidentified local HTTP fixture. It does not author a new
user PDF, reuse a real company seal, contact production, or attest human SSO.
Only the exact product bytes matching the stamped_file SHA256 are retained.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend
from tests.test_six_role_complete_flow import fixture_class
from tools.complete_role_flow_acceptance import loopback_only, source_digest


def _capture_uploaded_output():
    downloaded = {}
    fixture = fixture_class()
    fixture.setUpClass()
    try:
        request = fixture._request
        def retain(cls, method, path, **kwargs):
            result = request(method, path, **kwargs)
            if result.status == 200 and path.endswith("/download") and result.body.startswith(b"%PDF"):
                downloaded[backend.sha256_bytes(result.body)] = result.body
            return result
        with mock.patch.object(fixture, "_request", classmethod(retain)):
            tokens = {case["ordinal"]: fixture._portal_session(case["email"])
                      for case in fixture.case_definitions}
            case = next(case for case in fixture.case_definitions if case["role"] == "staff")
            row = fixture._run_case(case, tokens)
            retained = downloaded.get(row["stampedSha256"])
            if not retained or backend.sha256_bytes(retained) != row["stampedSha256"]:
                raise AssertionError("pdf_qa_product_download_hash_mismatch")
    finally:
        fixture.tearDownClass()
    return retained, {"pdf_sha256": row["stampedSha256"], "pages": row["pageCount"],
        "orientations": row["orientations"], "original_sha256": row["sourceSha256"],
        "prepared_sha256": row["preparedSha256"],
        "text_content_scope": "existing Latin fixture marker; no Chinese glyph attestation"}


def _capture_compose_output():
    from tests.test_compose_multiseal import ComposeMultiSealBackendTest
    fixture = ComposeMultiSealBackendTest("test_full_approval_uses_both_locked_assets_even_after_small_current_version_changes")
    fixture.setUp()
    try:
        # The legacy fixture contains company-shaped contact defaults. Replace
        # visible contacts in this temporary database before the existing
        # product workflow runs; no real private data belongs in QA evidence.
        fixture.conn.execute("UPDATE companies SET name='合成驗收公司',address='合成測試地址' WHERE id='CO-001'")
        fixture.conn.execute("UPDATE users SET name='合成簽核人-'||id,email='synthetic-'||id||'@example.invalid',company_name='合成驗收公司',company_address='合成測試地址' WHERE company_id='CO-001'")
        fixture.session["user"].update(name="合成申請人", email="synthetic@example.invalid",
                                        company_name="合成驗收公司", company_address="合成測試地址")
        with mock.patch.object(backend, "EDOC_DEFAULT_CONTACT_PHONE", "000-0000000"):
            fixture.test_full_approval_uses_both_locked_assets_even_after_small_current_version_changes()
        meta = fixture.conn.execute("SELECT f.file_hash,f.file_object_id FROM official_document_files f WHERE f.file_type='stamped_pdf'").fetchall()
        if len(meta) != 1:
            raise AssertionError("pdf_qa_compose_output_not_unique")
        _, retained = backend.read_file_object_bytes(fixture.conn, meta[0]["file_object_id"])
        if not retained or backend.sha256_bytes(retained) != meta[0]["file_hash"]:
            raise AssertionError("pdf_qa_product_download_hash_mismatch")
        return retained, {"pdf_sha256": meta[0]["file_hash"], "pages": 1,
            "orientations": ["portrait"], "deidentified_contacts": True,
            "text_content_scope": "existing Chinese synthetic compose fixture with synthetic visible contacts"}
    finally:
        fixture.tearDown()


def capture(destination: Path, profile="uploaded") -> dict:
    if profile not in {"uploaded", "compose"}:
        raise ValueError("pdf_qa_profile_invalid")
    filename = "synthetic-stamped-two-page.pdf" if profile == "uploaded" else "synthetic-compose-chinese.pdf"
    destination = destination.expanduser().absolute()
    if destination.is_symlink() or destination.resolve().is_relative_to(ROOT):
        raise ValueError("pdf_qa_destination_must_be_private_outside_repository")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    for name in (filename, "capture.json"):
        if (destination / name).exists() or (destination / name).is_symlink():
            raise ValueError("pdf_qa_output_already_exists")
    source_before = source_digest()
    with loopback_only():
        retained, details = _capture_uploaded_output() if profile == "uploaded" else _capture_compose_output()
    path = destination / filename
    with path.open("xb") as stream:
        stream.write(retained)
    os.chmod(path, 0o600)
    record = {"schema_version": 1, "scope": "isolated_product_download_visual_qa",
              "recorded_at": datetime.now(timezone.utc).isoformat(),
              **details, "bytes": len(retained),
              "synthetic_seal_only": True, "real_human_sso_verified": False,
              "government_exchange": "DISABLED", "production_accounts_changed": False,
              "source_unchanged": source_before == source_digest()}
    with (destination / "capture.json").open("x") as stream:
        json.dump(record, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    os.chmod(destination / "capture.json", 0o600)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("uploaded", "compose"), default="uploaded")
    args = parser.parse_args(argv)
    print(json.dumps(capture(args.output, args.profile), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
