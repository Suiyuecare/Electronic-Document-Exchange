"""Deidentified, isolated ACL/paging, full scan, clock and receipt regressions."""
import copy
import json
import unittest
import urllib.parse
from datetime import datetime, timezone
from unittest import mock

import backend
from workflow_readiness import inbound_list_options, inbound_page, timeliness_report, TAIPEI
from tests import test_notification_overdue_reminders as reminder_fixture


class CompleteWorkflowReadinessTests(reminder_fixture.OverdueReminderTests):
    def supabase_fixture(self):
        super().supabase_fixture()
        self.start(mock.patch.object(backend, "supabase_scan_rows", side_effect=lambda table: iter(copy.deepcopy(sorted(self.store.get(table, {}).values(), key=lambda row: row['id'])))))

    def session(self, manager=False):
        return {"user": self.user, "permissions": ["official_documents.receive", "reports.operational_view"] if manager else []}

    def test_local_acl_status_and_search_precede_1201_row_cursor_paging(self):
        for index in range(1201):
            self.inbound(f"INB-{index:04}", assignee_user_id=self.other['id'], status="registered", created_at="2026-10-07 10:00:00")
        self.inbound("OLD-PENDING", subject="Synthetic searchable", created_at="2026-01-01 10:00:00")
        self.inbound("FOREIGN-TENANT", finance_tenant_id="OTHER-TENANT")
        page = backend.list_inbound_documents(self.conn, {"paginated": ['1']}, self.session())
        self.assertEqual(["OLD-PENDING"], [row['id'] for row in page['items']])
        self.assertEqual(1, page['count'])
        self.assertFalse(page['hasMore'])
        self.assertEqual(1, backend.list_inbound_documents(self.conn, {"paginated": ['1'], 'q': ['searchable']}, self.session(True))['count'])
        self.assertEqual(1, backend.list_inbound_documents(self.conn, {'paginated': ['1'], 'status': ['assigned']}, self.session(True))['count'])
        ids, cursor = [], None
        while True:
            query = {'paginated': ['1'], 'page_size': ['100']}
            if cursor:
                query['cursor'] = [cursor]
            page = backend.list_inbound_documents(self.conn, query, self.session(True))
            self.assertEqual(1202, page['count'])
            ids.extend(row['id'] for row in page['items'])
            cursor = page['nextCursor']
            if not cursor:
                break
        self.assertEqual(1202, len(set(ids)))
        self.assertNotIn('FOREIGN-TENANT', ids)
        self.assertEqual('OLD-PENDING', ids[-1])
        self.assertEqual(1202, len(backend.list_inbound_documents(self.conn, {}, self.session(True))))

    def test_cursor_bound_to_actor_company_permissions_and_filters(self):
        scope = {'actor_id': 'A', 'company': 'C', 'tenant': 'T', 'company_wide': False}
        options = inbound_list_options({'paginated': ['1'], 'page_size': ['1']}, scope)
        page = inbound_page([{'id': 'B', 'created_at': '2026-10-01'}, {'id': 'A', 'created_at': '2026-09-01'}], 2, options)
        token = page['nextCursor']
        self.assertEqual(('2026-10-01', 'B'), inbound_list_options({'paginated': ['1'], 'cursor': [token]}, scope)['after'])
        for changes in ({'actor_id': 'B'}, {'company': 'OTHER'}, {'company_wide': True}):
            with self.assertRaisesRegex(ValueError, 'cursor_invalid'):
                inbound_list_options({'paginated': ['1'], 'cursor': [token]}, {**scope, **changes})
        with self.assertRaisesRegex(ValueError, 'cursor_invalid'):
            inbound_list_options({'paginated': ['1'], 'cursor': [token], 'status': ['closed']}, scope)

    def test_remote_keyset_scanner_reads_1201_and_detects_repeated_batch(self):
        source = [{'id': f'TEST-{n:04}'} for n in range(1201)]
        calls = []
        def request(method, path, *args):
            calls.append(path)
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            after = query.get('id', [''])[0].removeprefix('gt.').strip('"')
            return [row for row in source if row['id'] > after][:int(query['limit'][0])]
        with mock.patch.object(backend, 'supabase_request', side_effect=request):
            result = list(backend.supabase_scan_rows('inbound_documents'))
        self.assertEqual(source, result)
        self.assertEqual(3, len(calls))
        with mock.patch.object(backend, 'supabase_request', return_value=source[:500]):
            with self.assertRaisesRegex(RuntimeError, 'response_invalid'):
                list(backend.supabase_scan_rows('inbound_documents'))

    def test_remote_overdue_1201_partial_retry_dedupes_and_preserves_exact_identity(self):
        for index in range(1201):
            self.inbound(f'INB-{index:04}')
        # Same display names do not authorize substitutes, and departures fail closed.
        self.store['users'][self.other['id']]['name'] = self.user['name']
        self.inbound('INB-INACTIVE', assignee_user_id=self.other['id'])
        self.store['users'][self.other['id']]['status'] = '停用'
        self.supabase_fixture()
        def partial(table):
            if table == 'documents':
                return
            for row in sorted(self.store[table].values(), key=lambda r: r['id'])[:500]:
                yield copy.deepcopy(row)
            raise RuntimeError('synthetic_page_failure')
        with mock.patch.object(backend, 'supabase_scan_rows', side_effect=partial):
            first = self.run_job(True)
        self.assertEqual('待處理', first['status'])
        self.assertFalse(first['payload']['dataComplete'])
        self.assertEqual(500, len(self.store['system_inbox']))
        second = self.run_job(True)
        self.assertTrue(second['payload']['dataComplete'])
        self.assertEqual(1201, second['payload']['reminded'])
        self.assertEqual(500, second['payload']['deduplicated'])
        self.assertEqual(1201, len(self.store['system_inbox']))
        self.assertEqual({self.user['id']}, {r['target_user_id'] for r in self.store['system_inbox'].values()})
        self.assertEqual('notification_target_inactive', second['payload']['errors'][0]['code'])

    def test_fixed_clock_metrics_unknown_is_not_zero_and_date_deadline_includes_day(self):
        clock = datetime(2026, 10, 11, 23, 0, tzinfo=TAIPEI)
        rows = [
            {'source': 'inbound', 'id': 'A', 'entered_at': '2026-10-01T12:00:00+08:00', 'due_at': '2026-10-11'},
            {'source': 'reply', 'id': 'B', 'entered_at': '', 'due_at': ''},
            {'source': 'approval', 'id': 'C', 'entered_at': '2026-10-12T12:00:00+08:00', 'due_at': '2026-10-10'},
        ]
        report = timeliness_report(rows, generated_at=clock, scope={}, system_timezone=timezone.utc)
        self.assertEqual({'pending': 3, 'overdue': 1, 'unknownDue': 1, 'unknownAge': 2}, report['totals'])
        self.assertEqual(1, next(b['count'] for b in report['deadlineBuckets'] if b['key'] == 'today'))
        self.assertEqual(2, next(b['count'] for b in report['waitingBuckets'] if b['key'] == 'unknown'))

    def test_local_timeliness_is_scoped_aggregated_and_permission_guarded(self):
        for n in range(1201):
            self.inbound(f'INB-{n:04}', created_at='2026-10-01 10:00:00')
        self.inbound('FOREIGN', company_id='OTHER')
        result = backend.official_timeliness_report(self.session(True), conn=self.conn, generated_at=datetime(2026,10,11,12,tzinfo=TAIPEI))
        self.assertEqual(1201, result['totals']['pending'])
        self.assertTrue(result['dataComplete'])
        self.assertNotIn('INB-', json.dumps(result))
        with self.assertRaises(PermissionError):
            backend.official_timeliness_report(self.session(), conn=self.conn)

    def test_legacy_next_day_check_never_fabricates_receipt_and_preserves_failure(self):
        self.legacy()
        for index, status in enumerate(('已送出', '已确认收文', '交換失敗', '退回補正', '逾時', '已送達')):
            self.conn.execute("INSERT INTO exchange_tasks(id,document_id,direction,target_agency,status,updated_at) VALUES (?,?, '發文','Synthetic',?,?)", (f'TASK-{index}', 'LEGACY-TEST', status, '2026-10-01'))
        result = backend.execute_job_logic(self.conn, {'job_type': 'nextDayCheck'})
        self.assertEqual('待處理', result['status'])
        self.assertEqual(0, result['payload']['confirmed'])
        states = [r[0] for r in self.conn.execute('SELECT status FROM exchange_tasks ORDER BY id')]
        self.assertEqual(['待查核', '待查核', '交換失敗', '退回補正', '待查核', '待查核'], states)
        self.assertEqual(6, self.conn.execute('SELECT count(*) FROM exchange_events').fetchone()[0])
        self.assertEqual(0, result['payload']['externalAttempted'])

    def test_privacy_safe_performance_is_persisted_and_unknown_fields_rejected(self):
        event = {'eventType': 'performance', 'sessionId': 'TEST_SESSION_12345', 'deviceClass': 'mobile', 'route': 'electronicSeal',
                 'performance': {'stage': 'pdf_cloud_saved', 'durationMs': 1844, 'outcome': 'success', 'fileSizeBucket': '1_10mb', 'pageCountBucket': '2_25', 'cacheState': 'cold'}}
        result = backend.record_ui_usage(self.conn, event, self.session())
        self.assertEqual('performance', result['accepted'])
        stored = json.loads(self.conn.execute("SELECT metadata_json FROM audit_logs WHERE action='UI usage event'").fetchone()[0])
        self.assertEqual(event['performance'], stored['performance'])
        for invalid in ({**event, 'filename': 'secret.pdf'}, {**event, 'performance': {**event['performance'], 'url': 'secret'}},
                        {**event, 'performance': {**event['performance'], 'durationMs': True}},
                        {**event, 'performance': {**event['performance'], 'durationMs': 120001}}):
            with self.assertRaises(ValueError):
                backend.normalize_ui_usage_payload(invalid, self.session())

    def test_remote_timeliness_partial_failure_never_claims_complete_or_invents_missing_age(self):
        rows = [{'source': 'inbound', 'id': f'INB-{n:04}', 'entered_at': '', 'due_at': ''} for n in range(501)]
        with mock.patch.object(backend, 'supabase_official_session_user', return_value=self.user), mock.patch.object(backend, 'supabase_request', side_effect=[{'items': rows}, RuntimeError('synthetic_second_page_failure')]):
            report = backend.official_timeliness_report(self.session(True), generated_at=datetime(2026,10,11,12,tzinfo=TAIPEI))
        self.assertFalse(report['dataComplete'])
        self.assertEqual(['timeliness_scan_incomplete'], report['errors'])
        self.assertEqual({'pending': 500, 'overdue': 0, 'unknownDue': 500, 'unknownAge': 500}, report['totals'])

    def test_remote_legacy_status_and_mock_or_unverified_real_outbox_cannot_be_receipt(self):
        tasks = [
            {'id': 'TASK-MOCK', 'document_id': 'DOC', 'package_id': 'PKG', 'direction': '發文', 'status': '已送達'},
            {'id': 'TASK-REAL', 'document_id': 'DOC', 'package_id': 'PKG', 'direction': '發文', 'status': '已確認收文'},
            {'id': 'TASK-FAILED', 'document_id': 'DOC', 'package_id': 'PKG', 'direction': '發文', 'status': '交換失敗'},
        ]
        outboxes = {'MOCK': {'document_id': 'DOC', 'package_id': 'PKG', 'provider': 'mock', 'environment': 'sandbox', 'status': '已送達'},
                    'REAL': {'document_id': 'DOC', 'package_id': 'PKG', 'provider': 'real', 'environment': 'production', 'status': '已送達'}}
        patches, events = {}, []
        with mock.patch.object(backend, 'supabase_scan_rows', return_value=iter(tasks)), mock.patch.object(backend, 'supabase_get', side_effect=lambda table, identity: outboxes.get(identity)), mock.patch.object(backend, 'supabase_patch', side_effect=lambda table, identity, payload: patches.update({identity: payload})), mock.patch.object(backend, 'supabase_insert', side_effect=lambda table, payload: events.append(payload)):
            result = backend.supabase_execute_job_logic({'job_type': 'nextDayCheck'})
        self.assertEqual(0, result['payload']['confirmed'])
        self.assertEqual('待查核', patches['TASK-MOCK']['status'])
        self.assertEqual('待查核', patches['TASK-REAL']['status'])
        self.assertEqual('交換失敗', patches['TASK-FAILED']['status'])
        self.assertEqual({'exchange_sandbox_receipt_not_formal', 'exchange_formal_receipt_verifier_unavailable', 'exchange_formal_receipt_unverified'}, {json.loads(event['payload_json'])['code'] for event in events})
        self.assertTrue(all(not json.loads(event['payload_json'])['receiptConfirmed'] for event in events))


if __name__ == '__main__':
    unittest.main()
