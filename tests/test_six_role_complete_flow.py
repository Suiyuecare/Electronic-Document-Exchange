"""Six authoritative synthetic applicants run the shipping local HTTP flow.

This is not real Google SSO, hosted Storage or a human acceptance attestation.
No production identity or document is used. Each role gets a distinct Finance
applicant and independent reviewers, preventing self-approval in the fixture.
"""
import copy
import unittest

from tests import test_five_account_http_acceptance as existing

ROLES = ("staff", "section_chief", "department_head", "ga_chief", "admin_director", "ceo")


def fixture_class():
    class SixRoleFixture(existing.FiveAccountHttpAcceptanceTest):
        @classmethod
        def _build_case_definitions(cls):
            base = super()._build_case_definitions()
            template = min(base, key=lambda case: case["ordinal"])
            rows = []
            for index, role in enumerate(ROLES, 1):
                row = copy.deepcopy(template)
                row.update(ordinal=index, alias="synthetic-role-" + str(index), role=role,
                           route="D", category="採購合約", company_id="CO-002" if role == "ceo" else "CO-001",
                           orientations=("portrait", "landscape"),
                           finance_user_id="six-role-applicant-" + role,
                           auth_user_id="six-role-auth-" + role,
                           email="six-role-" + role + "@example.test")
                rows.append(row)
            return rows
    return SixRoleFixture


class SixRoleCompleteHttpFlowTest(unittest.TestCase):
    last_report = None

    @classmethod
    def setUpClass(cls):
        cls.fixture = fixture_class()
        cls.fixture.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def test_six_roles_create_edit_review_stamp_confirm_download_and_history(self):
        f = self.fixture
        tokens = {case["ordinal"]: f._portal_session(case["email"]) for case in f.case_definitions}
        rows = []
        for case in f.case_definitions:
            with self.subTest(role=case["role"]):
                row = f._run_case(case, tokens)
                self.assertEqual("passed", row["status"])
                self.assertTrue(row["reviewDownloadCount"])
                self.assertTrue(all(status == 403 for status in row["denialStatuses"]))
                self.assertNotEqual(row["sourceSha256"], row["stampedSha256"])
                self.assertNotEqual(row["preparedSha256"], row["stampedSha256"])
                rows.append(row)
        type(self).last_report = {"scope": "isolated_local_http_synthetic_finance",
            "realHumanSsoVerified": False, "hostedStorageVerified": False,
            "formalGovernmentExchangeCalled": False, "productionAccountsChanged": False,
            "expectedRoles": list(ROLES), "rows": rows}
        self.assertEqual(set(ROLES), {row["financeRole"] for row in rows})
        self.assertEqual(6, len(rows))


if __name__ == "__main__":
    unittest.main()
