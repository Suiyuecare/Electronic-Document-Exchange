"""P0 audit: immutable submissions and terminal transitions, synthetic only.

Uses real SQLite domain functions and storage with no production identities.
Hosted transaction/RLS behavior is covered separately and is not implied here.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import sqlite3
import unittest
from unittest import mock

import backend
from tests import test_configurable_official_workflow as configurable


class DocumentImmutabilityP0Audit(unittest.TestCase):
    def setUp(self):
        self.workflow = configurable.ConfigurableOfficialWorkflowTest()
        self.workflow.setUp()
        self.addCleanup(self.workflow.doCleanups)
        self.fixture = self.workflow.fixture
        self.conn = self.workflow.conn
        self.session = self.workflow.session

    def snapshot(self):
        tables = [r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE 'official_document%' OR name='file_objects') ORDER BY name")]
        rows = {table: sorted((dict(row) for row in self.conn.execute(f'SELECT * FROM "{table}"')), key=lambda row: json.dumps(row, sort_keys=True)) for table in tables}
        files = {str(path.relative_to(backend.STORAGE_DIR)): hashlib.sha256(path.read_bytes()).hexdigest() for path in backend.STORAGE_DIR.rglob('*') if path.is_file()}
        return rows, files

    def attempted_mutations(self, detail, revision, source):
        identity = detail['id']
        source_asset = self.conn.execute("SELECT id FROM official_document_editor_assets WHERE document_id=? AND asset_kind='source_pdf'", (identity,)).fetchone()[0]
        meta = {'asset_kind': 'source_pdf', 'file_name': 'replacement.pdf', 'mime_type': 'application/pdf', 'size_bytes': len(source), 'sha256': backend.sha256_bytes(source)}
        changed = copy.deepcopy(revision['state'])
        changed['elements'] = []
        changed['pages'].reverse()
        return {
            'metadata_patch': lambda: backend.update_official_document_correction(self.conn, identity, {'title': 'Injected title', 'description': 'Injected body', 'expected_content_revision': detail['content_revision']}, self.session),
            'editor_state_replace': lambda: backend.save_official_editor_state(self.conn, identity, {'revisionNo': revision['revisionNo'], 'baseManifestSha256': revision['manifestSha256'], 'state': changed}, self.session),
            'new_upload_intent': lambda: backend.create_official_editor_upload_intent(self.conn, identity, meta, self.session),
            'existing_upload_content_replace': lambda: backend.store_official_editor_local_upload(self.conn, identity, source_asset, source, self.session, 'application/pdf'),
            'existing_upload_finalize': lambda: backend.finalize_official_editor_upload(self.conn, identity, source_asset, {}, self.session),
            'existing_upload_fail': lambda: backend.fail_official_editor_upload(self.conn, identity, source_asset, {'error_code': 'editor_upload_incomplete'}, self.session),
            'existing_upload_convert': lambda: backend.convert_official_editor_upload_a4(self.conn, identity, source_asset, {'confirm': True, 'sourceSha256': backend.sha256_bytes(source), 'baseRevisionNo': revision['revisionNo']}, self.session),
            'new_prepared_pdf': lambda: backend.preflight_official_editor(self.conn, identity, {}, self.session),
            'conflict_copy_from_locked_case': lambda: backend.copy_official_editor_conflict(self.conn, identity, {'requestId': 'P0-AUDIT-COPY-0001', 'state': changed}, self.session),
            'legacy_stamp_and_text_replace': lambda: backend.update_official_stamp_position(self.conn, identity, {'page': 1, 'x': 10, 'y': 10, 'text_overlays': [{'text': 'Injected text', 'page': 1, 'x': 10, 'y': 10}]}, self.session),
            'attachment_upload': lambda: backend.upload_official_document_attachment(self.conn, identity, {'file_name': 'injected.pdf', 'file_mime_type': 'application/pdf', 'content_base64': base64.b64encode(source).decode()}, self.session),
        }

    def assert_all_mutations_denied(self, detail, revision, source):
        original = self.snapshot()
        for name, operation in self.attempted_mutations(detail, revision, source).items():
            with self.subTest(operation=name):
                with self.assertRaisesRegex(ValueError, '(locked_after_submit|attachments_locked_after_submit|official_document_correction_locked)'):
                    operation()
                self.assertEqual(self.snapshot(), original, name + ' changed a row or file after denial')

    def test_submitted_document_rejects_all_editor_file_and_overlay_mutations(self):
        detail, prepared, revision, source = self.fixture._submitted()
        self.assert_all_mutations_denied(detail, revision, source)
        locked = backend.get_official_editor_state(self.conn, detail['id'], self.session)
        self.assertEqual(locked['state'], revision['state'])
        self.assertEqual(locked['preparedFileId'], prepared['preparedFileId'])

    def test_stamped_document_rejects_mutations_cancel_and_withdraw_and_keeps_final_hash(self):
        submitted, prepared, revision, source = self.fixture._submitted()
        detail = self.fixture.fixture._approve_and_stamp(submitted)
        final_id = detail['stamped_file_id']
        final_before = backend.official_document_download_file(self.conn, detail['id'], final_id, self.session)[2]
        self.assert_all_mutations_denied(detail, revision, source)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'cannot_cancel_after_stamp'):
            backend.cancel_official_document(self.conn, detail['id'], {}, self.session)
        with self.assertRaises(ValueError):
            backend.mutate_official_workflow(self.conn, detail['id'], 'withdraw', {'operation_id': 'P0-AUDIT-STAMPED-WITHDRAW', 'expected_step_id': detail['approval_steps'][-1]['id'], 'expected_content_revision': detail['content_revision'], 'comment': 'Synthetic cancellation attempt'}, self.session)
        self.assertEqual(self.snapshot(), before)
        final_after = backend.official_document_download_file(self.conn, detail['id'], final_id, self.session)[2]
        self.assertEqual(final_before, final_after)
        self.assertEqual(detail['stamp_request']['prepared_sha256'], prepared['preparedSha256'])

    def test_withdraw_wins_then_stale_last_approval_cannot_stamp(self):
        detail = self.fixture._submitted()[0]
        while detail['current_step'] != 'general_affairs_review':
            detail = self.workflow._approve(detail)
        step, reviewer, payload = self.workflow._review(detail)
        withdrawn = backend.mutate_official_workflow(self.conn, detail['id'], 'withdraw', {'operation_id': 'P0-AUDIT-WITHDRAW-WINS', 'expected_step_id': step['id'], 'expected_content_revision': detail['content_revision'], 'comment': 'Synthetic withdrawal'}, self.session)
        self.assertEqual(withdrawn['current_status'], 'draft')
        before = self.snapshot()
        with self.assertRaises((ValueError, PermissionError)):
            backend.approve_official_document(self.conn, detail['id'], payload, reviewer)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.conn.execute("SELECT 1 FROM official_document_files WHERE document_id=? AND file_type='stamped_pdf'", (detail['id'],)).fetchone())

    def test_last_approval_and_stamp_claim_win_then_withdraw_and_cancel_are_denied(self):
        detail = self.fixture._submitted()[0]
        while detail['current_step'] != 'general_affairs_review':
            detail = self.workflow._approve(detail)
        step, reviewer, payload = self.workflow._review(detail)
        # Pause only the renderer after the real last-decision transaction.
        with mock.patch.object(backend, 'auto_stamp_official_document', return_value={'ok': True, 'paused_for_test': True}):
            approved = backend.approve_official_document(self.conn, detail['id'], payload, reviewer)
        claim = backend.claim_official_document_stamp(self.conn, detail['id'], approved['stamp_request']['id'], 'p0-synthetic-claim-token-' + 'x' * 32, reviewer['user']['id'])
        self.assertTrue(claim['claimed'])
        before = self.snapshot()
        with self.assertRaises((ValueError, PermissionError)):
            backend.mutate_official_workflow(self.conn, detail['id'], 'withdraw', {'operation_id': 'P0-AUDIT-APPROVAL-WINS', 'expected_step_id': step['id'], 'expected_content_revision': detail['content_revision'], 'comment': 'Synthetic late withdrawal'}, self.session)
        with self.assertRaisesRegex(ValueError, 'cannot_cancel_after_stamp'):
            backend.cancel_official_document(self.conn, detail['id'], {}, self.session)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(backend.official_document_row(self.conn, detail['id'])['current_status'], 'stamping')

    def test_database_guards_preserve_submitted_revision_asset_log_and_case(self):
        detail, _, revision, _ = self.fixture._submitted()
        asset = self.conn.execute("SELECT id FROM official_document_editor_assets WHERE document_id=? AND asset_kind='source_pdf'", (detail['id'],)).fetchone()[0]
        log = self.conn.execute("SELECT id FROM official_document_approval_logs WHERE document_id=? LIMIT 1", (detail['id'],)).fetchone()[0]
        operations = [
            ('UPDATE official_document_editor_revisions SET editor_state_json=? WHERE id=?', ('{}', revision['id'])),
            ('DELETE FROM official_document_editor_revisions WHERE id=?', (revision['id'],)),
            ('UPDATE official_document_editor_assets SET sha256=? WHERE id=?', ('0' * 64, asset)),
            ('DELETE FROM official_document_editor_assets WHERE id=?', (asset,)),
            ('UPDATE official_document_approval_logs SET comment=? WHERE id=?', ('Rewrite history', log)),
            ('DELETE FROM official_document_approval_logs WHERE id=?', (log,)),
            ('DELETE FROM official_documents WHERE id=?', (detail['id'],)),
        ]
        before = self.snapshot()
        for sql, args in operations:
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(sql, args)
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
