from __future__ import annotations

import unittest

import backend


class PortalFirstLoginBindingTestCase(unittest.TestCase):
    def finance_row(self, **overrides: object) -> dict:
        row = {
            "id": "FIN-USER-001",
            "email": "new-member@example.invalid",
            "auth_user_id": None,
            "account_source": "finance",
            "status": "啟用",
        }
        row.update(overrides)
        return row

    def test_unique_active_finance_member_can_bind_on_first_google_login(self) -> None:
        candidate, should_bind = backend.select_preprovisioned_finance_user(
            [self.finance_row()],
            "google-auth-user-001",
            "NEW-MEMBER@example.invalid",
        )

        self.assertEqual(candidate["id"], "FIN-USER-001")
        self.assertTrue(should_bind)

    def test_existing_exact_google_binding_is_reused_without_rebinding(self) -> None:
        candidate, should_bind = backend.select_preprovisioned_finance_user(
            [self.finance_row(auth_user_id="google-auth-user-001")],
            "google-auth-user-001",
            "new-member@example.invalid",
        )

        self.assertEqual(candidate["id"], "FIN-USER-001")
        self.assertFalse(should_bind)

    def test_different_existing_google_identity_is_rejected(self) -> None:
        with self.assertRaises(backend.PortalFinanceIdentityDenied):
            backend.select_preprovisioned_finance_user(
                [self.finance_row(auth_user_id="google-auth-user-other")],
                "google-auth-user-001",
                "new-member@example.invalid",
            )

    def test_duplicate_email_is_rejected(self) -> None:
        with self.assertRaises(backend.PortalFinanceIdentityDenied):
            backend.select_preprovisioned_finance_user(
                [
                    self.finance_row(),
                    self.finance_row(id="FIN-USER-002"),
                ],
                "google-auth-user-001",
                "new-member@example.invalid",
            )

    def test_disabled_or_non_finance_account_is_rejected(self) -> None:
        for row in (
            self.finance_row(status="停用"),
            self.finance_row(account_source="edoc"),
        ):
            with self.subTest(row=row):
                with self.assertRaises(backend.PortalFinanceIdentityDenied):
                    backend.select_preprovisioned_finance_user(
                        [row],
                        "google-auth-user-001",
                        "new-member@example.invalid",
                    )

    def test_google_identity_already_owned_by_another_member_is_rejected(self) -> None:
        with self.assertRaises(backend.PortalFinanceIdentityDenied):
            backend.select_preprovisioned_finance_user(
                [
                    self.finance_row(),
                    self.finance_row(
                        id="FIN-USER-002",
                        email="other-member@example.invalid",
                        auth_user_id="google-auth-user-001",
                    ),
                ],
                "google-auth-user-001",
                "new-member@example.invalid",
            )


if __name__ == "__main__":
    unittest.main()
