from __future__ import annotations

import unittest

from tools.compose_shared_forward import FORWARD_NAME, SOURCES, ROOT, render_shared_forward
from tools.shared_supabase_bootstrap import _postlude, sha256_text, transform_sql


class ComposeSharedForwardContractTest(unittest.TestCase):
    def test_forward_contains_exact_frozen_transforms_and_hash_ledger(self):
        shared = (ROOT / "supabase/shared-project-migrations" / FORWARD_NAME).read_text()
        self.assertEqual(shared, render_shared_forward())
        for name in SOURCES:
            source = (ROOT / "supabase/migrations" / name).read_text()
            transformed = transform_sql(source)
            self.assertIn(transformed, shared)
            self.assertIn(sha256_text(source), shared)
            self.assertIn(sha256_text(transformed), shared)
        self.assertNotIn("public.", shared)
        self.assertEqual(1, shared.lower().count("\nbegin;\n"))
        self.assertTrue(shared.endswith("commit;\n"))

    def test_shared_forward_carries_backend_rls_and_no_browser_grants(self):
        shared = render_shared_forward()
        for table in ("official_document_number_counters", "official_document_number_allocations"):
            self.assertIn(f"create policy edoc_backend_numbering on edoc.{table}", shared)
        self.assertIn("where rolname='edoc_backend' and not rolbypassrls", shared)
        self.assertIn("shared_compose_source_hash_mismatch", shared)
        self.assertIn("from public,anon,authenticated,service_role,authenticator", shared)
        self.assertIn("revoke all on function edoc_private.complete_electronic_compose(text,text) from edoc_backend", shared)

    def test_fresh_shared_bootstrap_restores_only_safe_predicate_after_revocation(self):
        postlude = _postlude(1)
        broad_revoke = postlude.index("revoke all privileges on all functions in schema edoc_private")
        predicate_grant = "grant execute on function edoc_private.is_electronic_compose(edoc.official_documents) to edoc_backend;"
        self.assertGreater(postlude.index(predicate_grant), broad_revoke)
        self.assertNotIn("grant execute on function edoc_private.complete_electronic_compose", postlude)


if __name__ == "__main__":
    unittest.main()
