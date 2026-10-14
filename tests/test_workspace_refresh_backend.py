"""Workspace refresh telemetry and request-local authentication regression."""
import json
from pathlib import Path
import unittest
from unittest import mock

import backend


class WorkspaceRefreshBackendTests(unittest.TestCase):
    def test_company_seal_catalog_resolves_session_once(self):
        handler = object.__new__(backend.Handler)
        handler.bearer_token = lambda: 'synthetic-only'
        handler.send_json = mock.Mock()
        handler.handle_handover_api = mock.Mock(return_value=False)
        session = {'user': {'id': 'SYNTHETIC', 'company_id': 'CO-SYNTHETIC'}, 'permissions': ['official_documents.compose']}
        with mock.patch.object(backend, 'USE_SUPABASE', True), \
                mock.patch.object(backend, 'supabase_current_session', return_value=session) as resolve, \
                mock.patch.object(backend, 'supabase_list_company_seals', return_value=[]) as catalog:
            handler.handle_api('GET', '/api/companies/CO-SYNTHETIC/seals', {'editor': ['1']})
        resolve.assert_called_once_with('synthetic-only')
        catalog.assert_called_once_with('CO-SYNTHETIC', session, editor=True)
        handler.send_json.assert_called_once_with([])

    def test_core_ready_stage_is_distinct_from_first_paint_and_privacy_safe(self):
        payload = {'eventType': 'performance', 'sessionId': 'SYNTHETIC_SESSION_123',
                   'deviceClass': 'desktop', 'route': 'electronicSeal',
                   'performance': {'stage': 'workspace_core_ready', 'durationMs': 1430,
                                   'outcome': 'success', 'fileSizeBucket': 'none',
                                   'pageCountBucket': 'none', 'cacheState': 'warm'}}
        session = {'user': {'id': 'SYNTHETIC', 'company_id': 'CO-SYNTHETIC'}}
        result = backend.normalize_ui_usage_payload(payload, session)
        self.assertEqual(result['performance'], payload['performance'])
        with self.assertRaises(ValueError):
            backend.normalize_ui_usage_payload({**payload, 'filename': 'private.pdf'}, session)

    def test_functions_colocated_with_edoc_database_region(self):
        config = json.loads((Path(__file__).resolve().parents[1] / 'vercel.json').read_text())
        self.assertEqual(['icn1'], config['regions'])


if __name__ == '__main__':
    unittest.main()
