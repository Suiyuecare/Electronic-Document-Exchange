"""Actual PostgreSQL public/shared RPC tests, disposable local databases only."""
import json
import re
import unittest
from tests import test_compose_output_postgres as fixture
from tools.workflow_readiness_shared_forward import SOURCE, FORWARD_NAME, render_shared_forward


@unittest.skipUnless(fixture.PORT, 'isolated PostgreSQL gate not enabled')
class WorkflowReadinessPostgresTest(unittest.TestCase):
    namespace = 'public'
    backend_role = 'service_role'
    cleanup = classmethod(fixture.ComposeOutputPostgresTest.cleanup.__func__)

    @classmethod
    def setUpClass(cls):
        fixture.ComposeOutputPostgresTest.setUpClass.__func__(cls)
        cls.pg.execute('SET ROLE postgres')
        try:
            if cls.namespace == 'public':
                cls.pg.execute((fixture.ROOT / 'supabase/migrations' / SOURCE).read_text())
            else:
                cls.pg.execute(render_shared_forward())
                cls.pg.execute(render_shared_forward())
        finally:
            cls.pg.execute('RESET ROLE')
        cls.pg.execute("UPDATE companies SET finance_tenant_id='TENANT-A',source_system='finance',status='active' WHERE id='CO-COMPOSE'")
        cls.pg.execute("INSERT INTO companies(id,name,finance_tenant_id,source_system,status) VALUES ('CO-OTHER','Synthetic foreign company','TENANT-B','finance','active')")
        cls.pg.execute("""INSERT INTO users(id,name,status,company_id,finance_tenant_id,account_source,role)
            VALUES ('ACTOR','Synthetic same name','啟用','CO-COMPOSE','TENANT-A','finance','員工'),
            ('OTHER','Synthetic same name','啟用','CO-COMPOSE','TENANT-A','finance','員工'),
            ('DEPARTED','Synthetic departed','停用','CO-COMPOSE','TENANT-A','finance','員工'),
            ('FOREIGN','Synthetic foreign','啟用','CO-OTHER','TENANT-B','finance','員工')""")
        cls.pg.execute("""INSERT INTO inbound_documents(id,company_id,finance_tenant_id,receive_no,sender_name,subject,status,assignee_user_id,created_by,created_at,updated_at,due_at)
            SELECT 'NEW-'||lpad(n::text,4,'0'),'CO-COMPOSE','TENANT-A','SYN-'||n::text,'Synthetic sender','Synthetic new case',
             'registered','OTHER','OTHER','2026-10-10T12:00:00Z','2026-10-10T12:00:00Z','2026-10-09'
            FROM generate_series(1,1201) n""")
        cls.pg.execute("""INSERT INTO inbound_documents(id,company_id,finance_tenant_id,receive_no,sender_name,subject,status,assignee_user_id,created_by,created_at,updated_at,due_at)
            VALUES ('OLD-TARGET','CO-COMPOSE','TENANT-A','SYN-OLD','Synthetic sender','Searchable old pending','assigned','ACTOR','OTHER','2026-01-01','2026-01-01','2026-10-09'),
             ('FOREIGN-COMPANY','CO-OTHER','TENANT-B','SYN-FOREIGN','Synthetic','Foreign case','assigned','ACTOR','FOREIGN','2026-10-11','2026-10-11','2026-10-09'),
             ('FOREIGN-TENANT','CO-COMPOSE','TENANT-B','SYN-TENANT','Synthetic','Foreign tenant','assigned','ACTOR','OTHER','2026-10-11','2026-10-11','2026-10-09')""")
        tables = ('users','inbound_documents','internal_dispatches','internal_dispatch_recipients','official_document_approval_steps')
        cls.pg.execute('GRANT SELECT ON ' + ','.join(f'{cls.namespace}.{table}' for table in tables) + f' TO {cls.backend_role}')

    def rpc(self, name='edoc_list_inbound_candidates', changes=None, role=None):
        request = {'actor_id': 'ACTOR', 'company_id': 'CO-COMPOSE', 'finance_tenant_id': 'TENANT-A', 'company_wide': False,
                   'limit': 100 if name == 'edoc_list_inbound_candidates' else 501, **(changes or {})}
        with self.pg.transaction():
            previous_role = self.pg.execute('SELECT current_user').fetchone()[0]
            self.pg.execute(f'SET LOCAL ROLE {role or self.backend_role}')
            result = self.pg.execute(f'SELECT {self.namespace}.{name}(%s::jsonb)', (json.dumps(request),)).fetchone()[0]
            self.pg.execute(f'SET LOCAL ROLE {previous_role}')
            return result

    def test_01_acl_status_and_search_precede_1201_newer_cases(self):
        result = self.rpc()
        self.assertEqual(1, result['count'])
        self.assertEqual(['OLD-TARGET'], [row['id'] for row in result['items']])
        self.assertEqual(1, self.rpc(changes={'company_wide': True, 'status': 'assigned'})['count'])
        self.assertEqual(1, self.rpc(changes={'company_wide': True, 'q': 'searchable'})['count'])
        self.assertEqual(0, self.rpc(changes={'status': 'registered'})['count'])

    def test_02_manager_keyset_reads_all_1202_without_foreign_or_duplicate(self):
        ids, after = [], {}
        while True:
            result = self.rpc(changes={'company_wide': True, **after})
            self.assertEqual(1202, result['count'])
            page = result['items']
            ids.extend(row['id'] for row in page)
            if len(page) < 100:
                break
            after = {'after_created_at': page[-1]['created_at'], 'after_id': page[-1]['id']}
        self.assertEqual(1202, len(ids))
        self.assertEqual(1202, len(set(ids)))
        self.assertEqual('OLD-TARGET', ids[-1])

    def test_03_inactive_or_scope_forgery_and_browser_roles_denied(self):
        for changes in ({'actor_id': 'DEPARTED'}, {'company_id': 'CO-OTHER'}, {'finance_tenant_id': 'TENANT-B'}):
            with self.assertRaisesRegex(self.psycopg.Error, 'scope_forbidden'):
                self.rpc(changes=changes)
        for name in ('edoc_list_inbound_candidates', 'edoc_timeliness_candidates'):
            for role in ('anon','authenticated'):
                with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                    self.rpc(name, role=role)
            self.assertFalse(self.pg.execute('SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure', (f'{self.namespace}.{name}(jsonb)',)).fetchone()[0])

    def test_04_report_full_scope_keyset_and_no_hidden_500_cap(self):
        ids, after = [], {}
        while True:
            result = self.rpc('edoc_timeliness_candidates', after)
            page = result['items'][:500]
            self.assertTrue(all(set(row) == {'source','id','entered_at','due_at'} for row in page))
            ids.extend((row['source'],row['id']) for row in page)
            if len(result['items']) <= 500:
                break
            after = {'after_source': page[-1]['source'], 'after_id': page[-1]['id']}
        self.assertEqual(1202, len(set(ids)))
        self.assertNotIn(('inbound', 'FOREIGN-COMPANY'), ids)
        self.assertNotIn(('inbound', 'FOREIGN-TENANT'), ids)

    def test_05_shared_forward_is_exact_idempotent_and_leaves_hr_unchanged(self):
        if self.namespace != 'edoc':
            return
        self.assertEqual(render_shared_forward(), (fixture.ROOT / 'supabase/shared-project-migrations' / FORWARD_NAME).read_text())
        self.assertEqual(1, self.pg.execute('SELECT count(*) FROM edoc_private.shared_project_migration_ledger WHERE file_name=%s', (SOURCE,)).fetchone()[0])
        self.assertEqual('unchanged', self.pg.execute("SELECT payload FROM public.hr_untouched WHERE id='HR'").fetchone()[0])

    def test_06_dispatch_acl_reply_instances_and_current_approval_generation(self):
        with self.pg.transaction():
            self.pg.execute("INSERT INTO internal_dispatches(id,inbound_document_id,title,subject,status,due_at,created_at) VALUES ('DISPATCH','NEW-0001','Synthetic','Synthetic','sent','2026-10-11','2026-10-02 10:00:00')")
            self.pg.execute("""INSERT INTO internal_dispatch_recipients(id,dispatch_id,recipient_user_id,action_required,replied_at,created_at)
                VALUES ('REPLY-A','DISPATCH','ACTOR',true,null,'2026-10-02 10:00:00'),
                 ('REPLY-B','DISPATCH','DEPARTED',true,null,'2026-10-03 10:00:00'),
                 ('REPLIED','DISPATCH','OTHER',true,'2026-10-04 10:00:00','2026-10-02 10:00:00')""")
            self.assertEqual(2, self.rpc()['count'])
            self.pg.execute("""INSERT INTO official_documents(id,company_id,applicant_id,title,source_type,requires_stamp,output_mode,dispatch_date,current_status,current_step,created_at,updated_at)
                VALUES ('METRIC-APPROVAL','CO-COMPOSE','ACTOR','Synthetic','uploaded_pdf',true,'physical','2026-10-11','draft','','2026-10-01 10:00:00','2026-10-01 10:00:00')""")
            self.pg.execute("""INSERT INTO official_document_approval_steps(id,document_id,workflow_generation,step_order,step_key,step_name,status,approved_at,created_at)
                VALUES ('OLD-PENDING','METRIC-APPROVAL',1,2,'department_head','Synthetic','pending',null,'2026-10-01 10:00:00'),
                 ('PREVIOUS','METRIC-APPROVAL',2,1,'applicant_manager','Synthetic','approved','2026-10-06 10:00:00','2026-10-01 10:00:00'),
                 ('CURRENT','METRIC-APPROVAL',2,2,'department_head','Synthetic','pending',null,'2026-10-01 10:00:00')""")
            self.pg.execute("UPDATE official_documents SET current_status='pending_department_head',current_step='department_head' WHERE id='METRIC-APPROVAL'")
            metric_rows = self.rpc('edoc_timeliness_candidates')['items']
            self.assertEqual(['CURRENT'], [r['id'] for r in metric_rows if r['source'] == 'approval'])
            self.assertEqual('2026-10-06 10:00:00', metric_rows[0]['entered_at'])
            tail = self.rpc('edoc_timeliness_candidates', {'after_source': 'inbound', 'after_id': 'ZZZ'})['items']
            self.assertEqual(['REPLY-A','REPLY-B'], [r['id'] for r in tail])
            self.pg.execute("UPDATE official_document_approval_steps SET approved_at=null WHERE id='PREVIOUS'")
            self.assertEqual('', self.rpc('edoc_timeliness_candidates')['items'][0]['entered_at'])
            # Roll back data; acceptance cases do not contaminate the next run.
            raise self.psycopg.Rollback()

    def test_07_shipping_gate_rejects_broadened_or_missing_read_rpc_privileges(self):
        filename = 'fresh_bootstrap_smoke.sql' if self.namespace == 'public' else 'shared_project_cutover_checks.sql'
        sql = (fixture.ROOT / 'supabase/verification' / filename).read_text()
        gate = re.search(r'do \$worklist_receipt_rpc_gate\$.*?\$worklist_receipt_rpc_gate\$;', sql, re.S).group(0)
        # This fixture installs the new read RPCs, not unrelated receipt RPCs.
        # Retain every shipping security check and exercise only these two.
        gate = re.sub(r'foreach v_rpc in array array\[[^\]]+\]',
                      "foreach v_rpc in array array['edoc_list_inbound_candidates(jsonb)','edoc_timeliness_candidates(jsonb)']", gate, count=1)
        self.pg.execute(gate)
        signature = f'{self.namespace}.edoc_list_inbound_candidates(jsonb)'
        mutations = (
            (f'ALTER FUNCTION {signature} SECURITY DEFINER', 'security_mismatch'),
            (f'ALTER FUNCTION {signature} RESET search_path', 'security_mismatch'),
            (f'REVOKE EXECUTE ON FUNCTION {signature} FROM {self.backend_role}', 'security_mismatch'),
            (f'GRANT EXECUTE ON FUNCTION {signature} TO anon', 'browser_grant'),
            (f'GRANT EXECUTE ON FUNCTION {signature} TO PUBLIC', 'browser_grant|public_grant'),
        )
        for mutation, code in mutations:
            with self.subTest(mutation=mutation), self.assertRaisesRegex(self.psycopg.Error, code):
                with self.pg.transaction():
                    self.pg.execute(mutation)
                    self.pg.execute(gate)
        self.pg.execute(gate)


class SharedWorkflowReadinessPostgresTest(WorkflowReadinessPostgresTest):
    namespace = 'edoc'
    backend_role = 'edoc_backend'
