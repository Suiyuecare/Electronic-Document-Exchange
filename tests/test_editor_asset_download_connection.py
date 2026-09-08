"""The HTTP route owns session resolution; asset authorization remains enforced."""
from __future__ import annotations

import io
import unittest
from unittest import mock

import backend


class EditorAssetDownloadConnectionTest(unittest.TestCase):
    @staticmethod
    def handler():
        handler = mock.Mock()
        handler.path = "/api/official-documents/TEST-OD/editor-assets/TEST-A/download?expires=123&token=isolated-test"
        handler.wfile = io.BytesIO()
        return handler

    def test_sqlite_download_uses_route_connection_without_session_resync(self):
        handler, conn = self.handler(), mock.Mock()
        session = {"user": {"id": "TEST-USER"}}
        asset = {"mime_type": "application/pdf", "file_name": "isolated.pdf"}
        with mock.patch.object(backend, "connect") as connect, mock.patch.object(backend, "current_session") as current_session, mock.patch.object(backend, "local_editor_asset_download", return_value=(asset, b"%PDF-isolated")) as download:
            backend.Handler.send_editor_asset(handler, "TEST-OD", "TEST-A", session=session, conn=conn)
            connect.assert_not_called()
            current_session.assert_not_called()
            download.assert_called_once_with(conn, "TEST-OD", "TEST-A", 123, "isolated-test", session)
            conn.commit.assert_called_once()
            self.assertEqual(handler.wfile.getvalue(), b"%PDF-isolated")

    def test_supabase_download_reuses_validated_session(self):
        handler = self.handler()
        session = {"user": {"id": "TEST-USER"}}
        signed = {"url": "isolated-private-url"}
        with mock.patch.object(backend, "supabase_current_session") as current_session, mock.patch.object(backend, "supabase_editor_asset_download", return_value=({}, signed)) as download:
            backend.Handler.send_editor_asset(handler, "TEST-OD", "TEST-A", session=session, supabase_mode=True)
            current_session.assert_not_called()
            download.assert_called_once_with("TEST-OD", "TEST-A", 123, "isolated-test", session)
            handler.send_supabase_storage_redirect.assert_called_once_with(signed)

    def test_asset_authorization_failure_never_sends_bytes_or_redirect(self):
        for supabase_mode in (False, True):
            with self.subTest(supabase_mode=supabase_mode):
                handler, conn = self.handler(), mock.Mock()
                name = "supabase_editor_asset_download" if supabase_mode else "local_editor_asset_download"
                with mock.patch.object(backend, name, side_effect=PermissionError("official_editor_company_forbidden")) as download:
                    with self.assertRaisesRegex(PermissionError, "official_editor_company_forbidden"):
                        backend.Handler.send_editor_asset(handler, "TEST-OD", "TEST-A", session=None, conn=conn, supabase_mode=supabase_mode)
                    self.assertIsNone(download.call_args.args[-1])
                    conn.commit.assert_not_called()
                    handler.send_response.assert_not_called()
                    handler.send_supabase_storage_redirect.assert_not_called()
                    self.assertEqual(handler.wfile.getvalue(), b"")

    def test_seal_preview_preserves_binding_and_uses_route_session(self):
        for supabase_mode in (False, True):
            with self.subTest(supabase_mode=supabase_mode):
                handler, conn = self.handler(), mock.Mock()
                handler.path = "/api/company-seals/TEST-SEAL/editor-preview?fileId=TEST-FILE&fileSha256=test-hash&documentId=TEST-OD&revisionId=TEST-REV"
                session = {"user": {"id": "TEST-USER"}}
                name = "supabase_editor_seal_preview" if supabase_mode else "local_editor_seal_preview"
                with mock.patch.object(backend, "connect") as connect, mock.patch.object(backend, "current_session") as local_session, mock.patch.object(backend, "supabase_current_session") as supabase_session, mock.patch.object(backend, name, return_value=b"isolated-preview") as preview:
                    backend.Handler.send_editor_seal_preview(handler, "TEST-SEAL", session=session, conn=conn, supabase_mode=supabase_mode)
                    connect.assert_not_called()
                    local_session.assert_not_called()
                    supabase_session.assert_not_called()
                    expected_args = ("TEST-SEAL", session) if supabase_mode else (conn, "TEST-SEAL", session)
                    self.assertEqual(preview.call_args.args, expected_args)
                    self.assertEqual(preview.call_args.kwargs, {"file_id": "TEST-FILE", "file_sha256": "test-hash", "document_id": "TEST-OD", "revision_id": "TEST-REV", "binding_requested": True})
                    self.assertEqual(handler.wfile.getvalue(), b"isolated-preview")

    def test_seal_preview_authorization_failure_never_sends_image(self):
        for supabase_mode in (False, True):
            with self.subTest(supabase_mode=supabase_mode):
                handler, conn = self.handler(), mock.Mock()
                name = "supabase_editor_seal_preview" if supabase_mode else "local_editor_seal_preview"
                with mock.patch.object(backend, name, side_effect=PermissionError("editor_seal_preview_company_forbidden")):
                    with self.assertRaisesRegex(PermissionError, "editor_seal_preview_company_forbidden"):
                        backend.Handler.send_editor_seal_preview(handler, "TEST-SEAL", session=None, conn=conn, supabase_mode=supabase_mode)
                    conn.commit.assert_not_called()
                    handler.send_response.assert_not_called()
                    self.assertEqual(handler.wfile.getvalue(), b"")
