#!/usr/bin/env python3
"""Exercise the editor-finalize RPC against the isolated local Supabase stack.

The five-account acceptance suite intentionally keeps its application records in
SQLite so each browser journey is hermetic.  This gate closes the remaining
boundary: it calls PostgREST with the local service-role credential and proves
that the PostgreSQL RPC commits (or rolls back) every editor row atomically.

No production URL or credential is accepted.  Fixture values are synthetic and
the service-role token is read only from the local ``supabase status -o env``
output supplied by CI; it is never printed.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import uuid
from typing import Any
from urllib import error, parse, request


LOCAL_HOSTS = {"127.0.0.1", "localhost"}
RPC_PATH = "/rest/v1/rpc/edoc_finalize_editor_asset_v2"
DB_HOST = "127.0.0.1"
DB_PORT = "54322"
DB_NAME = "postgres"
DB_USER = "postgres"


class GateFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_sql(sql: str, *, tuples_only: bool = False) -> str:
    command = [
        "psql",
        "--host",
        DB_HOST,
        "--port",
        DB_PORT,
        "--username",
        DB_USER,
        "--dbname",
        DB_NAME,
        "--set",
        "ON_ERROR_STOP=1",
        "--no-psqlrc",
    ]
    if tuples_only:
        command.extend(["--tuples-only", "--no-align"])
    env = {**os.environ, "PGPASSWORD": "postgres"}
    completed = subprocess.run(
        command,
        input=sql,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        # psql may include SQL text but never receives the service-role token.
        diagnostic = completed.stderr.strip().splitlines()[-1:] or ["unknown"]
        raise GateFailure(f"local_editor_finalize_sql_failed:{diagnostic[0][:240]}")
    return completed.stdout.strip()


def api_call(
    api_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    outbound = request.Request(api_url.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with request.urlopen(outbound, timeout=15) as response:
            raw = response.read(512 * 1024)
            return response.status, json.loads(raw.decode("utf-8")) if raw else None
    except error.HTTPError as exc:
        try:
            raw = exc.read(64 * 1024)
        finally:
            exc.close()
        try:
            decoded: Any = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = {"code": "non_json_error"}
        return exc.code, decoded


def rows(api_url: str, service_key: str, table: str, filters: dict[str, str]) -> list[dict[str, Any]]:
    query = {"select": "*", **{key: f"eq.{value}" for key, value in filters.items()}}
    status, payload = api_call(
        api_url,
        service_key,
        "GET",
        f"/rest/v1/{table}?{parse.urlencode(query)}",
    )
    require(status == 200 and isinstance(payload, list), f"local_editor_finalize_read_failed:{table}:{status}")
    return payload


def rpc(api_url: str, key: str, payload: dict[str, Any]) -> tuple[int, Any]:
    return api_call(api_url, key, "POST", RPC_PATH, {"p_request": payload})


def normalized_rpc_result(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return payload[0]
    return payload if isinstance(payload, dict) else {}


def exercise_service_role_data_api(
    api_url: str,
    service_key: str,
    anon_key: str,
) -> None:
    """Prove the fresh-project login and audit-view grants through PostgREST."""

    suffix = uuid.uuid4().hex[:12].upper()
    login_event_id = f"LOGIN-CI-GRANT-{suffix}"
    encoded_id = parse.urlencode({"id": f"eq.{login_event_id}"})

    status, payload = api_call(
        api_url,
        service_key,
        "GET",
        "/rest/v1/users?select=id&limit=1",
    )
    require(status == 200 and isinstance(payload, list), f"local_service_users_read_failed:{status}")

    status, _ = api_call(
        api_url,
        anon_key,
        "GET",
        "/rest/v1/users?select=id&limit=1",
    )
    require(status in {401, 403}, f"local_anon_users_read_not_denied:{status}")

    status, payload = api_call(
        api_url,
        service_key,
        "GET",
        "/rest/v1/audit_log_chain_check?select=id,hash_valid&limit=1",
    )
    require(status == 200 and isinstance(payload, list), f"local_service_audit_view_failed:{status}")

    status, _ = api_call(
        api_url,
        anon_key,
        "GET",
        "/rest/v1/audit_log_chain_check?select=id&limit=1",
    )
    require(status in {401, 403}, f"local_anon_audit_view_not_denied:{status}")

    try:
        status, _ = api_call(
            api_url,
            service_key,
            "POST",
            "/rest/v1/login_events",
            {
                "id": login_event_id,
                "email": "ci-service-grant@example.invalid",
                "provider": "CI isolated PostgREST gate",
                "ip": "127.0.0.1",
                "device": "GitHub Actions local Supabase",
                "status": "成功",
                "reason": "deidentified service-role grant verification",
                "created_at": "2099-01-01 00:00:00",
            },
        )
        require(status == 201, f"local_service_login_event_insert_failed:{status}")

        status, payload = api_call(
            api_url,
            service_key,
            "GET",
            f"/rest/v1/login_events?select=id,email&{encoded_id}",
        )
        require(
            status == 200
            and isinstance(payload, list)
            and len(payload) == 1
            and payload[0].get("id") == login_event_id,
            f"local_service_login_event_read_failed:{status}",
        )

        status, _ = api_call(
            api_url,
            service_key,
            "PATCH",
            f"/rest/v1/login_events?{encoded_id}",
            {"reason": "must remain immutable"},
        )
        require(status in {401, 403}, f"local_service_login_event_update_not_denied:{status}")

        status, _ = api_call(
            api_url,
            service_key,
            "DELETE",
            f"/rest/v1/login_events?{encoded_id}",
        )
        require(status in {401, 403}, f"local_service_login_event_delete_not_denied:{status}")
    finally:
        # Cleanup uses the isolated local postgres owner because the runtime
        # role is deliberately append-only for login evidence.
        run_sql(
            "delete from public.login_events where id = "
            + sql_literal(login_event_id)
            + ";"
        )


def main() -> int:
    api_url = os.environ.get("EDOC_LOCAL_SUPABASE_URL", "").strip()
    service_key = os.environ.get("EDOC_LOCAL_SUPABASE_SERVICE_ROLE_KEY", "").strip()
    anon_key = os.environ.get("EDOC_LOCAL_SUPABASE_ANON_KEY", "").strip()
    parsed_url = parse.urlparse(api_url)
    require(
        parsed_url.scheme == "http" and parsed_url.hostname in LOCAL_HOSTS,
        "local_editor_finalize_requires_loopback_supabase",
    )
    require(bool(service_key and anon_key), "local_editor_finalize_local_credentials_missing")

    exercise_service_role_data_api(api_url, service_key, anon_key)

    suffix = uuid.uuid4().hex[:12].upper()
    company_id = f"CI-EFIN-CO-{suffix}"
    other_company_id = f"CI-EFIN-XCO-{suffix}"
    applicant_id = f"CI-EFIN-USER-{suffix}"
    success_document_id = f"CI-EFIN-DOC-OK-{suffix}"
    rollback_document_id = f"CI-EFIN-DOC-RB-{suffix}"
    success_asset_id = f"CI-EFIN-ASSET-OK-{suffix}"
    rollback_asset_id = f"CI-EFIN-ASSET-RB-{suffix}"
    success_base_id = f"CI-EFIN-BASE-OK-{suffix}"
    rollback_base_id = f"CI-EFIN-BASE-RB-{suffix}"
    digest = "a" * 64
    manifest = "b" * 64
    file_size = 2048
    created_at = "2099-01-01 00:00:00"

    ids = {
        "operation": f"CI-EFIN-OP-{suffix}",
        "audit": f"CI-EFIN-AUD-{suffix}",
        "file": f"CI-EFIN-FILE-{suffix}",
        "official_file": f"CI-EFIN-ODFILE-{suffix}",
        "revision": f"CI-EFIN-REV-{suffix}",
        "rollback_operation": f"CI-EFIN-RBOP-{suffix}",
        "rollback_audit": f"CI-EFIN-RBAUD-{suffix}",
        "rollback_file": f"CI-EFIN-RBFILE-{suffix}",
        "rollback_official_file": f"CI-EFIN-RBODFILE-{suffix}",
        "rollback_revision": f"CI-EFIN-RBREV-{suffix}",
    }

    head_snapshot = run_sql(
        "select coalesce(row_to_json(head)::text, 'null') "
        "from (select chain_version, head_hash, last_audit_id, updated_at "
        "from edoc_private.audit_log_chain_heads where chain_version = 2) head;",
        tuples_only=True,
    )
    head = json.loads(head_snapshot or "null")

    setup_sql = f"""
      begin;
      insert into public.companies (id, name, tax_id, status, created_at, updated_at)
      values
        ({sql_literal(company_id)}, 'CI 去識別化測試公司', null, 'active', {sql_literal(created_at)}, {sql_literal(created_at)}),
        ({sql_literal(other_company_id)}, 'CI 隔離測試公司', null, 'active', {sql_literal(created_at)}, {sql_literal(created_at)});

      insert into public.official_documents (
        id, company_id, document_type, source_type, title, subject, applicant_id,
        applicant_name, current_status, request_reason, metadata_json, created_at, updated_at
      ) values
        ({sql_literal(success_document_id)}, {sql_literal(company_id)}, '其他', 'uploaded_pdf',
         'CI editor finalize atomic gate', 'deidentified', {sql_literal(applicant_id)},
         'CI Applicant', 'draft', 'atomic contract verification', '{{}}', {sql_literal(created_at)}, {sql_literal(created_at)}),
        ({sql_literal(rollback_document_id)}, {sql_literal(company_id)}, '其他', 'uploaded_pdf',
         'CI editor finalize rollback gate', 'deidentified', {sql_literal(applicant_id)},
         'CI Applicant', 'draft', 'rollback contract verification', '{{}}', {sql_literal(created_at)}, {sql_literal(created_at)});

      insert into public.official_document_editor_revisions (
        id, document_id, revision_no, parent_revision_id, schema_version,
        editor_state_json, manifest_sha256, renderer_version, created_by, created_at
      ) values
        ({sql_literal(success_base_id)}, {sql_literal(success_document_id)}, 1, null, 2,
         '{{"schemaVersion":2,"revisionNo":1,"sourceFiles":[],"pages":[],"elements":[]}}',
         repeat('1', 64), 'ci-gate', {sql_literal(applicant_id)}, {sql_literal(created_at)}),
        ({sql_literal(rollback_base_id)}, {sql_literal(rollback_document_id)}, 1, null, 2,
         '{{"schemaVersion":2,"revisionNo":1,"sourceFiles":[],"pages":[],"elements":[]}}',
         repeat('2', 64), 'ci-gate', {sql_literal(applicant_id)}, {sql_literal(created_at)});

      insert into public.official_document_editor_assets (
        id, document_id, editor_revision_id, asset_kind, file_name, mime_type,
        size_bytes, sha256, expected_sha256, storage_bucket, storage_path,
        upload_status, scan_status, preflight_status, page_count, metadata_json,
        created_by, created_at
      ) values
        ({sql_literal(success_asset_id)}, {sql_literal(success_document_id)}, null, 'source_pdf',
         'ci-deidentified.pdf', 'application/pdf', {file_size}, '', {sql_literal(digest)},
         'edoc-private', {sql_literal('editor/' + success_document_id + '/source.pdf')},
         'uploaded', 'pending', 'pending', 0, '{{"base_revision_no":1}}',
         {sql_literal(applicant_id)}, {sql_literal(created_at)}),
        ({sql_literal(rollback_asset_id)}, {sql_literal(rollback_document_id)}, null, 'source_pdf',
         'ci-deidentified-rollback.pdf', 'application/pdf', {file_size}, '', {sql_literal(digest)},
         'edoc-private', {sql_literal('editor/' + rollback_document_id + '/source.pdf')},
         'uploaded', 'pending', 'pending', 0, '{{"base_revision_no":1}}',
         {sql_literal(applicant_id)}, {sql_literal(created_at)});
      commit;
    """
    run_sql(setup_sql)

    def payload_for(
        *,
        document_id: str,
        asset_id: str,
        base_id: str,
        operation_id: str,
        audit_id: str,
        file_id: str,
        official_file_id: str,
        revision_id: str,
    ) -> dict[str, Any]:
        storage_path = f"editor/{document_id}/source.pdf"
        return {
            "operation_id": operation_id,
            "document_id": document_id,
            "applicant_id": applicant_id,
            "company_id": company_id,
            "asset_id": asset_id,
            "expected_asset_status": "uploaded",
            "expected_asset_sha256": digest,
            "expected_asset_size_bytes": file_size,
            "expected_base_revision_id": base_id,
            "expected_base_revision_no": 1,
            "file_object": {
                "id": file_id,
                "document_id": document_id,
                "file_name": "ci-deidentified.pdf",
                "storage_key": storage_path,
                "mime_type": "application/pdf",
                "size_bytes": file_size,
                "sha256": digest,
                "version_label": "editor-asset-source_pdf",
                "purpose": "official-editor",
                "created_by": applicant_id,
                "created_at": created_at,
                "bucket": "edoc-private",
                "storage_provider": "supabase",
                "encrypted_sha256": "",
                "encryption_status": "由物件儲存服務控管",
                "encryption_alg": "",
                "encryption_key_id": "",
                "scan_status": "已通過",
                "scan_engine": "ci-eicar-contract",
                "quarantine_reason": "",
                "signed_url_expires_at": None,
                "last_scan_at": "2099-01-01T00:00:00+00:00",
                "last_download_at": None,
            },
            "official_file": {
                "id": official_file_id,
                "document_id": document_id,
                "file_object_id": file_id,
                "file_type": "original_pdf",
                "file_name": "ci-deidentified.pdf",
                "file_storage_key": storage_path,
                "file_mime_type": "application/pdf",
                "file_size": file_size,
                "file_hash": digest,
                "version": 1,
                "uploaded_by": "CI Applicant",
                "created_at": created_at,
            },
            "asset_patch": {
                "file_object_id": file_id,
                "official_file_id": official_file_id,
                "sha256": digest,
                "upload_status": "finalized",
                "scan_status": "passed",
                "preflight_status": "passed",
                "page_count": 1,
                "metadata_json": "{\"base_revision_no\":1,\"renderer_version\":\"ci-gate\"}",
                "finalized_at": created_at,
                "editor_revision_id": revision_id,
            },
            "revision": {
                "id": revision_id,
                "document_id": document_id,
                "revision_no": 2,
                "parent_revision_id": base_id,
                "schema_version": 2,
                "editor_state_json": json.dumps(
                    {
                        "schemaVersion": 2,
                        "revisionNo": 2,
                        "sourceFiles": [{"assetId": asset_id}],
                        "pages": [],
                        "elements": [],
                        "manifestSha256": manifest.upper(),
                    },
                    separators=(",", ":"),
                ),
                "manifest_sha256": manifest,
                "renderer_version": "ci-gate",
                "created_by": applicant_id,
                "created_at": created_at,
            },
            "approval_log": {
                "id": operation_id,
                "document_id": document_id,
                "step_id": None,
                "file_id": official_file_id,
                "actor_id": applicant_id,
                "actor_name": "CI Applicant",
                "principal_actor_id": None,
                "action": "finalize_editor_upload",
                "comment": "deidentified atomic gate",
                "decision_evidence_json": {
                    "operation_id": operation_id,
                    "asset_id": asset_id,
                    "revision_id": revision_id,
                },
                "ip_address": "",
                "user_agent": "local-ci",
                "created_at": created_at,
            },
            "audit_log": {
                "id": audit_id,
                "actor": "CI Applicant",
                "action": "finalize_editor_upload",
                "target_type": "official_documents",
                "target_id": document_id,
                "detail": "deidentified atomic gate",
                "event_type": "submit",
                "module_code": "official_documents",
                "resource_type": "official_documents",
                "resource_id": document_id,
                "result": "success",
                "severity": "info",
                "actor_user_id": applicant_id,
                "request_id": operation_id,
                "metadata_json": {
                    "operation_id": operation_id,
                    "asset_id": asset_id,
                    "revision_id": revision_id,
                },
                "created_at": created_at,
            },
        }

    success_request = payload_for(
        document_id=success_document_id,
        asset_id=success_asset_id,
        base_id=success_base_id,
        operation_id=ids["operation"],
        audit_id=ids["audit"],
        file_id=ids["file"],
        official_file_id=ids["official_file"],
        revision_id=ids["revision"],
    )
    rollback_request = payload_for(
        document_id=rollback_document_id,
        asset_id=rollback_asset_id,
        base_id=rollback_base_id,
        operation_id=ids["rollback_operation"],
        audit_id=ids["rollback_audit"],
        file_id=ids["rollback_file"],
        official_file_id=ids["rollback_official_file"],
        revision_id=ids["rollback_revision"],
    )

    try:
        # The anonymous browser role must not be able to discover or execute
        # this SECURITY DEFINER function, even with a structurally valid request.
        anon_status, _anon_body = rpc(api_url, anon_key, success_request)
        require(anon_status >= 400, "local_editor_finalize_anon_rpc_exposed")

        wrong_company = copy.deepcopy(rollback_request)
        wrong_company["company_id"] = other_company_id
        denied_status, denied_body = rpc(api_url, service_key, wrong_company)
        denied = normalized_rpc_result(denied_body)
        require(denied_status >= 400, "local_editor_finalize_cross_company_accepted")
        require(
            denied.get("message") == "official_editor_write_forbidden",
            "local_editor_finalize_cross_company_wrong_error",
        )
        require(
            rows(api_url, service_key, "official_document_editor_assets", {"id": rollback_asset_id})[0]["upload_status"]
            == "uploaded",
            "local_editor_finalize_cross_company_mutated_asset",
        )

        stale_revision = copy.deepcopy(rollback_request)
        stale_revision["expected_base_revision_no"] = 999
        stale_status, stale_body = rpc(api_url, service_key, stale_revision)
        stale = normalized_rpc_result(stale_body)
        require(stale_status >= 400, "local_editor_finalize_stale_revision_accepted")
        require(
            stale.get("message") == "editor_revision_conflict",
            "local_editor_finalize_stale_revision_wrong_error",
        )
        require(
            not rows(api_url, service_key, "file_objects", {"id": ids["rollback_file"]})
            and not rows(api_url, service_key, "official_document_editor_revisions", {"id": ids["rollback_revision"]}),
            "local_editor_finalize_stale_revision_left_rows",
        )

        # Force a late not-null failure.  The RPC attempts file and official
        # file inserts before inserting this revision, so absence of all rows
        # proves PostgreSQL rolled the whole call back rather than committing a
        # partial finalize.
        invalid_request = copy.deepcopy(rollback_request)
        invalid_request["revision"]["editor_state_json"] = None
        invalid_status, invalid_body = rpc(api_url, service_key, invalid_request)
        invalid = normalized_rpc_result(invalid_body)
        require(invalid_status >= 400, "local_editor_finalize_invalid_payload_accepted")
        require(
            invalid.get("message") == "editor_finalize_invalid_payload",
            "local_editor_finalize_invalid_payload_wrong_error",
        )
        for table, row_id in (
            ("file_objects", ids["rollback_file"]),
            ("official_document_files", ids["rollback_official_file"]),
            ("official_document_editor_revisions", ids["rollback_revision"]),
            ("official_document_approval_logs", ids["rollback_operation"]),
            ("audit_logs", ids["rollback_audit"]),
        ):
            require(not rows(api_url, service_key, table, {"id": row_id}), f"local_editor_finalize_partial_row:{table}")
        rollback_asset = rows(api_url, service_key, "official_document_editor_assets", {"id": rollback_asset_id})[0]
        require(
            rollback_asset["upload_status"] == "uploaded"
            and rollback_asset.get("file_object_id") is None
            and rollback_asset.get("editor_revision_id") is None,
            "local_editor_finalize_partial_asset_patch",
        )

        status, body = rpc(api_url, service_key, success_request)
        result = normalized_rpc_result(body)
        require(status == 200, f"local_editor_finalize_commit_http:{status}")
        require(
            result.get("committed") is True
            and result.get("idempotent") is False
            and result.get("document_id") == success_document_id
            and result.get("asset_id") == success_asset_id
            and result.get("revision_id") == ids["revision"]
            and result.get("file_object_id") == ids["file"]
            and result.get("official_file_id") == ids["official_file"],
            "local_editor_finalize_commit_response_invalid",
        )
        finalized_asset = rows(api_url, service_key, "official_document_editor_assets", {"id": success_asset_id})[0]
        require(
            finalized_asset["upload_status"] == "finalized"
            and finalized_asset["scan_status"] == "passed"
            and finalized_asset["preflight_status"] == "passed"
            and finalized_asset["editor_revision_id"] == ids["revision"]
            and finalized_asset["file_object_id"] == ids["file"]
            and finalized_asset["official_file_id"] == ids["official_file"],
            "local_editor_finalize_asset_not_committed",
        )
        for table, row_id in (
            ("file_objects", ids["file"]),
            ("official_document_files", ids["official_file"]),
            ("official_document_editor_revisions", ids["revision"]),
            ("official_document_approval_logs", ids["operation"]),
            ("audit_logs", ids["audit"]),
        ):
            require(len(rows(api_url, service_key, table, {"id": row_id})) == 1, f"local_editor_finalize_missing_row:{table}")

        replay_status, replay_body = rpc(api_url, service_key, success_request)
        replay = normalized_rpc_result(replay_body)
        require(
            replay_status == 200 and replay.get("committed") is True and replay.get("idempotent") is True,
            "local_editor_finalize_replay_not_idempotent",
        )

        conflicting_replay = copy.deepcopy(success_request)
        conflict_operation = f"CI-EFIN-CONFLICT-{suffix}"
        conflict_audit = f"CI-EFIN-CAUD-{suffix}"
        conflicting_replay["operation_id"] = conflict_operation
        conflicting_replay["approval_log"]["id"] = conflict_operation
        conflicting_replay["audit_log"]["id"] = conflict_audit
        conflicting_replay["audit_log"]["request_id"] = conflict_operation
        conflict_status, conflict_body = rpc(api_url, service_key, conflicting_replay)
        conflict = normalized_rpc_result(conflict_body)
        require(conflict_status >= 400, "local_editor_finalize_conflicting_replay_accepted")
        require(
            conflict.get("message") == "editor_finalize_operation_conflict",
            "local_editor_finalize_conflicting_replay_wrong_error",
        )
        require(
            not rows(api_url, service_key, "official_document_approval_logs", {"id": conflict_operation})
            and not rows(api_url, service_key, "audit_logs", {"id": conflict_audit}),
            "local_editor_finalize_conflict_left_rows",
        )
    finally:
        # The immutable evidence triggers are intentionally bypassed only in
        # this isolated local cleanup transaction. Restore the exact audit head
        # captured before the gate so later CI assertions see an unchanged
        # chain. No production connection is permitted above.
        if head is None:
            restore_head = "delete from edoc_private.audit_log_chain_heads where chain_version = 2;"
        else:
            head_hash = "null" if head.get("head_hash") is None else sql_literal(str(head["head_hash"]))
            last_audit_id = "null" if head.get("last_audit_id") is None else sql_literal(str(head["last_audit_id"]))
            updated_at = sql_literal(str(head["updated_at"]))
            restore_head = f"""
              insert into edoc_private.audit_log_chain_heads (chain_version, head_hash, last_audit_id, updated_at)
              values (2, {head_hash}, {last_audit_id}, {updated_at}::timestamptz)
              on conflict (chain_version) do update set
                head_hash = excluded.head_hash,
                last_audit_id = excluded.last_audit_id,
                updated_at = excluded.updated_at;
            """
        cleanup_sql = f"""
          begin;
          lock table public.audit_logs in share row exclusive mode;
          set local session_replication_role = replica;
          delete from public.audit_logs where id in ({sql_literal(ids['audit'])}, {sql_literal(ids['rollback_audit'])}, {sql_literal('CI-EFIN-CAUD-' + suffix)});
          delete from public.official_document_approval_logs
          where id in ({sql_literal(ids['operation'])}, {sql_literal(ids['rollback_operation'])}, {sql_literal('CI-EFIN-CONFLICT-' + suffix)});
          delete from public.official_document_editor_assets
          where id in ({sql_literal(success_asset_id)}, {sql_literal(rollback_asset_id)});
          delete from public.official_document_files
          where id in ({sql_literal(ids['official_file'])}, {sql_literal(ids['rollback_official_file'])});
          delete from public.file_objects
          where id in ({sql_literal(ids['file'])}, {sql_literal(ids['rollback_file'])});
          delete from public.official_document_editor_revisions
          where id in (
            {sql_literal(ids['revision'])}, {sql_literal(ids['rollback_revision'])},
            {sql_literal(success_base_id)}, {sql_literal(rollback_base_id)}
          );
          delete from public.official_documents where id in ({sql_literal(success_document_id)}, {sql_literal(rollback_document_id)});
          delete from public.companies where id in ({sql_literal(company_id)}, {sql_literal(other_company_id)});
          {restore_head}
          commit;
        """
        run_sql(cleanup_sql)

    for table, column, prefix in (
        ("companies", "id", f"CI-EFIN-%-{suffix}"),
        ("official_documents", "id", f"CI-EFIN-%-{suffix}"),
        ("official_document_editor_assets", "id", f"CI-EFIN-%-{suffix}"),
        ("file_objects", "id", f"CI-EFIN-%-{suffix}"),
        ("official_document_files", "id", f"CI-EFIN-%-{suffix}"),
        ("official_document_editor_revisions", "id", f"CI-EFIN-%-{suffix}"),
        ("official_document_approval_logs", "id", f"CI-EFIN-%-{suffix}"),
        ("audit_logs", "id", f"CI-EFIN-%-{suffix}"),
    ):
        remaining = run_sql(
            f"select count(*) from public.{table} where {column} like {sql_literal(prefix)};",
            tuples_only=True,
        )
        require(remaining == "0", f"local_editor_finalize_cleanup_failed:{table}")

    print(
        json.dumps(
            {
                "gate": "local_supabase_editor_finalize_rpc",
                "passed": True,
                "rpcTransport": "PostgREST",
                "principal": "local_service_role",
                "atomicCommit": True,
                "idempotentReplay": True,
                "conflictRejected": True,
                "revisionConflictRejected": True,
                "crossCompanyRejected": True,
                "lateFailureRolledBack": True,
                "anonRoleDenied": True,
                "fixturesRemoved": True,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateFailure as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
