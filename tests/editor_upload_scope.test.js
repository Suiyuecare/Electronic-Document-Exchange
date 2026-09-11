// Run the shipping browser functions, with deferred transport/PDF.js promises.
// Fixtures contain no real users, PDF content, Storage credentials, or seals.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const match = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(match, `Shipping function ${name} exists`);
  const remainder = source.slice(match.index + match[0].length);
  const next = /^\n(?:async )?function \w+\(/m.exec(remainder);
  assert.ok(next, `Shipping function ${name} has a following function`);
  return source.slice(match.index, match.index + match[0].length + next.index);
}
const scopedFunctions = [
  'uploadedSealApplicationScopeSnapshot', 'uploadedSealApplicationScopeIsCurrent',
  'assertEditorUploadCurrent', 'requestEditorUpload', 'finalizeEditorUpload',
  'confirmUploadedPdfConversion', 'resolveUploadedPdfConversion',
  'loadPdfJsAsset', 'loadUploadedPdfIntoEditor', 'refreshUploadedEditorManifest',
  'hydrateUploadedEditorAuthorizedAssets', 'handleUploadedSealPdfChange',
  'handleUploadedEditorImportPdf', 'handleUploadedEditorImage',
];
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const settle = () => new Promise(resolve => setImmediate(resolve));
const emptyState = () => ({ schemaVersion: 2, revisionNo: 2, manifestSha256: 'CURRENT', sourceFiles: [], pages: [], elements: [] });
function harness() {
  const events = [];
  const nodes = new Map();
  const runtime = {
    documentId: 'DOC-A', revisionId: 'REV-A', currentPageId: '', reviewMode: 'edited',
    uploading: false, locked: false, dirtyGeneration: 0, savedGeneration: 0,
    selectedIds: new Set(), pdfDocuments: new Map(), assetFiles: new Map(),
    pageProxies: new Map(), assetUrls: new Map(), imageUrls: new Map(),
  };
  const context = {
    console, File, Blob, TextEncoder, Uint8Array, Map, Set, crypto: require('node:crypto').webcrypto,
    session: 'USER-A:COMPANY-A', uploadedSealApplicationRuntime: { epoch: 0 },
    uploadedSealEditorRuntime: runtime, uploadedSealEditorState: emptyState(),
    uploadedSealPdf: null, uploadedSealObjectUrl: '', uploadedSealPageCount: 0,
    PDF_EDITOR_MAX_PAGES: 300, PDF_EDITOR_MAX_FILE_BYTES: 50 * 1024 * 1024,
    PDF_EDITOR_MAX_IMAGE_BYTES: 10 * 1024 * 1024,
    frontendSessionScope: () => context.session,
    document: { querySelector: key => {
      if (!nodes.has(key)) nodes.set(key, { value: '', textContent: '', click() {} });
      return nodes.get(key);
    } },
    URL: {
      createObjectURL: () => { const url = `blob:fixture-${events.length}`; events.push(['url', url]); return url; },
      revokeObjectURL: url => events.push(['revoke', url]),
    },
    emptyUploadedSealEditorState: emptyState,
    cloneUploadedEditorValue: value => structuredClone(value),
    roundEditorPoint: value => Number(value.toFixed(3)),
    normalizeEditorDegrees: value => ((value || 0) % 360 + 360) % 360,
    hashBlob: async () => 'HASH',
    ensureUploadedEditorDraft: async () => runtime.documentId,
    backendRequest: async (url, options) => { events.push(['request', url, options]); return { upload_id: 'UP-A', asset_id: 'ASSET-A' }; },
    inspectPdfFileA4: async () => ({ valid: true }),
    validateUploadedPdfDocument: async () => {},
    showEditorA4Dialog: async () => true,
    editorAuthorizedAssetUrl: item => `https://private.invalid/${item.assetId}`,
    fetchEditorAuthorizedBlob: async () => new Blob(['fixture'], { type: 'application/pdf' }),
    calculateUploadedEditorManifest: async () => 'CALCULATED',
    applyEditorRevisionFromResponse: value => { events.push(['revision', value]); context.uploadedSealEditorState.revisionNo = value.editor_revision?.revisionNo || 3; },
    markUploadedEditorDirty: () => events.push(['dirty']),
    saveUploadedEditorState: async () => events.push(['save']),
    syncLegacyUploadedEditorCollections: () => events.push(['sync']),
    pushUploadedEditorHistory: () => events.push(['history']),
    clearUploadedEditorUploadError: () => events.push(['clearError']),
    renderUploadedSealWorkbench: () => events.push(['render']),
    setUploadedEditorSaveStatus: (...args) => events.push(['status', ...args]),
    setUploadedPdfA4Status: (...args) => events.push(['a4Status', ...args]),
    showUploadedEditorUploadError: () => events.push(['uploadError']),
    showToast: message => events.push(['toast', message]),
    performTusUpload: async () => {},
    reportEditorUploadFailure: async () => events.push(['failureReport']),
    pdfA4UiErrorMessage: error => error.message,
    ensureUploadedEditorPagesA4: () => events.push(['a4Check']),
    addSealAudit: () => events.push(['audit']),
    openUploadedPdfPicker() {},
    currentUploadedEditorPage: () => context.uploadedSealEditorState.pages[0],
    commitUploadedEditorMutation: mutate => mutate(context.uploadedSealEditorState),
    editorDefaultElement: () => ({ id: 'IMAGE', kind: 'image' }),
  };
  vm.createContext(context);
  vm.runInContext(scopedFunctions.map(implementation).join('\n'), context);
  context.ensurePdfJsLibrary = async () => ({ getDocument: () => ({ promise: Promise.resolve(pdf()), destroy() {} }) });
  function pdf(overrides = {}) {
    return {
      numPages: 1,
      getPage: async () => ({ view: [0, 0, 595.276, 841.89], rotate: 0, userUnit: 1 }),
      destroy: () => events.push(['destroy']), ...overrides,
    };
  }
  function switchScope(kind = 'logout') {
    if (kind === 'logout') context.session = 'SIGNED-OUT';
    if (kind === 'account') context.session = 'USER-B:COMPANY-B';
    context.uploadedSealApplicationRuntime.epoch++;
    runtime.documentId = kind === 'logout' ? '' : 'DOC-B';
    runtime.uploading = true; // A newer in-flight operation must retain its busy flag.
    for (const key of ['pdfDocuments', 'pageProxies', 'assetFiles', 'assetUrls', 'imageUrls']) runtime[key].clear();
    context.uploadedSealEditorState = emptyState();
    context.uploadedSealPdf = null;
    context.document.querySelector('#uploadedSealTitle').value = 'NEW-SCOPE';
    events.length = 0;
  }
  const file = new File(['%PDF-test'], 'fixture.pdf', { type: 'application/pdf' });
  const intent = () => ({ documentId: runtime.documentId, upload_id: 'UP-A', asset_id: 'ASSET-A', assetKind: 'source_pdf', sha256: 'HASH', scope: context.uploadedSealApplicationScopeSnapshot() });
  return { context, events, nodes, runtime, file, intent, switchScope, pdf };
}
function noSensitiveRuntime(h) {
  for (const key of ['pdfDocuments', 'pageProxies', 'assetFiles', 'assetUrls', 'imageUrls']) assert.equal(h.runtime[key].size, 0, key);
  assert.equal(h.context.uploadedSealEditorState.manifestSha256, 'CURRENT');
  assert.equal(h.context.uploadedSealPdf, null);
}

test('request cannot recapture a new scope after awaiting an existing draft ID', async () => {
  const h = harness(); const gate = deferred();
  h.context.ensureUploadedEditorDraft = () => gate.promise;
  const pending = h.context.requestEditorUpload(h.file);
  h.switchScope('account'); gate.resolve('DOC-A');
  await assert.rejects(pending, /已切換/);
  assert.equal(h.events.filter(x => x[0] === 'request').length, 0);
});
test('new draft creation may set its own document ID without invalidating the upload', async () => {
  const h = harness(); h.runtime.documentId = '';
  h.context.ensureUploadedEditorDraft = async () => { h.runtime.documentId = 'CREATED'; return 'CREATED'; };
  const intent = await h.context.requestEditorUpload(h.file);
  assert.equal(intent.documentId, 'CREATED');
  assert.equal(intent.scope.documentId, 'CREATED');
});
for (const phase of ['hash', 'intent', 'finalize']) {
  test(`${phase} awaited response cannot survive account/draft switch`, async () => {
    const h = harness(); const gate = deferred(); let reached = false;
    if (phase === 'hash') h.context.hashBlob = () => { reached = true; return gate.promise; };
    else h.context.backendRequest = () => { reached = true; return gate.promise; };
    const pending = phase === 'finalize' ? h.context.finalizeEditorUpload(h.intent(), h.file) : h.context.requestEditorUpload(h.file);
    await settle(); assert.equal(reached, true);
    h.switchScope('account'); gate.resolve(phase === 'hash' ? 'HASH' : { upload_id: 'OLD' });
    await assert.rejects(pending, /已切換/);
    noSensitiveRuntime(h);
  });
}
for (const phase of ['library', 'bytes', 'document', 'validation', 'page']) {
  test(`PDF.js ${phase} pending at logout never caches old content`, async () => {
    const h = harness(); const gate = deferred(); let reached = false;
    const oldPdf = h.pdf({ getPage: () => phase === 'page' ? (reached = true, gate.promise) : Promise.resolve({ view: [0, 0, 595, 842] }) });
    const library = { getDocument: () => ({ promise: phase === 'document' ? (reached = true, gate.promise) : Promise.resolve(oldPdf), destroy() {} }) };
    h.context.ensurePdfJsLibrary = () => phase === 'library' ? (reached = true, gate.promise) : Promise.resolve(library);
    let file = h.file;
    if (phase === 'bytes') file = { name: 'fixture.pdf', arrayBuffer: () => (reached = true, gate.promise) };
    if (phase === 'validation') h.context.validateUploadedPdfDocument = () => (reached = true, gate.promise);
    const pending = h.context.loadPdfJsAsset(file, 'OLD-ASSET');
    await settle(); assert.equal(reached, true);
    h.switchScope();
    gate.resolve(phase === 'library' ? library : phase === 'bytes' ? new ArrayBuffer(4) : phase === 'document' ? oldPdf : phase === 'page' ? { view: [0, 0, 595, 842] } : undefined);
    await assert.rejects(pending, /已切換/);
    noSensitiveRuntime(h);
    assert.equal(h.events.some(x => x[0] === 'url'), false);
    if (['document', 'validation', 'page'].includes(phase)) assert.equal(h.events.filter(x => x[0] === 'destroy').length, 1);
  });
}
test('PDF.js successful same-scope parse commits canonical page IDs and geometry', async () => {
  const h = harness();
  const pages = await h.context.loadPdfJsAsset(h.file, 'ASSET-A', [{ pageId: 'STABLE-PAGE', rotation: 90 }]);
  assert.equal(pages[0].pageId, 'STABLE-PAGE'); assert.equal(pages[0].rotation, 90);
  assert.equal(h.runtime.pdfDocuments.size, 1); assert.equal(h.runtime.pageProxies.size, 1);
  assert.equal(h.events.some(x => x[0] === 'destroy'), false);
});
for (const kind of ['source_pdf', 'image']) {
  test(`hydration fetch for ${kind} cannot attach old bytes to a reopened draft`, async () => {
    const h = harness(); const gate = deferred();
    h.context.uploadedSealEditorState.sourceFiles = [{ assetId: 'OLD', kind, fileName: 'old', mimeType: kind === 'image' ? 'image/png' : 'application/pdf' }];
    h.context.uploadedSealEditorState.pages = [{ pageId: 'OLD-PAGE', sourceAssetId: 'OLD' }];
    h.context.fetchEditorAuthorizedBlob = () => gate.promise;
    const pending = h.context.hydrateUploadedEditorAuthorizedAssets({});
    await settle(); h.switchScope('draft'); gate.resolve(new Blob(['old']));
    await assert.rejects(pending, /已切換/); noSensitiveRuntime(h);
    assert.equal(h.events.some(x => x[0] === 'url'), false);
  });
}
test('hydration skips cancelled/unreferenced original and derivative PDFs', async () => {
  const h = harness();
  h.context.uploadedSealEditorState.sourceFiles = ['ORIGINAL', 'DERIVATIVE'].map(assetId => ({ assetId, kind: 'source_pdf', a4Conversion: {} }));
  let fetched = 0; h.context.fetchEditorAuthorizedBlob = async () => { fetched++; return new Blob(); };
  await h.context.hydrateUploadedEditorAuthorizedAssets({});
  assert.equal(fetched, 0); noSensitiveRuntime(h);
});
for (const replacement of ['logout', 'same-scope-state']) {
  test(`manifest digest cannot write after ${replacement}`, async () => {
    const h = harness(); const gate = deferred(); const oldState = h.context.uploadedSealEditorState;
    h.context.calculateUploadedEditorManifest = () => gate.promise;
    const pending = h.context.refreshUploadedEditorManifest();
    if (replacement === 'logout') h.switchScope(); else h.context.uploadedSealEditorState = emptyState();
    gate.resolve('OLD-HASH'); await assert.rejects(pending, /已切換/);
    assert.equal(oldState.manifestSha256, 'CURRENT');
    assert.equal(h.context.uploadedSealEditorState.manifestSha256, 'CURRENT');
  });
}
test('logout during final manifest does not mark dirty or render the new editor', async () => {
  const h = harness(); const gate = deferred(); let reached = false;
  h.context.calculateUploadedEditorManifest = () => (reached = true, gate.promise);
  const pending = h.context.loadUploadedPdfIntoEditor(h.file, h.intent(), { asset: { id: 'ASSET-A' } });
  await settle(); assert.equal(reached, true);
  h.switchScope(); gate.resolve('OLD-HASH');
  await assert.rejects(pending, /已切換/); noSensitiveRuntime(h);
  assert.equal(h.events.some(x => ['dirty', 'render'].includes(x[0])), false);
});
for (const handler of ['main', 'import']) {
  for (const phase of ['save', 'confirmation', 'load', 'failure-report']) {
    test(`${handler} ${phase} completion after logout cannot update UI or clear new busy flag`, async () => {
      const h = harness(); const gate = deferred(); let reached = false;
      h.runtime.dirtyGeneration = 1;
      h.context.confirmUploadedPdfConversion = async () => true;
      h.context.requestEditorUpload = async () => h.intent();
      h.context.finalizeEditorUpload = async () => ({ asset: { id: 'ASSET-A' } });
      h.context.loadUploadedPdfIntoEditor = async () => {};
      if (phase === 'save') h.context.saveUploadedEditorState = () => (reached = true, gate.promise);
      if (phase === 'confirmation') h.context.confirmUploadedPdfConversion = () => (reached = true, gate.promise);
      if (phase === 'load') h.context.loadUploadedPdfIntoEditor = () => (reached = true, gate.promise);
      if (phase === 'failure-report') {
        h.context.confirmUploadedPdfConversion = async () => { throw new Error('OLD-ERROR'); };
        h.context.reportEditorUploadFailure = () => (reached = true, gate.promise);
      }
      const pending = handler === 'main' ? h.context.handleUploadedSealPdfChange(h.file) : h.context.handleUploadedEditorImportPdf([h.file]);
      await settle(); assert.equal(reached, true);
      h.switchScope(); gate.resolve(true); await pending;
      assert.equal(h.runtime.uploading, true);
      assert.equal(h.context.uploadedSealPdf, null);
      assert.equal(h.nodes.get('#uploadedSealTitle').value, 'NEW-SCOPE');
      assert.equal(h.events.length, 0, JSON.stringify(h.events));
    });
  }
}
test('image finalize after logout cannot apply a revision or release a newer upload gate', async () => {
  const h = harness(); const gate = deferred(); let reached = false;
  // Image insertion requires an already loaded destination PDF page.
  h.context.uploadedSealEditorState.pages = [{ pageId: 'PAGE-A', widthPt: 595.276, heightPt: 841.89 }];
  h.context.requestEditorUpload = async () => h.intent();
  h.context.finalizeEditorUpload = () => (reached = true, gate.promise);
  const pending = h.context.handleUploadedEditorImage(new File(['png'], 'test.png', { type: 'image/png' }));
  await settle(); assert.equal(reached, true); h.switchScope();
  gate.resolve({ asset: { id: 'OLD-IMAGE' } }); await pending;
  noSensitiveRuntime(h); assert.equal(h.runtime.uploading, true); assert.equal(h.events.length, 0);
});

function conversionFixture(h) {
  const original = { assetId: 'ORIGINAL', kind: 'source_pdf', sha256: 'ORIGINAL-HASH', a4Conversion: { required: true } };
  const derived = { assetId: 'A4', kind: 'import_pdf', sha256: 'HASH', a4Conversion: { converted: true, sourceAssetId: 'ORIGINAL', sourceSha256: 'ORIGINAL-HASH' } };
  const converted = {
    asset: { id: 'A4', sha256: 'HASH', fileName: 'fixture-A4.pdf', a4Conversion: derived.a4Conversion },
    editor_state: { sourceFiles: [original, derived] }, editor_revision: { revisionNo: 4 },
  };
  h.context.backendRequest = async url => url.endsWith('/convert-a4') ? converted : { assets: [{ id: 'A4' }] };
  const finalized = { a4Conversion: { required: true, sourceAssetId: 'ORIGINAL', sourceSha256: 'ORIGINAL-HASH' }, editor_revision: { revisionNo: 3 } };
  h.context.uploadedSealEditorState.sourceFiles = [{ assetId: 'CURRENT', kind: 'source_pdf' }];
  h.context.uploadedSealEditorState.pages = [{ pageId: 'KEEP-PAGE', sourceAssetId: 'CURRENT' }];
  h.context.uploadedSealEditorState.elements = [{ id: 'KEEP-TEXT', kind: 'text', pageId: 'KEEP-PAGE' }];
  return { original, derived, converted, finalized };
}
for (const phase of ['conversion', 'state', 'download', 'hash', 'preview', 'cancel-save']) {
  test(`A4 ${phase} response after account switch cannot mutate current revision or lineage`, async () => {
    const h = harness(); const f = conversionFixture(h); const gate = deferred(); let reached = false;
    const originalRequest = h.context.backendRequest;
    h.context.backendRequest = url => {
      if ((phase === 'conversion' && url.endsWith('/convert-a4')) || (phase === 'state' && url.endsWith('/editor-state'))) return (reached = true, gate.promise);
      return originalRequest(url);
    };
    if (phase === 'download') h.context.fetchEditorAuthorizedBlob = () => (reached = true, gate.promise);
    if (phase === 'hash') h.context.hashBlob = () => (reached = true, gate.promise);
    if (phase === 'preview') h.context.showEditorA4Dialog = () => (reached = true, gate.promise);
    if (phase === 'cancel-save') {
      h.context.showEditorA4Dialog = async () => false;
      h.context.saveUploadedEditorState = () => (reached = true, gate.promise);
    }
    const pending = h.context.resolveUploadedPdfConversion(h.file, h.intent(), f.finalized);
    await settle(); assert.equal(reached, true);
    h.switchScope('account');
    gate.resolve(phase === 'conversion' ? f.converted : phase === 'state' ? {} : phase === 'download' ? new Blob(['A4']) : phase === 'hash' ? 'HASH' : true);
    await assert.rejects(pending, /已切換/); noSensitiveRuntime(h);
    assert.equal(h.context.uploadedSealEditorState.sourceFiles.length, 0);
    assert.equal(h.context.uploadedSealEditorState.revisionNo, 2);
    assert.equal(h.events.length, 0);
  });
}
test('cancelling A4 preview saves existing edits and retained audit lineage without adopting pages', async () => {
  const h = harness(); const f = conversionFixture(h);
  h.context.showEditorA4Dialog = async () => false;
  const pages = h.context.uploadedSealEditorState.pages;
  const elements = h.context.uploadedSealEditorState.elements;
  const result = await h.context.resolveUploadedPdfConversion(h.file, h.intent(), f.finalized);
  assert.equal(result, null);
  assert.equal(h.context.uploadedSealEditorState.pages, pages);
  assert.equal(h.context.uploadedSealEditorState.elements, elements);
  assert.deepEqual(Array.from(h.context.uploadedSealEditorState.sourceFiles, x => x.assetId), ['CURRENT', 'ORIGINAL', 'A4']);
  assert.equal(h.context.uploadedSealEditorState.revisionNo, 4);
  assert.equal(h.events.filter(x => x[0] === 'save').length, 1);
});
test('accepted A4 preview returns derivative File and matching intent hash while keeping original lineage', async () => {
  const h = harness(); const f = conversionFixture(h);
  const result = await h.context.resolveUploadedPdfConversion(h.file, h.intent(), f.finalized);
  assert.equal(result.file.name, 'fixture-A4.pdf');
  assert.equal(result.intent.asset_id, 'A4'); assert.equal(result.intent.sha256, 'HASH');
  assert.equal(result.intent.scope.documentId, 'DOC-A'); assert.equal(result.intent.assetKind, 'import_pdf');
  assert.equal(h.context.uploadedSealEditorState.sourceFiles.find(x => x.assetId === 'A4').a4Conversion.sourceAssetId, 'ORIGINAL');
  assert.equal(h.context.uploadedSealEditorState.pages[0].pageId, 'KEEP-PAGE');
  assert.equal(h.events.filter(x => x[0] === 'save').length, 0);
});
