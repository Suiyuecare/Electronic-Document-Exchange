#!/usr/bin/env python3
"""Current upload intent -> PostgREST -> frontend TUS -> current finalize.

Every application row, trigger, RPC and Storage operation is real on the
disposable loopback Supabase stack. The only transport adaptation is the exact
loopback Storage origin (the frontend runner maps its cloud-shaped origin).
An in-process synthetic own-company session replaces external Google SSO.
An EICAR-like marker verifies source PDFs bypass AV; image assets still use
the isolated scanner. No user document, hosted credential, seal or exchange
call is used.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.support.local_supabase_editor_filename_gate import image_bytes, pdf_bytes, run_frontend
from tests.support.local_supabase_editor_finalize_rpc_gate import run_sql, sql_literal

STAGE = "configuration"


class PipelineGateFailure(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise PipelineGateFailure(code)


def loopback_configuration():
    api_url = os.environ.get("EDOC_LOCAL_SUPABASE_URL", "").strip().rstrip("/")
    parsed = urlparse(api_url)
    require(parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
            and not parsed.username and not parsed.password,
            "pipeline_gate_loopback_required")
    key = os.environ.get("EDOC_LOCAL_SUPABASE_SERVICE_ROLE_KEY", "")
    anon = os.environ.get("EDOC_LOCAL_SUPABASE_ANON_KEY", "")
    require(key and anon, "pipeline_gate_local_credentials_missing")
    # Override all database/Storage destinations so inherited shell settings
    # cannot route an isolated CI credential to any other service.
    os.environ.update({
        "EDOC_DEPLOYMENT_ENV": "development", "EDOC_DB_MODE": "supabase",
        "SUPABASE_URL": api_url, "SUPABASE_SERVICE_ROLE_KEY": key,
        "SUPABASE_ANON_KEY": anon, "EDOC_SUPABASE_SCHEMA": "public",
        "EDOC_SUPABASE_BACKEND_ROLE": "service_role",
        "EDOC_STORAGE_PROVIDER": "supabase", "EDOC_STORAGE_BUCKET": "edoc-private",
        "EDOC_STORAGE_SUPABASE_URL": api_url, "EDOC_STORAGE_SERVICE_ROLE_KEY": key,
        "EDOC_STORAGE_SUPABASE_MODE": "same-project",
        "EDOC_OBJECT_STORAGE_URL": f"{api_url}/storage/v1",
        "EDOC_STORAGE_PUBLISHABLE_KEY": anon,
        "EDOC_LAUNCH_COMPANY_MODE": "finance_active",
        "EDOC_PDF_EDITOR_V2_COMPANY_MODE": "finance_active",
    })
    return api_url


def seed_draft(backend, document_id, company_id, actor):
    # Seed only the pre-existing draft boundary. In particular, assets and
    # lifecycle jobs must be inserted by the shipping upload-intent function.
    backend.supabase_insert("official_documents", {
        "id": document_id, "company_id": company_id, "document_type": "其他",
        "source_type": "uploaded_pdf", "title": "Synthetic pipeline gate",
        "subject": "Deidentified upload acceptance", "applicant_id": actor["id"],
        "applicant_name": actor["name"], "current_status": "draft",
        "request_reason": "Isolated integration test", "metadata_json": '{"pdf_editor_v2":true}',
    })
    backend._supabase_insert_editor_revision(document_id, {
        "schemaVersion": 2, "revisionNo": 1, "sourceFiles": [],
        "pages": [], "elements": [], "manifestSha256": "",
    }, actor)


def expect_rejected(callback, expected):
    try:
        callback()
    except (PermissionError, ValueError) as exc:
        require(str(exc) == expected, "pipeline_gate_wrong_rejection")
    else:
        raise PipelineGateFailure("pipeline_gate_expected_rejection_missing")


def restore_fixtures(document_ids, company_id, head):
    # Owner-only cleanup is restricted by loopback_configuration() and the
    # imported helper's hard-coded 127.0.0.1:54322 disposable database. No
    # trigger or role is disabled during the tested application operations.
    quoted = ",".join(sql_literal(value) for value in document_ids)
    if head is None:
        restore_head = "delete from edoc_private.audit_log_chain_heads where chain_version=2;"
    else:
        literal = lambda value: "null" if value is None else sql_literal(str(value))
        restore_head = f"""
          insert into edoc_private.audit_log_chain_heads
            (chain_version, head_hash, last_audit_id, updated_at)
          values (2, {literal(head['head_hash'])}, {literal(head['last_audit_id'])},
                  {literal(head['updated_at'])}::timestamptz)
          on conflict (chain_version) do update set head_hash=excluded.head_hash,
            last_audit_id=excluded.last_audit_id, updated_at=excluded.updated_at;
        """
    run_sql(f"""
      begin;
      lock table public.audit_logs in share row exclusive mode;
      set local session_replication_role=replica;
      delete from public.audit_logs where target_id in ({quoted});
      delete from public.official_document_approval_logs where document_id in ({quoted});
      delete from public.official_document_editor_storage_jobs where document_id in ({quoted});
      delete from public.official_document_editor_assets where document_id in ({quoted});
      delete from public.official_document_files where document_id in ({quoted});
      delete from public.file_objects where document_id in ({quoted});
      delete from public.official_document_editor_revisions where document_id in ({quoted});
      delete from public.official_documents where id in ({quoted});
      delete from public.companies where id={sql_literal(company_id)};
      {restore_head}
      commit;
    """)
    count = run_sql(
        f"select count(*) from public.official_documents where id in ({quoted});",
        tuples_only=True,
    )
    require(count == "0", "pipeline_gate_fixture_cleanup_incomplete")


def main():
    global STAGE
    api_url = loopback_configuration()
    require("backend" not in sys.modules, "pipeline_gate_backend_imported_before_origin_guard")
    import backend
    require(backend.SUPABASE_URL == api_url and backend.object_storage_endpoint() == f"{api_url}/storage/v1"
            and not backend.is_production(), "pipeline_gate_runtime_origin_mismatch")
    # Cloud URL syntax is the sole backend adaptation. Do not mock inserts,
    # row reads, access checks, scans, PDF inspection, promotion or finalize.
    backend._supabase_storage_endpoint_issue = lambda: ""
    suffix = uuid.uuid4().hex[:12].upper()
    company_id = f"CI-UPIPE-CO-{suffix}"
    actor = {"id": f"CI-UPIPE-USER-{suffix}", "name": "CI Synthetic Applicant",
             "company_id": company_id, "role": "員工"}
    session = {"user": actor, "permissions": ["official_documents.compose"]}
    head = json.loads(run_sql(
        "select coalesce(row_to_json(h)::text, 'null') from "
        "(select head_hash,last_audit_id,updated_at from edoc_private.audit_log_chain_heads "
        "where chain_version=2) h;", tuples_only=True,
    ) or "null")
    small_pdf = pdf_bytes()
    cases = [
        ("source_chinese", "驗收 聘僱合約.pdf", "application/pdf", "source_pdf", small_pdf, ""),
        ("import_symbols", "résumé [50%] 📄.pdf", "application/pdf", "import_pdf", small_pdf, ""),
        ("png_image", "驗收 圖片.png", "image/png", "image", image_bytes("PNG"), ""),
        ("jpeg_image", "驗收 圖片.jpeg", "image/jpeg", "image", image_bytes("JPEG"), ""),
        ("source_resume", "驗收 續傳.pdf", "application/pdf", "source_pdf", pdf_bytes(large=True), ""),
        ("hash_mismatch", "synthetic-mismatch.pdf", "application/pdf", "source_pdf", small_pdf, "editor_upload_hash_mismatch"),
        ("pdf_no_av_scan", "synthetic-eicar.pdf", "application/pdf", "source_pdf",
         small_pdf + b"\n%EICAR-STANDARD-ANTIVIRUS-TEST-FILE\n", ""),
    ]
    document_ids = [f"CI-UPIPE-DOC-{index}-{suffix}" for index in range(len(cases))]
    cleanup = set()
    results = []
    try:
        STAGE = "seed_company"
        backend.supabase_insert("companies", {"id": company_id, "name": "CI Synthetic Company", "status": "active"})
        for document_id, case in zip(document_ids, cases):
            label, file_name, mime_type, kind, data, rejection = case
            STAGE = f"seed_draft:{label}"
            seed_draft(backend, document_id, company_id, actor)
            digest = hashlib.sha256(data).hexdigest().upper()
            committed_digest = "A" * 64 if label == "hash_mismatch" else digest
            payload = {"file_name": file_name, "mime_type": mime_type, "asset_kind": kind,
                       "size_bytes": len(data), "sha256": committed_digest}
            outsider = {**session, "user": {**actor, "id": actor["id"] + "-OTHER"}}
            expect_rejected(lambda: backend.supabase_create_official_editor_upload_intent(
                document_id, payload, outsider), "official_editor_write_forbidden")
            require(not backend.supabase_filter_rows("official_document_editor_assets", {"document_id": document_id}),
                    "pipeline_gate_foreign_actor_created_asset")
            STAGE = f"create_intent:{label}"
            intent = backend.supabase_create_official_editor_upload_intent(document_id, payload, session)
            asset_id = intent["upload_id"]
            cleanup.add(intent["path"])
            assets = backend.supabase_filter_rows("official_document_editor_assets", {"id": asset_id})
            jobs = backend.supabase_filter_rows("official_document_editor_storage_jobs", {"asset_id": asset_id})
            require(len(assets) == 1 and len(jobs) == 1, "pipeline_gate_durable_rows_missing")
            asset, job = assets[0], jobs[0]
            cleanup.add(job["final_path"])
            require(asset["file_name"] == file_name and intent["asset"]["fileName"] == file_name
                    and json.loads(asset["metadata_json"])["storage_key_version"] == 2,
                    "pipeline_gate_original_name_or_key_version_changed")
            require(job["status"] == "pending" and job["staging_path"] == intent["path"]
                    and re.fullmatch(r"[A-Za-z0-9_./-]+", job["final_path"]),
                    "pipeline_gate_durable_path_binding_invalid")
            STAGE = f"frontend_tus:{label}"
            uploaded = run_frontend(api_url, intent, data, file_name, mime_type,
                                    interrupt=label == "source_resume")
            require(uploaded["ok"] and uploaded["offset"] == len(data)
                    and uploaded["progressComplete"], "pipeline_gate_tus_failed")
            if label == "source_resume":
                require(uploaded["interrupted"] and any(row["method"] == "HEAD" for row in uploaded["trace"]),
                        "pipeline_gate_resume_not_exercised")
            expect_rejected(lambda: backend.supabase_finalize_official_editor_upload(
                document_id, asset_id, {"sha256": digest}, outsider), "official_editor_write_forbidden")
            STAGE = f"finalize:{label}"
            if rejection:
                expect_rejected(lambda: backend.supabase_finalize_official_editor_upload(
                    document_id, asset_id, {"sha256": committed_digest}, session), rejection)
                failed = backend.supabase_get("official_document_editor_assets", asset_id)
                require(failed["upload_status"] == "failed"
                        and not failed["file_object_id"]
                        and backend._supabase_editor_latest_revision(document_id)["revision_no"] == 1,
                        "pipeline_gate_failure_not_atomic")
                expect_rejected(lambda: backend.supabase_finalize_official_editor_upload(
                    document_id, asset_id, {"sha256": committed_digest}, session), "editor_upload_new_intent_required")
                results.append({"case": label, "passed": True, "rejected_fail_closed": True})
                continue
            finalized = backend.supabase_finalize_official_editor_upload(
                document_id, asset_id, {"sha256": digest}, session)
            STAGE = f"verify_committed:{label}"
            committed = backend.supabase_get("official_document_editor_assets", asset_id)
            committed_job = backend.supabase_get("official_document_editor_storage_jobs", job["id"])
            expected_scan_status = "not_scanned" if kind in {"source_pdf", "import_pdf"} else "passed"
            require(committed["upload_status"] == "finalized" and committed["preflight_status"] == "passed"
                    and committed["scan_status"] == expected_scan_status and committed["sha256"] == digest
                    and committed["storage_path"] == job["final_path"] and committed_job["status"] == "committed"
                    and committed["file_object_id"] == committed_job["final_file_object_id"],
                    "pipeline_gate_finalize_not_committed")
            final_data = backend.supabase_storage_download(committed["storage_path"], "edoc-private")
            require(hashlib.sha256(final_data).hexdigest().upper() == digest,
                    "pipeline_gate_final_bytes_changed")
            state = backend.supabase_get_official_editor_state(document_id, session)
            require(state["revisionNo"] == 2 and finalized["editor_revision"]["revisionNo"] == 2,
                    "pipeline_gate_editor_revision_missing")
            if mime_type == "application/pdf":
                require(len(finalized["pages"]) == 1 and len(state["state"]["pages"]) == 1,
                        "pipeline_gate_editable_pdf_pages_missing")
            STAGE = f"retry_finalize:{label}"
            repeated = backend.supabase_finalize_official_editor_upload(
                document_id, asset_id, {"sha256": digest}, session)
            require(repeated["asset"]["id"] == asset_id
                    and backend._supabase_editor_latest_revision(document_id)["revision_no"] == 2
                    and len(backend.supabase_filter_rows("official_document_approval_logs", {"document_id": document_id,
                                                                                         "action": "finalize_editor_upload"})) == 1,
                    "pipeline_gate_finalize_retry_not_idempotent")
            results.append({"case": label, "passed": True, "real_intent_rows": True,
                            "real_finalize_rpc": True, "source_and_final_hash_match": True,
                            "editor_revision_loaded": True, "idempotent_finalize": True,
                            "resumed": uploaded["interrupted"], "foreign_actor_denied": True,
                            "scan_status": committed["scan_status"]})
    finally:
        original_error = sys.exc_info()[1]
        for path in cleanup:
            try:
                backend.supabase_storage_delete(path, "edoc-private")
            except Exception:
                pass
        try:
            restore_fixtures(document_ids, company_id, head)
        except Exception:
            # Preserve the first failing application boundary. An immutable
            # cleanup error must never obscure a trigger/RPC regression.
            if original_error is None:
                raise PipelineGateFailure("pipeline_gate_fixture_cleanup_failed") from None
            print("pipeline_gate_fixture_cleanup_also_failed", file=sys.stderr)
    report = {"passed": True, "cases": results, "real_postgrest_application_rows": True,
              "real_postgres_triggers_and_finalize_rpc": True, "real_loopback_storage": True,
              "production_tus_client_executed": True, "current_backend_intent_and_finalize": True,
              "application_database_mocks": False, "auth": "synthetic_in_process_session",
              "scanner": "unchanged_nonproduction_eicar", "hosted_storage_tested": False,
              "physical_browser_tested": False, "submitted_or_stamped": False}
    target = ROOT / "tests/.artifacts/editor-upload-pipeline/report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except PipelineGateFailure as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        # Even on failure, never print PostgREST text, signed tokens or paths.
        # Stable backend machine codes help locate the failed boundary in CI.
        message = str(exc)
        code = message if re.fullmatch(r"(?:editor|supabase|pipeline_gate)_[a-z0-9_]+(?::[0-9]{3})?", message) else "unexpected"
        print(f"pipeline_gate_integration_failed:{STAGE}:{code}", file=sys.stderr)
        raise SystemExit(1) from None
