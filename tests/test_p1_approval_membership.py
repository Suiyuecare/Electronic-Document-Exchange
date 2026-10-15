"""AP-01 authoritative membership; SQLite integration and local Supabase adapter.

No remote Supabase project or real employee is contacted.
"""
import copy
import unittest
from contextlib import contextmanager
from unittest import mock

import backend
import official_listing
from tests import test_configurable_official_workflow as fixture_module


class ApprovalMembershipUnitTest(unittest.TestCase):
    def membership(self, steps=(), logs=(), user=None, **changes):
        item = dict(current_status='pending_approval', current_step='review', applicant_id='APPLICANT',
                    approval_steps=list(steps), can_manage_dispatch=False, can_retry_stamp=False,
                    can_confirm=False, can_create_linked_application=False, can_act=False, **changes)
        return official_listing.approval_membership(backend, item, steps, logs, user or {})

    def test_assignee_and_download_log_are_not_actual_decision(self):
        steps = [{'step_key': 'review', 'approver_user_id': 'ACTOR', 'status': 'approved'}]
        self.assertFalse(self.membership(steps, [{'action': 'download', 'actor_id': 'ACTOR'}], {'id': 'ACTOR'})['approval_views']['acted'])

    def test_each_real_decision_action_and_actual_actor_column_count(self):
        for action in ('approve', 'reject', 'add_sign', 'return_previous', 'decline'):
            with self.subTest(action=action):
                self.assertTrue(self.membership(logs=[{'action': action, 'actor_id': 'ACTOR'}], user={'id': 'ACTOR'})['approval_views']['acted'])
        for status in ('approved', 'rejected'):
            self.assertTrue(self.membership([{'step_key': 'review', 'decision_actor_user_id': 'ACTOR', 'status': status}], user={'id': 'ACTOR'})['approval_views']['acted'])

    def test_no_actor_and_receipt_confirmation_do_not_count_as_approval(self):
        self.assertFalse(self.membership(logs=[{'action': 'approve', 'actor_id': None}])['approval_views']['acted'])
        self.assertFalse(self.membership([{'step_key': 'applicant_confirm', 'decision_actor_user_id': 'ACTOR', 'status': 'approved'}], user={'id': 'ACTOR'})['approval_views']['acted'])


class ApprovalMembershipIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ConfigurableOfficialWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.conn = self.fixture.conn

    @contextmanager
    def supabase_adapter(self):
        with self.fixture.fixture._supabase_adapter(), \
                mock.patch.object(backend, 'supabase_request', side_effect=AssertionError('remote_request_forbidden_in_isolated_test')), \
                mock.patch.object(backend, 'supabase_official_document_actor_snapshots', side_effect=lambda identity: backend.official_document_actor_snapshots(self.conn, identity)):
            yield

    def test_all_review_steps_keep_actual_actors_in_list_detail_and_supabase_adapter(self):
        detail = self.fixture.fixture._submitted()[0]
        reviewers = []
        while detail['current_status'] not in {'stamped', 'stamping_failed'}:
            step, session, payload = self.fixture._review(detail)
            had_acted = any(person['user']['id'] == session['user']['id'] for person in reviewers)
            self.assertEqual(backend.official_document_detail(self.conn, detail['id'], session)['approval_views']['acted'], had_acted)
            detail = backend.approve_official_document(self.conn, detail['id'], payload, session)
            self.assertTrue(detail['approval_views']['acted'])
            reviewers.append(session)
            for reviewer in reviewers:
                local = backend.official_document_detail(self.conn, detail['id'], reviewer)
                listed = backend.list_official_documents(self.conn, {'view': ['acted'], 'page_size': ['50']}, reviewer)
                listed = next(item for item in listed['items'] if item['id'] == detail['id'])
                self.assertEqual(local['approval_views'], listed['approval_views'])
                self.assertTrue(local['approval_views']['acted'])
                with self.supabase_adapter():
                    remote = backend.supabase_official_document_detail(detail['id'], reviewer)
                self.assertEqual(remote['approval_views'], local['approval_views'])
                self.assertEqual(remote['approval_task_filters'], local['approval_task_filters'])
        self.assertEqual(len(reviewers), 5)

    def test_detail_still_rejects_unrelated_cross_company_actor(self):
        detail = self.fixture.fixture._submitted()[0]
        outsider = self.fixture.fixture.fixture._session_for_user_id(self.fixture.target_id)
        outsider = copy.deepcopy(outsider)
        outsider['user']['company_id'] = 'CO-002'
        with self.assertRaises(PermissionError):
            backend.official_document_detail(self.conn, detail['id'], outsider)
        with self.supabase_adapter(), self.assertRaises(PermissionError):
            backend.supabase_official_document_detail(detail['id'], outsider)


if __name__ == '__main__':
    unittest.main()
