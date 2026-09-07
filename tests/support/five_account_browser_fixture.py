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
