// Shipping controls, fake clock and deidentified DOM. No external requests.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const start = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(start, name);
  const after = source.slice(start.index + start[0].length);
  const next = /^\n(?:async function|function|const|let|document\.|window\.)/m.exec(after);
  return source.slice(start.index, start.index + start[0].length + next.index);
}
class Node {
  constructor(id, classes = []) {
    this.id = id; this.dataset = {}; this.attributes = {}; this.classes = new Set(classes);
    this.inert = false; this.isConnected = true; this.scrollTop = 0; this.scrollLeft = 0;
    this.children = []; this.controls = []; this._text = ''; this.writes = 0;
    this.classList = { contains: c => this.classes.has(c), add: c => this.classes.add(c),
      remove: c => this.classes.delete(c), toggle: (c, on) => on ? this.classes.add(c) : this.classes.delete(c) };
  }
  set textContent(value) { this._text = value; this.writes++; }
  get textContent() { return this._text; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  toggleAttribute(name, on) { if (on) this.attributes[name] = ''; else delete this.attributes[name]; }
  getClientRects() { return [1]; }
  querySelectorAll() { return this.controls; }
  contains(node) { return node === this || this.controls.includes(node); }
  closest(selector) { return selector === '.nav-list' ? {} : null; }
  scrollTo({ top, left }) { this.scrollTop = top; this.scrollLeft = left; }
  focus() { this.document.activeElement = this; }
}
function harness() {
  const ids = ['toast', 'appShell', 'pageTitle', 'primarySidebar', 'mobileDrawerBackdrop', 'mobileMenuButton', 'topInfo', 'moduleTodoBadge', 'headerNotificationBadge', 'inboundModal', 'contractModal', 'officialDecisionModal'];
  const nodes = Object.fromEntries(ids.map(id => [id, new Node(id, id.endsWith('Modal') ? ['hidden'] : [])]));
  const routes = ['dashboard', 'compose', 'electronicSeal', 'approvalLog', 'inbound', 'settings'].map(id => new Node(id, id === 'dashboard' ? ['active'] : []));
  const nav = routes.map(r => { const n = new Node('nav-' + r.id); n.dataset.target = r.id; return n; });
  const document = { activeElement: nav[0], body: new Node('body'),
    getElementById: id => routes.find(r => r.id === id) || nodes[id],
    querySelector: selector => nodes[selector.slice(1)] || (selector.startsWith('.nav-item') ? nav[0] : null),
    querySelectorAll: selector => selector === '.view' ? routes : selector === '.nav-item' ? nav : selector === '.modal-backdrop:not(.hidden)' ? Object.values(nodes).filter(n => n.id.endsWith('Modal') && !n.classes.has('hidden')) : [],
  };
  for (const n of [...Object.values(nodes), ...routes, ...nav, document.body]) n.document = document;
  nodes.appShell.children = [nodes.primarySidebar, routes[0], nodes.mobileDrawerBackdrop];
  const timers = new Map(); let now = 0, timerId = 0;
  const c = { document, Date: { now: () => now }, Map, Set, String, Boolean, HTMLElement: Node,
    getComputedStyle: () => ({ visibility: 'visible' }),
    window: { setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, at: now + ms }); return id; }, clearTimeout: id => timers.delete(id), matchMedia: () => ({ matches: false }), requestAnimationFrame: fn => fn() },
    toastDismissTimer: null, toastDismissAt: 0, toastRemainingMs: 0,
    workspaceModalReturnFocus: new Map(), workspaceOverlayInertRecords: new Map(),
    routeScrollPositions: new Map(), routeScrollScope: '', activeRouteTarget: 'dashboard', scope: 'actor-a',
    frontendSessionScope: () => c.scope, isRouteAllowed: () => true, majorRouteForRoute: t => t,
    simpleRouteTitle: t => t, hasAuthenticatedBackendSession: () => false,
    scheduleOfficialDraftFontRerender() {}, prepareComposeDraftRecovery() {}, refreshWorkflowReadinessForContext() {},
    configureUploadedSealMode() {}, uploadedSealEditorRuntime: {}, companySealCompanies: [],
    openIntegratedPageSection() {}, loadRouteBackendData() {}, trackUiUsage() {},
    location: { hash: '#dashboard' }, history: { replaceState() {} }, activeRole: () => 'synthetic-role',
    authState: { user: { name: 'synthetic-user' } }, headerBackendSyncState: { status: 'idle' }, headerTodoCount: () => 2,
  };
  vm.createContext(c);
  vm.runInContext(['dismissToast', 'resumeToastDismissal', 'pauseToastDismissal', 'showToast', 'visibleWorkspaceModals', 'syncWorkspaceOverlayIsolation', 'workspaceModalFocusableItems', 'trapWorkspaceModalFocus', 'showWorkspaceModal', 'hideWorkspaceModal', 'mobileNavigationIsCompact', 'setView', 'updateHeaderStatus'].map(implementation).join('\n'), c);
  function advance(ms) { now += ms; for (const [id, timer] of timers) if (timer.at <= now) { timers.delete(id); timer.fn(); } }
  return { c, nodes, routes, nav, document, timers, advance };
}
test('latest toast owns its duration; identical messages do not rewrite the live region', () => {
  const h = harness(); h.c.showToast('first'); h.advance(3000); h.c.showToast('latest'); h.advance(1000);
  assert.equal(h.nodes.toast.classes.has('show'), true);
  assert.equal(h.nodes.toast.textContent, 'latest'); assert.equal(h.timers.size, 1);
  const writes = h.nodes.toast.writes; h.c.showToast('latest'); assert.equal(h.nodes.toast.writes, writes);
  h.advance(3999); assert.equal(h.nodes.toast.classes.has('show'), true);
  h.advance(1); assert.equal(h.nodes.toast.classes.has('show'), false);
});
test('toast pauses while reading and resumes only the remaining time', () => {
  const h = harness(); h.c.showToast('notice'); h.advance(1000); h.c.pauseToastDismissal(); h.advance(5000);
  assert.equal(h.nodes.toast.classes.has('show'), true); h.c.resumeToastDismissal(); h.advance(2999);
  assert.equal(h.nodes.toast.classes.has('show'), true); h.advance(1); assert.equal(h.nodes.toast.classes.has('show'), false);
});
test('same route retains scroll and input focus; returning restores position; new actor has no inherited position', () => {
  const h = harness(); h.routes[0].scrollTop = 420; h.document.activeElement = h.nav[0];
  h.c.setView('dashboard'); assert.equal(h.routes[0].scrollTop, 420); assert.equal(h.document.activeElement, h.nav[0]);
  h.c.setView('compose'); assert.equal(h.document.activeElement.id, 'pageTitle'); h.routes[1].scrollTop = 730;
  h.c.setView('dashboard'); assert.equal(h.routes[0].scrollTop, 420);
  h.c.setView('compose'); assert.equal(h.routes[1].scrollTop, 730);
  h.c.scope = 'actor-b'; h.c.setView('dashboard'); assert.equal(h.routes[0].scrollTop, 0);
  h.c.setView('compose'); assert.equal(h.routes[1].scrollTop, 0);
});
test('dialog isolates background children without changing auth inert gate and restores trigger focus', () => {
  const h = harness(); const modal = h.nodes.inboundModal, button = new Node('close'); button.document = h.document; modal.controls = [button];
  h.nodes.appShell.inert = true; h.c.showWorkspaceModal(modal);
  assert.equal(h.document.activeElement, button); assert.equal(h.nodes.primarySidebar.inert, true);
  h.c.hideWorkspaceModal(modal); assert.equal(h.nodes.primarySidebar.inert, false);
  assert.equal(h.nodes.appShell.inert, true); assert.equal(h.document.activeElement, h.nav[0]);
});
test('dialog Tab wraps, hidden controls are excluded, and reopening does not replace trigger', () => {
  const h = harness(); const modal = h.nodes.contractModal;
  const buttons = [new Node('first'), new Node('last')]; for (const b of buttons) b.document = h.document; modal.controls = buttons;
  h.c.showWorkspaceModal(modal); buttons[1].focus(); let prevented = false;
  h.c.trapWorkspaceModalFocus({ key: 'Tab', shiftKey: false, preventDefault() { prevented = true; } }, modal);
  assert.equal(prevented, true); assert.equal(h.document.activeElement, buttons[0]);
  h.c.showWorkspaceModal(modal); h.c.hideWorkspaceModal(modal); assert.equal(h.document.activeElement, h.nav[0]);
});
test('unchanged header state does not churn live region or counter text', () => {
  const h = harness(); h.c.updateHeaderStatus(); h.c.updateHeaderStatus();
  assert.equal(h.nodes.topInfo.writes, 1); assert.equal(h.nodes.moduleTodoBadge.writes, 1);
});
test('closing a decision dialog restores focus immediately and cannot steal a later route focus', () => {
  const h = harness();
  h.c.officialDecisionPreviousFocus = h.nav[0];
  h.c.officialDecisionState = { documentId: 'synthetic-document', action: 'approve' };
  h.nodes.officialDecisionModal.classList.remove('hidden');
  h.document.activeElement = h.nodes.officialDecisionModal;
  vm.runInContext(implementation('closeOfficialDecisionDialog'), h.c);
  h.c.closeOfficialDecisionDialog();
  assert.equal(h.document.activeElement, h.nav[0]);
  h.c.setView('compose'); h.advance(1);
  assert.equal(h.document.activeElement, h.nodes.pageTitle);
  assert.equal(h.timers.size, 0);
});
test('printing does not use a stale preview during composition or after a session change', async () => {
  const h = harness(); let composing = true, releaseFont, fontReads = 0;
  Object.assign(h.c, {
    composeInputIsComposing: () => composing,
    composeInputScope: () => h.c.scope,
    ensureOfficialDraftFontReady: () => { fontReads++; return new Promise(resolve => { releaseFont = resolve; }); },
  });
  vm.runInContext(implementation('printOfficialDraft'), h.c);
  await h.c.printOfficialDraft();
  assert.equal(fontReads, 0);
  assert.equal(h.nodes.toast.textContent, '請先完成文字輸入，再列印公文。');
  composing = false; const pending = h.c.printOfficialDraft();
  h.c.scope = 'actor-b'; releaseFont(true); await pending;
  assert.equal(fontReads, 1);
  // Any preview/print access would fail this minimal shipping-function harness.
});
test('same-account re-login does not coalesce or announce the old refresh result', async () => {
  const h = harness(), reads = [];
  h.c.authState.token = 'synthetic-session-a';
  Object.assign(h.c, {
    workspaceRefreshRequest: null, hasAuthenticatedBackendSession: () => true,
    activeRouteTarget: 'settings', syncNotificationsFromBackend: async () => true,
    loadRouteBackendData: () => new Promise(resolve => reads.push(resolve)),
    routeBackendDataErrors: new Map(), routeBackendDataLoaded: new Set(), renderWorkspaceLoadStatus() {},
  });
  vm.runInContext(implementation('refreshCurrentWorkspace'), h.c);
  const old = h.c.refreshCurrentWorkspace();
  h.c.authState.token = 'synthetic-session-b';
  const newer = h.c.refreshCurrentWorkspace();
  assert.equal(reads.length, 2);
  const newEntry = h.c.workspaceRefreshRequest;
  reads[0](true); assert.equal(await old, false);
  assert.equal(h.c.workspaceRefreshRequest, newEntry); assert.equal(h.c.headerBackendSyncState.status, 'syncing');
  assert.equal(h.nodes.toast.classes.has('show'), false);
  reads[1](false); assert.equal(await newer, false);
  assert.equal(h.c.headerBackendSyncState.status, 'error');
  assert.equal(h.nodes.toast.textContent, '部分資料更新失敗，已保留目前內容，請重試。');
});
