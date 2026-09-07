import json
import threading
import unittest
from unittest import mock

import backend
from test_finance_bridge_v1_tenant_compatibility import production_v1_snapshot, projected_user, projected_company


class PortalHandoffParallelTimingTests(unittest.TestCase):
    def projection(self, *, revoke_final=False):
        barrier = threading.Barrier(2, timeout=2)
        lock = threading.Lock()
        counts = {"users": 0, "companies": 0}

        def request(method, path, *_args, **_kwargs):
            table = path.split("?")[0]
            self.assertEqual(method, "GET")
            self.assertIn(table, counts)
            with lock:
                counts[table] += 1
                occurrence = counts[table]
            # All three pairs must actually overlap. Serial code times out.
            barrier.wait()
            if table == "companies":
                return [projected_company()]
            user = projected_user()
            if revoke_final and occurrence == 3:
                user.update(status="停用", finance_source_status="inactive")
            return [user]

        with mock.patch.object(backend, "supabase_request", side_effect=request), mock.patch.object(backend, "launch_company_in_scope", return_value=True), mock.patch.object(backend, "is_production", return_value=False), mock.patch.object(backend, "_urlopen_no_redirect", side_effect=AssertionError("live_network_forbidden")):
            result = backend.sync_supabase_finance_login_snapshot(production_v1_snapshot(), portal_authenticated=True)
        return result, counts

    def test_all_three_read_pairs_overlap_and_all_six_checks_remain(self):
        result, counts = self.projection()
        self.assertEqual(counts, {"users": 3, "companies": 3})
        self.assertEqual(result["status"], "啟用")
        self.assertIn(backend.FINANCE_LOGIN_EXPECTED_BINDING_KEY, result)

    def test_revocation_during_parallel_final_read_still_denies_login(self):
        with mock.patch.object(backend, "supabase_create_finance_login_session") as session:
            with self.assertRaises((backend.FinanceBridgeDenied, backend.FinanceBridgeContractError)):
                self.projection(revoke_final=True)
        session.assert_not_called()

    def test_stage_failure_records_duration_only_and_preserves_exception(self):
        timings = {}
        context = backend._HANDOFF_STAGE_TIMINGS.set(timings)
        try:
            with mock.patch.object(backend.time, "monotonic", side_effect=[10, 10.123]):
                with self.assertRaisesRegex(RuntimeError, "private"):
                    backend.timed_finance_login_stage("finance", lambda: (_ for _ in ()).throw(RuntimeError("private person@example.invalid token")))
        finally:
            backend._HANDOFF_STAGE_TIMINGS.reset(context)
        self.assertEqual(timings, {"finance": 123.0})
        self.assertNotIn("private", json.dumps(timings))

    def test_redirect_server_timing_and_logs_are_allowlisted(self):
        handler = object.__new__(backend.Handler)
        handler._handoff_stage_timings = {"nonce": 1.0, "finance": 22.0, "projection": 33.0, "session": 4.0, "person@example.invalid": 99, "token": "secret"}
        handler._handoff_started = 100
        with mock.patch.object(backend.time, "monotonic", return_value=100.2), mock.patch.object(handler, "send_response"), mock.patch.object(handler, "send_header") as header, mock.patch.object(handler, "end_headers"), mock.patch.object(backend, "log_structured") as log:
            handler.send_handoff_redirect(token="a" * 48)
        timing = next(call.args[1] for call in header.call_args_list if call.args[0] == "Server-Timing")
        self.assertEqual(timing, "nonce;dur=1.0, finance;dur=22.0, projection;dur=33.0, session;dur=4.0, total;dur=200.0")
        safe = json.dumps(log.call_args.kwargs)
        for forbidden in ("person", "secret", "a" * 48):
            self.assertNotIn(forbidden, safe)

    def test_handoff_timing_context_is_reset_even_on_failure(self):
        handler = object.__new__(backend.Handler)
        before = backend._HANDOFF_STAGE_TIMINGS.get()
        with mock.patch.object(handler, "_handle_portal_handoff", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                handler.handle_portal_handoff()
        self.assertIs(backend._HANDOFF_STAGE_TIMINGS.get(), before)

    def test_live_finance_and_nonce_failure_cannot_be_replaced_by_timing(self):
        timings = {}
        context = backend._HANDOFF_STAGE_TIMINGS.set(timings)
        try:
            self.assertFalse(backend.timed_finance_login_stage("nonce", lambda: False))
            with self.assertRaises(backend.FinanceBridgeDenied):
                backend.timed_finance_login_stage("finance", lambda: (_ for _ in ()).throw(backend.FinanceBridgeDenied("finance_identity_denied")))
        finally:
            backend._HANDOFF_STAGE_TIMINGS.reset(context)
        self.assertEqual(set(timings), {"nonce", "finance"})
