const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const match = new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n.*?^\\}`, 'ms').exec(source);
  assert.ok(match, name); return match[0];
}
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const tick = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function harness() {
  const nodes = {};
  for (const name of ['headerRefreshBtn', 'mobileDrawerRefreshBtn', 'workspaceLoadStatus', 'workspaceLoadLabel', 'workspaceLoadRetryBtn']) nodes['#' + name] = { hidden: false, dataset: {}, disabled: false, textContent: '', setAttribute(k, v) { this[k] = v; }, removeAttribute(k) { delete this[k]; } };
  nodes['#uploadedSealTitle'] = { value: 'Synthetic unsaved title' };
  const c = { console, Map, Set, Promise, Date, Error, nodes, calls: [], toasts: [], scope: 'actor', authState: { token: 'session' },
    document: { querySelector: s => nodes[s] || null }, activeRouteTarget: 'electronicSeal', frontendSessionScope: () => c.scope, hasAuthenticatedBackendSession: () => true,
    workspaceRefreshRequest: null, workspaceSupplementalReads: new Map(), routeBackendDataScope: 'actor', routeBackendDataToken: 'session', routeBackendDataRequests: new Map(), routeBackendDataErrors: new Map(), routeBackendDataLoaded: new Set(['electronicSeal']),
    headerBackendSyncState: { status: 'idle' }, updateHeaderStatus() {}, showToast: value => c.toasts.push(value), officialWorkflowScope: 'all', officialWorkflowPage: { query: { source: 'editor' } }
  };
  for (const name of ['loadRouteBackendData', 'syncNotificationsFromBackend', 'loadOfficialWorkflow']) c[name] = (...args) => { const d = deferred(); c.calls.push({ name, args, ...d }); return d.promise; };
  vm.createContext(c); vm.runInContext(['refreshWorkspaceSupplementalData', 'refreshCurrentWorkspace', 'renderWorkspaceLoadStatus'].map(implementation).join('\n'), c); return c;
}
test('30-second supplemental reads do not block actual editor-core completion or overwrite input', async () => {
  const c = harness(); const first = c.refreshCurrentWorkspace(), same = c.refreshCurrentWorkspace();
  assert.deepEqual(c.calls.map(x => x.name), ['loadRouteBackendData', 'syncNotificationsFromBackend', 'loadOfficialWorkflow']);
  assert.equal(c.nodes['#headerRefreshBtn'].disabled, true);
  c.calls[0].resolve(true); assert.equal(await first, true); assert.equal(await same, true);
  assert.equal(c.nodes['#headerRefreshBtn'].disabled, false); assert.equal(c.headerBackendSyncState.status, 'core_synced');
  assert.match(c.nodes['#workspaceLoadLabel'].textContent, /通知、案件清單背景更新中/);
  assert.equal(c.nodes['#workspaceLoadStatus'].dataset.state, 'background');
  assert.equal(c.nodes['#uploadedSealTitle'].value, 'Synthetic unsaved title');
  assert.doesNotMatch(c.toasts[0], /已取得最新資料/);
  c.calls[1].resolve(); c.calls[2].resolve(); await tick();
  assert.equal(c.nodes['#workspaceLoadStatus'].hidden, true);
});
test('supplemental error names its own source and leaves successful core catalog usable', async () => {
  const c = harness(), refresh = c.refreshCurrentWorkspace();
  c.calls[0].resolve(true); c.calls[1].reject(Error('synthetic notification failure')); c.calls[2].resolve(); await refresh; await tick();
  assert.equal(c.routeBackendDataLoaded.has('electronicSeal'), true); assert.equal(c.routeBackendDataErrors.size, 0);
  assert.match(c.nodes['#workspaceLoadLabel'].textContent, /通知更新失敗/); assert.doesNotMatch(c.nodes['#workspaceLoadLabel'].textContent, /印章|權限/);
  assert.equal(c.nodes['#workspaceLoadRetryBtn'].hidden, false);
});
test('manual retry coalesces pending supplements and preserves core source-specific failures', async () => {
  const c = harness(), first = c.refreshCurrentWorkspace(); c.calls[0].resolve(true); await first;
  const retry = c.refreshCurrentWorkspace(); assert.equal(c.calls.length, 4);
  c.routeBackendDataErrors.set('electronicSeal', ['簽核設定']); c.calls[3].resolve(false); assert.equal(await retry, false);
  assert.deepEqual(Array.from(c.routeBackendDataErrors.get('electronicSeal')), ['簽核設定']);
  assert.match(c.nodes['#workspaceLoadLabel'].textContent, /簽核設定更新失敗/);
  c.calls[1].resolve(); c.calls[2].resolve(); await tick();
});
test('late supplemental response from previous session never displays private status in next session', async () => {
  const c = harness(); const pending = c.refreshWorkspaceSupplementalData('electronicSeal');
  c.authState.token = 'new-session'; c.renderWorkspaceLoadStatus();
  assert.equal(c.nodes['#workspaceLoadStatus'].hidden, true);
  c.calls[0].reject(Error('old session')); c.calls[1].resolve(); await pending;
  assert.equal(c.nodes['#workspaceLoadStatus'].hidden, true); assert.equal(c.workspaceSupplementalReads.get('electronicSeal').errors.length, 0);
});
