"""Approved preparation permits dormant code, never unaccepted capabilities.

Human acceptance is still pending. Candidate database transformations remain
outside both formal migration paths, and missing server flags deny all access.
"""
import json
from pathlib import Path
import unittest
from unittest import mock
import types
import official_handover
import official_handover_followup
import official_handover_service
import official_handover_store

ROOT = Path(__file__).resolve().parents[1]


class PhaseOneReleaseBoundaryTest(unittest.TestCase):
    def test_missing_flag_disables_every_handover_adapter_before_database_access(self):
        api = types.SimpleNamespace()
        conn = mock.Mock()
        session = {"user": {"id": "FORGED", "role": "行政部門主任"}}
        self.assertFalse(official_handover.enabled(api))
        self.assertIsNone(official_handover_followup.load(api, {"id": "FORGED"}, conn=conn))
        with self.assertRaisesRegex(PermissionError, "handover_feature_disabled"):
            official_handover_service.Service(api, session, conn)
        with self.assertRaisesRegex(PermissionError, "handover_feature_disabled"):
            official_handover_followup.LinkedApplication(api, session, conn)
        for method, args in ((official_handover_store.propose, (conn, "CASE", {}, session)),
                             (official_handover_store.confirm, (conn, "REQUEST", session)),
                             (official_handover_store.reject, (conn, "REQUEST", "reason", session))):
            with self.assertRaisesRegex(PermissionError, "handover_feature_disabled"):
                method(*args, backend=api)
        conn.execute.assert_not_called()

    def test_production_schema_inventory_does_not_require_handover(self):
        manifest = json.dumps(json.loads((ROOT / 'supabase/verification/migration_manifest.json').read_text()))
        self.assertNotIn('offboarding_handover', manifest)
        self.assertFalse((ROOT / 'supabase/migrations/20261007004716_offboarding_handover.sql').exists())
        self.assertFalse((ROOT / 'supabase/shared-project-migrations/20261007005211_shared_offboarding_handover.sql').exists())
        inventory = json.loads((ROOT / 'supabase/candidate-migrations/inventory.json').read_text())
        self.assertIs(inventory['automatic_production_apply'], False)
        self.assertEqual('OFFBOARDING_HUMAN_ACCEPTANCE_PENDING', inventory['release_gate'])
        self.assertEqual(2, len(inventory['files']))
        for name in inventory['files']:
            self.assertTrue((ROOT / name).is_file())

    def test_shared_action_target_does_not_replace_finance_navigation(self):
        css = (ROOT / 'styles.css').read_text()
        self.assertIn('--action-hit-size: 44px', css)
        self.assertIn('#appShell button:not(.nav-item)', css)
        self.assertIn('min-width: var(--action-hit-size)', css)
        self.assertIn('min-height: var(--action-hit-size)', css)


if __name__ == '__main__':
    unittest.main()
