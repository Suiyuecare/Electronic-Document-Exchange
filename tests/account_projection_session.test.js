// Shipping /auth/me projection lifecycle; synthetic sessions, no network.
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
const start = source.indexOf('async function refreshFinanceAccountProjection(');
const implementation = source.slice(start, source.indexOf('\n}\n', start) + 3);
const session = (id, token = id, company = 'synthetic-company') => ({ token, user: { id, company_id: company }, bridge: 'synthetic-bridge' });
function harness() {
  const button = { disabled: false }, reads = [], events = [];
  const c = { authState: session('synthetic-A'), Promise,
    frontendSessionScope: (value = c.authState) => `${value?.user?.id}:${value?.user?.company_id}`,
    document: { querySelector: () => button },
    backendRequest(path) { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); reads.push({ path, resolve, reject }); return promise; },
    persistAuthenticatedSession(value) { events.push(['persist', value.user.id]); },
    syncUserAccountFromSession(value) { events.push(['sync', value.user.id]); },
    applyAuthUser() { events.push(['apply', c.authState.user.id]); },
    loadFinanceCompanyDirectory: async () => {}, ensureAccountLaunchAudit: async () => {},
    renderAccounts() { events.push(['render', c.authState.user.id]); },
    addAccountAudit(title) { events.push(['audit', title]); }, showToast(text) { events.push(['toast', text]); },
  };
  vm.createContext(c); vm.runInContext(implementation, c);
  return { c, button, reads, events };
}
test('old A response cannot install its user/permissions alongside B credential', async () => {
  const h = harness(), old = h.c.refreshFinanceAccountProjection();
  const nextSession = session('synthetic-B'); h.c.authState = nextSession;
  h.reads[0].resolve({ user: { id: 'synthetic-A' }, permissions: ['synthetic-admin'] });
  assert.equal(await old, false); assert.equal(h.c.authState, nextSession);
  assert.deepEqual(h.events, []); assert.equal(h.button.disabled, false);
});
test('same user re-login starts a distinct read and old finally cannot clear new busy', async () => {
  const h = harness(), old = h.c.refreshFinanceAccountProjection();
  h.c.authState = session('synthetic-A', 'new-token'); const next = h.c.refreshFinanceAccountProjection();
  assert.equal(h.reads.length, 2);
  h.reads[0].reject(new Error('synthetic-old-failure'));
  assert.equal(await old, false); assert.equal(h.button.disabled, true); assert.deepEqual(h.events, []);
  h.reads[1].resolve({ user: { id: 'synthetic-A', company_id: 'synthetic-company' }, permissions: ['synthetic-member'] });
  assert.equal(await next, true); assert.equal(h.c.authState.token, 'new-token');
  assert.deepEqual([...h.c.authState.permissions], ['synthetic-member']);
  assert.equal(h.button.disabled, false); assert.equal(h.c.refreshFinanceAccountProjection.operation, null);
});
test('one current session coalesces reads, accepts authoritative company update and preserves credential', async () => {
  const h = harness(), first = h.c.refreshFinanceAccountProjection(), second = h.c.refreshFinanceAccountProjection();
  assert.equal(h.reads.length, 1);
  h.reads[0].resolve({ user: { id: 'synthetic-A', company_id: 'new-company' }, permissions: ['synthetic-member'] });
  assert.equal(await first, true); assert.equal(await second, true);
  assert.equal(h.c.authState.user.company_id, 'new-company'); assert.equal(h.c.authState.token, 'synthetic-A');
  assert.equal(h.events.filter(e => e[0] === 'audit').length, 1); assert.equal(h.button.disabled, false);
});
test('logout during dependent reads suppresses old render, audit and completion toast', async () => {
  const h = harness(); let release; h.c.loadFinanceCompanyDirectory = () => new Promise(r => { release = r; });
  const old = h.c.refreshFinanceAccountProjection();
  h.reads[0].resolve({ user: { id: 'synthetic-A', company_id: 'synthetic-company' } });
  await new Promise(resolve => setImmediate(resolve));
  h.c.authState = null; release(); assert.equal(await old, false);
  assert.deepEqual(h.events.map(e => e[0]), ['persist', 'sync', 'apply']); assert.equal(h.button.disabled, false);
});
test('current failure reports once and clears operation so retry makes a fresh read', async () => {
  const h = harness(), failed = h.c.refreshFinanceAccountProjection(); h.reads[0].reject(new Error('synthetic-offline'));
  assert.equal(await failed, false); assert.equal(h.events.filter(e => e[0] === 'toast').length, 1);
  const retry = h.c.refreshFinanceAccountProjection(); assert.equal(h.reads.length, 2);
  h.reads[1].resolve({ user: { id: 'synthetic-A', company_id: 'synthetic-company' } });
  assert.equal(await retry, true); assert.equal(h.button.disabled, false);
});

test('shipping session reset releases account refresh immediately and stale cleanup cannot touch new busy', async () => {
  const h = harness();
  const node = { classList: { add() {}, remove() {} }, setAttribute() {}, removeAttribute() {} };
  h.c.document.querySelector = selector => selector === '#accountRefreshBtn' ? h.button : node;
  Object.assign(h.c, { workspaceRefreshRequest: null, headerBackendSyncState: {}, routeScrollPositions: new Map(), routeScrollScope: '',
    composeAutosaveRestoredForIdentity: '', composeAutosaveLastWrittenRaw: null, composeCloudRows: [], composeCloudRevisions: new Map(), composeCloudSavedSnapshots: new Map(), officialAttachmentUploadCache: new Map(),
    composeCloudListGeneration: 0, composeCloudCountGeneration: 0, composeCloudListRequest: null, composeCloudCountRequest: null,
    composePendingArchiveCache: { key: '', rows: [] }, composePendingArchiveRequests: new Map(), renderComposeDraftCount() {}, renderComposeDraftList() {} });
  for (const name of ['clearCurrentFrontendSessionState', 'dismissToast', 'closeInboundModal', 'closeContractModal', 'stopFinanceDirectoryAutoRefresh', 'clearFinanceDirectoryCache',
    'clearUploadedEditorSensitivePreviews', 'resetOfficialWorkflowConfigEditor', 'closeOfficialDecisionDialog', 'clearComposeAutosave', 'resetComposeAsyncScope',
    'cleanPortalHandoffUrl', 'closeMobileNavigation', 'resetCachedSessionShellReveal', 'applyProductionLoginSafetyState']) h.c[name] = () => {};
  const clearStart = source.indexOf('function clearAppSessionUi(');
  vm.runInContext(source.slice(clearStart, source.indexOf('\n}\n', clearStart) + 3), h.c);
  const old = h.c.refreshFinanceAccountProjection(); assert.equal(h.button.disabled, true);
  h.c.clearAppSessionUi(h.c.authState);
  assert.equal(h.c.authState, null); assert.equal(h.button.disabled, false);
  assert.equal(h.button._financeAccountRefreshOperation, undefined); assert.equal(h.c.refreshFinanceAccountProjection.operation, null);
  h.c.authState = session('synthetic-B'); const next = h.c.refreshFinanceAccountProjection();
  h.reads[0].resolve({ user: { id: 'synthetic-A', company_id: 'synthetic-company' } });
  assert.equal(await old, false); assert.equal(h.button.disabled, true); assert.deepEqual(h.events, []);
  h.reads[1].resolve({ user: { id: 'synthetic-B', company_id: 'synthetic-company' } });
  assert.equal(await next, true); assert.equal(h.c.authState.user.id, 'synthetic-B'); assert.equal(h.button.disabled, false);
});
