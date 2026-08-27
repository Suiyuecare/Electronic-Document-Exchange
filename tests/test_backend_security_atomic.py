from __future__ import annotations

import json
import sqlite3
import unittest
from unittest import mock

import backend


class BackendSecurityAndAtomicityTestCase(unittest.TestCase):
    def test_exchange_mutations_require_exchange_manage(self) -> None:
        class ResponseRecorder:
            def __init__(self) -> None:
                self.responses = []

            def send_json(self, payload, status=200):
                self.responses.append((payload, status))

        denied = ResponseRecorder()
        self.assertFalse(
            backend.Handler.require_exchange_mutation_access(
                denied,
                {"permissions": ["official_documents.receive"]},
            )
        )
        self.assertEqual(denied.responses[-1][1], 403)
        self.assertEqual(
            denied.responses[-1][0]["detail"],
            "exchange_manage_forbidden",
        )

        allowed = ResponseRecorder()
        self.assertTrue(
            backend.Handler.require_exchange_mutation_access(
                allowed,
                {"permissions": ["exchange.manage"]},
            )
        )
        self.assertEqual(allowed.responses, [])

    def test_formal_exchange_remains_disabled_for_internal_launch(self) -> None:
        with mock.patch.object(backend, "launch_scope", return_value="internal_official"):
            with self.assertRaisesRegex(PermissionError, "formal_exchange_disabled"):
                backend.assert_formal_exchange_allowed({"formal": True})

            with self.assertRaisesRegex(PermissionError, "formal_exchange_disabled"):
                backend.exchange_queue_document(
                    mock.Mock(),
                    {"formal": True, "document_id": "DOC-1"},
                )
            with self.assertRaisesRegex(PermissionError, "formal_exchange_disabled"):
                backend.supabase_exchange_acknowledge_received(
                    {"formal": True, "inbox_id": "EXIN-1"}
                )

    def test_supabase_dispatch_rejects_cross_tenant_before_any_insert(self) -> None:
        sender = {
            "id": "FIN-U1",
            "company_id": "CO-1",
            "finance_tenant_id": "TENANT-1",
        }
        recipient = {
            "id": "FIN-U2",
            "status": "啟用",
            "company_id": "CO-1",
            "finance_tenant_id": "TENANT-2",
        }
        insert = mock.Mock()
        with mock.patch.object(
            backend,
            "require_internal_dispatch_creator",
            return_value=sender,
        ), mock.patch.object(
            backend,
            "supabase_get",
            return_value={
                "id": "CO-1",
                "name": "測試公司",
                "finance_tenant_id": "TENANT-1",
            },
        ), mock.patch.object(
            backend,
            "supabase_user_by_id",
            return_value=recipient,
        ), mock.patch.object(backend, "supabase_insert", insert):
            with self.assertRaisesRegex(
                PermissionError,
                "internal_dispatch_recipient_company_forbidden",
            ):
                backend.supabase_create_internal_dispatch(
                    {
                        "subject": "跨租戶測試",
                        "recipients": [{"user_id": "FIN-U2"}],
                    },
                    {"user": sender},
                )
        insert.assert_not_called()

    def test_supabase_dispatch_detail_checks_company_before_global_permission(self) -> None:
        user = {
            "id": "FIN-U1",
            "company_id": "CO-1",
            "finance_tenant_id": "TENANT-1",
        }
        dispatch = {
            "id": "IDISP-1",
            "official_document_id": "OD-2",
            "sender_user_id": "FIN-U2",
            "metadata_json": {},
        }
        with mock.patch.object(backend, "supabase_get") as get, mock.patch.object(
            backend,
            "supabase_filter_rows",
            return_value=[],
        ), mock.patch.object(
            backend,
            "supabase_official_session_user",
            return_value=user,
        ), mock.patch.object(
            backend,
            "supabase_official_document_row",
            return_value={"id": "OD-2", "company_id": "CO-2"},
        ):
            get.side_effect = lambda table, _id: (
                dispatch
                if table == "internal_dispatches"
                else {
                    "id": "CO-2",
                    "finance_tenant_id": "TENANT-2",
                }
            )
            with self.assertRaisesRegex(
                PermissionError,
                "internal_dispatch_company_forbidden",
            ):
                backend.supabase_internal_dispatch_detail(
                    "IDISP-1",
                    {
                        "user": user,
                        "permissions": ["official_documents.all_records"],
                    },
                )

    def test_global_dispatch_list_omits_foreign_tenant_rows(self) -> None:
        user = {
            "id": "FIN-U1",
            "company_id": "CO-1",
            "finance_tenant_id": "TENANT-1",
        }

        def rows(table, *_args, **_kwargs):
            if table == "internal_dispatches":
                return [{"id": "IDISP-FOREIGN"}, {"id": "IDISP-OWN"}]
            if table == "internal_dispatch_recipients":
                return []
            return []

        def detail(dispatch_id, _session):
            if dispatch_id == "IDISP-FOREIGN":
                raise PermissionError("internal_dispatch_company_forbidden")
            return {"id": dispatch_id}

        with mock.patch.object(
            backend,
            "supabase_official_session_user",
            return_value=user,
        ), mock.patch.object(
            backend,
            "supabase_filter_rows",
            side_effect=rows,
        ), mock.patch.object(
            backend,
            "session_has_any_permission",
            return_value=True,
        ), mock.patch.object(
            backend,
            "supabase_internal_dispatch_detail",
            side_effect=detail,
        ):
            result = backend.supabase_list_internal_dispatches(
                {},
                {"user": user, "permissions": ["official_documents.all_records"]},
            )
        self.assertEqual(result, [{"id": "IDISP-OWN"}])

    def test_sqlite_login_and_session_ids_do_not_collide_same_millisecond(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(backend.SCHEMA)
        backend.seed(conn)
        backend.seed_auth(conn)
        user = conn.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
        self.assertIsNotNone(user)
        with mock.patch.object(backend.time, "time", return_value=1_700_000_000.123):
            backend.record_login_event(
                conn,
                user["email"],
                "unit",
                "成功",
                "first",
                user["id"],
                "127.0.0.1",
                "unit",
            )
            backend.record_login_event(
                conn,
                user["email"],
                "unit",
                "成功",
                "second",
                user["id"],
                "127.0.0.1",
                "unit",
            )
            backend.create_session(conn, user, "unit", "127.0.0.1", "unit")
            backend.create_session(conn, user, "unit", "127.0.0.1", "unit")
        self.assertEqual(
            conn.execute("SELECT COUNT(DISTINCT id) FROM login_events").fetchone()[0],
            4,
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(DISTINCT id) FROM auth_sessions").fetchone()[0],
            2,
        )
        conn.close()

    def test_timezone_parsing_and_cron_threshold_are_exact(self) -> None:
        utc = backend.parse_time("2026-08-27T01:15:00Z")
        taipei = backend.parse_time("2026-08-27T09:15:00+08:00")
        self.assertEqual(utc, taipei)
        self.assertIsNone(backend.age_minutes("not-a-time"))
        with mock.patch.object(backend, "is_production", return_value=True), mock.patch.object(
            backend,
            "EDOC_MONITORING_EXPECTED_CRON_MINUTES",
            100,
        ):
            self.assertFalse(backend.cron_run_is_stalled(100))
            self.assertTrue(backend.cron_run_is_stalled(101))
            self.assertTrue(backend.cron_run_is_stalled(None))
            self.assertEqual(backend.cron_monitoring_status(101), "stalled")

    def test_internal_monitoring_does_not_raise_formal_signing_alerts(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(backend.SCHEMA)
        ready = {"ready": True, "missing": [], "blockers": [], "warnings": []}
        formal = {
            "ready": False,
            "missing": ["EDOC_SIGNATURE_API_KEY"],
            "blockers": ["formal signing missing"],
            "warnings": [],
        }
        signing = {
            "ready": False,
            "productionBlocked": True,
            "missing": ["provider"],
            "mode": "simulation-or-incomplete",
            "services": {},
            "policy": {},
        }
        storage = {
            "ready": True,
            "productionBlocked": False,
            "missing": [],
            "services": {},
            "policy": {},
        }
        credential = {"channel": "Email", "status": "有效", "ok": True}
        with mock.patch.object(backend, "launch_scope", return_value="internal_official"), mock.patch.object(
            backend,
            "internal_readiness",
            return_value=ready,
        ), mock.patch.object(
            backend,
            "production_readiness",
            return_value=formal,
        ), mock.patch.object(
            backend,
            "signing_service_status",
            return_value=signing,
        ), mock.patch.object(
            backend,
            "storage_service_status",
            return_value=storage,
        ), mock.patch.object(
            backend,
            "notification_credential_status_for_channel",
            side_effect=lambda _conn, channel: {**credential, "channel": channel},
        ), mock.patch.object(backend, "is_production", return_value=False):
            snapshot = backend.local_monitoring_snapshot(conn)
        codes = {item["code"] for item in snapshot["alerts"]}
        self.assertNotIn("SIGNING-SERVICE-INCOMPLETE", codes)
        self.assertEqual(snapshot["checks"]["readiness"]["scope"], "internal")
        self.assertEqual(snapshot["checks"]["formalReadiness"]["status"], "disabled")
        self.assertEqual(snapshot["checks"]["signing"]["status"], "disabled")
        self.assertFalse(snapshot["checks"]["signing"]["affectsCurrentScope"])
        conn.close()

    def test_unknown_upload_failure_code_is_masked_and_idempotent(self) -> None:
        document = {"id": "OD-1", "company_id": "CO-1"}
        user = {"id": "FIN-U1"}
        pending = {
            "id": "ASSET-1",
            "document_id": "OD-1",
            "upload_status": "pending",
            "metadata_json": "{}",
            "storage_path": "editor/OD-1/a.pdf",
            "storage_bucket": "private",
        }
        failed = {**pending, "upload_status": "failed"}
        patches = []
        with mock.patch.object(
            backend,
            "supabase_official_document_row",
            return_value=document,
        ), mock.patch.object(
            backend,
            "_supabase_editor_assert_document_access",
            return_value=user,
        ), mock.patch.object(
            backend,
            "supabase_filter_rows",
            side_effect=[[pending], [failed]],
        ), mock.patch.object(
            backend,
            "supabase_patch",
            side_effect=lambda table, item_id, payload: patches.append(payload) or payload,
        ), mock.patch.object(
            backend,
            "supabase_storage_delete",
        ), mock.patch.object(
            backend,
            "supabase_insert_official_log",
        ) as log:
            result = backend.supabase_fail_official_editor_upload(
                "OD-1",
                "ASSET-1",
                {"error_code": "raw cloud provider stack trace"},
                {"user": user},
            )
        self.assertFalse(result["idempotent"])
        metadata = json.loads(patches[0]["metadata_json"])
        self.assertEqual(metadata["error_code"], "editor_upload_failed")
        self.assertNotIn("stack trace", repr(patches))
        self.assertIn("error_code=editor_upload_failed", log.call_args.args[3])

    def _submission_fixture(self, status: str = "draft"):
        document = {
            "id": "OD-ATOMIC-1",
            "applicant_id": "FIN-U1",
            "applicant_name": "測試申請人",
            "company_id": "CO-1",
            "current_status": status,
            "current_step": "applicant" if status == "rejected" else "",
            "updated_at": "2026-08-27 10:00:00",
            "created_at": "2026-08-27 09:00:00",
            "correction_requested_at": (
                "2026-08-27T02:00:00+00:00" if status == "rejected" else None
            ),
            "requires_stamp": True,
            "source_type": "uploaded_pdf",
            "title": "原子送簽測試",
            "metadata_json": "{}",
        }
        user = {
            "id": "FIN-U1",
            "name": "測試申請人",
            "email": "applicant@example.test",
            "role": "員工",
            "company_id": "CO-1",
        }
        stamp_request = {
            "id": "ODSTAMP-1",
            "document_id": document["id"],
            "company_id": "CO-1",
            "seal_id": "SEAL-1",
            "requested_by": user["id"],
            "stamp_page": 1,
            "stamp_x": 100,
            "stamp_y": 100,
            "stamp_width": 80,
            "stamp_height": 80,
            "status": "pending",
            "locked_editor_revision_id": "REV-1",
            "locked_source_sha256": "A" * 64,
            "prepared_file_id": "ODFILE-1",
            "prepared_sha256": "B" * 64,
            "editor_manifest_sha256": "C" * 64,
            "editor_schema_version": 2,
            "renderer_version": backend.EDOC_EDITOR_RENDERER_VERSION,
            "editor_locked_at": "2026-08-27 10:00:00",
            "error_message": "",
            "created_at": "2026-08-27 09:00:00",
            "updated_at": "2026-08-27 10:00:00",
        }
        position = {
            "id": "ODPOS-1",
            "request_id": stamp_request["id"],
            "seal_id": "SEAL-1",
            "page": 1,
            "x": 100,
            "y": 100,
            "width": 80,
            "height": 80,
            "locked_seal_file_id": "SEALFILE-1",
            "locked_seal_sha256": "D" * 64,
            "locked_render_width_pt": 80,
            "locked_render_height_pt": 80,
            "locked_dimension_policy_version": backend.EDOC_SEAL_DIMENSION_POLICY_VERSION,
            "order_index": 1,
        }
        generation = 2 if status == "rejected" else 1
        step = {
            "id": f"ODSTEP-{generation}",
            "document_id": document["id"],
            "workflow_generation": generation,
            "step_order": 1,
            "step_key": "applicant_manager",
            "step_name": "申請人主管",
            "approver_user_id": "FIN-MANAGER",
            "approver_name": "測試主管",
            "approver_role": "主管",
            "status": "pending",
            "comment": "",
            "approved_at": "",
            "review_started_at": None,
            "created_at": "2026-08-27 10:00:00",
            "updated_at": "2026-08-27 10:00:00",
        }
        snapshot = backend.official_document_actor_snapshot_payload(
            document["id"],
            step,
            "2026-08-27 10:00:00",
        )
        return document, user, stamp_request, position, step, snapshot

    def test_submit_and_resubmit_use_one_atomic_rpc(self) -> None:
        for status in ("draft", "rejected"):
            with self.subTest(status=status):
                document, user, stamp_request, position, step, snapshot = (
                    self._submission_fixture(status)
                )
                request_seen = {}

                def rpc(_method, endpoint, body, **_kwargs):
                    self.assertEqual(
                        endpoint,
                        "rpc/edoc_commit_official_document_submission",
                    )
                    request_seen.update(body["p_request"])
                    request = body["p_request"]
                    return {
                        "ok": True,
                        "committed": True,
                        "idempotent": False,
                        "document_id": document["id"],
                        "operation_id": request["operation_id"],
                        "current_status": request["first_status"],
                        "current_step": request["first_step_key"],
                        "first_step_id": request["first_step_id"],
                        "workflow_generation": request["workflow_generation"],
                        "resubmitted": status == "rejected",
                    }

                with mock.patch.object(
                    backend,
                    "supabase_official_session_user",
                    return_value=user,
                ), mock.patch.object(
                    backend,
                    "supabase_official_document_row",
                    return_value=document,
                ), mock.patch.object(
                    backend,
                    "official_seal_context_from_document",
                    return_value={"approval_route_code": "A"},
                ), mock.patch.object(
                    backend,
                    "official_seal_workflow_steps",
                    return_value=[{"key": "applicant_manager"}],
                ), mock.patch.object(
                    backend,
                    "is_production",
                    return_value=False,
                ), mock.patch.object(
                    backend,
                    "require_official_creation_company",
                ), mock.patch.object(
                    backend,
                    "supabase_assert_official_document_uploads_av_clean",
                ), mock.patch.object(
                    backend,
                    "supabase_lock_official_editor_submission",
                    return_value={
                        "revision_id": "REV-1",
                        "manifest_sha256": "C" * 64,
                        "source_sha256": "A" * 64,
                        "prepared_file_id": "ODFILE-1",
                        "prepared_sha256": "B" * 64,
                        "seal_positions": 1,
                        "request_row": stamp_request,
                        "position_rows": [position],
                    },
                ) as editor_lock, mock.patch.object(
                    backend,
                    "supabase_user_by_id",
                    side_effect=lambda user_id: (
                        user
                        if user_id == user["id"]
                        else {
                            "id": user_id,
                            "name": "測試主管",
                            "email": "manager@example.test",
                            "company_id": "CO-1",
                            "status": "啟用",
                        }
                    ),
                ), mock.patch.object(
                    backend,
                    "supabase_plan_official_workflow_submission",
                    return_value={
                        "workflow_generation": step["workflow_generation"],
                        "supersede_generation": 1 if status == "rejected" else 0,
                        "steps": [step],
                        "actor_snapshots": [snapshot],
                    },
                ), mock.patch.object(
                    backend,
                    "supabase_request",
                    side_effect=rpc,
                ), mock.patch.object(
                    backend,
                    "supabase_create_and_deliver_notification",
                ), mock.patch.object(
                    backend,
                    "supabase_official_document_detail",
                    return_value={"id": document["id"], "current_status": "pending"},
                ), mock.patch.object(backend, "supabase_patch") as patch, mock.patch.object(
                    backend,
                    "supabase_insert",
                ) as insert, mock.patch.object(
                    backend,
                    "supabase_create_official_workflow_steps",
                ) as legacy_steps:
                    result = backend.supabase_submit_official_document(
                        document["id"],
                        {"comment": "送簽"},
                        {"user": user},
                    )
                self.assertEqual(result["id"], document["id"])
                editor_lock.assert_called_once_with(
                    document,
                    {"comment": "送簽"},
                    user,
                    persist=False,
                )
                self.assertEqual(request_seen["expected_status"], status)
                self.assertEqual(request_seen["resubmit"]["enabled"], status == "rejected")
                self.assertEqual(request_seen["stamp_request"]["id"], "ODSTAMP-1")
                self.assertEqual(request_seen["first_step_id"], step["id"])
                self.assertEqual(
                    request_seen["submit_audit"]["request_id"],
                    request_seen["operation_id"],
                )
                self.assertIsInstance(
                    request_seen["actor_snapshots"][0]["snapshot_json"],
                    dict,
                )
                patch.assert_not_called()
                insert.assert_not_called()
                legacy_steps.assert_not_called()

    def test_editor_finalize_registers_metadata_and_revision_in_one_rpc(self) -> None:
        data = b"deidentified-pdf-bytes"
        digest = backend.sha256_bytes(data)
        document = {
            "id": "OD-1",
            "applicant_id": "FIN-U1",
            "company_id": "CO-1",
            "current_status": "draft",
        }
        user = {"id": "FIN-U1", "name": "申請人"}
        asset = {
            "id": "ASSET-1",
            "document_id": "OD-1",
            "editor_revision_id": "REV-1",
            "asset_kind": "image",
            "file_name": "image.png",
            "mime_type": "image/png",
            "size_bytes": len(data),
            "expected_sha256": digest,
            "storage_bucket": "private",
            "storage_path": "editor/OD-1/image.png",
            "upload_status": "pending",
            "metadata_json": json.dumps({"base_revision_no": 1}),
        }
        latest = {"id": "REV-1", "revision_no": 1}
        operation_digest = backend.hashlib.sha256(
            f"OD-1\nASSET-1\n{digest}\nREV-1".encode("utf-8")
        ).hexdigest().upper()
        deterministic_revision_id = f"ODREV-EFIN-{operation_digest[:32]}"
        revision = {
            "id": deterministic_revision_id,
            "document_id": "OD-1",
            "revision_no": 2,
            "parent_revision_id": "REV-1",
            "schema_version": 2,
            "editor_state_json": json.dumps(
                {
                    "schemaVersion": 2,
                    "revisionNo": 2,
                    "sourceFiles": [],
                    "pages": [],
                    "elements": [],
                    "manifestSha256": "E" * 64,
                }
            ),
            "manifest_sha256": "E" * 64,
            "renderer_version": backend.EDOC_EDITOR_RENDERER_VERSION,
            "created_by": "FIN-U1",
            "created_at": "2026-08-27 10:00:00",
        }
        rpc_payload = {}

        def rpc(_method, endpoint, body, **_kwargs):
            self.assertEqual(endpoint, "rpc/edoc_finalize_editor_asset_v2")
            rpc_payload.update(body["p_request"])
            request = body["p_request"]
            return {
                "ok": True,
                "committed": True,
                "idempotent": False,
                "document_id": "OD-1",
                "asset_id": "ASSET-1",
                "operation_id": request["operation_id"],
                "revision_id": request["revision"]["id"],
                "revision_no": 2,
                "manifest_sha256": "E" * 64,
                "file_object_id": request["file_object"]["id"],
                "official_file_id": None,
            }

        with mock.patch.object(
            backend,
            "supabase_official_document_row",
            return_value=document,
        ), mock.patch.object(
            backend,
            "_supabase_editor_assert_document_access",
            return_value=user,
        ), mock.patch.object(
            backend,
            "supabase_filter_rows",
            return_value=[asset],
        ), mock.patch.object(
            backend,
            "supabase_storage_download",
            return_value=data,
        ), mock.patch.object(
            backend,
            "_supabase_editor_latest_revision",
            return_value=latest,
        ), mock.patch.object(
            backend,
            "editor_scan_bytes_for_threats",
            return_value=("已通過", "clean"),
        ), mock.patch.object(
            backend,
            "inspect_editor_image",
            return_value={"pageCount": 0, "pages": [], "flags": {}},
        ), mock.patch.object(
            backend,
            "_editor_state_with_asset",
            return_value={},
        ), mock.patch.object(
            backend,
            "_supabase_editor_revision_payload",
            return_value=revision,
        ), mock.patch.object(
            backend,
            "supabase_request",
            side_effect=rpc,
        ), mock.patch.object(
            backend,
            "_editor_revision_public",
            return_value={"id": revision["id"], "state": {}},
        ), mock.patch.object(backend, "supabase_insert") as insert, mock.patch.object(
            backend,
            "supabase_patch",
        ) as patch:
            result = backend.supabase_finalize_official_editor_upload(
                "OD-1",
                "ASSET-1",
                {"sha256": digest},
                {"user": user},
            )
        self.assertEqual(result["editor_revision"]["id"], revision["id"])
        self.assertEqual(rpc_payload["expected_asset_status"], "pending")
        self.assertEqual(rpc_payload["expected_asset_sha256"], digest)
        self.assertEqual(rpc_payload["revision"]["parent_revision_id"], "REV-1")
        self.assertEqual(rpc_payload["file_object"]["created_by"], "FIN-U1")
        self.assertIsNone(rpc_payload["file_object"]["signed_url_expires_at"])
        self.assertIsNone(rpc_payload["file_object"]["last_download_at"])
        self.assertEqual(
            rpc_payload["audit_log"]["request_id"],
            rpc_payload["operation_id"],
        )
        insert.assert_not_called()
        patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
