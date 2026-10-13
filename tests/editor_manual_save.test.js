// Execute the real manual-save, metadata and revision-CAS owners without
// network, credentials, production records, original PDFs or Seal Vault files.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');

function implementation(name) {
  const match = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(match, name);
  const remainder = source.slice(match.index + match[0].length);
  const next = /^\n(?:async )?function \w+\(/m.exec(remainder);
  assert.ok(next, name);
  return source.slice(match.index, match.index + match[0].length + next.index);
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function tick() { await new Promise(setImmediate); }

function harness() {
  const fields = { company_id: 'SYNTHETIC-CO', title: 'Synthetic title', description: 'Synthetic reason',
    request_reason: 'Synthetic reason', handler_name: 'Test actor', dispatch_unit: 'Test department',
    applicant_department_id: 'SYNTHETIC-UNIT', applicant_department_name: 'Test department', document_category: 'test_document' };
  const nodes = new Map();
  for (const id of ['uploadedEditorSaveDraftBtn', 'uploadedEditorSaveDraftFooterBtn']) {
    nodes.set('#' + id, { disabled: true, title: '', attrs: {}, setAttribute(key, value) { this.attrs[key] = value; } });
  }
  nodes.set('#uploadedSealTitle', { get value() { return fields.title; } });
  nodes.set('#uploadedSealDepartment', { get value() { return fields.dispatch_unit; } });
  const fallbackNode = { toggleAttribute() {} };
  const statuses = [], toasts = [], calls = [], timers = new Map();
  let timerId = 0, serverRevision = 1, session = 'synthetic-actor:scope-a';
  const runtime = { documentId: 'SYNTHETIC-DOC', revisionId: 'SYNTHETIC-REV-1', baseManifestSha256: 'initial',
    locked: false, uploading: false, saving: false, savePromise: null, saveQueued: false,
    dirtyGeneration: 0, savedGeneration: 0, currentPageId: 'p1', selectedIds: new Set() };
  const application = { documentId: runtime.documentId, epoch: 0, contentRevision: 0, companyId: fields.company_id,
    editable: true, metadataEditable: true, companyEditable: true, composing: false,
    conflict: false, promise: null, timer: 0, retryCount: 0, error: '', manualSaveOperation: null };
  const state = { schemaVersion: 2, revisionNo: 1, manifestSha256: 'initial', sourceFiles: [], pages: [{ pageId: 'p1' }],
    elements: [{ id: 'text1', kind: 'text', pageId: 'p1', x: 10, properties: { text: 'Synthetic PDF text' } }] };
  const context = {
    uploadedSealEditorRuntime: runtime, uploadedSealApplicationRuntime: application, uploadedSealEditorState: state,
    frontendSessionScope: () => session, PDF_EDITOR_SCHEMA_VERSION: 2, navigator: { onLine: true },
    workspaceComposingControls: new WeakSet(),
    document: { activeElement: {}, querySelector: selector => nodes.get(selector) || fallbackNode },
    window: { clearTimeout: id => timers.delete(id), setTimeout: fn => { timers.set(++timerId, fn); return timerId; } },
    editorDraftPayload: () => ({ ...fields }), approvalSelectionForSelect: () => ({ documentCategory: fields.document_category }),
    cloneUploadedEditorValue: value => structuredClone(value),
    normalizeUploadedEditorSealGeometry: () => false,
    calculateUploadedEditorManifest: async snapshot => JSON.stringify(snapshot.elements),
    setUploadedEditorSaveStatus: (...args) => statuses.push(args), showToast: message => toasts.push(message),
    finishUploadedEditorTextEdit: () => !runtime.textEdit?.composing,
    finishUploadedEditorPointerAction: () => {
      if (runtime.pointerAction) { runtime.pointerAction = null; runtime.dirtyGeneration += 1; }
    },
    syncLegacyUploadedEditorCollections() {}, renderUploadedEditorSvgLayer() {}, renderUploadedEditorProperties() {},
    renderUploadedSealWorkbench() { context.renderUploadedEditorDraftSaveActions(); },
    renderUploadedEditorSubmissionActions() { context.renderUploadedEditorDraftSaveActions(); },
    renderUploadedSealApplicationSaveStatus() {}, renderElectronicSealWorkQueue() {},
    rememberUploadedEditorSavedSealBindings() {}, emptyUploadedSealEditorState: () => ({ pages: [], elements: [] }),
    officialWorkflowItems: [{ id: runtime.documentId }], invalidateUploadedEditorSubmissionPreview() {},
    invalidateUploadedEditorApplicationReview() {},
    handleUploadedEditorConflict() { runtime.conflict = {}; },
    backendRequest: async (url, options) => {
      const body = JSON.parse(options.body);
      calls.push({ url, method: options.method, headers: options.headers, body });
      const gateResult = await h.beforeResponse?.(calls.at(-1), calls.length);
      if (gateResult !== undefined) return gateResult;
      if (options.method === 'PATCH') return {
        company_id: body.company_id, content_revision: body.expected_content_revision + 1,
        application_metadata_editable: true, application_company_editable: true,
        editor_revision: { id: runtime.revisionId, manifestSha256: context.uploadedSealEditorState.manifestSha256, state: context.uploadedSealEditorState },
        editor_state: context.uploadedSealEditorState,
      };
      const revisionNo = ++serverRevision;
      return { revisionNo, revision_id: 'SYNTHETIC-REV-' + revisionNo, manifestSha256: body.manifestSha256,
        state: { ...body.state, revisionNo, manifestSha256: body.manifestSha256 } };
    },
  };
  vm.createContext(context);
  const names = ['uploadedSealApplicationPatch', 'uploadedSealApplicationKey', 'uploadedSealApplicationHasUnsavedChanges',
    'uploadedSealApplicationMetadataReadOnly', 'uploadedSealApplicationScopeSnapshot', 'uploadedSealApplicationScopeIsCurrent',
    'applyEditorRevisionFromResponse', 'applyUploadedEditorCanonicalSaveResponse',
    'saveUploadedEditorState', 'syncUploadedSealApplicationDraft', 'uploadedEditorDraftSaveIssue',
    'renderUploadedEditorDraftSaveActions', 'saveUploadedEditorDraft'];
  vm.runInContext(names.map(implementation).join('\n'), context);
  application.savedKey = context.uploadedSealApplicationKey();
  const h = { context, runtime, application, state, fields, nodes, statuses, toasts, calls, timers,
    replaceScope() {
      session = 'synthetic-actor:scope-b'; application.epoch += 1;
      runtime.documentId = 'SYNTHETIC-NEW-DOC';
      application.manualSaveOperation = { scope: context.uploadedSealApplicationScopeSnapshot(), new: true };
    } };
  return h;
}

test('both visible save entries use the same availability and busy owner without a seal prerequisite', () => {
  const h = harness();
  h.context.renderUploadedEditorDraftSaveActions();
  assert.ok([...h.nodes.values()].slice(0, 2).every(button => !button.disabled && button.attrs['aria-busy'] === 'false'));
  h.runtime.documentId = '';
  h.context.renderUploadedEditorDraftSaveActions();
  assert.ok([...h.nodes.values()].slice(0, 2).every(button => button.disabled && /PDF/.test(button.title)));
});

test('manual save commits the newest application and PDF through the real CAS owners', async () => {
  const h = harness();
  h.fields.title = 'Newest application title';
  h.state.elements[0].properties.text = 'Newest PDF text'; h.runtime.dirtyGeneration = 1;
  assert.equal(await h.context.saveUploadedEditorDraft(), true);
  assert.deepEqual(h.calls.map(call => call.method), ['PUT', 'PATCH', 'PUT']);
  assert.equal(h.calls[0].body.state.elements[0].properties.text, 'Newest PDF text');
  assert.equal(h.calls[1].body.title, 'Newest application title');
  assert.equal(h.calls[1].body.expected_editor_revision_id, 'SYNTHETIC-REV-2');
  assert.equal(h.calls[2].body.expected_content_revision, 1);
  assert.equal(h.application.savedKey, h.context.uploadedSealApplicationKey());
  assert.equal(h.runtime.savedGeneration, h.runtime.dirtyGeneration);
  assert.equal(h.toasts.at(-1), '草稿已暫存');
  assert.ok(!h.statuses.some(status => status[1] === '送簽前同步中'));
});

test('manual save prevents duplicate activation and exposes busy state in both entries', async () => {
  const h = harness(), gate = deferred();
  h.beforeResponse = () => gate.promise;
  const first = h.context.saveUploadedEditorDraft(); await tick();
  assert.equal(await h.context.saveUploadedEditorDraft(), false);
  assert.equal(h.calls.length, 1);
  for (const id of ['uploadedEditorSaveDraftBtn', 'uploadedEditorSaveDraftFooterBtn']) {
    assert.equal(h.nodes.get('#' + id).disabled, true);
    assert.equal(h.nodes.get('#' + id).attrs['aria-busy'], 'true');
  }
  gate.resolve(); assert.equal(await first, true);
  assert.equal(h.application.manualSaveOperation, null);
  assert.equal(h.nodes.get('#uploadedEditorSaveDraftBtn').disabled, false);
});

test('offline, locked, pending upload, conflict and IME cannot write or claim saved', async () => {
  const conditions = [
    h => { h.context.navigator.onLine = false; }, h => { h.runtime.locked = true; },
    h => { h.application.submissionBusy = true; }, h => { h.runtime.uploading = true; },
    h => { h.runtime.finalizingAsset = true; }, h => { h.runtime.finalizationError = true; },
    h => { h.runtime.pendingFinalization = {}; }, h => { h.runtime.pendingEditorSave = true; },
    h => { h.runtime.draftCreatePromise = Promise.resolve(); }, h => { h.runtime.companyChanging = true; },
    h => { h.runtime.conflict = {}; }, h => { h.application.conflict = true; },
    h => { h.application.composing = true; }, h => { h.runtime.textEdit = { composing: true }; },
    h => { h.context.workspaceComposingControls.add(h.context.document.activeElement); },
  ];
  for (const condition of conditions) {
    const h = harness(); condition(h);
    assert.equal(await h.context.saveUploadedEditorDraft(), false);
    assert.equal(h.calls.length, 0);
    assert.ok(!h.toasts.includes('草稿已暫存'));
  }
});

test('a metadata keystroke during PDF save is flushed before saved acknowledgement', async () => {
  const h = harness(), gate = deferred();
  h.beforeResponse = (_, count) => count === 1 ? gate.promise : undefined;
  const saving = h.context.saveUploadedEditorDraft(); await tick();
  h.fields.title = 'A later committed title'; gate.resolve();
  assert.equal(await saving, true);
  assert.deepEqual(h.calls.map(call => call.method), ['PUT', 'PATCH', 'PUT']);
  assert.equal(h.calls[1].body.title, 'A later committed title');
  assert.equal(h.calls[2].body.expected_content_revision, 1);
});

test('a live drag during PDF save is preserved and committed in a newer revision', async () => {
  const h = harness(), gate = deferred();
  h.beforeResponse = (_, count) => count === 1 ? gate.promise : undefined;
  const saving = h.context.saveUploadedEditorDraft(); await tick();
  h.runtime.pointerAction = { type: 'drag' };
  h.context.uploadedSealEditorState.elements[0].x = 42; gate.resolve();
  assert.equal(await saving, true);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].body.state.elements[0].x, 10);
  assert.equal(h.calls[1].body.state.elements[0].x, 42);
  assert.equal(h.runtime.savedGeneration, 1);
});

test('an old save cannot announce success or clear the next actor/document operation', async () => {
  const h = harness(), gate = deferred();
  h.beforeResponse = () => gate.promise;
  const saving = h.context.saveUploadedEditorDraft(); await tick();
  h.replaceScope(); const newOperation = h.application.manualSaveOperation;
  const count = h.statuses.length; gate.resolve();
  assert.equal(await saving, false);
  assert.equal(h.application.manualSaveOperation, newOperation);
  assert.equal(h.statuses.length, count);
  assert.ok(!h.toasts.includes('草稿已暫存'));
});

test('permission failure and conflict keep local edits and never announce saved', async () => {
  for (const status of [403, 409, 503]) {
    const h = harness(); h.state.elements[0].properties.text = 'Retained edit'; h.runtime.dirtyGeneration = 1;
    h.beforeResponse = () => { throw Object.assign(new Error('Synthetic save failure'), { status }); };
    assert.equal(await h.context.saveUploadedEditorDraft(), false);
    assert.equal(h.context.uploadedSealEditorState.elements[0].properties.text, 'Retained edit');
    assert.equal(h.application.manualSaveOperation, null);
    assert.ok(!h.toasts.includes('草稿已暫存'));
    assert.equal(h.timers.size, 0, 'immediate save must not schedule a silent mutation retry');
    assert.ok(!h.statuses.at(-1)[1].includes('將自動重試'));
  }
});

test('IME started during a save does not receive a whole-draft saved acknowledgement', async () => {
  const h = harness(), gate = deferred();
  h.beforeResponse = () => gate.promise;
  const saving = h.context.saveUploadedEditorDraft(); await tick();
  h.application.composing = true; gate.resolve();
  assert.equal(await saving, false);
  assert.ok(!h.toasts.includes('草稿已暫存'));
  assert.match(h.statuses.at(-1)[1], /完成文字輸入/);
});

test('server-null result does not become a saved acknowledgement even when generations match', async () => {
  const h = harness();
  h.context.saveUploadedEditorState = async () => null;
  assert.equal(await h.context.saveUploadedEditorDraft(), false);
  assert.ok(!h.toasts.includes('草稿已暫存'));
  assert.match(h.statuses.at(-1)[1], /尚未同步完成/);
});

test('the save trigger regains focus after a native disabled button moved it to body', async () => {
  const h = harness(), gate = deferred(), trigger = h.nodes.get('#uploadedEditorSaveDraftBtn');
  Object.assign(trigger, { id: 'uploadedEditorSaveDraftBtn', isConnected: true,
    focus(options) { h.context.document.activeElement = this; this.focusOptions = options; } });
  h.context.document.body = {}; h.context.document.activeElement = trigger;
  h.beforeResponse = () => gate.promise;
  const saving = h.context.saveUploadedEditorDraft(); await tick();
  h.context.document.activeElement = h.context.document.body; gate.resolve();
  assert.equal(await saving, true);
  assert.equal(h.context.document.activeElement, trigger);
  assert.equal(trigger.focusOptions.preventScroll, true);
});

test('completing a save never steals focus from a newly focused form field', async () => {
  const h = harness(), gate = deferred(), trigger = h.nodes.get('#uploadedEditorSaveDraftFooterBtn');
  let restores = 0;
  Object.assign(trigger, { id: 'uploadedEditorSaveDraftFooterBtn', isConnected: true, focus() { restores += 1; } });
  h.context.document.body = {}; h.context.document.activeElement = trigger;
  h.beforeResponse = () => gate.promise;
  const saving = h.context.saveUploadedEditorDraft(); await tick();
  const newField = { id: 'uploadedSealReason' }; h.context.document.activeElement = newField; gate.resolve();
  assert.equal(await saving, true);
  assert.equal(h.context.document.activeElement, newField);
  assert.equal(restores, 0);
});
