// Exercise shipping submission/error owners with synthetic records and no network.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  // A few legacy owners are redeclared; JavaScript uses the final declaration.
  const start = [...source.matchAll(new RegExp(`^(?:async )?function ${name}\\(`, 'gm'))].at(-1);
  assert.ok(start, `Shipping function ${name} exists`);
  const rest = source.slice(start.index + start[0].length);
  const next = /^\n(?:async )?function \w+\(/m.exec(rest);
  assert.ok(next, `Shipping function ${name} has a boundary`);
  return source.slice(start.index, start.index + start[0].length + next.index);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const tick = () => new Promise(setImmediate);
const ERROR_ID = 'ERR-0123456789ABCDEF01234567';
function failureResponse(code, status) {
  return { ok: false, status, text: async () => JSON.stringify({
    error: code, detail: code, errorId: ERROR_ID, retryable: false,
    submissionStatus: code === 'official_submission_validation_failed' ? 'not_submitted' : 'unknown',
  }) };
}

function harness(code = 'official_submission_validation_failed', status = 500) {
  const calls = [], toasts = [], audits = [], timers = new Set();
  let session = 'synthetic-user:session-1', navigations = 0, confirmations = 0;
  const nodes = new Map();
  const node = () => ({ textContent: '', attrs: {}, disabled: false, hidden: false,
    setAttribute(name, value) { this.attrs[name] = value; } });
  for (const id of ['uploadedEditorPreflightStatus', 'submitUploadedSealBtn',
    'uploadedEditorSubmitToolbarBtn', 'uploadedEditorBackToEditBtn',
    'uploadedEditorSubmissionSummary', 'uploadedPdfEditor']) nodes.set('#' + id, node());
  const runtime = {
    documentId: 'SYNTHETIC-DOCUMENT', revisionId: 'SYNTHETIC-REVISION',
    preparedFileId: 'SYNTHETIC-PREPARED', preparedSha256: 'b'.repeat(64),
    preparedPdfDocument: {}, reviewMode: 'prepared', locked: false,
    savedGeneration: 1, dirtyGeneration: 1,
  };
  const application = {
    epoch: 0, contentRevision: 2, submissionBusy: false, submissionOperation: null,
    submissionPreview: null, manualSaveOperation: null, conflict: false,
  };
  const state = {
    revisionNo: 3, manifestSha256: 'a'.repeat(64),
    sourceFiles: [{ assetId: 'SYNTHETIC-PDF', fileName: 'synthetic.pdf' }],
    pages: [{ pageId: 'p1', sourceAssetId: 'SYNTHETIC-PDF' }],
    elements: [{ id: 'SYNTHETIC-SEAL', kind: 'seal', pageId: 'p1', x: 12, y: 20 },
      { id: 'SYNTHETIC-TEXT', kind: 'text', properties: { text: 'Retained synthetic edit' } }],
  };
  const h = { calls, toasts, audits, timers, nodes, runtime, application, state,
    get navigations() { return navigations; }, get confirmations() { return confirmations; },
    respond: async () => failureResponse(code, status),
    replaceScope() {
      session = 'synthetic-user:session-2'; application.epoch += 1;
      runtime.documentId = 'SYNTHETIC-NEW-DOCUMENT';
      application.submissionOperation = { newer: true };
      application.submissionBusy = true;
      nodes.get('#uploadedEditorPreflightStatus').textContent = 'New document status';
    },
  };
  const c = {
    console, AbortController, encodeURIComponent, PDF_A4_INVALID_MESSAGE: 'Synthetic A4 validation message',
    setTimeout(fn, ms) { const timer = setTimeout(fn, ms); timers.add(timer); return timer; },
    clearTimeout(timer) { timers.delete(timer); clearTimeout(timer); },
    document: { querySelector: selector => nodes.get(selector) || null },
    backendApiBase: '/api', authState: { token: '' }, isHeaderSafeToken: () => false,
    fetch: async (url, options) => { calls.push({ url, options }); return h.respond(); },
    uploadedSealEditorRuntime: runtime, uploadedSealApplicationRuntime: application,
    uploadedSealEditorState: state, uploadedSealMode: 'seal',
    frontendSessionScope: () => session,
    uploadedSealCatalogReady: () => true, uploadedSealCatalogMessage: () => '',
    approvalSelectionForSelect: () => ({ documentCategory: 'synthetic-category', approvalRouteCode: 'A' }),
    uploadedSealApplicationKey: () => 'synthetic-application-key',
    uploadedSealApplicationHasUnsavedChanges: () => false,
    syncUploadedSealApplicationDraft: async () => {},
    loadOfficialWorkflowReadiness: async () => ({ ready: true }),
    workflowReadinessAllowsSubmit: () => true,
    workflowReadinessSelection: () => ({}),
    officialWorkflowReadinessByRoute: new Map(), workflowReadinessCacheKey: () => 'synthetic',
    uploadedSealCompanyRecords: () => [{ id: 'SYNTHETIC-SEAL' }], companySealSelectable: () => true,
    renderUploadedEditorDraftSaveActions() {},
    renderUploadedSealWorkbench() { c.renderUploadedEditorSubmissionActions(); },
    uploadedEditorSubmissionSummaryText: () => 'Synthetic confirmation summary',
    requestWorkspaceConfirmation: async () => { confirmations += 1; return true; },
    setUploadedEditorSaveStatus() {},
    showSubmittedOfficialDocument: async () => { navigations += 1; },
    renderUploadedSealApplicationSaveStatus() {},
    handleUploadedEditorConflict() {},
    addSealAudit: (...args) => audits.push(args), showToast: message => toasts.push(message),
  };
  vm.createContext(c);
  vm.runInContext(['fetchWithDeadline', 'backendRequest', 'friendlyBackendErrorMessage',
    'uploadedSealApplicationScopeSnapshot', 'uploadedSealApplicationScopeIsCurrent',
    'uploadedEditorSubmissionFingerprint', 'uploadedEditorSubmissionPreviewIsCurrent',
    'invalidateUploadedEditorSubmissionPreview', 'renderUploadedEditorSubmissionActions',
    'submitUploadedSealApplication'].map(implementation).join('\n'), c);
  application.submissionPreview = c.uploadedEditorSubmissionFingerprint();
  h.c = c;
  return h;
}

test('known atomic validation rejection is localized before the generic 500 message', () => {
  const h = harness();
  const message = h.c.friendlyBackendErrorMessage('official_submission_validation_failed', 500);
  assert.match(message, /尚未送出/);
  assert.match(message, /內容與文件已保留/);
  assert.match(message, /不需重新上傳/);
  assert.doesNotMatch(message, /稍後再試/);
});

test('unknown commit outcome directs the user to records without claiming no submission', () => {
  const h = harness();
  const message = h.c.friendlyBackendErrorMessage('official_document_submit_commit_state_unknown', 503);
  assert.match(message, /尚未確認送簽結果/);
  assert.match(message, /簽核紀錄查看案件狀態/);
  assert.match(message, /勿重複送出/);
  assert.doesNotMatch(message, /尚未送出：|稍後再試/);
});

test('transport preserves both fixed error codes and support IDs without replaying POST', async () => {
  for (const [code, status] of [['official_submission_validation_failed', 500],
    ['official_document_submit_commit_state_unknown', 503]]) {
    const h = harness(code, status);
    await assert.rejects(h.c.backendRequest('/official-documents/SYNTHETIC-DOCUMENT/submit',
      { method: 'POST', body: '{}' }), error => {
      assert.equal(error.code, code); assert.equal(error.detail, code);
      assert.equal(error.status, status); assert.equal(error.errorId, ERROR_ID);
      assert.equal(error.retryable, false); assert.ok(error.message.includes(ERROR_ID));
      assert.doesNotMatch(error.message, /系統暫時無法完成操作/);
      return true;
    });
    await tick();
    assert.equal(h.calls.length, 1); assert.equal(h.calls[0].options.method, 'POST');
    assert.equal(h.timers.size, 0);
  }
});

test('validation rejection leaves a persistent accessible status and retains all draft content', async () => {
  const h = harness(), original = structuredClone(h.state);
  const originalRevision = h.runtime.revisionId, originalPrepared = h.runtime.preparedFileId;
  await h.c.submitUploadedSealApplication();
  const status = h.nodes.get('#uploadedEditorPreflightStatus');
  assert.match(status.textContent, /尚未送出/); assert.match(status.textContent, /已保留/);
  assert.ok(status.textContent.includes(ERROR_ID)); assert.equal(status.attrs.role, 'status');
  const retainedStatus = status.textContent;
  h.c.renderUploadedEditorSubmissionActions(); await tick();
  assert.equal(status.textContent, retainedStatus, 'rendering must not erase the error after the toast');
  assert.deepEqual(h.state, original); assert.equal(h.runtime.revisionId, originalRevision);
  assert.equal(h.runtime.preparedFileId, originalPrepared); assert.equal(h.runtime.locked, false);
  assert.equal(h.application.submissionBusy, false); assert.equal(h.application.submissionOperation, null);
  assert.equal(h.navigations, 0); assert.equal(h.calls.length, 1); assert.equal(h.timers.size, 0);
  assert.ok(!h.toasts.some(message => message.includes('已鎖定並送出')));
});

test('unknown commit status remains visible and does not automatically resubmit or claim success', async () => {
  const h = harness('official_document_submit_commit_state_unknown', 503);
  await h.c.submitUploadedSealApplication();
  const status = h.nodes.get('#uploadedEditorPreflightStatus');
  assert.match(status.textContent, /尚未確認送簽結果/);
  assert.match(status.textContent, /簽核紀錄/); assert.match(status.textContent, /勿重複送出/);
  h.c.renderUploadedEditorSubmissionActions(); await tick();
  assert.match(status.textContent, /勿重複送出/);
  assert.equal(h.calls.length, 1); assert.equal(h.navigations, 0); assert.equal(h.runtime.locked, false);
  assert.equal(h.application.submissionBusy, false); assert.equal(h.timers.size, 0);
});

test('a second click during a pending submission cannot issue another mutation', async () => {
  const h = harness(), gate = deferred(); h.respond = () => gate.promise;
  const first = h.c.submitUploadedSealApplication(); await tick();
  assert.equal(h.calls.length, 1); assert.equal(h.application.submissionBusy, true);
  await h.c.submitUploadedSealApplication();
  assert.equal(h.calls.length, 1); assert.equal(h.confirmations, 1);
  gate.resolve(failureResponse('official_submission_validation_failed', 500)); await first;
  assert.equal(h.calls.length, 1); assert.equal(h.application.submissionBusy, false);
});

test('late failure from an old document or session cannot pollute the new screen', async () => {
  const h = harness(), gate = deferred(); h.respond = () => gate.promise;
  const pending = h.c.submitUploadedSealApplication(); await tick();
  h.replaceScope(); const newOperation = h.application.submissionOperation;
  gate.resolve(failureResponse('official_submission_validation_failed', 500)); await pending;
  assert.equal(h.nodes.get('#uploadedEditorPreflightStatus').textContent, 'New document status');
  assert.equal(h.application.submissionOperation, newOperation);
  assert.equal(h.application.submissionBusy, true, 'the old finally must not clear the new operation');
  assert.equal(h.toasts.length, 0); assert.equal(h.audits.length, 0); assert.equal(h.navigations, 0);
  assert.equal(h.calls.length, 1); assert.equal(h.timers.size, 0);
});

test('a fresh 403 remains a permissions error instead of being mislabeled as validation failure', async () => {
  const h = harness('forbidden', 403);
  await h.c.submitUploadedSealApplication();
  assert.match(h.nodes.get('#uploadedEditorPreflightStatus').textContent, /沒有權限/);
  assert.doesNotMatch(h.nodes.get('#uploadedEditorPreflightStatus').textContent, /系統送簽資料驗證失敗/);
  assert.equal(h.runtime.locked, false); assert.equal(h.calls.length, 1);
});
