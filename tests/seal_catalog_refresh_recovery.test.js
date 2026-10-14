const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const matches = [...source.matchAll(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n.*?^\\}`, 'msg'))];
  assert.ok(matches.length, name);
  return matches.at(-1)[0];
}
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function harness() {
  const company = { value: 'A' };
  const nodes = { '#uploadedSealCompany': company, '#composeCompanySelect': company };
  const c = {
    console, AbortController, Array, Promise, Error, Map, Set, authState: { token: 'session-A' }, scope: 'actor-A', authenticated: true,
    document: { querySelector: selector => nodes[selector] || null }, nodes, requests: [], renders: 0,
    uploadedSealCatalogState: { scope: 'actor-A', token: 'session-A', companyId: 'A', status: 'ready', request: null },
    uploadedSealOptions: [{ id: 'last-good', company_id: 'A', is_active: true, selectable: true }], uploadedSealOptionsRequestNo: 0,
    uploadedSealEditorRuntime: { reviewMode: 'edited', documentId: 'synthetic-document', locked: false }, uploadedSealApplicationRuntime: { companyId: 'A' }, uploadedSealEditorState: {},
    composeSealCatalogState: { scope: 'actor-A', token: 'session-A', status: 'ready', request: null },
    composeSealOptions: [{ id: 'last-good', company_id: 'A', is_active: true, selectable: true }], composeSealOptionsCompanyId: 'A', composeSealOptionsRequestNo: 0, composeSealOptionsLoading: false, composeSealOptionsError: false,
    normalizeUploadedEditorSealGeometry: () => false, renderUploadedSealOptions() {}, renderUploadedSealWorkbench() { c.renders++; }, renderComposeSealTypeOptions() {},
    companySealSelectable: row => row.selectable === true, composeCompanyForOfficialApplication: name => ({ id: name }),
    frontendSessionScope: () => c.scope, hasAuthenticatedBackendSession: () => c.authenticated,
    backendRequest: (url, options) => { const d = deferred(); c.requests.push({ url, options, ...d }); return d.promise; }
  };
  vm.createContext(c);
  vm.runInContext(['uploadedSealCatalogReady', 'uploadedSealCatalogMessage', 'companySealCatalogUnavailableReason', 'uploadedSealCompanyRecords', 'uploadedSealPickerReadOnly', 'retryUploadedSealCatalog', 'loadUploadedSealOptions', 'loadComposeSealOptions', 'composeSealOptionsForSelectedCompany', 'backendRequest'].filter(name => name !== 'backendRequest').map(implementation).join('\n'), c);
  return c;
}
test('transient failure retains last-good metadata but denies placement; explicit retry restores freshness', async () => {
  const c = harness(), loading = c.loadUploadedSealOptions('A');
  assert.equal(c.uploadedSealPickerReadOnly(), true);
  assert.match(c.uploadedSealCatalogMessage(), /正在更新/);
  c.requests[0].reject(Object.assign(Error('synthetic unavailable'), { status: 503 }));
  await loading;
  assert.equal(c.uploadedSealOptions[0].id, 'last-good');
  assert.equal(c.uploadedSealCatalogState.status, 'error');
  assert.equal(c.uploadedSealPickerReadOnly(), true);
  assert.match(c.uploadedSealCatalogMessage(), /更新失敗/);
  assert.doesNotMatch(c.uploadedSealCatalogMessage(), /尚無/);
  const retry = c.retryUploadedSealCatalog();
  c.requests[1].resolve([{ id: 'fresh', company_id: 'A', selectable: true }]);
  await retry;
  assert.equal(c.uploadedSealCatalogReady(), true);
  assert.equal(c.uploadedSealPickerReadOnly(), false);
  assert.equal(c.uploadedSealOptions[0].id, 'fresh');
});
test('403 clears catalog and is not disguised as empty or retryable transport failure', async () => {
  const c = harness(), request = c.loadUploadedSealOptions('A');
  c.requests[0].reject(Object.assign(Error('forbidden'), { status: 403 })); await request;
  assert.equal(c.uploadedSealOptions.length, 0); assert.equal(c.uploadedSealCatalogState.status, 'forbidden');
  assert.match(c.uploadedSealCatalogMessage(), /權限/); assert.equal(c.uploadedSealCatalogReady(), false);
});
test('same actor/company requests coalesce, token changes abort and isolate late responses', async () => {
  const c = harness(), first = c.loadUploadedSealOptions('A'), same = c.loadUploadedSealOptions('A');
  assert.equal(c.requests.length, 1);
  c.authState.token = 'session-B'; assert.equal(c.uploadedSealCatalogReady(), false); assert.equal(c.uploadedSealCompanyRecords().length, 0);
  const latest = c.loadUploadedSealOptions('A');
  assert.equal(c.requests[0].options.signal.aborted, true); assert.equal(c.uploadedSealOptions.length, 0);
  c.requests[1].resolve([{ id: 'new-session', company_id: 'A', selectable: true }]); await latest;
  c.requests[0].resolve([{ id: 'old-session', company_id: 'A', selectable: true }]); await Promise.all([first, same]);
  assert.equal(c.uploadedSealOptions[0].id, 'new-session');
});
test('company changes cannot display or accept old selections; wrong-company server rows are discarded', async () => {
  const c = harness(); c.nodes['#uploadedSealCompany'].value = 'B';
  assert.equal(c.uploadedSealCompanyRecords().length, 0); assert.equal(c.uploadedSealPickerReadOnly(), true);
  const next = c.loadUploadedSealOptions('B'); assert.equal(c.uploadedSealOptions.length, 0);
  c.requests[0].resolve([{ id: 'foreign', company_id: 'A', selectable: true }, { id: 'right', company_id: 'B', selectable: true }]); await next;
  assert.deepEqual(Array.from(c.uploadedSealCompanyRecords(), row => row.id), ['right']);
});
test('empty, file verification unavailable, classification and owner mismatch are distinguishable', () => {
  const c = harness();
  for (const [reason, expected] of [['verification_unavailable', /暫時無法確認/], ['classification_required', /分類尚未設定/], ['owner_policy_mismatch', /類型不符/], ['unusable_current', /目前無法使用/]]) {
    c.uploadedSealOptions = [{ company_id: 'A', availability_reason: reason, selectable: false }];
    assert.match(c.uploadedSealCatalogMessage(), expected); assert.doesNotMatch(c.uploadedSealCatalogMessage(), /尚無/);
  }
  c.uploadedSealOptions = []; assert.match(c.uploadedSealCatalogMessage(), /尚無已登錄/);
});
test('20-second real request deadline ends catalog loading, not a false empty success', async () => {
  const c = harness(); let deadline;
  c.backendApiBase = ''; c.isHeaderSafeToken = () => false;
  c.fetchWithDeadline = (_url, _options, policy) => { deadline = policy.timeoutMs; return Promise.reject(Object.assign(Error('synthetic deadline'), { name: 'TimeoutError' })); };
  vm.runInContext(implementation('backendRequest'), c);
  await c.loadUploadedSealOptions('A');
  assert.equal(deadline, 20000); assert.equal(c.uploadedSealEditorRuntime.sealOptionsLoading, false);
  assert.equal(c.uploadedSealCatalogState.status, 'error'); assert.equal(c.uploadedSealOptions[0].id, 'last-good');
  assert.equal(c.uploadedSealCatalogReady(), false);
});
test('compose catalog coalesces and retains same-scope choices on 503, clears them on 403', async () => {
  const c = harness(), a = c.loadComposeSealOptions('A', { force: true }), b = c.loadComposeSealOptions('A', { force: true });
  assert.equal(c.requests.length, 1); assert.equal(c.composeSealOptionsLoading, true);
  c.requests[0].reject(Object.assign(Error('unavailable'), { status: 503 })); await Promise.all([a, b]);
  assert.equal(c.composeSealOptions[0].id, 'last-good'); assert.equal(c.composeSealOptionsError, true); assert.equal(c.composeSealCatalogState.status, 'error');
  const retry = c.loadComposeSealOptions('A', { force: true }); c.requests[1].reject(Object.assign(Error('forbidden'), { status: 403 })); await retry;
  assert.equal(c.composeSealOptions.length, 0); assert.equal(c.composeSealCatalogState.status, 'forbidden');
});
test('editor 409 recovery cleanup preserves valid same-scope catalog; auth cleanup invalidates it', () => {
  const recover = implementation('clearUploadedEditorSensitivePreviews');
  assert.doesNotMatch(recover, /uploadedSealCatalogState\s*=|uploadedSealOptions\s*=|uploadedSealOptionsRequestNo\s*\+=/);
  const logout = implementation('clearFinanceDirectoryCache');
  assert.match(logout, /uploadedSealCatalogState =/); assert.match(logout, /uploadedSealOptions = \[\]/); assert.match(logout, /composeSealCatalogState =/);
});
