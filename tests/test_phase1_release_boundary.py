"""The approved first-stage release excludes unaccepted handover capabilities.

Phase two must deliberately replace this boundary only after human acceptance;
an accidental merge of its UI, routes or migration must fail first-stage CI.
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PhaseOneReleaseBoundaryTest(unittest.TestCase):
    def test_handover_frontend_and_backend_are_not_shipped(self):
        for name in ('official-handover-ui.js', 'official_handover.py',
                     'official_handover_store.py', 'official_handover_service.py',
                     'official_handover_followup.py'):
            self.assertFalse((ROOT / name).exists(), name)
        for name in ('index.html', 'app.js', 'backend.py', 'official_listing.py', 'vercel.json'):
            source = (ROOT / name).read_text()
            self.assertNotIn('officialHandover', source, name)
            self.assertNotIn('official_handover', source, name)
            self.assertNotIn('can_create_linked_application', source, name)

    def test_production_schema_inventory_does_not_require_handover(self):
        manifest = json.dumps(json.loads((ROOT / 'supabase/verification/migration_manifest.json').read_text()))
        self.assertNotIn('offboarding_handover', manifest)
        self.assertFalse((ROOT / 'supabase/migrations/20261007004716_offboarding_handover.sql').exists())
        self.assertFalse((ROOT / 'supabase/shared-project-migrations/20261007005211_shared_offboarding_handover.sql').exists())

    def test_shared_action_target_does_not_replace_finance_navigation(self):
        css = (ROOT / 'styles.css').read_text()
        self.assertIn('--action-hit-size: 44px', css)
        self.assertIn('#appShell button:not(.nav-item)', css)
        self.assertIn('min-width: var(--action-hit-size)', css)
        self.assertIn('min-height: var(--action-hit-size)', css)


if __name__ == '__main__':
    unittest.main()
