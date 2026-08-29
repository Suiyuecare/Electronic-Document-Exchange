from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import io
import json
import os
import random
import re
import tempfile
import threading
import time
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import backend
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


ACCEPTANCE_SEED = int(os.getenv("EDOC_ACCEPTANCE_SEED", "20260827"))
ACCEPTANCE_UPLOAD_PROTOCOL = os.getenv(
    "EDOC_ACCEPTANCE_UPLOAD_PROTOCOL", "local_direct"
).strip().lower()
ARTIFACT_DIR = Path(__file__).resolve().parent / ".artifacts" / "five-account-acceptance"
TEST_HANDOFF_SECRET = "isolated-five-account-handoff-secret-20260827"


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else {}


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _machine_error(error: BaseException) -> str:
    candidates = re.findall(r"[a-z][a-z0-9_:-]{2,120}", str(error).lower())
    safe = next((value for value in candidates if "_" in value and "@" not in value), "")
    if not safe:
        safe = next((value for value in candidates if "@" not in value), "")
    return safe[:120] or type(error).__name__


class QuietAcceptanceHandler(backend.Handler):
    """Keep CI output focused on the acceptance result and evidence paths."""

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class FiveAccountHttpAcceptanceTest(unittest.TestCase):
    """Replay five deidentified Finance journeys through the real local HTTP API.

    The server runs against a temporary SQLite database. Its default transport
    uses temporary local storage; CI can bind the same five journeys to an
    isolated local Supabase signed-TUS stack. Production identity/workflow
    guards stay enabled, while Finance and antivirus use deterministic test
    doubles. No real account, Seal Vault file, hosted Supabase project, or
    exchange provider is contacted.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if ACCEPTANCE_UPLOAD_PROTOCOL not in {"local_direct", "local_supabase_tus"}:
            raise AssertionError("acceptance_upload_protocol_invalid")
        cls.upload_protocol = ACCEPTANCE_UPLOAD_PROTOCOL
        cls.local_supabase_api_url = os.getenv("EDOC_LOCAL_SUPABASE_URL", "").rstrip("/")
        cls.local_supabase_anon_key = os.getenv("EDOC_LOCAL_SUPABASE_ANON_KEY", "").strip()
        cls.local_supabase_service_role_key = os.getenv(
            "EDOC_LOCAL_SUPABASE_SERVICE_ROLE_KEY", ""
        ).strip()
        if cls.upload_protocol == "local_supabase_tus":
            if not all(
                (
                    cls.local_supabase_api_url,
                    cls.local_supabase_anon_key,
                    cls.local_supabase_service_role_key,
                )
            ):
                raise AssertionError("local_supabase_tus_env_missing")
            parsed_local = urllib.parse.urlparse(cls.local_supabase_api_url)
            if (
                parsed_local.scheme != "http"
                or parsed_local.hostname not in {"127.0.0.1", "localhost"}
                or not parsed_local.port
                or parsed_local.path not in {"", "/"}
            ):
                raise AssertionError("local_supabase_tus_origin_invalid")
        cls.tmp = tempfile.TemporaryDirectory(prefix="edoc-five-account-")
        cls.originals = {
            "DB_PATH": backend.DB_PATH,
            "STORAGE_DIR": backend.STORAGE_DIR,
            "PRIVATE_SEAL_STORAGE_DIR": backend.PRIVATE_SEAL_STORAGE_DIR,
            "USE_SUPABASE": backend.USE_SUPABASE,
            "DEPLOYMENT_ENV": backend.DEPLOYMENT_ENV,
            "LOCAL_SCHEMA_READY": backend.LOCAL_SCHEMA_READY,
            "PORTAL_HANDOFF_SECRET": backend.PORTAL_HANDOFF_SECRET,
            "EDOC_PORTAL_ALLOWED_ORIGINS": backend.EDOC_PORTAL_ALLOWED_ORIGINS,
        }
        cls.storage_patches: list[Any] = []
        cls.env_patch = mock.patch.dict(
            os.environ,
            {
                "EDOC_LAUNCH_COMPANY_MODE": "finance_active",
                "EDOC_LAUNCH_COMPANY_IDS": "",
                "EDOC_PDF_EDITOR_V2_COMPANY_MODE": "finance_active",
                "EDOC_PDF_EDITOR_V2_COMPANY_IDS": "",
            },
            clear=False,
        )
        cls.env_patch.start()

        root = Path(cls.tmp.name)
        backend.DB_PATH = root / "data" / "acceptance.sqlite3"
        backend.STORAGE_DIR = root / "storage"
        backend.PRIVATE_SEAL_STORAGE_DIR = backend.STORAGE_DIR / "seal-vault" / "seals"
        backend.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        backend.USE_SUPABASE = False
        # Keep the live authorization and seniority-reduction branches active.
        backend.DEPLOYMENT_ENV = "production"
        backend.LOCAL_SCHEMA_READY = False
        backend.PORTAL_HANDOFF_SECRET = TEST_HANDOFF_SECRET
        backend.migrate()

        cls.rng = random.Random(ACCEPTANCE_SEED)
        cls.case_definitions = cls._build_case_definitions()
        cls.snapshots_by_email, cls.identity_by_email = cls._build_finance_snapshots()
        cls.av_scan_count = 0
        cls.av_quarantine_count = 0
        cls.tus_replay_isolations = 0
        cls.private_storage_denials = 0
        cls.finalize_replay_idempotent_count = 0
        cls.failed_intent_replay_rejections = 0

        def isolated_av_scan(data: bytes, file_name: str, **_: Any) -> tuple[str, str]:
            cls.av_scan_count += 1
            return backend.scan_bytes_for_threats(data, file_name)

        cls.av_patch = mock.patch.object(
            backend,
            "editor_scan_bytes_for_threats",
            side_effect=isolated_av_scan,
        )
        cls.av_patch.start()
        cls.seals = cls._prepare_isolated_companies_and_seals()

        cls.finance_patch = mock.patch.object(
            backend,
            "current_finance_bridge_snapshot",
            side_effect=lambda email: copy.deepcopy(cls.snapshots_by_email[str(email).lower()]),
        )
        cls.finance_patch.start()
        original_local_upload = backend.store_official_editor_local_upload

        def isolated_local_upload(*args: Any, **kwargs: Any) -> Any:
            # The production branch correctly forbids local disk upload.  This
            # isolated suite has no Supabase Storage by design, so only the
            # upload write itself is executed under the test transport flag;
            # handoff, session, workflow, authorization and submission remain
            # on the production branches.
            previous = backend.DEPLOYMENT_ENV
            backend.DEPLOYMENT_ENV = "test"
            try:
                return original_local_upload(*args, **kwargs)
            finally:
                backend.DEPLOYMENT_ENV = previous

        cls.local_upload_patch = mock.patch.object(
            backend,
            "store_official_editor_local_upload",
            side_effect=isolated_local_upload,
        )
        cls.local_upload_patch.start()

        if cls.upload_protocol == "local_supabase_tus":
            cls._install_local_supabase_tus_transport(original_local_upload)

        cls.server = backend.ThreadingHTTPServer(("127.0.0.1", 0), QuietAcceptanceHandler)
        cls.port = int(cls.server.server_address[1])
        cls.origin = f"http://127.0.0.1:{cls.port}"
        backend.EDOC_PORTAL_ALLOWED_ORIGINS = frozenset({cls.origin})
        cls.server_thread = threading.Thread(
            target=cls.server.serve_forever,
            name="edoc-five-account-http",
            daemon=True,
        )
        cls.server_thread.start()
        cls.tokens_by_email: dict[str, str] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.server.shutdown()
            cls.server.server_close()
            cls.server_thread.join(timeout=5)
        finally:
            for patcher in reversed(cls.storage_patches):
                patcher.stop()
            cls.local_upload_patch.stop()
            cls.av_patch.stop()
            cls.finance_patch.stop()
            for key, value in cls.originals.items():
                setattr(backend, key, value)
            cls.env_patch.stop()
            cls.tmp.cleanup()

    @classmethod
    def _install_local_supabase_tus_transport(cls, original_local_upload: Any) -> None:
        """Use real local Storage TUS while keeping all test records isolated.

        The production backend intentionally rejects local Supabase origins.
        This test-only adapter changes only that transport boundary: the real
        Storage API issues the object capability and receives the TUS stream;
        the normal finalize, antivirus and PDF preflight code remains in use.
        """

        storage_endpoint = f"{cls.local_supabase_api_url}/storage/v1"
        if not backend._browser_safe_supabase_public_key(cls.local_supabase_anon_key):
            raise AssertionError("local_supabase_tus_anon_key_invalid")
        if backend._browser_safe_supabase_public_key(
            cls.local_supabase_service_role_key
        ):
            raise AssertionError("local_supabase_tus_service_role_key_misclassified")
        patch_values = {
            "EDOC_STORAGE_PROVIDER": "supabase",
            "EDOC_STORAGE_SUPABASE_URL": cls.local_supabase_api_url,
            "EDOC_OBJECT_STORAGE_URL": storage_endpoint,
            "EDOC_STORAGE_SERVICE_ROLE_KEY": cls.local_supabase_service_role_key,
            "EDOC_STORAGE_PUBLISHABLE_KEY": cls.local_supabase_anon_key,
            "EDOC_STORAGE_BUCKET": "edoc-private",
        }
        for name, value in patch_values.items():
            patcher = mock.patch.object(backend, name, value)
            patcher.start()
            cls.storage_patches.append(patcher)
        for name, replacement in (
            ("object_storage_endpoint", lambda: storage_endpoint),
            ("_supabase_storage_endpoint_issue", lambda: ""),
        ):
            patcher = mock.patch.object(backend, name, side_effect=replacement)
            patcher.start()
            cls.storage_patches.append(patcher)

        original_create_intent = backend.create_official_editor_upload_intent
        original_finalize = backend.finalize_official_editor_upload

        def create_tus_intent(
            conn: Any,
            document_id: str,
            payload: dict[str, Any],
            session: dict[str, Any] | None,
        ) -> dict[str, Any]:
            intent = original_create_intent(conn, document_id, payload, session)
            asset = conn.execute(
                "SELECT storage_bucket, storage_path, mime_type "
                "FROM official_document_editor_assets WHERE id = ?",
                (intent["upload_id"],),
            ).fetchone()
            if not asset:
                raise AssertionError("local_supabase_tus_asset_missing")
            bucket = str(asset["storage_bucket"])
            storage_path = str(asset["storage_path"])
            mime_type = str(asset["mime_type"])
            upload_token = backend._supabase_create_signed_upload_token(
                storage_path, bucket
            )
            return {
                **intent,
                "protocol": "tus",
                "upload_url": backend._supabase_storage_direct_tus_url(),
                "upload_token": upload_token,
                "storage_publishable_key": cls.local_supabase_anon_key,
                "bucket": bucket,
                "path": storage_path,
                "content_type": mime_type,
                "cache_control": "0",
                "headers": {
                    "x-signature": upload_token,
                    "Cache-Control": "no-store",
                },
                "metadata": {
                    "bucketName": bucket,
                    "objectName": storage_path,
                    "contentType": mime_type,
                    "cacheControl": "0",
                },
            }

        def finalize_tus_upload(
            conn: Any,
            document_id: str,
            upload_id: str,
            payload: dict[str, Any],
            session: dict[str, Any] | None,
        ) -> dict[str, Any]:
            asset_row = conn.execute(
                "SELECT * FROM official_document_editor_assets "
                "WHERE id = ? AND document_id = ?",
                (upload_id, document_id),
            ).fetchone()
            if not asset_row:
                return original_finalize(conn, document_id, upload_id, payload, session)
            asset = dict(asset_row)
            if asset.get("upload_status") == "pending":
                data = backend.supabase_storage_download(
                    str(asset["storage_path"]), str(asset["storage_bucket"])
                )
                previous = backend.DEPLOYMENT_ENV
                backend.DEPLOYMENT_ENV = "test"
                try:
                    original_local_upload(
                        conn,
                        document_id,
                        upload_id,
                        data,
                        session,
                        str(asset["mime_type"]),
                    )
                finally:
                    backend.DEPLOYMENT_ENV = previous
            try:
                return original_finalize(conn, document_id, upload_id, payload, session)
            finally:
                if asset.get("upload_status") in {"pending", "uploading", "uploaded"}:
                    backend.supabase_storage_delete(
                        str(asset["storage_path"]), str(asset["storage_bucket"])
                    )

        for name, replacement in (
            ("create_official_editor_upload_intent", create_tus_intent),
            ("finalize_official_editor_upload", finalize_tus_upload),
        ):
            patcher = mock.patch.object(backend, name, side_effect=replacement)
            patcher.start()
            cls.storage_patches.append(patcher)

    @classmethod
    def _build_case_definitions(cls) -> list[dict[str, Any]]:
        aliases = cls.rng.sample(
            ["amber", "birch", "cedar", "dawn", "ember", "fern", "gale", "harbor", "iris", "jade"],
            5,
        )
        policies = [
            ("staff", "A", "合作意向書", "CO-001", ("portrait",)),
            ("staff", "B", "商務合約", "CO-001", ("landscape",)),
            ("staff", "C", "服務委託合約", "CO-001", ("portrait", "landscape")),
            ("section_chief", "D", "採購合約", "CO-001", ("landscape", "portrait", "landscape")),
            ("department_head", "C", "官方公文（需公司最高層代表時）", "CO-002", ("portrait", "landscape")),
        ]
        cases: list[dict[str, Any]] = []
        for ordinal, (alias, policy) in enumerate(zip(aliases, policies), start=1):
            role, route, category, company_id, orientations = policy
            identity_token = f"{ACCEPTANCE_SEED}:{ordinal}:{alias}:{role}:{company_id}"
            cases.append(
                {
                    "ordinal": ordinal,
                    "alias": alias,
                    "role": role,
                    "route": route,
                    "category": category,
                    "company_id": company_id,
                    "orientations": orientations,
                    "finance_user_id": f"acceptance-applicant-{_fingerprint(identity_token)}",
                    "auth_user_id": f"google-{_fingerprint(identity_token + ':auth')}",
                    "email": f"acceptance-{_fingerprint(identity_token + ':mail')}@example.test",
                }
            )
        cls.rng.shuffle(cases)
        return cases

    @classmethod
    def _actor_identity(cls, company_id: str, slot: str, role: str) -> dict[str, Any]:
        token = f"{ACCEPTANCE_SEED}:{company_id}:{slot}:{role}"
        return {
            "finance_user_id": f"acceptance-actor-{_fingerprint(token)}",
            "auth_user_id": f"google-{_fingerprint(token + ':auth')}",
            "email": f"actor-{_fingerprint(token + ':mail')}@example.test",
            "name": f"隔離簽核角色{_fingerprint(token)[:6]}",
            "role": role,
        }

    @staticmethod
    def _identity_record(
        identity: dict[str, Any],
        *,
        tenant_id: str,
        entity_id: str,
        department_code: str,
        department_name: str,
        revision: int,
    ) -> dict[str, Any]:
        profile = backend.strict_finance_role_profile(identity["role"])
        return {
            "tenantId": tenant_id,
            "financeUserId": identity["finance_user_id"],
            "authUserId": identity["auth_user_id"],
            "name": identity["name"],
            "email": identity["email"],
            "role": identity["role"],
            "roleLabel": profile["title"],
            "entityId": entity_id,
            "departmentCode": department_code,
            "departmentName": department_name,
            "jobTitle": profile["title"],
            "extension": f"9{revision:03d}",
            "contactEmail": identity["email"],
            "orgStatus": "active",
            "sourceUpdatedAt": "2026-08-27T00:00:00Z",
            "memberRevision": revision,
            "active": True,
            "authUserBound": True,
            "googleLoginVerified": True,
        }

    @classmethod
    def _build_finance_snapshots(cls) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        companies = {
            "CO-001": {
                "tenant_id": "tenant-acceptance-one",
                "entity_id": "E1",
                "name": "隔離驗收公司一",
                "department_code": "QA100",
                "department_name": "隔離驗收部一",
            },
            "CO-002": {
                "tenant_id": "tenant-acceptance-two",
                "entity_id": "E2",
                "name": "隔離驗收公司二",
                "department_code": "QA200",
                "department_name": "隔離驗收部二",
            },
        }
        actor_roles = {
            "applicantManager": "section_chief",
            "departmentHead": "department_head",
            "ceo": "ceo",
            "adminDirector": "admin_director",
            "generalAffairs": "ga_chief",
        }
        actors_by_company: dict[str, dict[str, dict[str, Any]]] = {}
        identities: dict[str, dict[str, Any]] = {}
        for company_id, company in companies.items():
            actors_by_company[company_id] = {}
            for index, (slot, role) in enumerate(actor_roles.items(), start=1):
                actor = cls._actor_identity(company_id, slot, role)
                actor["name"] = f"隔離{slot}{index}"
                actors_by_company[company_id][slot] = actor
                identities[actor["email"]] = actor

        for case in cls.case_definitions:
            case["name"] = f"隔離申請人{case['ordinal']}"
            identities[case["email"]] = case

        snapshots: dict[str, dict[str, Any]] = {}
        for email, identity in identities.items():
            company_id = identity.get("company_id") or next(
                company_key
                for company_key, company_actors in actors_by_company.items()
                if identity in company_actors.values()
            )
            company = companies[company_id]
            identity_record = cls._identity_record(
                identity,
                tenant_id=company["tenant_id"],
                entity_id=company["entity_id"],
                department_code=company["department_code"],
                department_name=company["department_name"],
                revision=100 + len(snapshots),
            )
            is_applicant = "ordinal" in identity
            actors: dict[str, Any] = {slot: None for slot in actor_roles}
            if is_applicant:
                for slot, actor in actors_by_company[company_id].items():
                    actors[slot] = cls._identity_record(
                        actor,
                        tenant_id=company["tenant_id"],
                        entity_id=company["entity_id"],
                        department_code=company["department_code"],
                        department_name=company["department_name"],
                        revision=500 + list(actor_roles).index(slot),
                    )
            snapshots[email] = {
                "ok": True,
                "source": "finance",
                "schemaVersion": 2,
                "snapshotAt": "2026-08-27T00:00:00Z",
                "identity": identity_record,
                "company": {
                    "tenantId": company["tenant_id"],
                    "entityId": company["entity_id"],
                    "name": company["name"],
                    "taxId": f"TEST-{company_id}",
                    "address": f"隔離測試地址-{company_id}",
                    "active": True,
                },
                "actors": actors,
                "workflowReady": bool(is_applicant),
                "issues": [],
            }
        return snapshots, identities

    @classmethod
    def _prepare_isolated_companies_and_seals(cls) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        company_fixtures = {
            "CO-001": {
                "tenant_id": "tenant-acceptance-one",
                "company_name": "隔離驗收公司一",
                "department_id": "QA100",
                "department_name": "隔離驗收部一",
            },
            "CO-002": {
                "tenant_id": "tenant-acceptance-two",
                "company_name": "隔離驗收公司二",
                "department_id": "QA200",
                "department_name": "隔離驗收部二",
            },
        }
        with backend.connect() as conn:
            for company_id, fixture in company_fixtures.items():
                conn.execute(
                    "UPDATE companies SET finance_tenant_id = ?, source_system = 'finance', status = 'active' WHERE id = ?",
                    (fixture["tenant_id"], company_id),
                )
                conn.execute(
                    """
                    INSERT INTO department_registry (
                      id, company_name, name, manager_role, status, created_at, updated_at
                    ) VALUES (?, ?, ?, '隔離 Finance 組織主檔', '啟用', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      company_name = excluded.company_name,
                      name = excluded.name,
                      manager_role = excluded.manager_role,
                      status = excluded.status,
                      updated_at = excluded.updated_at
                    """,
                    (
                        fixture["department_id"],
                        fixture["company_name"],
                        fixture["department_name"],
                        backend.now(),
                        backend.now(),
                    ),
                )
                seal = conn.execute(
                    """
                    SELECT id FROM company_seals
                    WHERE company_id = ? AND seal_category = 'general_seal'
                      AND seal_size_type = 'large_seal' AND is_active = 1
                    ORDER BY id LIMIT 1
                    """,
                    (company_id,),
                ).fetchone()
                if not seal:
                    raise AssertionError(f"isolated seal slot missing for {company_id}")
                image = Image.new("RGBA", (400, 400), (255, 255, 255, 0))
                draw = ImageDraw.Draw(image)
                color = (150, 0, 0, 255) if company_id == "CO-001" else (0, 70, 150, 255)
                draw.rectangle((28, 28, 372, 372), outline=color, width=18)
                draw.line((80, 200, 320, 200), fill=color, width=14)
                stream = io.BytesIO()
                image.save(stream, format="PNG")
                uploaded = backend.upload_company_seal_file(
                    conn,
                    str(seal["id"]),
                    {
                        "file_name": f"isolated-{company_id.lower()}-not-a-real-seal.png",
                        "file_mime_type": "image/png",
                        "content_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
                        "actor": "isolated-acceptance-fixture",
                        "render_width_mm": 30,
                        "render_height_mm": 30,
                    },
                )
                file_meta = backend.require_current_company_seal_file(conn, str(seal["id"]))
                profile = backend.company_seal_file_dimension_profile(
                    "large_seal", file_meta, current=True
                )
                result[company_id] = {
                    "seal_id": str(seal["id"]),
                    "seal_file_id": file_meta["id"],
                    "seal_file_sha256": file_meta["file_hash"],
                    "profile": profile,
                    "uploaded": uploaded,
                }
            conn.commit()
        return result

    @classmethod
    def _request(
        cls,
        method: str,
        path: str,
        *,
        token: str = "",
        json_body: Any | None = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        request_headers = {"User-Agent": "edoc-isolated-five-account/1.0", **(headers or {})}
        body = raw_body
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        if body is not None:
            request_headers["Content-Length"] = str(len(body))
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            response_body = response.read()
            return HttpResult(int(response.status), tuple(response.getheaders()), response_body)
        finally:
            connection.close()

    @classmethod
    def _storage_request(
        cls,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResult:
        parsed = urllib.parse.urlparse(url)
        configured = urllib.parse.urlparse(cls.local_supabase_api_url)
        if (
            parsed.scheme != configured.scheme
            or parsed.hostname != configured.hostname
            or parsed.port != configured.port
        ):
            raise AssertionError("local_supabase_tus_response_origin_invalid")
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=30)
        try:
            request_headers = {**(headers or {})}
            if body is not None:
                request_headers["Content-Length"] = str(len(body))
            target = urllib.parse.urlunparse(("", "", parsed.path, parsed.params, parsed.query, ""))
            connection.request(method, target, body=body, headers=request_headers)
            response = connection.getresponse()
            return HttpResult(
                int(response.status), tuple(response.getheaders()), response.read()
            )
        finally:
            connection.close()

    @staticmethod
    def _header(result: HttpResult, name: str) -> str:
        return next(
            (value for key, value in result.headers if key.lower() == name.lower()),
            "",
        )

    @classmethod
    def _perform_tus_upload(
        cls, intent: dict[str, Any], data: bytes
    ) -> dict[str, Any]:
        if intent.get("protocol") != "tus":
            raise AssertionError("local_supabase_tus_intent_required")
        endpoint = str(intent.get("upload_url") or "")
        expected_endpoint = f"{cls.local_supabase_api_url}/storage/v1/upload/resumable/sign"
        if endpoint.rstrip("/") != expected_endpoint:
            raise AssertionError("local_supabase_tus_endpoint_mismatch")
        signature = str(intent.get("upload_token") or "")
        if not signature:
            raise AssertionError("local_supabase_tus_signature_missing")
        metadata_values = {
            "bucketName": str(intent.get("bucket") or ""),
            "objectName": str(intent.get("path") or ""),
            "contentType": str(intent.get("content_type") or ""),
            "cacheControl": str(intent.get("cache_control") or "0"),
        }
        if not all(metadata_values.values()):
            raise AssertionError("local_supabase_tus_metadata_missing")
        upload_metadata = ",".join(
            f"{key} {base64.b64encode(value.encode('utf-8')).decode('ascii')}"
            for key, value in metadata_values.items()
        )
        base_headers = {
            "apikey": cls.local_supabase_anon_key,
            "x-signature": signature,
            "Tus-Resumable": "1.0.0",
        }
        create_headers = {
            **base_headers,
            "Upload-Length": str(len(data)),
            "Upload-Metadata": upload_metadata,
        }
        created = cls._storage_request("POST", endpoint, headers=create_headers)
        if created.status != 201:
            raise AssertionError(f"local_supabase_tus_create_failed:{created.status}")
        location = cls._header(created, "Location")
        if not location:
            raise AssertionError("local_supabase_tus_location_missing")
        upload_url = urllib.parse.urljoin(endpoint, location)
        parsed_endpoint = urllib.parse.urlparse(endpoint)
        parsed_upload = urllib.parse.urlparse(upload_url)
        if (
            parsed_upload.scheme,
            parsed_upload.hostname,
            parsed_upload.port,
        ) != (
            parsed_endpoint.scheme,
            parsed_endpoint.hostname,
            parsed_endpoint.port,
        ) or not parsed_upload.path.startswith(
            "/storage/v1/upload/resumable/sign/"
        ):
            raise AssertionError("local_supabase_tus_location_invalid")
        split_at = max(1, len(data) // 2)
        first_chunk = data[:split_at]
        patched = cls._storage_request(
            "PATCH",
            upload_url,
            headers={
                **base_headers,
                "Upload-Offset": "0",
                "Content-Type": "application/offset+octet-stream",
            },
            body=first_chunk,
        )
        if patched.status != 204:
            raise AssertionError(f"local_supabase_tus_patch_failed:{patched.status}")
        if int(cls._header(patched, "Upload-Offset") or -1) != split_at:
            raise AssertionError("local_supabase_tus_offset_mismatch")
        headed = cls._storage_request(
            "HEAD", upload_url, headers=base_headers
        )
        if headed.status not in {200, 204}:
            raise AssertionError(f"local_supabase_tus_head_failed:{headed.status}")
        if int(cls._header(headed, "Upload-Offset") or -1) != split_at:
            raise AssertionError("local_supabase_tus_resume_offset_mismatch")
        completed = cls._storage_request(
            "PATCH",
            upload_url,
            headers={
                **base_headers,
                "Upload-Offset": str(split_at),
                "Content-Type": "application/offset+octet-stream",
            },
            body=data[split_at:],
        )
        if completed.status != 204:
            raise AssertionError(
                f"local_supabase_tus_complete_failed:{completed.status}"
            )
        if int(cls._header(completed, "Upload-Offset") or -1) != len(data):
            raise AssertionError("local_supabase_tus_complete_offset_mismatch")

        cls._assert_private_storage_denied(
            metadata_values["bucketName"], metadata_values["objectName"]
        )
        return {"uploadUrl": upload_url, "offset": len(data)}

    @classmethod
    def _assert_tus_replay_cannot_mutate_finalized_asset(
        cls,
        intent: dict[str, Any],
        original_data: bytes,
        document_id: str,
    ) -> None:
        """Replay a still-valid capability with different bytes after finalize.

        Supabase signed upload tokens are expiring, not cryptographically
        single-use.  The invariant that matters is that the finalized file
        object has already been promoted away from the capability-writable
        staging path.
        """
        upload_id = str(intent.get("upload_id") or "")
        with backend.connect() as conn:
            before_asset = conn.execute(
                "SELECT file_object_id, storage_bucket, storage_path, sha256, "
                "upload_status FROM official_document_editor_assets "
                "WHERE id = ? AND document_id = ?",
                (upload_id, document_id),
            ).fetchone()
            if not before_asset or before_asset["upload_status"] != "finalized":
                raise AssertionError("local_supabase_tus_finalized_asset_missing")
            before_object, before_bytes = backend.read_file_object_bytes(
                conn,
                str(before_asset["file_object_id"]),
            )
        if before_bytes != original_data or backend.sha256_bytes(before_bytes) != str(before_asset["sha256"]):
            raise AssertionError("local_supabase_tus_finalized_asset_hash_invalid")

        endpoint = str(intent.get("upload_url") or "")
        signature = str(intent.get("upload_token") or "")
        metadata_values = {
            "bucketName": str(intent.get("bucket") or ""),
            "objectName": str(intent.get("path") or ""),
            "contentType": str(intent.get("content_type") or ""),
            "cacheControl": str(intent.get("cache_control") or "0"),
        }
        upload_metadata = ",".join(
            f"{key} {base64.b64encode(value.encode('utf-8')).decode('ascii')}"
            for key, value in metadata_values.items()
        )
        altered = b"X" + original_data[1:]
        if len(altered) != len(original_data) or altered == original_data:
            raise AssertionError("local_supabase_tus_replay_fixture_invalid")
        base_headers = {
            "apikey": cls.local_supabase_anon_key,
            "x-signature": signature,
            "Tus-Resumable": "1.0.0",
        }
        replay_create = cls._storage_request(
            "POST",
            endpoint,
            headers={
                **base_headers,
                "Upload-Length": str(len(altered)),
                "Upload-Metadata": upload_metadata,
            },
        )
        replay_wrote_staging = False
        if replay_create.status == 201:
            location = cls._header(replay_create, "Location")
            if not location:
                raise AssertionError("local_supabase_tus_replay_location_missing")
            replay_patch = cls._storage_request(
                "PATCH",
                urllib.parse.urljoin(endpoint, location),
                headers={
                    **base_headers,
                    "Upload-Offset": "0",
                    "Content-Type": "application/offset+octet-stream",
                },
                body=altered,
            )
            if 200 <= replay_patch.status < 300:
                replay_wrote_staging = True
            elif not 400 <= replay_patch.status < 500:
                raise AssertionError(
                    f"local_supabase_tus_replay_unexpected:{replay_patch.status}"
                )
        elif not 400 <= replay_create.status < 500:
            raise AssertionError(
                f"local_supabase_tus_replay_create_unexpected:{replay_create.status}"
            )

        with backend.connect() as conn:
            after_asset = conn.execute(
                "SELECT file_object_id, storage_bucket, storage_path, sha256, "
                "upload_status FROM official_document_editor_assets "
                "WHERE id = ? AND document_id = ?",
                (upload_id, document_id),
            ).fetchone()
            if not after_asset:
                raise AssertionError("local_supabase_tus_finalized_asset_disappeared")
            after_object, after_bytes = backend.read_file_object_bytes(
                conn,
                str(after_asset["file_object_id"]),
            )
        if (
            tuple(before_asset) != tuple(after_asset)
            or str(before_object.get("id") or "") != str(after_object.get("id") or "")
            or before_bytes != after_bytes
            or backend.sha256_bytes(after_bytes) != str(after_asset["sha256"])
        ):
            raise AssertionError("local_supabase_tus_replay_mutated_finalized_asset")
        if replay_wrote_staging:
            backend.supabase_storage_delete(
                metadata_values["objectName"],
                metadata_values["bucketName"],
            )
        cls.tus_replay_isolations += 1

    @classmethod
    def _assert_private_storage_denied(cls, bucket: str, storage_path: str) -> None:
        url = (
            f"{cls.local_supabase_api_url}/storage/v1/object/"
            f"{urllib.parse.quote(bucket, safe='')}/"
            f"{urllib.parse.quote(storage_path, safe='/')}"
        )
        denied = cls._storage_request(
            "GET",
            url,
            headers={
                "apikey": cls.local_supabase_anon_key,
                "Authorization": f"Bearer {cls.local_supabase_anon_key}",
            },
        )
        if denied.status not in {400, 401, 403, 404}:
            raise AssertionError(
                f"local_supabase_private_object_exposed:{denied.status}"
            )
        cls.private_storage_denials += 1

    @classmethod
    def _expect_json(
        cls,
        method: str,
        path: str,
        expected_status: int,
        **kwargs: Any,
    ) -> Any:
        result = cls._request(method, path, **kwargs)
        if result.status != expected_status:
            detail = result.body.decode("utf-8", "replace")[:600]
            raise AssertionError(f"{method} {path}: expected {expected_status}, got {result.status}: {detail}")
        return result.json()

    @classmethod
    def _portal_session(cls, email: str) -> str:
        normalized = email.lower()
        if normalized in cls.tokens_by_email:
            return cls.tokens_by_email[normalized]
        identity = cls.identity_by_email[normalized]
        now_ts = int(time.time())
        assertion = {
            "moduleId": "edoc",
            "authUserId": identity["auth_user_id"],
            "email": normalized,
            "iat": now_ts,
            "exp": now_ts + 300,
            "jti": f"jti-{_fingerprint(normalized + ':' + str(now_ts) + ':' + str(len(cls.tokens_by_email)))}",
        }
        encoded = _base64url(
            json.dumps(assertion, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signed = f"{encoded}.{backend.base64url_hmac_sha256(TEST_HANDOFF_SECRET, encoded)}"
        form = urllib.parse.urlencode({"token": signed}).encode("ascii")
        handoff = cls._request(
            "POST",
            "/api/auth/handoff",
            raw_body=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": cls.origin,
            },
        )
        if handoff.status != 303:
            raise AssertionError(f"portal handoff failed with {handoff.status}")
        cookie = ""
        for name, value in handoff.headers:
            if name.lower() == "set-cookie" and value.startswith(f"{backend.EDOC_HANDOFF_COOKIE_NAME}="):
                cookie = value.split(";", 1)[0]
                break
        if not cookie:
            raise AssertionError("portal handoff cookie missing")
        session = cls._expect_json(
            "POST",
            "/api/auth/handoff-session",
            200,
            raw_body=b"",
            headers={
                "Content-Length": "0",
                "Cookie": cookie,
                "X-EDOC-Handoff-Exchange": "1",
                "Sec-Fetch-Site": "same-origin",
                "Origin": cls.origin,
            },
        )
        token = str(session.get("token") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
            raise AssertionError("portal bearer missing")
        if str((session.get("user") or {}).get("account_source") or "").lower() != "finance":
            raise AssertionError("portal session is not Finance-owned")
        snapshot_identity = cls.snapshots_by_email[normalized]["identity"]
        with backend.connect() as conn:
            projected = conn.execute(
                """
                SELECT account_source, auth_user_id, finance_employee_id,
                       finance_tenant_id, company_id, unit, status,
                       last_synced_from_logging_at
                FROM users WHERE lower(email) = ?
                """,
                (normalized,),
            ).fetchone()
        if not projected:
            raise AssertionError("finance_identity_projection_missing")
        expected_company = "CO-001" if snapshot_identity["entityId"] == "E1" else "CO-002"
        expected_projection = {
            "account_source": "finance",
            "auth_user_id": identity["auth_user_id"],
            "finance_employee_id": identity["finance_user_id"],
            "finance_tenant_id": snapshot_identity["tenantId"],
            "company_id": expected_company,
            "unit": snapshot_identity["departmentName"],
            "status": "啟用",
        }
        for field, expected in expected_projection.items():
            if str(projected[field] or "") != str(expected):
                raise AssertionError(f"finance_identity_projection_mismatch_{field}")
        if not str(projected["last_synced_from_logging_at"] or ""):
            raise AssertionError("finance_identity_projection_timestamp_missing")
        cls.tokens_by_email[normalized] = token
        return token

    @classmethod
    def _token_for_user_id(cls, user_id: str) -> str:
        with backend.connect() as conn:
            row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AssertionError("approval actor missing from Finance projection")
        return cls._portal_session(str(row["email"]))

    @staticmethod
    def _make_a4_pdf(case: dict[str, Any]) -> bytes:
        stream = io.BytesIO()
        first_size = A4 if case["orientations"][0] == "portrait" else landscape(A4)
        pdf = canvas.Canvas(stream, pagesize=first_size, pageCompression=1)
        pdf.setTitle(f"isolated-case-{case['ordinal']}")
        for page_number, orientation in enumerate(case["orientations"], start=1):
            page_size = A4 if orientation == "portrait" else landscape(A4)
            if page_number > 1:
                pdf.setPageSize(page_size)
            width, height = page_size
            pdf.setFont("Helvetica", 12)
            pdf.drawString(48, height - 52, f"ISOLATED ACCEPTANCE CASE {case['ordinal']} PAGE {page_number}")
            pdf.rect(36, 36, width - 72, height - 96, stroke=1, fill=0)
            pdf.showPage()
        pdf.save()
        return stream.getvalue()

    @staticmethod
    def _make_attachment_pdf(case_ordinal: int) -> bytes:
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(48, A4[1] - 52, f"ISOLATED ATTACHMENT CASE {case_ordinal}")
        pdf.showPage()
        pdf.save()
        return stream.getvalue()

    @classmethod
    def _editor_state(cls, revision: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
        state = copy.deepcopy(revision["state"])
        if len(state.get("pages") or []) != len(case["orientations"]):
            raise AssertionError("editor page count mismatch")
        seal = cls.seals[case["company_id"]]
        profile = seal["profile"]
        elements: list[dict[str, Any]] = []
        for page_number, page in enumerate(state["pages"], start=1):
            width = float(page["widthPt"])
            height = float(page["heightPt"])
            short_edge, long_edge = sorted((width, height))
            if abs(short_edge - backend.EDOC_A4_WIDTH_PT) > 1 or abs(long_edge - backend.EDOC_A4_HEIGHT_PT) > 1:
                raise AssertionError("non-A4 geometry reached editor")
            expected_orientation = case["orientations"][page_number - 1]
            actual_orientation = "landscape" if width > height else "portrait"
            if actual_orientation != expected_orientation:
                raise AssertionError("editor orientation mismatch")
            marker = f"ACCEPTANCE-{case['ordinal']}-PAGE-{page_number}"
            text_x = max(36.0, width - profile["width_pt"] - 84.0)
            text_y = 72.0 + profile["height_pt"] * 0.35
            elements.append(
                {
                    "id": f"TEXT-{case['ordinal']}-{page_number}",
                    "pageId": page["pageId"],
                    "kind": "text",
                    "x": text_x,
                    "y": text_y,
                    "width": min(190.0, width - text_x - 24.0),
                    "height": 24.0,
                    "rotation": 0,
                    "opacity": 1,
                    "zIndex": 20,
                    "properties": {
                        "text": marker,
                        "fontSize": 11,
                        "fontFamily": "edukai",
                        "color": "#202020",
                    },
                }
            )
        last_page = state["pages"][-1]
        last_width = float(last_page["widthPt"])
        elements.append(
            {
                "id": f"SEAL-{case['ordinal']}",
                "pageId": last_page["pageId"],
                "kind": "seal",
                "x": max(36.0, last_width - profile["width_pt"] - 72.0),
                "y": 72.0,
                "width": profile["width_pt"],
                "height": profile["height_pt"],
                "rotation": 0,
                "opacity": 1,
                "zIndex": 10,
                "properties": {
                    "sealId": seal["seal_id"],
                    "sealFileId": seal["seal_file_id"],
                    "sealFileSha256": seal["seal_file_sha256"],
                    "renderWidthMm": profile["width_mm"],
                    "renderHeightMm": profile["height_mm"],
                    "dimensionPolicyVersion": profile["dimension_policy_version"],
                },
            }
        )
        state["elements"] = elements
        return state

    @classmethod
    def _run_case(cls, case: dict[str, Any], all_applicant_tokens: dict[int, str]) -> dict[str, Any]:
        applicant_token = all_applicant_tokens[case["ordinal"]]
        expected_department = "隔離驗收部一" if case["company_id"] == "CO-001" else "隔離驗收部二"
        directory = cls._expect_json(
            "GET",
            "/api/finance-directory",
            200,
            token=applicant_token,
        )
        if directory.get("currentCompanyId") != case["company_id"]:
            raise AssertionError("finance_directory_current_company_mismatch")
        if not any(
            item.get("name") == expected_department
            and case["company_id"] in set(item.get("entityCodes") or [])
            for item in directory.get("departments") or []
        ):
            # Local compatibility responses scope entityCodes by Finance entity
            # id (E1/E2), while the browser later maps that identifier back to
            # the selected company. Accept that canonical representation too.
            expected_entity = "E1" if case["company_id"] == "CO-001" else "E2"
            if not any(
                item.get("name") == expected_department
                and expected_entity in set(item.get("entityCodes") or [])
                for item in directory.get("departments") or []
            ):
                raise AssertionError("finance_directory_department_missing")
        readiness = cls._expect_json(
            "GET",
            f"/api/official-documents/workflow-readiness?route_code={case['route']}",
            200,
            token=applicant_token,
        )
        if not readiness.get("submitAllowed"):
            raise AssertionError(f"workflow readiness blocked: {readiness.get('blockers')}")

        draft = cls._expect_json(
            "POST",
            "/api/official-documents/editor-drafts",
            201,
            token=applicant_token,
            json_body={
                "company_id": case["company_id"],
                "title": f"隔離五帳號驗收第 {case['ordinal']} 件",
                "subject": f"隔離五帳號驗收第 {case['ordinal']} 件",
                "request_reason": "隔離自動化驗收",
                "document_category": case["category"],
                "dispatch_method": "no_dispatch_required",
            },
        )
        document_id = draft["document_id"]
        source_pdf = cls._make_a4_pdf(case)
        source_hash = backend.sha256_bytes(source_pdf)
        upload_intent = cls._expect_json(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-uploads",
            201,
            token=applicant_token,
            json_body={
                "asset_kind": "source_pdf",
                "file_name": f"isolated-case-{case['ordinal']}.pdf",
                "mime_type": "application/pdf",
                "size_bytes": len(source_pdf),
                "sha256": source_hash,
            },
        )
        if upload_intent.get("protocol") != cls.upload_protocol.replace(
            "local_supabase_", ""
        ):
            raise AssertionError("isolated upload protocol changed unexpectedly")
        if cls.upload_protocol == "local_supabase_tus":
            if cls.local_supabase_service_role_key in json.dumps(
                upload_intent, ensure_ascii=False
            ):
                raise AssertionError("local_supabase_tus_server_key_exposed")
            cls._perform_tus_upload(upload_intent, source_pdf)
        else:
            cls._expect_json(
                "PUT",
                upload_intent["upload_url"],
                201,
                token=applicant_token,
                raw_body=source_pdf,
                headers={"Content-Type": "application/pdf"},
            )
        finalized = cls._expect_json(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-uploads/{urllib.parse.quote(upload_intent['upload_id'])}/finalize",
            200,
            token=applicant_token,
            json_body={"sha256": source_hash},
        )
        if cls.upload_protocol == "local_supabase_tus":
            cls._assert_tus_replay_cannot_mutate_finalized_asset(
                upload_intent,
                source_pdf,
                document_id,
            )
        revision = finalized["editor_revision"]
        finalize_replay = cls._expect_json(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-uploads/"
            f"{urllib.parse.quote(upload_intent['upload_id'])}/finalize",
            200,
            token=applicant_token,
            json_body={"sha256": source_hash},
        )
        replay_revision = finalize_replay["editor_revision"]
        if (
            replay_revision.get("id") != revision.get("id")
            or replay_revision.get("revisionNo") != revision.get("revisionNo")
            or replay_revision.get("manifestSha256") != revision.get("manifestSha256")
        ):
            raise AssertionError("editor_finalize_replay_mutated_revision")
        cls.finalize_replay_idempotent_count += 1
        state = cls._editor_state(revision, case)
        saved = cls._expect_json(
            "PUT",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-state",
            200,
            token=applicant_token,
            json_body={
                "revisionNo": revision["revisionNo"],
                "baseManifestSha256": revision["manifestSha256"],
                "state": state,
            },
        )

        attachment = cls._make_attachment_pdf(case["ordinal"])
        attachment_upload = cls._expect_json(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/files",
            201,
            token=applicant_token,
            json_body={
                "file_name": f"isolated-attachment-{case['ordinal']}.pdf",
                "file_mime_type": "application/pdf",
                "content_base64": base64.b64encode(attachment).decode("ascii"),
            },
        )
        attachment_file_id = attachment_upload["file"]["id"]

        preflight = cls._expect_json(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-preflight",
            201,
            token=applicant_token,
            json_body={
                "editorRevisionId": saved["id"],
                "manifestSha256": saved["manifestSha256"],
            },
        )
        detail = cls._expect_json(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/submit",
            200,
            token=applicant_token,
            json_body={
                "editorRevisionId": preflight["editorRevisionId"],
                "manifestSha256": preflight["manifestSha256"],
                "preparedFileId": preflight["preparedFileId"],
                "preparedSha256": preflight["preparedSha256"],
                "comment": "隔離驗收送簽",
            },
        )
        if detail["metadata"]["official_seal"]["approval_route_code"] != case["route"]:
            raise AssertionError("server-derived route mismatch")
        expected_keys = [
            step["key"]
            for step in backend.official_workflow_steps_for_finance_applicant(case["route"], case["role"])
        ]
        actual_keys = [step["step_key"] for step in detail["approval_steps"]]
        if actual_keys != expected_keys:
            raise AssertionError(f"workflow mismatch expected={expected_keys} actual={actual_keys}")

        locked_attempt = cls._request(
            "PUT",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-state",
            token=applicant_token,
            json_body={
                "revisionNo": preflight["revisionNo"],
                "baseManifestSha256": preflight["manifestSha256"],
                "state": preflight["revision"]["state"],
            },
        )
        if locked_attempt.status != 409:
            raise AssertionError("submitted editor revision was not locked")

        review_downloads = 0
        while detail["current_status"] not in {"stamped", "stamping_failed"}:
            step = next(
                item for item in detail["approval_steps"] if item["step_key"] == detail["current_step"]
            )
            approver_token = cls._token_for_user_id(step["approver_user_id"])
            review_files = [
                item for item in detail["files"] if item["file_type"] in {"original_pdf", "prepared_pdf", "attachment"}
            ]
            if {item["file_type"] for item in review_files} != {"original_pdf", "prepared_pdf", "attachment"}:
                raise AssertionError("approval package is missing source, prepared, or attachment")
            for file_meta in review_files:
                downloaded = cls._request(
                    "GET",
                    f"/api/official-documents/{urllib.parse.quote(document_id)}/files/{urllib.parse.quote(file_meta['id'])}/download",
                    token=approver_token,
                )
                if downloaded.status != 200 or not downloaded.body:
                    raise AssertionError("approver could not download complete review package")
                review_downloads += 1
            detail = cls._expect_json(
                "POST",
                f"/api/official-documents/{urllib.parse.quote(document_id)}/approve",
                200,
                token=approver_token,
                json_body={
                    "expected_step_id": step["id"],
                    "comment": f"隔離驗收核准 {step['step_key']}",
                    "prepared_sha256": detail["stamp_request"]["prepared_sha256"],
                    "manifest_sha256": detail["stamp_request"]["editor_manifest_sha256"],
                    "review_acknowledgements": {
                        "original_reviewed": True,
                        "edited_version_reviewed": True,
                        "attachments_reviewed": True,
                    },
                },
            )
        if detail["current_status"] != "stamped" or detail["stamp_request"]["status"] != "stamped":
            raise AssertionError("automatic stamping did not complete")

        stamped_file = next(item for item in detail["files"] if item["file_type"] == "stamped_pdf")
        prepared_file = next(item for item in detail["files"] if item["file_type"] == "prepared_pdf")
        stamped_download = cls._request(
            "GET",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/files/{urllib.parse.quote(stamped_file['id'])}/download",
            token=applicant_token,
        )
        if stamped_download.status != 200 or not stamped_download.body.startswith(b"%PDF"):
            raise AssertionError("applicant could not receive stamped PDF")
        prepared_download = cls._request(
            "GET",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/files/{urllib.parse.quote(prepared_file['id'])}/download",
            token=applicant_token,
        )
        if prepared_download.status != 200:
            raise AssertionError("applicant could not compare prepared PDF")
        if backend.sha256_bytes(stamped_download.body) == backend.sha256_bytes(prepared_download.body):
            raise AssertionError("stamped derivative is byte-identical to prepared PDF")
        stamped_reader = PdfReader(io.BytesIO(stamped_download.body))
        if len(stamped_reader.pages) != len(case["orientations"]):
            raise AssertionError("stamped page count changed")
        for page, expected_orientation in zip(stamped_reader.pages, case["orientations"]):
            width = float(page.cropbox.width)
            height = float(page.cropbox.height)
            actual_orientation = "landscape" if width > height else "portrait"
            if actual_orientation != expected_orientation:
                raise AssertionError("stamped orientation changed")
            short_edge, long_edge = sorted((width, height))
            if abs(short_edge - backend.EDOC_A4_WIDTH_PT) > 1 or abs(long_edge - backend.EDOC_A4_HEIGHT_PT) > 1:
                raise AssertionError("stamped PDF is not A4")

        detail = cls._expect_json(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/confirm",
            200,
            token=applicant_token,
            json_body={"comment": "隔離驗收申請人確認收件"},
        )
        if detail["current_status"] != "closed":
            raise AssertionError("applicant receipt did not close workflow")
        if not any(item["id"] == attachment_file_id for item in detail["attachments"]):
            raise AssertionError("attachment disappeared after approval")

        participant_ids = {
            detail["applicant_id"],
            *(item["approver_user_id"] for item in detail["approval_steps"] if item.get("approver_user_id")),
        }
        for participant_id in participant_ids:
            participant_token = cls._token_for_user_id(participant_id)
            response = cls._request(
                "GET",
                f"/api/official-documents/{urllib.parse.quote(document_id)}/files/{urllib.parse.quote(stamped_file['id'])}/download",
                token=participant_token,
            )
            if response.status != 200 or backend.sha256_bytes(response.body) != stamped_file["file_hash"]:
                raise AssertionError("workflow participant lost completed-file access")

        same_company_other = next(
            candidate
            for candidate in cls.case_definitions
            if candidate["company_id"] == case["company_id"] and candidate["ordinal"] != case["ordinal"]
        ) if case["company_id"] == "CO-001" else None
        denial_statuses: list[int] = []
        if same_company_other:
            denied = cls._request(
                "GET",
                f"/api/official-documents/{urllib.parse.quote(document_id)}/files/{urllib.parse.quote(stamped_file['id'])}/download",
                token=all_applicant_tokens[same_company_other["ordinal"]],
            )
            denial_statuses.append(denied.status)
        cross_company = next(
            candidate for candidate in cls.case_definitions if candidate["company_id"] != case["company_id"]
        )
        denied = cls._request(
            "GET",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/files/{urllib.parse.quote(stamped_file['id'])}/download",
            token=all_applicant_tokens[cross_company["ordinal"]],
        )
        denial_statuses.append(denied.status)
        if any(status != 403 for status in denial_statuses):
            raise AssertionError(f"nonparticipant download was not denied: {denial_statuses}")

        return {
            "caseOrdinal": case["ordinal"],
            "accountFingerprint": _fingerprint(case["finance_user_id"]),
            "companyAlias": "company-1" if case["company_id"] == "CO-001" else "company-2",
            "financeRole": case["role"],
            "route": case["route"],
            "orientations": list(case["orientations"]),
            "pageCount": len(case["orientations"]),
            "workflowStepKeys": actual_keys,
            "reviewDownloadCount": review_downloads,
            "participantDownloadCount": len(participant_ids),
            "denialStatuses": denial_statuses,
            "uploadProtocol": upload_intent["protocol"],
            "sourceSha256": source_hash,
            "preparedSha256": preflight["preparedSha256"],
            "stampedSha256": stamped_file["file_hash"],
            "uploadProtocol": (
                "tus" if cls.upload_protocol == "local_supabase_tus" else "local_direct"
            ),
            "status": "passed",
        }

    @classmethod
    def _write_artifacts(cls, cases: list[dict[str, Any]]) -> None:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        passed = sum(1 for case in cases if case.get("status") == "passed")
        acceptance_passed = len(cases) == 5 and passed == len(cases)
        using_tus = cls.upload_protocol == "local_supabase_tus"
        report = {
            "schemaVersion": 2,
            "artifactKind": "five-account-full-http-acceptance",
            "passed": acceptance_passed,
            "caseCount": len(cases),
            "seed": ACCEPTANCE_SEED,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "isolation": {
                "accounts": "synthetic-example.test-only",
                "database": "temporary-sqlite",
                "storage": (
                    "isolated-local-supabase-private-storage"
                    if using_tus
                    else "temporary-local-directory"
                ),
                "supabase": "isolated-local-stack" if using_tus else "not-contacted",
                "sealFiles": "synthetic-not-real-seals",
                "formalExchange": "mock-disabled",
                "financeBridge": "deterministic-snapshot-double",
                "antivirus": "deterministic-eicar-fixture-double",
                "localDirectProductionGuard": (
                    "not-used"
                    if using_tus
                    else "test-only-bypass-for-isolated-storage"
                ),
            },
            "coverage": {
                "applicantAccounts": 5,
                "routes": ["A", "B", "C", "D"],
                "seniority": ["staff", "section_chief", "department_head"],
                "http": True,
                "signedPortalHandoff": True,
                "financeOrgUserProjection": True,
                "financeDirectoryApi": True,
                "a4PortraitLandscapeMultipage": True,
                "attachments": True,
                "editorPreflightApprovalStampReceiptDownload": True,
                "sameCompanyNonparticipantDenial": True,
                "crossCompanyDenial": True,
                "tus": using_tus,
                "signedTusCapability": using_tus,
                "stagingReplayCannotMutateFinalizedAsset": (
                    cls.tus_replay_isolations >= 5 if using_tus else False
                ),
                "finalizeReplayIdempotentWithoutNewRevision": (
                    cls.finalize_replay_idempotent_count == 5
                ),
                "failedIntentReplayRejected": (
                    cls.failed_intent_replay_rejections > 0 if using_tus else False
                ),
                "storageTokenCryptographicSingleUseClaimed": False,
                "privateStorageAnonymousReadDenied": (
                    cls.private_storage_denials >= 5 if using_tus else False
                ),
                "antivirusScans": cls.av_scan_count,
                "malwareFixtureRejected": cls.av_quarantine_count > 0 if using_tus else False,
            },
            "limitations": ([
                "The signed Storage token is path-scoped and expiring rather than cryptographically single-use; the suite replays different bytes and proves the finalized file remains isolated from the staging path.",
                "The application upload intent is finalized idempotently without creating a second revision; quarantined intent replay is rejected and requires a new intent.",
                "The production Finance endpoint, production AV transport, real Seal Vault files, and formal exchange provider are intentionally not contacted.",
                "This HTTP suite does not replace browser visual/device acceptance.",
            ] if using_tus else [
                "TUS requires an isolated Supabase Storage stack and is not exercised by the local_direct transport.",
                "The production Finance endpoint, production AV transport, real Seal Vault files, and formal exchange provider are intentionally not contacted.",
                "This HTTP suite does not replace browser visual/device acceptance.",
            ]),
            "summary": {"total": len(cases), "passed": passed, "failed": len(cases) - passed},
            "cases": cases,
        }
        report_json = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        for report_path in (
            ARTIFACT_DIR / "latest.json",
            ARTIFACT_DIR / f"seed-{ACCEPTANCE_SEED}.json",
        ):
            report_path.write_text(report_json, encoding="utf-8")

        suite = ET.Element(
            "testsuite",
            {
                "name": "five-account-http-acceptance",
                "tests": str(len(cases)),
                "failures": str(len(cases) - passed),
                "errors": "0",
                "skipped": "0",
            },
        )
        properties = ET.SubElement(suite, "properties")
        ET.SubElement(properties, "property", {"name": "seed", "value": str(ACCEPTANCE_SEED)})
        ET.SubElement(
            properties,
            "property",
            {"name": "uploadProtocol", "value": "tus" if using_tus else "local_direct"},
        )
        ET.SubElement(properties, "property", {"name": "financeOrgUserProjection", "value": "true"})
        ET.SubElement(properties, "property", {"name": "financeDirectoryApi", "value": "true"})
        ET.SubElement(properties, "property", {"name": "productionSystemsContacted", "value": "false"})
        for case in cases:
            testcase = ET.SubElement(
                suite,
                "testcase",
                {
                    "classname": "edoc.acceptance.five_account",
                    "name": f"case-{case['caseOrdinal']}-{case.get('financeRole', 'unknown')}-route-{case.get('route', 'unknown')}",
                },
            )
            if case.get("status") != "passed":
                failure = ET.SubElement(testcase, "failure", {"message": case.get("errorCode", "acceptance_failed")})
                failure.text = case.get("errorCode", "acceptance_failed")
        suite_tree = ET.ElementTree(suite)
        for junit_path in (
            ARTIFACT_DIR / "junit.xml",
            ARTIFACT_DIR / f"junit-seed-{ACCEPTANCE_SEED}.xml",
        ):
            suite_tree.write(junit_path, encoding="utf-8", xml_declaration=True)

    def test_00_local_supabase_tus_rejects_eicar_before_pdf_preflight(self) -> None:
        if self.upload_protocol != "local_supabase_tus":
            self.skipTest("isolated local Supabase TUS stack not requested")
        case = min(self.case_definitions, key=lambda item: item["ordinal"])
        applicant_token = self._portal_session(case["email"])
        draft = self._expect_json(
            "POST",
            "/api/official-documents/editor-drafts",
            201,
            token=applicant_token,
            json_body={
                "company_id": case["company_id"],
                "title": "隔離惡意檔案閘門驗收",
                "subject": "隔離惡意檔案閘門驗收",
                "request_reason": "EICAR 標準測試字串，不含真實資料",
                "document_category": case["category"],
                "dispatch_method": "no_dispatch_required",
            },
        )
        document_id = draft["document_id"]
        eicar_fixture = base64.b64decode(
            "WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo="
        )
        eicar_pdf = (
            b"%PDF-1.4\n% isolated antivirus fixture\n"
            + eicar_fixture
            + b"\n%%EOF\n"
        )
        digest = backend.sha256_bytes(eicar_pdf)
        intent = self._expect_json(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-uploads",
            201,
            token=applicant_token,
            json_body={
                "asset_kind": "source_pdf",
                "file_name": "isolated-eicar-fixture.pdf",
                "mime_type": "application/pdf",
                "size_bytes": len(eicar_pdf),
                "sha256": digest,
            },
        )
        self._perform_tus_upload(intent, eicar_pdf)
        finalized = self._request(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-uploads/"
            f"{urllib.parse.quote(intent['upload_id'])}/finalize",
            token=applicant_token,
            json_body={"sha256": digest},
        )
        finalized_payload = finalized.json()
        finalized_error = finalized_payload.get("error")
        finalized_detail = finalized_payload.get("detail")
        if not (
            finalized.status == 422
            and finalized_error == "request_rejected"
            and finalized_detail == "editor_asset_quarantined"
        ):
            raise AssertionError(
                f"local_supabase_eicar_not_rejected:{finalized.status}:"
                f"{_machine_error(RuntimeError(str(finalized_detail or finalized_error)))}"
            )
        with backend.connect() as conn:
            asset = conn.execute(
                "SELECT upload_status, scan_status, preflight_status "
                "FROM official_document_editor_assets WHERE id = ?",
                (intent["upload_id"],),
            ).fetchone()
        if not asset or tuple(asset) != ("quarantined", "failed", "blocked"):
            raise AssertionError("local_supabase_eicar_quarantine_state_invalid")
        replay = self._request(
            "POST",
            f"/api/official-documents/{urllib.parse.quote(document_id)}/editor-uploads/"
            f"{urllib.parse.quote(intent['upload_id'])}/finalize",
            token=applicant_token,
            json_body={"sha256": digest},
        )
        replay_payload = replay.json()
        replay_error = replay_payload.get("error")
        replay_detail = replay_payload.get("detail")
        if not (
            replay.status == 409
            and replay_error == "request_rejected"
            and replay_detail == "editor_upload_new_intent_required"
        ):
            raise AssertionError(
                f"local_supabase_failed_intent_replay_not_rejected:{replay.status}:"
                f"{_machine_error(RuntimeError(str(replay_detail or replay_error)))}"
            )
        with self.assertRaisesRegex(ValueError, "supabase_storage_download_failed"):
            backend.supabase_storage_download(intent["path"], intent["bucket"])
        self.av_quarantine_count += 1
        self.failed_intent_replay_rejections += 1

    def test_five_replayable_finance_accounts_complete_isolated_http_journeys(self) -> None:
        self.assertTrue(backend.exchange_gateway_status()["formalExchangeDisabled"])
        applicant_tokens = {
            case["ordinal"]: self._portal_session(case["email"])
            for case in self.case_definitions
        }
        cases: list[dict[str, Any]] = []
        for case in sorted(self.case_definitions, key=lambda item: item["ordinal"]):
            try:
                cases.append(self._run_case(case, applicant_tokens))
            except BaseException as error:  # preserve evidence for every attempted case
                cases.append(
                    {
                        "caseOrdinal": case["ordinal"],
                        "accountFingerprint": _fingerprint(case["finance_user_id"]),
                        "companyAlias": "company-1" if case["company_id"] == "CO-001" else "company-2",
                        "financeRole": case["role"],
                        "route": case["route"],
                        "orientations": list(case["orientations"]),
                        "status": "failed",
                        "errorCode": _machine_error(error),
                    }
                )
        self._write_artifacts(cases)
        failures = [case for case in cases if case["status"] != "passed"]
        self.assertEqual(failures, [], f"five-account acceptance failures: {failures}")
        self.assertEqual(sorted({case["route"] for case in cases}), ["A", "B", "C", "D"])
        self.assertEqual(
            {case["financeRole"] for case in cases},
            {"staff", "section_chief", "department_head"},
        )


class FourPerspectiveFiveAccountMatrixTest(unittest.TestCase):
    """Prove five distinct Finance accounts for each requested perspective.

    The full HTTP suite above replays five applicant documents.  That does not,
    by itself, prove five distinct supervisors, general-affairs reviewers, and
    CEOs.  This deterministic, deidentified matrix exercises the production
    Finance snapshot contract and server-owned workflow policy for five
    independent organization chains across every A-D route.  It performs no
    database, Storage, Finance, exchange-provider, or other network call.
    """

    PERSPECTIVE_BY_STEP = {
        "applicant_manager": "supervisor",
        "department_head": "supervisor",
        "ceo": "ceo",
        "general_affairs_review": "general_affairs",
        "applicant_confirm": "new_employee",
    }

    @staticmethod
    def _write_perspective_artifact(
        fixtures: list[dict[str, Any]],
        actions: dict[str, dict[str, int]],
        route_summaries: list[dict[str, Any]],
        expected_actions_per_account: dict[str, int],
    ) -> dict[str, Any]:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        perspectives = []
        for perspective in ("new_employee", "supervisor", "general_affairs", "ceo"):
            account_actions = actions[perspective]
            perspectives.append(
                {
                    "perspective": perspective,
                    "accountCount": len(account_actions),
                    "accountFingerprints": sorted(
                        _fingerprint(account_id) for account_id in account_actions
                    ),
                    "actionsPerAccount": sorted(set(account_actions.values())),
                    "expectedActionsPerAccount": expected_actions_per_account[perspective],
                    "totalActions": sum(account_actions.values()),
                }
            )

        passed = (
            len(fixtures) == 5
            and len(route_summaries) == 20
            and {summary["routeCode"] for summary in route_summaries}
            == {"A", "B", "C", "D"}
            and all(
                item["accountCount"] == 5
                and item["actionsPerAccount"] == [item["expectedActionsPerAccount"]]
                for item in perspectives
            )
        )
        report = {
            "schemaVersion": 1,
            "artifactKind": "four-perspective-five-account-workflow-matrix",
            "passed": passed,
            "seed": ACCEPTANCE_SEED,
            "selection": "deterministic-replayable-random-seed",
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "isolation": {
                "accounts": "synthetic-example.test-only",
                "financeBridge": "deterministic-snapshot-double",
                "productionSystemsContacted": False,
                "formalExchange": "mock-disabled",
            },
            "coverage": {
                "perspectives": [
                    "new_employee",
                    "supervisor",
                    "general_affairs",
                    "ceo",
                ],
                "accountsPerPerspective": 5,
                "uniqueRequiredAccounts": len(
                    {
                        account_id
                        for perspective_accounts in actions.values()
                        for account_id in perspective_accounts
                    }
                ),
                "routes": ["A", "B", "C", "D"],
                "routeChecks": len(route_summaries),
            },
            "perspectives": perspectives,
        }
        report_json = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if "@" in report_json:
            raise AssertionError("perspective acceptance artifact contains an email address")
        for report_path in (
            ARTIFACT_DIR / "latest-perspectives.json",
            ARTIFACT_DIR / f"perspective-seed-{ACCEPTANCE_SEED}.json",
        ):
            report_path.write_text(report_json, encoding="utf-8")
        return report

    @staticmethod
    def _finance_record(
        *,
        seed_token: str,
        role: str,
        tenant_id: str,
        entity_id: str,
        department_code: str,
        department_name: str,
        revision: int,
    ) -> dict[str, Any]:
        profile = backend.strict_finance_role_profile(role)
        fingerprint = _fingerprint(seed_token)
        email = f"perspective-{fingerprint}@example.test"
        return {
            "tenantId": tenant_id,
            "financeUserId": f"perspective-{fingerprint}",
            "authUserId": f"google-{_fingerprint(seed_token + ':auth')}",
            "name": f"隔離驗收角色{fingerprint[:6]}",
            "email": email,
            "role": role,
            "roleLabel": profile["title"],
            "entityId": entity_id,
            "departmentCode": department_code,
            "departmentName": department_name,
            "jobTitle": profile["title"],
            "extension": f"8{revision:03d}",
            "contactEmail": email,
            "orgStatus": "active",
            "sourceUpdatedAt": "2026-08-27T00:00:00Z",
            "memberRevision": revision,
            "active": True,
            "authUserBound": True,
            "googleLoginVerified": True,
        }

    @classmethod
    def _build_fixtures(cls) -> list[dict[str, Any]]:
        rng = random.Random(ACCEPTANCE_SEED)
        random_tokens = rng.sample(range(100_000, 1_000_000), 25)
        token_index = 0
        fixtures: list[dict[str, Any]] = []
        required_step_keys = {
            step["key"]
            for route in ("A", "B", "C", "D")
            for step in backend.official_workflow_steps_for_finance_applicant(route, "staff")
        }
        for ordinal in range(1, 6):
            tenant_id = f"tenant-perspective-{ordinal}"
            entity_id = f"TEST-ENTITY-{ordinal}"
            department_code = f"TEST-DEPT-{ordinal}"
            department_name = f"隔離驗收部門{ordinal}"

            records: dict[str, dict[str, Any]] = {}
            for perspective, role in (
                ("new_employee", "staff"),
                ("supervisor", "department_head"),
                ("general_affairs", "ga_chief"),
                ("ceo", "ceo"),
                ("admin_director", "admin_director"),
            ):
                random_token = random_tokens[token_index]
                token_index += 1
                records[perspective] = cls._finance_record(
                    seed_token=(
                        f"{ACCEPTANCE_SEED}:{random_token}:{ordinal}:"
                        f"{perspective}:{role}"
                    ),
                    role=role,
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    department_code=department_code,
                    department_name=department_name,
                    revision=ordinal * 10 + token_index,
                )

            snapshot = {
                "ok": True,
                "source": "finance",
                "schemaVersion": 2,
                "snapshotAt": "2026-08-27T00:00:00Z",
                "identity": records["new_employee"],
                "company": {
                    "tenantId": tenant_id,
                    "entityId": entity_id,
                    "name": f"隔離驗收公司{ordinal}",
                    "taxId": f"TEST-{ordinal:04d}",
                    "address": f"隔離測試地址{ordinal}",
                    "active": True,
                },
                # One Finance department head may validly fill both consecutive
                # supervisor slots; the real workflow still records two decisions.
                "actors": {
                    "applicantManager": records["supervisor"],
                    "departmentHead": records["supervisor"],
                    "ceo": records["ceo"],
                    "adminDirector": records["admin_director"],
                    "generalAffairs": records["general_affairs"],
                },
                "workflowReady": True,
                "issues": [],
            }
            normalized = backend.normalize_finance_bridge_snapshot(
                snapshot,
                require_workflow=True,
                required_step_keys=required_step_keys,
            )
            applicant_projection = normalized["applicant"]
            actor_projections = normalized["actors"]

            def projected_user(item: dict[str, Any], company_id: str) -> dict[str, Any]:
                return {
                    "id": item["finance_user_id"],
                    "finance_employee_id": item["finance_user_id"],
                    "email": item["email"],
                    "account_source": "finance",
                    "logging_role_key": item["profile"]["logging_role_key"],
                    "company_id": company_id,
                    "unit": item.get("department_name") or department_name,
                }

            company_id = f"TEST-CO-{ordinal}"
            supervisor = projected_user(actor_projections["applicantManager"], company_id)
            applicant = projected_user(applicant_projection, company_id)
            applicant.update(
                {
                    "manager_employee_id": supervisor["finance_employee_id"],
                    "manager_email": supervisor["email"],
                    "approval_manager_employee_id": supervisor["finance_employee_id"],
                    "approval_manager_email": supervisor["email"],
                }
            )
            fixtures.append(
                {
                    "company": {"id": company_id, "name": f"隔離驗收公司{ordinal}"},
                    "applicant": applicant,
                    "actors": {
                        "applicant_manager": supervisor,
                        "department_head": supervisor,
                        "ceo": projected_user(actor_projections["ceo"], company_id),
                        "admin_director": projected_user(
                            actor_projections["adminDirector"], company_id
                        ),
                        "general_affairs_review": projected_user(
                            actor_projections["generalAffairs"], company_id
                        ),
                    },
                    "fixtureEmails": [record["email"] for record in records.values()],
                }
            )
        return fixtures

    def test_five_accounts_per_perspective_cover_every_approval_route(self) -> None:
        fixtures = self._build_fixtures()
        # The seed must select a stable, replayable set instead of live accounts.
        self.assertEqual(fixtures, self._build_fixtures())
        self.assertEqual(len(fixtures), 5)

        fixture_by_applicant_id = {
            fixture["applicant"]["id"]: fixture for fixture in fixtures
        }
        companies = [fixture["company"] for fixture in fixtures]
        applicants_by_company = {
            fixture["company"]["id"]: [fixture["applicant"]]
            for fixture in fixtures
        }

        def resolve_step(
            step: dict[str, Any],
            applicant: dict[str, Any],
            _company: dict[str, Any],
        ) -> dict[str, Any] | None:
            if step["key"] == "applicant_confirm":
                return applicant
            return fixture_by_applicant_id[applicant["id"]]["actors"].get(step["key"])

        readiness = backend.build_internal_launch_workflow_readiness(
            companies,
            applicants_by_company,
            resolve_step,
        )
        self.assertTrue(readiness["ready"], readiness["blockers"])
        # The launch summary intentionally collapses routes with identical
        # approval shapes (A/B and C/D). The explicit loop below still checks
        # all four business route codes independently.
        self.assertEqual(readiness["routeCodes"], ["A", "C"])
        self.assertEqual(len(readiness["routeChecks"]), 10)
        self.assertTrue(all(check["ready"] for check in readiness["routeChecks"]))

        actions: dict[str, dict[str, int]] = {
            perspective: {}
            for perspective in ("new_employee", "supervisor", "general_affairs", "ceo")
        }
        route_summaries: list[dict[str, Any]] = []
        for fixture in fixtures:
            applicant = fixture["applicant"]
            for route in ("A", "B", "C", "D"):
                steps = backend.official_workflow_steps_for_finance_applicant(
                    route, applicant["logging_role_key"]
                )
                step_keys = [step["key"] for step in steps]
                self.assertEqual("ceo" in step_keys, route in {"C", "D"})
                route_summary = backend.workflow_readiness_summary(
                    applicant,
                    route,
                    [
                        (step, resolve_step(step, applicant, fixture["company"]))
                        for step in steps
                    ],
                    company_ready=True,
                )
                self.assertTrue(route_summary["ready"], route_summary["blockers"])
                route_summaries.append(route_summary)
                for step_key in step_keys:
                    perspective = self.PERSPECTIVE_BY_STEP.get(step_key)
                    if not perspective:
                        continue
                    actor = (
                        applicant
                        if step_key == "applicant_confirm"
                        else fixture["actors"][step_key]
                    )
                    actions[perspective][actor["id"]] = (
                        actions[perspective].get(actor["id"], 0) + 1
                    )

        self.assertEqual(len(route_summaries), 20)
        self.assertEqual(
            {summary["routeCode"] for summary in route_summaries},
            {"A", "B", "C", "D"},
        )

        expected_actions_per_account = {
            "new_employee": 4,
            "supervisor": 8,
            "general_affairs": 4,
            "ceo": 2,
        }
        for perspective, expected_count in expected_actions_per_account.items():
            with self.subTest(perspective=perspective):
                self.assertEqual(len(actions[perspective]), 5)
                self.assertEqual(set(actions[perspective].values()), {expected_count})

        required_account_ids = {
            account_id
            for perspective_accounts in actions.values()
            for account_id in perspective_accounts
        }
        self.assertEqual(len(required_account_ids), 20)
        fixture_emails = {
            email for fixture in fixtures for email in fixture["fixtureEmails"]
        }
        self.assertEqual(len(fixture_emails), 25)
        self.assertTrue(all(email.endswith("@example.test") for email in fixture_emails))

        evidence = self._write_perspective_artifact(
            fixtures,
            actions,
            route_summaries,
            expected_actions_per_account,
        )
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["coverage"]["accountsPerPerspective"], 5)
        self.assertEqual(evidence["coverage"]["uniqueRequiredAccounts"], 20)


if __name__ == "__main__":
    unittest.main()
