// Shipping decision/recovery functions; synthetic state and controlled HTTP only.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const start = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(start, name);
  const end = source.indexOf('\n}\n', start.index);
  return source.slice(start.index, end + 2);
}
const tick = () => new Promise(setImmediate);
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const stale = (status = 403, detail = 'not_current_official_document_approver') => Object.assign(new Error(detail), { status, detail });
const latest = () => ({ id: 'A', current_status: 'pending', current_step: 'director', current_step_name: '主任簽核', can_act: false, available_actions: [], approval_steps: [{ id: 'NEW', step_key: 'director', status: 'pending', approver_name: '合成主任' }] });
function harness() {
  const nodes = new Map(), calls = [], renders = [], toasts = [];
  function node(id = '') {
    if (id && nodes.has(id)) return nodes.get(id);
    const n = { id, value: '', textContent: '', hidden: false, disabled: false, checked: false, dataset: {}, children: [], handlers: {},
      classList: { add() {}, remove() {}, toggle() {} },
      querySelector(selector) { return selector === 'h4' ? node('heading') : nodes.get(selector.replace(/^#/, '')) || null; },
      querySelectorAll() { return this.children; },
      replaceChildren() { this.children = []; this.textContent = ''; },
      addEventListener(name, handler) { this.handlers[name] = handler; },
      prepend(child) { nodes.set(child.id, child); this.children.unshift(child); },
      remove() { nodes.delete(this.id); }, focus() { this.focused = true; },
      set innerHTML(value) { this.html = value; for (const match of value.matchAll(/id="([^"]+)"/g)) node(match[1]); },
      get innerHTML() { return this.html || ''; }
    };
    if (id) nodes.set(id, n);
    return n;
  }
  for (const id of ['officialDecisionForm', 'officialDecisionSubmitBtn', 'officialDecisionCancelBtn', 'officialDecisionRequirements', 'officialDecisionModalTitle', 'officialDecisionError', 'officialDecisionSummary', 'officialDecisionEvidence', 'officialDecisionEvidenceActions', 'officialApprovalReviewFields', 'officialRejectionFields', 'officialWorkflowActionFields', 'officialApprovalComment', 'officialRejectComment', 'officialWithdrawComment', 'officialReviewOriginal', 'officialReviewAttachments', 'officialReviewEdited', 'officialRejectCategory', 'officialCorrectionDueDate']) node(id);
  for (const id of ['officialReviewOriginal', 'officialReviewAttachments', 'officialReviewEdited']) { Object.assign(node(id), { type: 'checkbox', checked: true }); node('officialApprovalReviewFields').children.push(node(id)); }
  node('officialApprovalComment').value = '合成未送出意見'; node('officialRejectComment').value = '請補齊合成附件'; node('officialRejectCategory').value = 'other';
  node('officialDecisionEvidence').dataset.applicationReviewed = 'true';
  node('officialDecisionSummary').textContent = '合成案件私密摘要';
  const item = { id: 'A', can_act: true, available_actions: ['approve', 'reject'], current_step: 'manager', current_status: 'pending', content_revision: 1,
    approval_steps: [{ id: 'OLD', step_key: 'manager', status: 'pending' }], prepared_sha256: 'prepared-v1', manifest_sha256: 'manifest-v1' };
  const c = { console, URLSearchParams, Map, Set, Promise, Error, encodeURIComponent, crypto: { randomUUID: () => `op-${++c.sequence}` }, sequence: 0,
    actor: 'synthetic-actor', authState: { token: 'synthetic-token' }, frontendSessionScope: () => c.actor,
    officialWorkflowItems: [item], homeOfficialCases: { items: [item] },
    officialDocumentDetailReady: new Set(['A']), officialDocumentDetailRequests: new Map([['A', Promise.resolve(item)]]),
    officialCaseNavigation: { id: 'A', generation: 1, detail: item, controller: { abort() { c.aborted = true; } } },
    selectedOfficialDocumentId: 'A', selectedWorkflowTaskId: 'A',
    officialDecisionState: { documentId: 'A', action: 'approve', source: 'approvalLog', operationId: 'opened-op', scope: 'synthetic-actor', token: 'synthetic-token', expectedStepId: 'OLD', expectedContentRevision: 1, integrity: { preparedSha256: 'prepared-v1', manifestSha256: 'manifest-v1' }, busy: false },
    document: { querySelector: selector => nodes.get(selector.replace(/^#/, '')) || null, querySelectorAll: () => [], createElement: () => node() },
    officialDecisionIntegrity: entry => ({ preparedSha256: entry.prepared_sha256, manifestSha256: entry.manifest_sha256 }),
    officialStatusLabels: { pending: '待簽核' }, officialDecisionPendingRequirements: () => [], isValidFutureOrToday: () => true,
    showToast: message => toasts.push(message),
    closeOfficialDecisionDialog() { c.officialDecisionState = { documentId: '', operationId: '' }; },
    clearOfficialCaseNavigation() { c.officialCaseNavigation = { id: '', generation: 9, detail: null }; },
    writeWorkspaceCaseRoute() {}, setView() {}, closeApprovalLogMobileDetail() {},
    async openOfficialCaseFromNavigation(id) { c.opened = id; },
    async backendRequest(url, options) { calls.push({ url, options }); if (options?.method === 'POST') throw stale(); return latest(); },
  };
  for (const name of ['renderOfficialWorkflow', 'renderApprovalLog', 'renderElectronicSealWorkQueue', 'refreshDashboardWorkEntryPoints', 'renderHomeMyCases']) c[name] = () => renders.push(name);
  vm.createContext(c);
  for (const name of ['officialDocumentAvailableActions', 'officialStatusLabel', 'officialApprovalStepActor', 'officialDecisionEvidenceReady', 'officialDecisionEvidenceComplete', 'officialDecisionReviewAcknowledgements', 'markOfficialDecisionEvidenceReviewed', 'updateOfficialDecisionSubmitAvailability', 'officialDecisionRecoveryKind', 'invalidateOfficialDecisionCase', 'renderOfficialDecisionRecovery', 'reloadOfficialDecisionRecovery', 'recoverOfficialDecision', 'mutateOfficialDocument', 'submitOfficialDecision']) vm.runInContext(implementation(name), c);
  return { c, item, nodes, calls, renders, toasts, submit: () => c.submitOfficialDecision({ preventDefault() {} }) };
}

test('conflict taxonomy is exact; generic 403/422 are never claimed as another approval', () => {
  const { c } = harness();
  assert.equal(c.officialDecisionRecoveryKind(stale()), 'conflict');
  assert.equal(c.officialDecisionRecoveryKind(stale(409, 'revision_changed')), 'conflict');
  for (const code of ['official_document_approval_already_claimed', 'official_document_not_pending_approval', 'official_document_current_step_not_pending']) assert.equal(c.officialDecisionRecoveryKind(stale(422, code)), 'conflict');
  assert.equal(c.officialDecisionRecoveryKind(stale(403, 'forbidden')), 'forbidden');
  assert.equal(c.officialDecisionRecoveryKind(stale(422, 'missing_evidence')), '');
  assert.equal(c.officialDecisionRecoveryKind(stale(503, 'unavailable')), '');
});

test('stale 403 stops once, resets evidence and shows authoritative status/next actor with own unsent comment', async () => {
  const h = harness(); await h.submit();
  assert.deepEqual(h.calls.map(x => x.options?.method || 'GET'), ['POST', 'GET']);
  assert.equal(h.c.officialDecisionState.recovery.status, 'ready');
  assert.equal(h.c.officialDecisionState.expectedStepId, '');
  assert.equal(h.c.officialDecisionState.integrity, null);
  assert.equal(h.c.officialDocumentDetailRequests.has('A'), false);
  assert.equal(h.c.officialCaseNavigation.detail.current_step, 'director');
  assert.match(h.nodes.get('officialDecisionRecoveryStatus').textContent, /待處理：合成主任/);
  assert.doesNotMatch(h.nodes.get('officialDecisionRecoveryStatus').textContent, /已由：/);
  assert.equal(h.nodes.get('officialDecisionUnsentComment').value, '合成未送出意見');
  assert.equal(h.nodes.get('officialDecisionSummary').textContent, '');
  for (const id of ['officialReviewOriginal', 'officialReviewAttachments', 'officialReviewEdited']) { assert.equal(h.nodes.get(id).checked, false); assert.equal(h.nodes.get(id).disabled, true); }
  assert.equal(h.nodes.get('officialDecisionSubmitBtn').disabled, true);
  assert.equal(h.nodes.get('officialDecisionSubmitBtn').hidden, true);
  assert.equal(h.c.officialDecisionEvidenceComplete(), false);
  h.c.markOfficialDecisionEvidenceReviewed('application');
  assert.equal(h.c.officialDecisionEvidenceComplete(), false);
  await h.submit(); assert.equal(h.calls.length, 2);
  // Closing does not let a stale row regain actions.
  h.c.closeOfficialDecisionDialog();
  assert.deepEqual(Array.from(h.c.officialDocumentAvailableActions({ ...h.item, can_act: true, available_actions: ['approve'] })), []);
});

test('refresh failure keeps decision stopped; retry is GET-only and then exposes latest record', async () => {
  const h = harness(); let fail = true;
  h.c.backendRequest = async (url, options) => { h.calls.push({ url, options }); if (options) throw stale(409); if (fail) throw stale(503); return latest(); };
  await h.submit(); assert.equal(h.c.officialDecisionState.recovery.status, 'failed');
  assert.equal(h.nodes.get('officialDecisionRecoveryRetryBtn').hidden, false);
  assert.equal(h.nodes.get('officialDecisionRecoveryOpenBtn').hidden, true);
  await h.submit(); assert.equal(h.calls.length, 2);
  fail = false; await h.c.reloadOfficialDecisionRecovery();
  assert.deepEqual(h.calls.map(x => x.options?.method || 'GET'), ['POST', 'GET', 'GET']);
  assert.equal(h.c.officialDecisionState.recovery.status, 'ready');
  assert.equal(h.nodes.get('officialDecisionUnsentComment').value, '合成未送出意見');
});

test('generic mutation 403 does not GET, reuse sensitive summary, or permit a stale case action', async () => {
  const h = harness(); h.c.backendRequest = async (url, options) => { h.calls.push({ url, options }); throw stale(403, 'access_denied'); };
  await h.submit(); assert.equal(h.calls.length, 1);
  assert.equal(h.c.officialDecisionState.recovery.status, 'forbidden');
  assert.equal(h.c.officialWorkflowItems.length, 0); assert.equal(h.c.homeOfficialCases.items.length, 0);
  assert.equal(h.c.officialCaseNavigation.detail, null);
  assert.equal(h.c.officialDocumentDetailReady.has('A'), false);
  assert.equal(h.nodes.get('officialDecisionSummary').textContent, '');
  assert.equal(h.nodes.get('officialDecisionRecoveryOpenBtn').hidden, true);
  await h.c.reloadOfficialDecisionRecovery(); assert.equal(h.calls.length, 1);
});

test('an old home request cannot reintroduce a case denied during the request', async () => {
  const h = harness(), gate = deferred();
  vm.runInContext(implementation('loadHomeOfficialCases'), h.c);
  h.c.backendRequest = async (url, options) => { if (options) throw stale(403, 'access_denied'); return gate.promise; };
  const home = h.c.loadHomeOfficialCases();
  await h.submit(); assert.equal(h.c.officialDecisionState.recovery.status, 'forbidden');
  gate.resolve({ items: [{ id: 'A', subject: 'private old summary' }, { id: 'allowed' }] }); await home;
  assert.deepEqual(Array.from(h.c.homeOfficialCases.items, item => item.id), ['allowed']);
});

test('recovery GET forbidden or wrong ID never installs another or denied case', async () => {
  for (const forbidden of [true, false]) {
    const h = harness(); h.c.backendRequest = async (url, options) => { if (options) throw stale(); if (forbidden) throw stale(403, 'no_view'); return { ...latest(), id: 'B' }; };
    await h.submit(); assert.equal(h.c.officialWorkflowItems.length, 0);
    assert.equal(h.c.officialCaseNavigation.detail, null);
    assert.equal(h.c.officialDecisionState.recovery.status, forbidden ? 'forbidden' : 'failed');
  }
});

test('ordinary validation and transient mutation failures preserve comment without mislabeling permission or success', async () => {
  for (const status of [422, 503]) {
    const h = harness(); h.c.backendRequest = async (url, options) => { h.calls.push({ url, options }); throw stale(status, 'synthetic failure'); };
    await h.submit(); assert.equal(h.calls.length, 1); assert.equal(h.c.officialDecisionState.recovery, undefined);
    assert.equal(h.nodes.get('officialApprovalComment').value, '合成未送出意見');
    assert.equal(h.nodes.get('officialDecisionError').hidden, false);
    assert.equal(h.c.officialDecisionState.busy, false);
  }
});

test('opening step and hashes are pinned; changed step/revision/hash or absent capability causes zero POST', async () => {
  const changes = [h => { h.item.approval_steps[0].id = 'NEW'; }, h => { h.item.content_revision = 2; }, h => { h.item.prepared_sha256 = 'prepared-v2'; }, h => { h.item.manifest_sha256 = 'manifest-v2'; }, h => { h.item.available_actions = []; h.item.can_act = false; }, h => { h.c.officialWorkflowItems = []; }];
  for (const change of changes) {
    const h = harness(); change(h); await h.submit();
    assert.equal(h.calls.filter(x => x.options?.method === 'POST').length, 0);
    assert.equal(h.c.officialDecisionState.recovery.status, 'ready');
    assert.equal(h.nodes.get('officialDecisionUnsentComment').value, '合成未送出意見');
  }
});

test('approve and correction always send the opening expected step', async () => {
  for (const action of ['approve', 'reject']) {
    const h = harness(); h.c.officialDecisionState.action = action;
    h.c.backendRequest = async (url, options) => { h.calls.push({ url, options }); return latest(); };
    await h.submit(); assert.equal(h.calls.length, 1);
    assert.equal(JSON.parse(h.calls[0].options.body).expected_step_id, 'OLD');
    assert.equal(JSON.parse(h.calls[0].options.body).prepared_sha256, 'prepared-v1');
  }
});

test('late mutation success or error cannot change a new case, reopened same case, or renewed token', async () => {
  for (const change of ['case', 'reopen', 'token', 'actor']) for (const ok of [true, false]) {
    const h = harness(), gate = deferred(); h.c.backendRequest = () => gate.promise;
    const running = h.c.mutateOfficialDocument('approve', { expected_step_id: 'OLD', comment: 'comment' }, h.item);
    if (change === 'token') h.c.authState.token = 'new-token';
    else if (change === 'actor') h.c.actor = 'new-actor';
    else h.c.officialDecisionState = { documentId: change === 'case' ? 'B' : 'A', operationId: 'new-dialog' };
    h.c.selectedOfficialDocumentId = 'B';
    if (ok) gate.resolve(latest()); else gate.reject(stale());
    assert.equal(await running, false); assert.equal(h.c.selectedOfficialDocumentId, 'B');
    assert.equal(h.c.officialDecisionState.recovery, undefined); assert.equal(h.renders.length, 0); assert.equal(h.toasts.length, 0);
  }
});

test('late recovery GET cannot refill another case or a new authorization session', async () => {
  for (const change of ['case', 'reopen', 'token', 'actor']) for (const ok of [true, false]) {
    const h = harness(), gate = deferred();
    h.c.backendRequest = async (url, options) => { if (options) throw stale(); return gate.promise; };
    const running = h.submit(); await tick();
    assert.equal(h.c.officialDecisionState.recovery.status, 'loading');
    if (change === 'token') h.c.authState.token = 'new-token';
    else if (change === 'actor') h.c.actor = 'new-actor';
    else h.c.officialDecisionState = { documentId: change === 'case' ? 'B' : 'A', operationId: 'new-dialog' };
    h.c.officialWorkflowItems = [{ id: 'B' }]; h.c.officialCaseNavigation = { id: 'B', detail: { id: 'B' } };
    h.renders.length = 0;
    if (ok) gate.resolve(latest()); else gate.reject(stale(403));
    await running; assert.equal(h.c.officialWorkflowItems[0].id, 'B');
    assert.equal(h.c.officialCaseNavigation.detail.id, 'B'); assert.equal(h.renders.length, 0);
  }
});

test('actual hashchange handler closes the old decision before restoring browser history', () => {
  const listener = source.slice(source.indexOf('window.addEventListener("hashchange"'), source.indexOf('\n});', source.indexOf('window.addEventListener("hashchange"')) + 4);
  const calls = [];
  const c = { officialDecisionState: { documentId: 'A' }, window: { addEventListener(name, callback) { c.listener = callback; } },
    closeOfficialDecisionDialog() { calls.push('close'); c.officialDecisionState = { documentId: '' }; }, hasAuthenticatedBackendSession: () => true,
    restoreWorkspaceCaseRoute() { calls.push('restore'); assert.equal(c.officialDecisionState.documentId, ''); } };
  vm.createContext(c); vm.runInContext(listener, c); c.listener();
  assert.deepEqual(calls, ['close', 'restore']);
});
