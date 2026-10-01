// Shipping functions, controlled synthetic reads/timers, no hosted services.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const start = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(start, name);
  const end = source.indexOf('\n}\n', start.index);
  assert.ok(end > start.index, name);
  return source.slice(start.index, end + 2);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
const tick = () => new Promise(setImmediate);
function listHarness() {
  const reads = [], renders = [], toasts = [];
  const c = { console, URLSearchParams, Map, Set, Array, JSON, Promise, Error,
    actor: 'synthetic-A', frontendSessionScope: () => c.actor,
    authState: { token: 'synthetic-session-A' },
    officialWorkflowScope: 'all', officialWorkflowSearchTerm: '', officialWorkflowStatusFilter: '',
    officialWorkflowPage: { generation: 0, scope: '', query: null, cursor: '', hasMore: false, loading: false, error: false },
    officialWorkflowItems: [{ id: 'old' }], selectedOfficialDocumentId: 'old',
    officialDocumentDetailReady: new Set(), officialDocumentDetailRequests: new Map(),
    officialWorkflowEndpoint: () => '/official-documents',
    backendRequest(url) { const read = deferred(); reads.push({ ...read, url, actor: c.actor }); return read.promise; },
    showToast(message) { toasts.push(message); },
  };
  for (const name of ['renderOfficialWorkflowPagination', 'renderOfficialWorkflow', 'renderApprovalLog', 'renderElectronicSealWorkQueue', 'refreshDashboardWorkEntryPoints']) c[name] = () => renders.push(name);
  vm.createContext(c); vm.runInContext(implementation('loadOfficialWorkflow'), c);
  return { c, reads, renders, toasts };
}
const response = (id, more = false, cursor = '') => ({ items: [{ id }], has_more: more, next_cursor: cursor });

test('same actor/query shares one HTTP read while every caller retains its generation', async () => {
  const h = listHarness();
  const first = h.c.loadOfficialWorkflow('all', { source: 'editor', search: ' synthetic ' });
  const second = h.c.loadOfficialWorkflow('all', { source: 'editor', search: 'synthetic' });
  assert.equal(h.reads.length, 1);
  assert.equal(h.c.officialWorkflowPage.generation, 2);
  h.reads[0].resolve(response('latest')); await Promise.all([first, second]);
  assert.equal(h.c.officialWorkflowItems[0].id, 'latest');
  assert.equal(h.renders.filter(name => name === 'renderApprovalLog').length, 1);
  assert.equal(h.c.loadOfficialWorkflow.pendingReads.size, 0);
});

test('different queries and actors never share, and old responses cannot replace latest content', async () => {
  const h = listHarness();
  const old = h.c.loadOfficialWorkflow('all', { search: 'old' });
  const latest = h.c.loadOfficialWorkflow('all', { search: 'new' });
  assert.equal(h.reads.length, 2);
  h.reads[1].resolve(response('new')); await latest;
  h.reads[0].resolve(response('old')); await old;
  assert.equal(h.c.officialWorkflowItems[0].id, 'new');
  const actorA = h.c.loadOfficialWorkflow('all', { search: 'shared' });
  h.c.actor = 'synthetic-B';
  const actorB = h.c.loadOfficialWorkflow('all', { search: 'shared' });
  assert.equal(h.reads.length, 4);
  h.reads[3].resolve(response('owner-B')); await actorB;
  h.reads[2].resolve(response('private-A')); await actorA;
  assert.equal(h.c.officialWorkflowItems[0].id, 'owner-B');
  assert.equal(h.c.loadOfficialWorkflow.pendingReads.size, 0);
});

test('shared failure obeys latest caller throwOnError and permits a fresh retry', async () => {
  for (const throwOnError of [true, false]) {
    const h = listHarness();
    const first = h.c.loadOfficialWorkflow('all', { throwOnError: !throwOnError });
    const second = h.c.loadOfficialWorkflow('all', { throwOnError });
    const secondResult = throwOnError ? assert.rejects(second, /offline/) : second;
    h.reads[0].reject(new Error('synthetic offline'));
    await first; await secondResult;
    assert.equal(h.c.officialWorkflowItems[0].id, 'old');
    assert.equal(h.c.officialWorkflowPage.error, true);
    assert.equal(h.toasts.length, 1);
    assert.equal(h.c.loadOfficialWorkflow.pendingReads.size, 0);
    const retry = h.c.loadOfficialWorkflow('all', { throwOnError: true });
    assert.equal(h.reads.length, 2);
    h.reads[1].resolve(response('retried')); await retry;
    assert.equal(h.c.officialWorkflowItems[0].id, 'retried');
    assert.equal(h.c.officialWorkflowPage.error, false);
  }
});

test('append guards and cursor identity remain separate from a first-page refresh', async () => {
  const h = listHarness();
  const first = h.c.loadOfficialWorkflow('all'); h.reads[0].resolve(response('first', true, 'cursor:a+b')); await first;
  const more = h.c.loadOfficialWorkflow('all', { append: true });
  await h.c.loadOfficialWorkflow('all', { append: true });
  assert.equal(h.reads.length, 2, 'a second append remains blocked while loading');
  assert.match(h.reads[1].url, /cursor=cursor%3Aa%2Bb/);
  const refresh = h.c.loadOfficialWorkflow('all');
  assert.equal(h.reads.length, 3, 'refresh cannot reuse an append transport');
  h.reads[2].resolve(response('fresh')); await refresh;
  h.reads[1].resolve(response('appended-stale')); await more;
  assert.deepEqual(Array.from(h.c.officialWorkflowItems, item => item.id), ['fresh']);
});

test('explicit current guard still prevents reads and ignores an invalidated shared response', async () => {
  const h = listHarness(); let valid = true;
  await h.c.loadOfficialWorkflow('all', { isCurrent: () => false });
  assert.equal(h.reads.length, 0);
  const load = h.c.loadOfficialWorkflow('all', { isCurrent: () => valid });
  valid = false; h.reads[0].resolve(response('must-not-apply')); await load;
  assert.equal(h.c.officialWorkflowItems[0].id, 'old');
  assert.equal(h.c.loadOfficialWorkflow.pendingReads.size, 0);
});

test('reauthentication of the same user does not share the old authorization transport', async () => {
  const h = listHarness();
  const old = h.c.loadOfficialWorkflow('all', { search: 'same' });
  h.c.authState = { token: 'synthetic-session-B' };
  const fresh = h.c.loadOfficialWorkflow('all', { search: 'same' });
  assert.equal(h.reads.length, 2);
  h.reads[1].resolve(response('new-authorization')); await fresh;
  h.reads[0].resolve(response('old-authorization')); await old;
  assert.equal(h.c.officialWorkflowItems[0].id, 'new-authorization');
  const invalidated = h.c.loadOfficialWorkflow('all');
  h.c.authState = null; h.reads[2].resolve(response('late-private')); await invalidated;
  assert.equal(h.c.officialWorkflowItems[0].id, 'new-authorization');
});

function directoryHarness() {
  const counts = { full: 0, status: 0, readiness: 0 };
  const c = { console, Object, Array, JSON, String, Number, Date, Map, actor: 'synthetic-A',
    frontendSessionScope: () => c.actor, financeDirectoryState: {}, companySealCompanies: [], companyRegistry: [], departmentRegistry: [],
    selectedCompanySealCompanyId: 'company', officialWorkflowReadinessByRoute: new Map(), activeRouteTarget: 'electronicSeal',
    normalizeFinanceDirectoryCompany: item => ({ ...item }), normalizeFinanceDirectoryDepartment: item => ({ ...item }),
    financeDirectoryDepartmentCompanyLabel: () => 'Synthetic company',
    financeDirectoryCurrentCompany: () => ({ id: 'company' }), setCompanySealCompanySelection() {},
    renderFinanceDirectoryConsumers: () => counts.full++, renderFinanceDirectorySyncStatus: () => counts.status++,
    refreshWorkflowReadinessForContext: () => { counts.readiness++; return Promise.resolve(); },
  };
  vm.createContext(c); vm.runInContext(implementation('financeDirectoryContentKey') + '\n' + implementation('applyFinanceDirectoryPayload'), c);
  const payload = { source: 'finance', schemaVersion: 2, directoryVersion: 'synthetic-version', currentCompanyId: 'company',
    companies: [{ id: 'company', name: 'Synthetic company', status: 'active' }],
    departments: [{ id: 'dept', code: 'D1', name: 'Synthetic department', status: 'active' }],
    organization: { manager: 'synthetic-manager' }, syncedAt: '2026-09-28T00:00:00Z' };
  return { c, counts, payload };
}

test('unchanged canonical directory preserves controls/references/readiness but advances sync time', () => {
  const h = directoryHarness(); h.c.applyFinanceDirectoryPayload(h.payload);
  const companies = h.c.companySealCompanies, departments = h.c.departmentRegistry;
  h.c.officialWorkflowReadinessByRoute.set('ready', { submitAllowed: true });
  h.c.financeDirectoryState.status = 'error'; h.c.financeDirectoryState.error = 'synthetic transient';
  h.c.applyFinanceDirectoryPayload({ ...h.payload, companies: [{ status: 'active', name: 'Synthetic company', id: 'company' }], syncedAt: '2026-09-28T00:01:00Z' });
  assert.equal(h.counts.full, 1); assert.equal(h.counts.readiness, 1); assert.equal(h.counts.status, 1);
  assert.equal(h.c.companySealCompanies, companies); assert.equal(h.c.departmentRegistry, departments);
  assert.equal(h.c.officialWorkflowReadinessByRoute.has('ready'), true);
  assert.equal(h.c.financeDirectoryState.syncedAt, '2026-09-28T00:01:00Z');
  assert.equal(h.c.financeDirectoryState.status, 'synced'); assert.equal(h.c.financeDirectoryState.error, '');
});

test('same directory version with an actual organization/permission/context change always redraws', () => {
  const h = directoryHarness(); h.c.applyFinanceDirectoryPayload(h.payload);
  for (const extra of [{ organization: { manager: 'different-manager' } }, { editorApplicantCompanies: [] }, { currentApplicantDepartment: null }]) {
    h.c.officialWorkflowReadinessByRoute.set('ready', {});
    const before = h.counts.full;
    h.c.applyFinanceDirectoryPayload({ ...h.payload, ...extra });
    assert.equal(h.counts.full, before + 1);
    assert.equal(h.c.officialWorkflowReadinessByRoute.size, 0);
  }
});

test('an identical directory never reuses another account content fingerprint', () => {
  const h = directoryHarness(); h.c.applyFinanceDirectoryPayload(h.payload);
  h.c.actor = 'synthetic-B'; h.c.applyFinanceDirectoryPayload(h.payload);
  assert.equal(h.counts.full, 2); assert.equal(h.c.financeDirectoryState.contentScope, 'synthetic-B');
});

const INITIALIZATION_ORDER = `renderComposeApprovalRoute renderOfficialApplicationApprovalRoute renderUploadedSealApprovalRoute assignNextDispatchNo composeTodayDate syncComposeElectronicExchangeMode applyComposeContactDefaults renderDraftPreview renderQueueRows renderInboundRows renderInboundDetail renderInboundAuditLog setInboundSection renderDispatchBoard renderDispatchDetail renderDispatchAuditLog renderInternalDispatchModule renderPrechecks renderJagentStatus renderAddressResults renderFormatAttachments renderFormatChecks renderFormatAgencyResults renderFormatAuditLog renderWorkflowRole renderOfficialWorkflowConfig renderWorkflowTasks renderUnifiedFlows renderWorkflowSteps renderApprovalProgress renderApprovalLog renderWorkflowAuditLog renderApprovalCategorySelect renderWorkflowTemplateSteps renderWorkflowConditions renderWorkflowProxies renderWorkflowProofLog renderContracts renderContractSeal fillContractForm renderSeals renderTrackingSummary renderTrackingRows renderTrackingDetail renderTrackingAuditLog renderTimeline renderTimeline renderArchiveSummary renderArchiveRows renderArchiveDetail renderArchiveGrid renderArchiveAuditLog renderSecurityStatus renderSecurityPermissionGrid renderSecurityDeviceList renderSecurityAuditLog renderFileSecurity renderAccounts renderReports renderReportsAuditLog renderNotifications renderNotificationAuditLog renderJobs renderDatabase renderOps renderComplianceOps renderSettings renderSearch applyFormalExchangeUiState applyProductionLoginSafetyState`.split(' ');
function initializationHarness(cost = 0) {
  const calls = [], timers = [], idle = []; let clock = 0;
  const dateInput = { value: '' };
  const c = { console, Promise, actor: 'synthetic-A', authenticated: true, authState: { token: 'synthetic-token-A' },
    frontendSessionScope: () => c.actor, hasAuthenticatedBackendSession: () => c.authenticated,
    deferredWorkspaceInitialized: false, deferredWorkspaceScheduled: false, deferredWorkspaceInitializedScope: '', deferredWorkspaceInitializedToken: '', deferredWorkspaceOperation: null,
    document: { querySelector: () => dateInput }, performance: { now: () => clock }, exchangeEvents: [], auditEvents: [],
    window: { setTimeout(fn, delay) { timers.push({ fn, delay }); }, requestIdleCallback(fn) { idle.push(fn); } },
  };
  for (const name of new Set(INITIALIZATION_ORDER)) c[name] = (...args) => { calls.push({ name, args, actor: c.actor }); clock += cost; if (name === 'composeTodayDate') return '2026-09-28'; };
  vm.createContext(c); vm.runInContext(implementation('initializeDeferredWorkspace') + '\n' + implementation('scheduleDeferredWorkspaceInitialization'), c);
  return { c, calls, timers, idle, dateInput, drain() { let count = 0; while (timers.length) { assert.ok(count++ < 1000); timers.shift().fn(); } } };
}

test('deferred initialization yields, coalesces, and preserves every original step and order', async () => {
  const h = initializationHarness();
  const first = h.c.initializeDeferredWorkspace(), second = h.c.initializeDeferredWorkspace();
  assert.equal(first, second); assert.equal(h.calls.length, 6); assert.equal(h.timers.length, 1);
  assert.equal(h.c.deferredWorkspaceInitialized, false);
  h.drain(); assert.equal(await first, true);
  assert.deepEqual(h.calls.map(item => item.name), INITIALIZATION_ORDER);
  assert.equal(h.calls.find(item => item.name === 'assignNextDispatchNo').args[0], true);
  assert.equal(h.calls.find(item => item.name === 'setInboundSection').args[0], 'records');
  assert.equal(h.dateInput.value, '2026-09-28');
  assert.equal(h.c.deferredWorkspaceInitialized, true);
  await h.c.initializeDeferredWorkspace(); assert.equal(h.calls.length, INITIALIZATION_ORDER.length);
});

test('elapsed budget yields after a costly step and does not overwrite an existing date', async () => {
  const h = initializationHarness(7); h.dateInput.value = '2026-09-30';
  const load = h.c.initializeDeferredWorkspace(); assert.equal(h.calls.length, 1);
  h.timers.shift().fn(); assert.equal(h.calls.length, 2);
  h.drain(); await load;
  assert.equal(h.dateInput.value, '2026-09-30');
  assert.equal(h.calls.some(item => item.name === 'composeTodayDate'), false);
});

test('account switch stops the old batch and initializes the new actor without stale continuation', async () => {
  const h = initializationHarness(); const old = h.c.initializeDeferredWorkspace();
  h.c.actor = 'synthetic-B'; const next = h.c.initializeDeferredWorkspace();
  const split = h.calls.length; h.drain();
  assert.equal(await old, false); assert.equal(await next, true);
  assert.equal(h.calls.slice(split).every(item => item.actor === 'synthetic-B'), true);
  assert.equal(h.calls.filter(item => item.actor === 'synthetic-A').length, 6);
  assert.equal(h.c.deferredWorkspaceInitializedScope, 'synthetic-B');
  const loggedOut = initializationHarness(); const pending = loggedOut.c.initializeDeferredWorkspace();
  loggedOut.c.authenticated = false; loggedOut.drain(); assert.equal(await pending, false);
  assert.equal(loggedOut.calls.length, 6); assert.equal(loggedOut.c.deferredWorkspaceInitialized, false);
});

test('idle scheduling remains post-auth and a renderer failure can be explicitly retried', async () => {
  const h = initializationHarness(); h.c.scheduleDeferredWorkspaceInitialization(); h.c.scheduleDeferredWorkspaceInitialization();
  assert.equal(h.idle.length, 1); assert.equal(h.calls.length, 0);
  h.idle.shift()(); h.drain(); await tick(); assert.equal(h.c.deferredWorkspaceInitialized, true);
  const failure = initializationHarness(); const original = failure.c.renderContractSeal;
  failure.c.renderContractSeal = () => { throw new Error('synthetic renderer failure'); };
  const first = failure.c.initializeDeferredWorkspace(); const rejected = assert.rejects(first, /renderer failure/);
  failure.drain(); await rejected;
  assert.equal(failure.c.deferredWorkspaceOperation, null); assert.equal(failure.c.deferredWorkspaceInitialized, false);
  failure.c.renderContractSeal = original; const retry = failure.c.initializeDeferredWorkspace(); failure.drain(); assert.equal(await retry, true);
});

test('same actor re-login stops old batches and does not reuse completed initialization', async () => {
  const h = initializationHarness(); const old = h.c.initializeDeferredWorkspace();
  h.c.authState.token = 'synthetic-token-B';
  h.c.scheduleDeferredWorkspaceInitialization(); assert.equal(h.idle.length, 1);
  h.idle.shift()(); const next = h.c.initializeDeferredWorkspace(); h.drain();
  assert.equal(await old, false); assert.equal(await next, true);
  assert.equal(h.calls.length, 6 + INITIALIZATION_ORDER.length - 1); // Existing date is retained.
  assert.equal(h.c.deferredWorkspaceInitializedToken, 'synthetic-token-B');
  h.c.authState.token = 'synthetic-token-C';
  h.c.scheduleDeferredWorkspaceInitialization(); assert.equal(h.idle.length, 1);
  h.idle.shift()(); h.drain(); await tick();
  assert.equal(h.calls.length, 6 + 2 * (INITIALIZATION_ORDER.length - 1));
  assert.equal(h.c.deferredWorkspaceInitializedToken, 'synthetic-token-C');
  const stopped = initializationHarness(); const pending = stopped.c.initializeDeferredWorkspace();
  stopped.c.authState = null; stopped.drain();
  assert.equal(await pending, false); assert.equal(stopped.calls.length, 6);
});

test('contract input changed between initialization batches is never cleared by late defaults', async () => {
  const h = initializationHarness();
  const fields = [{ id: 'contractTitleInput', value: '' }, { id: 'contractSummaryInput', value: '' }];
  h.c.document.querySelector = selector => selector === '#contractForm' ? { querySelectorAll: () => fields } : h.dateInput;
  h.c.fillContractForm = () => { h.calls.push({ name: 'fillContractForm', args: [], actor: h.c.actor }); fields.forEach(field => { field.value = ''; }); };
  const load = h.c.initializeDeferredWorkspace();
  fields[0].value = 'Synthetic new contract'; fields[1].value = 'Unsaved latest content';
  h.drain(); assert.equal(await load, true);
  assert.equal(fields[0].value, 'Synthetic new contract'); assert.equal(fields[1].value, 'Unsaved latest content');
  assert.deepEqual(h.calls.map(item => item.name), INITIALIZATION_ORDER.filter(name => name !== 'fillContractForm'));
  const unchanged = initializationHarness();
  unchanged.c.document.querySelector = selector => selector === '#contractForm' ? { querySelectorAll: () => fields } : unchanged.dateInput;
  const next = unchanged.c.initializeDeferredWorkspace(); unchanged.drain(); await next;
  assert.deepEqual(unchanged.calls.map(item => item.name), INITIALIZATION_ORDER);
});
