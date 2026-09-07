"""Run the isolated Finance fixture long enough for a real-browser smoke test.

This helper prints one ephemeral JSON line containing the localhost origin and
synthetic auth state.  It never writes a bearer token to disk.  Type ``stop``
or close stdin to tear down the temporary database and storage directory.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_five_account_http_acceptance import ACCEPTANCE_SEED, FiveAccountHttpAcceptanceTest
import backend


BROWSER_ROLES = ("staff", "section_chief", "department_head", "admin_director", "ga_chief", "ceo")


def isolated_browser_session(fixture, role: str, *, entity_id: str = "") -> dict:
    """Seed a local test session, without manufacturing a Portal assertion.

    This is deliberately not an authentication acceptance test. Never expose
    this helper from a production HTTP route or point it at an existing DB.
    """
    if role not in BROWSER_ROLES:
        raise ValueError("browser_fixture_role_invalid")
    if fixture.origin != f"http://127.0.0.1:{fixture.port}" or not backend.DB_PATH.resolve().is_relative_to(Path(fixture.tmp.name).resolve()):
        raise ValueError("browser_fixture_must_be_isolated")
    identity = next(item for item in fixture.identity_by_email.values() if item["role"] == role and (not entity_id or fixture.snapshots_by_email[item["email"]]["identity"]["entityId"] == entity_id))
    with backend.connect() as conn:
        user, _ = backend.sync_sqlite_finance_snapshot(conn, fixture.snapshots_by_email[identity["email"]], auth_user_id=identity["auth_user_id"])
        row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        session = backend.create_session(conn, row, "Isolated browser fixture", "127.0.0.1", "six-role-browser-fixture")
        conn.commit()
    return session


def main() -> int:
    fixture = FiveAccountHttpAcceptanceTest
    fixture.setUpClass()
    try:
        case = min(fixture.case_definitions, key=lambda item: item["ordinal"])
        role = os.environ.get("EDOC_BROWSER_ROLE", "")
        identity = next((item for item in fixture.identity_by_email.values() if item["role"] == role), case)
        token = fixture._portal_session(identity["email"])
        current = fixture._expect_json("GET", "/api/auth/me", 200, token=token)
        auth_state = {**current, "token": token}
        print(
            json.dumps(
                {
                    "origin": fixture.origin,
                    "authState": auth_state,
                    "caseOrdinal": case["ordinal"],
                    "route": case["route"],
                    "financeRole": identity["role"],
                    "seed": ACCEPTANCE_SEED,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )
        for line in sys.stdin:
            if line.strip().lower() == "stop":
                break
        return 0
    finally:
        fixture.tearDownClass()


if __name__ == "__main__":
    raise SystemExit(main())
