// Reopening uses synthetic files and controlled reads only. No credentials,
// production requests, people, signatures or business approvals are involved.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const start = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(start, name);
  const after = source.slice(start.index + start[0].length);
  const next = /^\n(?:async )?function \w+\(/m.exec(after);
  return source.slice(start.index, start.index + start[0].length + next.index);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
const tick = () => new Promise(setImmediate);
function stageHarness() {
  const pending = new Map(), starts = [], destroyed = [];
  let current = true, active = 0, maximum = 0;
  const c = { File, Blob, Uint8Array, Map, Set, Promise, Error, console,
    uploadedSealEditorRuntime: { pdfDocuments: new Map([['active', { destroy() { destroyed.push('ACTIVE'); } }]]) },
    uploadedSealApplicationScopeIsCurrent: () => current,
    editorAuthorizedAssetUrl: item => item.assetId,
    fetchEditorAuthorizedBlob: (url, { signal } = {}) => {
      starts.push(url); active++; maximum = Math.max(maximum, active);
      const item = deferred(); pending.set(url, item);
      if (signal) signal.addEventListener('abort', () => item.reject(Object.assign(new Error('cancelled'), { name: 'AbortError' })), { once: true });
      return item.promise.finally(() => active--);
    },
    ensurePdfJsLibrary: async () => ({ getDocument: () => {
      const id = `parsed-${starts.length}-${destroyed.length}`;
      const pdfDocument = { numPages: 1, id, destroy() { destroyed.push(id); } };
      return { promise: Promise.resolve(pdfDocument), destroy() { pdfDocument.destroy(); } };
    } }),
    validateUploadedPdfDocument: async () => ({ pageProxies: new Map([[1, { fixture: true }]]) }),
  };
  vm.createContext(c);
  vm.runInContext(['discardUploadedEditorStagedAssets', 'stageUploadedEditorAuthorizedAssets'].map(implementation).join('\n'), c);
  const state = { sourceFiles: ['secondary', 'third', 'primary'].map(assetId => ({ assetId, kind: 'source_pdf', mimeType: 'application/pdf', fileName: `${assetId}.pdf` })),
    pages: ['primary', 'secondary', 'third'].map(assetId => ({ pageId: `page-${assetId}`, sourceAssetId: assetId, sourcePageIndex: 0 })), elements: [] };
  return { c, pending, starts, destroyed, state, maximum: () => maximum, invalidate: () => { current = false; },
    resolve: id => pending.get(id).resolve(new Blob(['synthetic'], { type: 'application/pdf' })) };
}

test('staging prioritizes the visible source, previews it before a slow secondary, and caps reads at two', async () => {
  const h = stageHarness(), previews = [], progress = [];
  const stage = h.c.stageUploadedEditorAuthorizedAssets(h.state, {}, {}, {
    onAssetReady: (asset, page) => previews.push([asset.assetId, page.pageId]),
    onProgress: item => progress.push({ ...item }),
  });
  await tick();
  assert.deepEqual(h.starts, ['primary', 'secondary']);
  h.resolve('primary'); await tick();
  assert.deepEqual(previews, [['primary', 'page-primary']]);
  assert.deepEqual(h.starts, ['primary', 'secondary', 'third']);
  assert.equal(h.c.uploadedSealEditorRuntime.pdfDocuments.has('primary'), false, 'preview must not install into active runtime');
  assert.equal(h.maximum(), 2);
  h.resolve('third'); h.resolve('secondary');
  const assets = await stage;
  assert.equal(assets.length, 3);
  assert.deepEqual(progress.at(-1), { completed: 3, total: 3 });
  h.c.discardUploadedEditorStagedAssets(assets);
  assert.equal(h.destroyed.length, 3);
  assert.equal(h.destroyed.includes('ACTIVE'), false);
});

test('failure waits for another in-flight worker then disposes its late PDF without touching the current case', async () => {
  const h = stageHarness();
  let settled = false;
  const stage = h.c.stageUploadedEditorAuthorizedAssets(h.state, {}, {});
  stage.catch(() => { settled = true; });
  h.pending.get('primary').reject(new Error('synthetic forbidden'));
  await tick();
  assert.equal(settled, false, 'cleanup must wait for the running secondary');
  h.resolve('secondary');
  await assert.rejects(stage, /synthetic forbidden/);
  assert.deepEqual(h.starts, ['primary', 'secondary'], 'no queued third read after failure');
  assert.equal(h.destroyed.length, 1, 'late staged secondary must be disposed');
  assert.equal(h.destroyed.includes('ACTIVE'), false);
});

test('optional first-page rendering cannot delay a fully verified single-source reopen', async () => {
  const h = stageHarness(), preview = deferred();
  h.state.sourceFiles = h.state.sourceFiles.filter(item => item.assetId === 'primary');
  h.state.pages = h.state.pages.filter(item => item.sourceAssetId === 'primary');
  const stage = h.c.stageUploadedEditorAuthorizedAssets(h.state, {}, {}, { onAssetReady: () => preview.promise });
  h.resolve('primary');
  const assets = await stage;
  assert.equal(assets.length, 1, 'critical path is independent of preview render completion');
  preview.resolve();
  h.c.discardUploadedEditorStagedAssets(assets);
});

test('cancelling aborts both reads, rejects with AbortError, and never launches queued files', async () => {
  const h = stageHarness(), controller = new AbortController();
  const stage = h.c.stageUploadedEditorAuthorizedAssets(h.state, {}, {}, { signal: controller.signal });
  assert.equal(h.starts.length, 2);
  controller.abort();
  await assert.rejects(stage, { name: 'AbortError' });
  assert.deepEqual(h.starts, ['primary', 'secondary']);
  assert.equal(h.destroyed.includes('ACTIVE'), false);
});

test('a preserved non-A4 original unused by editor geometry is not unnecessarily downloaded', async () => {
  const h = stageHarness();
  h.state.sourceFiles.push({ assetId: 'audit-original', kind: 'original_pdf', mimeType: 'application/pdf' });
  const stage = h.c.stageUploadedEditorAuthorizedAssets(h.state, {}, {});
  h.resolve('primary'); h.resolve('secondary'); await tick(); h.resolve('third');
  const assets = await stage;
  assert.equal(h.starts.includes('audit-original'), false);
  h.c.discardUploadedEditorStagedAssets(assets);
});

function openingHarness() {
  const pending = new Map(), events = [];
  const oldState = { schemaVersion: 2, sourceFiles: [], pages: [], elements: [{ id: 'unsaved', x: 37 }] };
  const runtime = { documentId: 'old-case', dirtyGeneration: 0, savedGeneration: 0, locked: false, pdfDocuments: new Map() };
  const scope = { epoch: 0 };
  const c = { console, Promise, Error, Set, Map, PDF_EDITOR_SCHEMA_VERSION: 2,
    uploadedSealApplicationRuntime: { epoch: 0, editable: true }, uploadedSealEditorRuntime: runtime, uploadedSealEditorState: oldState,
    uploadedSealApplicationScopeSnapshot: () => ({ epoch: c.uploadedSealApplicationRuntime.epoch }),
    uploadedSealApplicationScopeIsCurrent: snapshot => snapshot.epoch === c.uploadedSealApplicationRuntime.epoch,
    flushUploadedSealDraftBeforeSwitch: async () => events.push('flushed'), uploadedSealApplicationKey: () => 'stable',
    backendRequest: (url, { signal } = {}) => { events.push(url); const d = deferred(); pending.set(url.endsWith('/editor-state') ? 'state' : 'application', d); return d.promise; },
    stageUploadedEditorAuthorizedAssets: async () => { events.push('staged'); return []; },
    discardUploadedEditorStagedAssets() {},
    clearUploadedEditorSensitivePreviews: options => { events.push('cleared'); c.clearOptions = options; runtime.documentId = ''; },
    emptyUploadedSealEditorState: () => ({}), cloneUploadedEditorValue: structuredClone,
    applyEditorRevisionFromResponse() {}, editorPreparedAuthorizedUrl: () => '', officialDocumentIsApplicant: () => true,
    restoreUploadedSealApplication() {}, rememberUploadedEditorSavedSealBindings() {}, normalizeUploadedEditorSealGeometry: () => false,
    renderUploadedSealWorkbench() {}, hydrateUploadedEditorAuthorizedAssets: async () => events.push('hydrated'),
    syncLegacyUploadedEditorCollections() {}, ensureUploadedEditorPagesA4() {}, markUploadedEditorDirty() {}, setUploadedEditorSaveStatus() {},
    loadUploadedSealOptions: async () => events.push('seals'), refreshWorkflowReadinessForContext: async () => events.push('readiness'),
  };
  vm.createContext(c); vm.runInContext(implementation('loadUploadedEditorState'), c);
  const application = { current_status: 'draft', company_id: 'synthetic-company' };
  const result = { state: { schemaVersion: 2, sourceFiles: [], pages: [], elements: [] }, status: 'draft' };
  return { c, runtime, oldState, events, pending, application, result, scope };
}

test('application and editor-state reads run together only after old draft flush', async () => {
  const h = openingHarness();
  const opening = h.c.loadUploadedEditorState('new-case');
  await tick();
  assert.equal(h.events[0], 'flushed');
  assert.equal(h.pending.size, 2, 'both metadata APIs must already be in flight');
  h.pending.get('state').resolve(h.result); await tick();
  assert.equal(h.events.includes('cleared'), false);
  h.pending.get('application').resolve(h.application); await opening;
  assert.equal(h.runtime.documentId, 'new-case');
  assert.equal(h.events.includes('hydrated'), true);
  assert.equal(h.runtime.locked, false);
  assert.equal(h.c.clearOptions.preserveOpeningPreview, true, 'verified commit must not abort its own open operation');
});

test('logout removes and aborts an active first-page preview; late render or another session cannot reveal it', async () => {
  for (const action of ['logout', 'scope-only']) {
    const rendered = deferred(), nodes = {};
    let actorScope = 'synthetic-old', cancelled = 0, removed = false;
    const controller = new AbortController();
    const status = { textContent: '', hidden: false };
    const button = () => ({ disabled: false, hidden: false, addEventListener() {} });
    const figure = { hidden: true };
    const canvas = { width: 0, height: 0, getContext: () => ({ clearRect() {} }) };
    const panel = { isConnected: true, setAttribute() {}, remove() { removed = true; this.isConnected = false; delete nodes['#uploadedEditorOpeningPreview']; },
      querySelector: selector => ({ '[role="status"]': status, '[data-editor-open-cancel]': button(), '[data-editor-open-retry]': button(), figure, canvas })[selector] };
    const runtime = { reviewGeneration: 0, renderNonce: 0 };
    const c = { AbortController, Map, Set, Promise, Error,
      document: { querySelector: selector => nodes[selector] || null, createElement: () => panel },
      frontendSessionScope: () => actorScope,
      window: { clearTimeout() {} }, URL: { revokeObjectURL() {} },
      uploadedSealEditorRuntime: runtime, uploadedSealApplicationRuntime: { openAbortController: controller }, uploadedSealOptionsRequestNo: 0,
      finishUploadedEditorTextEdit() {}, resetUploadedSealApplicationSaving() {}, emptyUploadedSealEditorState: () => ({ pages: [] }),
      uploadedSealEditorState: {}, uploadedSealPdf: null, clearUploadedEditorUploadError() {},
    };
    nodes['#uploadedPdfEditor'] = { prepend(item) { nodes['#uploadedEditorOpeningPreview'] = item; } };
    nodes['#uploadedPdfCanvas'] = canvas;
    vm.createContext(c);
    const clearStart = source.indexOf('function clearUploadedEditorSensitivePreviews(');
    const clearSource = source.slice(clearStart, source.indexOf('\n}\n', clearStart) + 2);
    vm.runInContext(implementation('createUploadedEditorOpeningPreview') + '\n' + clearSource, c);
    const preview = c.createUploadedEditorOpeningPreview(controller, () => {});
    const proxy = { getViewport: () => ({ width: 595, height: 842 }), render: () => ({ promise: rendered.promise, cancel() { cancelled++; } }) };
    const pending = preview.assetReady({ preparation: { pdfDocument: {}, pageProxies: new Map([[1, proxy]]) } }, { sourcePageIndex: 0 });
    await tick();
    if (action === 'logout') {
      c.clearUploadedEditorSensitivePreviews();
      assert.equal(controller.signal.aborted, true);
      assert.equal(c.uploadedSealApplicationRuntime.openAbortController, null);
      assert.equal(removed, true);
      assert.equal(nodes['#uploadedEditorOpeningPreview'], undefined);
      assert.equal(cancelled, 1);
    } else {
      actorScope = 'synthetic-new';
    }
    rendered.resolve(); await pending;
    assert.equal(figure.hidden, true, 'late PDF render cannot reveal another actor\'s first-page preview');
    preview.dispose();
  }
});

test('cancelled metadata leaves old inputs and PDF active even if late API responses succeed', async () => {
  const h = openingHarness(), controller = new AbortController();
  const opening = h.c.loadUploadedEditorState('new-case', { signal: controller.signal });
  await tick(); controller.abort();
  h.pending.get('state').resolve(h.result); h.pending.get('application').resolve(h.application);
  await assert.rejects(opening, { name: 'AbortError' });
  assert.equal(h.runtime.documentId, 'old-case');
  assert.equal(h.c.uploadedSealEditorState, h.oldState);
  assert.equal(h.events.includes('cleared'), false);
});

test('a staging error and a fresh edit each fail closed before the commit callback', async () => {
  for (const scenario of ['asset-error', 'new-edit']) {
    const h = openingHarness(); let committed = false;
    h.c.stageUploadedEditorAuthorizedAssets = async () => {
      if (scenario === 'asset-error') throw new Error('synthetic asset failure');
      h.runtime.dirtyGeneration++; h.oldState.elements[0].x = 88; return [];
    };
    const opening = h.c.loadUploadedEditorState('new-case', { onCommit: () => { committed = true; } });
    await tick(); h.pending.get('state').resolve(h.result); h.pending.get('application').resolve(h.application);
    await assert.rejects(opening, /failure|修改.*保留/);
    assert.equal(committed, false);
    assert.equal(h.runtime.documentId, 'old-case');
    assert.equal(h.events.includes('cleared'), false);
  }
});

test('parallel reads cannot pair locked approval metadata with an old draft or another prepared file', async () => {
  const locked = { locked_editor_revision_id: 'submitted-revision', prepared_file_id: 'submitted-file', prepared_sha256: 'a'.repeat(64) };
  for (const mismatch of ['draft-revision', 'prepared-file', 'prepared-hash', 'missing-lock', 'draft-status']) {
    const h = openingHarness();
    h.application.current_status = 'pending_ceo';
    h.application.stamp_request = { ...locked };
    Object.assign(h.result, { revision_id: locked.locked_editor_revision_id, status: 'locked', preparedFileId: locked.prepared_file_id, preparedSha256: locked.prepared_sha256 });
    if (mismatch === 'draft-revision') h.result.revision_id = 'old-draft';
    if (mismatch === 'prepared-file') h.result.preparedFileId = 'other-file';
    if (mismatch === 'prepared-hash') h.result.preparedSha256 = 'b'.repeat(64);
    if (mismatch === 'missing-lock') h.application.stamp_request = {};
    if (mismatch === 'draft-status') h.result.status = 'draft';
    const opening = h.c.loadUploadedEditorState('new-case');
    await tick(); h.pending.get('state').resolve(h.result); h.pending.get('application').resolve(h.application);
    await assert.rejects(opening, /案件版本.*更新/);
    assert.equal(h.events.includes('staged'), false, 'inconsistent evidence must fail before file downloads');
    assert.equal(h.events.includes('cleared'), false);
    assert.equal(h.runtime.documentId, 'old-case');
  }
});

test('exact submitted revision and prepared identity reopen read-only, including completed cases', async () => {
  for (const status of ['pending_ceo', 'stamped', 'closed']) {
    const h = openingHarness();
    h.application.current_status = status;
    h.application.stamp_request = { locked_editor_revision_id: 'locked-revision', prepared_file_id: 'locked-file', prepared_sha256: 'c'.repeat(64) };
    Object.assign(h.result, { id: 'locked-revision', status: 'locked', preparedFileId: 'locked-file', preparedSha256: 'c'.repeat(64) });
    const opening = h.c.loadUploadedEditorState('new-case');
    await tick(); h.pending.get('state').resolve(h.result); h.pending.get('application').resolve(h.application);
    await opening;
    assert.equal(h.runtime.documentId, 'new-case');
    assert.equal(h.runtime.locked, true);
    assert.equal(h.c.uploadedSealApplicationRuntime.editable, false);
  }
});
