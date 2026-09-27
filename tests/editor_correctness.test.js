// Shipping editor regression tests. All PDFs, people and assets are synthetic;
// no network, storage credentials, real documents or Seal Vault files are used.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
function implementation(name) {
  const match = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(match, name);
  const remainder = source.slice(match.index + match[0].length);
  const next = /^\n(?:async )?function \w+\(/m.exec(remainder);
  return source.slice(match.index, match.index + match[0].length + next.index);
}

function pointerRaceHarness() {
  const h = harness();
  Object.assign(h.runtime, { tool: 'select', zoom: 1, touchPointers: new Map(), dirtyGeneration: 0, savedGeneration: 0, undoStack: [], guides: [] });
  h.state.elements = [{ id: 'seal', kind: 'seal', pageId: 'p1', x: 100, y: 100, width: 80, height: 80, properties: {} }];
  h.runtime.selectedIds.add('seal');
  Object.assign(h.c, {
    performance, PDF_EDITOR_SCHEMA_VERSION: 2,
    editorElementById: id => h.c.uploadedSealEditorState.elements.find(element => element.id === id),
    uploadedEditorClientPoint: (x, y) => ({ x, y }),
    snapUploadedEditorPosition: (element, x, y) => ({ x, y, guides: [] }),
    setUploadedEditorZoom: value => { h.runtime.zoom = value; },
    emptyUploadedSealEditorState: () => ({}), rememberUploadedEditorSavedSealBindings() {},
    pushUploadedEditorHistory: state => h.runtime.undoStack.push(structuredClone(state)),
    markUploadedEditorDirty: () => { h.runtime.dirtyGeneration += 1; },
    renderUploadedEditorSvgLayer() {}, renderUploadedEditorProperties() {},
    selectUploadedEditorElement: id => { h.runtime.selectedIds = new Set(id ? [id] : []); },
  });
  const names = ['beginUploadedEditorPointer', 'moveUploadedEditorPointer', 'endUploadedEditorPointer', 'applyUploadedEditorCanonicalSaveResponse'];
  if (source.includes('function finishUploadedEditorPointerAction(')) names.push('finishUploadedEditorPointerAction');
  vm.runInContext(names.map(implementation).join('\n'), h.c);
  h.pointer = (id, x, y, onElement = true, type = 'pointermove') => ({
    type, pointerType: 'touch', pointerId: id, clientX: x, clientY: y,
    preventDefault() {}, currentTarget: { setPointerCapture() {} },
    target: { closest: selector => onElement && selector === '[data-editor-element-id]' ? { dataset: { editorElementId: 'seal' } } : null },
  });
  return h;
}

test('joining a pinch commits an already moved seal exactly once', () => {
  const h = pointerRaceHarness();
  h.c.beginUploadedEditorPointer(h.pointer(1, 110, 110));
  h.c.moveUploadedEditorPointer(h.pointer(1, 140, 110));
  h.c.beginUploadedEditorPointer(h.pointer(2, 220, 110, false));
  h.c.endUploadedEditorPointer(h.pointer(2, 220, 110, false, 'pointerup'));
  h.c.endUploadedEditorPointer(h.pointer(1, 140, 110, true, 'pointerup'));
  assert.equal(h.c.uploadedSealEditorState.elements[0].x, 130);
  assert.equal(h.runtime.dirtyGeneration, 1);
  assert.equal(h.runtime.undoStack.length, 1);
});

test('canonical autosave response cannot overwrite a drag before pointerup', () => {
  const h = pointerRaceHarness();
  h.runtime.dirtyGeneration = 1;
  const savedState = structuredClone(h.state);
  h.c.beginUploadedEditorPointer(h.pointer(1, 110, 110));
  h.c.moveUploadedEditorPointer(h.pointer(1, 140, 110));
  assert.equal(h.c.applyUploadedEditorCanonicalSaveResponse({ state: savedState, revisionNo: 2, manifestSha256: 'saved' }, 1), false);
  h.c.endUploadedEditorPointer(h.pointer(1, 140, 110, true, 'pointerup'));
  assert.equal(h.c.uploadedSealEditorState.elements[0].x, 130);
  assert.equal(h.runtime.dirtyGeneration, 2);
});

test('the real autosave snapshot and delayed response preserve a later live drag', async () => {
  const h = pointerRaceHarness();
  let release, sentState;
  Object.assign(h.runtime, { documentId: 'fixture-document', dirtyGeneration: 1, savedGeneration: 0, baseManifestSha256: 'initial', saving: false });
  Object.assign(h.c, {
    navigator: { onLine: true }, window: { clearTimeout() {}, setTimeout: () => 1 },
    calculateUploadedEditorManifest: async () => 'saved-hash',
    backendRequest: (url, options) => { sentState = JSON.parse(options.body).state; return new Promise(resolve => { release = resolve; }); },
    applyEditorRevisionFromResponse: result => { h.c.uploadedSealEditorState.revisionNo = result.revisionNo; },
  });
  vm.runInContext(implementation('saveUploadedEditorState'), h.c);
  const saving = h.c.saveUploadedEditorState();
  await new Promise(setImmediate);
  assert.equal(sentState.elements[0].x, 100);
  h.c.beginUploadedEditorPointer(h.pointer(1, 110, 110));
  h.c.moveUploadedEditorPointer(h.pointer(1, 140, 110));
  release({ state: sentState, revisionNo: 2, manifestSha256: 'saved-hash' });
  await saving;
  assert.equal(h.c.uploadedSealEditorState.elements[0].x, 130);
  assert.equal(h.runtime.savedGeneration, 1);
  h.c.endUploadedEditorPointer(h.pointer(1, 140, 110, true, 'pointerup'));
  assert.equal(h.runtime.dirtyGeneration, 2);
  assert.equal(h.runtime.undoStack.length, 1);
});

test('only the owning pointer moves and completes a gesture; pointercancel preserves visible work', () => {
  const h = pointerRaceHarness();
  h.c.beginUploadedEditorPointer(h.pointer(1, 110, 110));
  h.c.moveUploadedEditorPointer(h.pointer(99, 190, 110));
  assert.equal(h.state.elements[0].x, 100);
  h.c.endUploadedEditorPointer(h.pointer(99, 190, 110, true, 'pointerup'));
  assert.ok(h.runtime.pointerAction);
  h.c.moveUploadedEditorPointer(h.pointer(1, 140, 110));
  h.c.endUploadedEditorPointer(h.pointer(1, 140, 110, true, 'pointercancel'));
  assert.equal(h.state.elements[0].x, 130);
  assert.equal(h.runtime.dirtyGeneration, 1);
  assert.equal(h.runtime.undoStack.length, 1);
});

test('a third touch cannot take over the original pinch pair or create a drag', () => {
  const h = pointerRaceHarness();
  h.c.beginUploadedEditorPointer(h.pointer(1, 110, 110, false));
  h.c.beginUploadedEditorPointer(h.pointer(2, 210, 110, false));
  h.c.beginUploadedEditorPointer(h.pointer(3, 410, 110));
  h.c.moveUploadedEditorPointer(h.pointer(3, 610, 110));
  assert.equal(h.runtime.zoom, 1);
  assert.equal(h.runtime.pointerAction, null);
  h.c.moveUploadedEditorPointer(h.pointer(2, 310, 110, false));
  assert.equal(h.runtime.zoom, 2);
  h.c.endUploadedEditorPointer(h.pointer(2, 310, 110, false, 'pointercancel'));
  h.c.moveUploadedEditorPointer(h.pointer(3, 810, 110));
  assert.equal(h.runtime.zoom, 2);
  assert.equal(h.state.elements[0].x, 100);
});

test('a nonmoving press does not become an edit when autosave advances the revision cursor', () => {
  const h = pointerRaceHarness();
  h.c.beginUploadedEditorPointer(h.pointer(1, 110, 110));
  h.state.revisionNo = 2;
  h.state.manifestSha256 = 'confirmed-new-cursor';
  h.c.endUploadedEditorPointer(h.pointer(1, 110, 110, true, 'pointerup'));
  assert.equal(h.runtime.dirtyGeneration, 0);
  assert.equal(h.runtime.undoStack.length, 0);
});

test('approval evidence uses the submitted prepared file, never a newer historical preflight', () => {
  const c = { officialApplicationFiles: item => item.files };
  vm.createContext(c);
  vm.runInContext(implementation('officialDecisionEvidenceFiles'), c);
  const files = [{ id: 'newer', file_type: 'prepared_pdf' }, { id: 'locked', file_type: 'prepared_pdf' }, { id: 'original', file_type: 'original_pdf' }];
  const item = { files, stamp_request: { prepared_file_id: 'locked', prepared_sha256: 'locked-hash', locked_editor_revision_id: 'revision' } };
  assert.equal(c.officialDecisionEvidenceFiles(item).edited.id, 'locked');
  assert.equal(c.officialDecisionEvidenceFiles({ ...item, files: files.filter(file => file.id !== 'locked') }).edited, null);
  assert.equal(c.officialDecisionEvidenceFiles({ ...item, stamp_request: { locked_editor_revision_id: 'revision' } }).edited, null);
});

function openingRaceHarness() {
  const h = harness();
  let release;
  h.state.elements = [{ id: 'seal', kind: 'seal', pageId: 'p1', x: 100, properties: {} }];
  Object.assign(h.runtime, { documentId: 'old-draft', dirtyGeneration: 0, savedGeneration: 0 });
  const application = { epoch: 0 };
  Object.assign(h.c, {
    uploadedSealApplicationRuntime: application, PDF_EDITOR_SCHEMA_VERSION: 2,
    uploadedSealApplicationKey: () => 'application-key',
    uploadedSealApplicationScopeSnapshot: () => ({ epoch: application.epoch, documentId: h.runtime.documentId }),
    uploadedSealApplicationScopeIsCurrent: scope => scope.epoch === application.epoch && scope.documentId === h.runtime.documentId,
    flushUploadedSealDraftBeforeSwitch: async () => {},
    backendRequest: path => path.endsWith('/editor-state')
      ? Promise.resolve({ state: { schemaVersion: 2, revisionNo: 1, sourceFiles: [], pages: [], elements: [] }, status: 'draft' })
      : new Promise(resolve => { release = resolve; }),
    clearUploadedEditorSensitivePreviews: () => { h.events.push('cleared'); h.runtime.documentId = ''; },
    stageUploadedEditorAuthorizedAssets: async () => [],
    discardUploadedEditorStagedAssets() {}, emptyUploadedSealEditorState: () => ({}),
    editorPreparedAuthorizedUrl: () => '', officialDocumentIsApplicant: () => true,
    restoreUploadedSealApplication() {}, rememberUploadedEditorSavedSealBindings() {},
    hydrateUploadedEditorAuthorizedAssets: async () => {},
    loadUploadedSealOptions: async () => {}, refreshWorkflowReadinessForContext: async () => {},
    markUploadedEditorDirty: () => { h.runtime.dirtyGeneration++; },
  });
  vm.runInContext(implementation('loadUploadedEditorState'), h.c);
  h.release = () => release({ current_status: 'draft', company_id: 'fixture-company' });
  return h;
}

test('a new edit while opening another case preserves the active case and aborts the switch', async () => {
  const h = openingRaceHarness();
  const opening = h.c.loadUploadedEditorState('new-draft');
  await new Promise(setImmediate);
  assert.equal(h.c.commitUploadedEditorMutation(state => { state.elements[0].x = 130; }), true);
  h.release();
  await assert.rejects(opening, /修改.*保留|內容.*變更/);
  assert.equal(h.runtime.documentId, 'old-draft');
  assert.equal(h.c.uploadedSealEditorState.elements[0].x, 130);
  assert.equal(h.events.includes('cleared'), false);
});

test('asset staging failure leaves the previous case editable and intact', async () => {
  const h = openingRaceHarness();
  h.c.stageUploadedEditorAuthorizedAssets = async () => { throw new Error('synthetic asset access failure'); };
  const opening = h.c.loadUploadedEditorState('new-draft');
  await new Promise(setImmediate);
  h.release();
  await assert.rejects(opening, /synthetic asset access failure/);
  assert.equal(h.runtime.documentId, 'old-draft');
  assert.equal(h.runtime.locked, false);
  assert.equal(h.c.uploadedSealEditorState.elements[0].x, 100);
  assert.equal(h.events.includes('cleared'), false);
});
function harness() {
  const events = [];
  const page = { pageId: 'p1', sourceAssetId: 'pdf', sourcePageIndex: 0, widthPt: 595.2756, heightPt: 841.8898, rotation: 0 };
  const state = { schemaVersion: 2, revisionNo: 1, sourceFiles: [{ assetId: 'pdf', kind: 'source_pdf' }], pages: [page], elements: [] };
  const runtime = { reviewMode: 'edited', uploading: false, locked: false, currentPageId: 'p1', imageUrls: new Map(), selectedIds: new Set(), clipboard: [], pdfDocuments: new Map(), assetFiles: new Map(), assetUrls: new Map(), pageProxies: new Map() };
  const c = { File, Blob, Uint8Array, console, Map, Set, crypto: require('node:crypto').webcrypto,
    uploadedSealEditorState: state, uploadedSealEditorRuntime: runtime,
    PDF_EDITOR_MAX_IMAGE_BYTES: 10 * 1024 * 1024, PDF_EDITOR_MAX_ELEMENTS: 1000,
    PDF_EDITOR_ALLOWED_KINDS: new Set(['text', 'seal', 'image']),
    document: { querySelector: () => null }, URL: { createObjectURL: () => 'blob:fixture', revokeObjectURL() {} },
    window: { confirm: () => true }, EDOCSeam: require(path.join(root, 'editor-seam.js')),
    uploadedSealApplicationScopeSnapshot: () => ({ id: 'test' }), uploadedSealApplicationScopeIsCurrent: () => true,
    clearUploadedEditorUploadError() {}, setUploadedEditorSaveStatus() {},
    requestEditorUpload: async () => ({ asset_id: 'image', sha256: 'abc' }), performTusUpload: async () => {},
    assertEditorUploadCurrent() {}, finalizeEditorUpload: async () => ({ asset: { id: 'image' } }), applyEditorRevisionFromResponse() {},
    currentUploadedEditorPage: () => state.pages[0], editorDefaultElement: () => ({ id: 'image-element', kind: 'image', pageId: 'p1', width: 100, height: 100, x: 20, y: 20 }),
    reportEditorUploadFailure: async () => {}, showUploadedEditorUploadError: () => events.push('error'),
    showToast: message => events.push(message), renderUploadedSealWorkbench() {},
    cloneUploadedEditorValue: structuredClone, normalizeUploadedEditorSealGeometry() {}, normalizeUploadedEditorElementLayers() {},
    canonicalEditorJson: JSON.stringify, pushUploadedEditorHistory() {}, syncLegacyUploadedEditorCollections() {}, markUploadedEditorDirty: () => events.push('dirty'),
    validateUploadedPdfDocument: async () => {}, roundEditorPoint: value => Number(value.toFixed(4)), normalizeEditorDegrees: value => value || 0,
  };
  vm.createContext(c);
  vm.runInContext(['commitUploadedEditorMutation', 'handleUploadedEditorImage', 'uploadedEditorCopyPlacement', 'pasteUploadedEditorSelection', 'parseUploadedEditorPageRange', 'copyUploadedEditorSelectionToPages', 'loadPdfJsAsset', 'hydrateUploadedEditorAuthorizedAssets'].map(implementation).join('\n'), c);
  return { c, page, state, runtime, events };
}

test('image completion inserts once through the real mutation gate, while external edits remain blocked', async () => {
  const h = harness();
  h.c.performTusUpload = async () => {
    assert.equal(h.runtime.uploading, true);
    h.c.commitUploadedEditorMutation(state => state.elements.push({ id: 'unexpected', kind: 'text', pageId: 'p1' }));
    assert.equal(h.state.elements.length, 0);
  };
  await h.c.handleUploadedEditorImage(new File(['synthetic'], 'test.png', { type: 'image/png' }));
  assert.equal(h.state.elements.length, 1);
  assert.equal(h.state.elements[0].kind, 'image');
  assert.equal(h.state.sourceFiles.filter(item => item.assetId === 'image').length, 1);
  assert.equal(h.events.filter(item => item === 'dirty').length, 1);
  assert.equal(h.runtime.uploading, false);
  assert.ok(h.runtime.selectedIds.has('image-element'));
});

test('image completion never circumvents locked or read-only versions', async () => {
  for (const change of [runtime => { runtime.locked = true; }, runtime => { runtime.reviewMode = 'original'; }]) {
    const h = harness();
    h.c.finalizeEditorUpload = async () => { change(h.runtime); return { asset: { id: 'image' } }; };
    await h.c.handleUploadedEditorImage(new File(['synthetic'], 'test.png', { type: 'image/png' }));
    assert.equal(h.state.elements.length, 0);
    assert.equal(h.events.filter(item => item === 'dirty').length, 0);
  }
});

test('pasting at each edge stays inside the page without changing object size', () => {
  for (const [x, y] of [[0, 0], [495.2756, 0], [0, 817.8898], [495.2756, 817.8898]]) {
    const h = harness();
    const original = { id: 'original', kind: 'text', pageId: 'p1', x, y, width: 100, height: 24, rotation: 0, opacity: 1, zIndex: 1, properties: { text: 'synthetic' } };
    h.runtime.clipboard = [original];
    h.c.pasteUploadedEditorSelection();
    const copied = h.state.elements[0];
    assert.equal(copied.width, 100);
    assert.equal(copied.height, 24);
    assert.ok(copied.x >= 0 && copied.y >= 0);
    assert.ok(copied.x + copied.width <= h.page.widthPt);
    assert.ok(copied.y + copied.height <= h.page.heightPt);
    assert.equal(original.x, x);
    assert.equal(original.y, y);
  }
});

test('cross-orientation copies clamp positions, reject oversize objects atomically and keep seam safeguards', () => {
  const h = harness();
  const landscape = { pageId: 'landscape', widthPt: 841.8898, heightPt: 595.2756 };
  h.state.pages.push(landscape);
  h.runtime.clipboard = [{ id: 'seal', kind: 'seal', width: 85, height: 85, x: 510, y: 750, properties: {} }];
  h.c.pasteUploadedEditorSelection('landscape');
  assert.equal(h.state.elements[0].height, 85);
  assert.equal(h.state.elements[0].y, landscape.heightPt - 85);
  h.runtime.clipboard.push({ id: 'too-large', kind: 'image', width: 800, height: 650, x: 0, y: 0 });
  const before = JSON.stringify(h.state);
  h.c.pasteUploadedEditorSelection('landscape');
  assert.equal(JSON.stringify(h.state), before);
  h.runtime.clipboard = [{ id: 'half-seal', kind: 'seal', width: 40, height: 85, x: 0, y: 0, properties: { seamGroupId: 'group' } }];
  h.c.pasteUploadedEditorSelection('landscape');
  assert.equal(JSON.stringify(h.state), before);
});

function syntheticThreePagePdf() {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>'];
  for (let index = 0; index < 3; index++) {
    const content = `BT /F1 16 Tf 40 780 Td (SYNTHETIC PAGE ${index + 1}) Tj ET`;
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.2756 841.8898] /Resources << /Font << /F1 9 0 R >> >> /Contents ${4 + index * 2} 0 R >>`, `<< /Length ${content.length} >>\nstream\n${content}\nendstream`);
  }
  objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((value, index) => { offsets.push(pdf.length); pdf += `${index + 1} 0 obj\n${value}\nendobj\n`; });
  const xref = pdf.length;
  pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
  offsets.slice(1).forEach(offset => { pdf += `${String(offset).padStart(10, '0')} 00000 n \n`; });
  return Buffer.from(`${pdf}trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`);
}

test('real pinned PDF.js reopens deleted/reordered pages by stable source index, retaining rotation', async () => {
  const h = harness();
  const pdfjs = await import(pathToFileURL(path.join(root, 'vendor/pdfjs/pdf.min.mjs')).href);
  pdfjs.GlobalWorkerOptions.workerSrc = pathToFileURL(path.join(root, 'vendor/pdfjs/pdf.worker.min.mjs')).href;
  const bytes = syntheticThreePagePdf();
  h.c.ensurePdfJsLibrary = async () => pdfjs;
  h.state.sourceFiles = [{ assetId: 'pdf', kind: 'source_pdf', fileName: 'synthetic.pdf', mimeType: 'application/pdf' }];
  h.state.pages = [2, 1].map((index, order) => ({ ...h.page, pageId: `stable-${index}`, sourcePageIndex: index, rotation: index === 2 ? 270 : 90, order }));
  h.c.editorAuthorizedAssetUrl = () => 'https://synthetic.invalid/source';
  h.c.fetchEditorAuthorizedBlob = async () => new Blob([bytes], { type: 'application/pdf' });
  try {
    await h.c.hydrateUploadedEditorAuthorizedAssets({});
    assert.equal(h.runtime.pageProxies.size, 2);
    for (const page of h.state.pages) {
      const proxy = h.runtime.pageProxies.get(page.pageId).proxy;
      assert.equal(proxy.pageNumber, page.sourcePageIndex + 1);
      const text = (await proxy.getTextContent()).items.map(item => item.str).join('');
      assert.equal(text, `SYNTHETIC PAGE ${page.sourcePageIndex + 1}`);
    }
    const loaded = await h.c.loadPdfJsAsset(new File([bytes], 'synthetic.pdf', { type: 'application/pdf' }), 'pdf', h.state.pages);
    assert.deepEqual(Array.from(loaded, page => page.rotation), [270, 90]);
    assert.deepEqual(Array.from(loaded, page => page.sourcePageIndex), [2, 1]);
    await assert.rejects(h.c.loadPdfJsAsset(new File([bytes], 'synthetic.pdf', { type: 'application/pdf' }), 'pdf', [{ pageId: 'bad', sourcePageIndex: 3 }]), /頁面對應/);
  } finally {
    for (const pdf of h.runtime.pdfDocuments.values()) await pdf.destroy();
  }
});

test('staging parses real synthetic PDFs before installation and cleans up rejected mappings', async () => {
  const h = harness();
  const pdfjs = await import(pathToFileURL(path.join(root, 'vendor/pdfjs/pdf.min.mjs')).href);
  pdfjs.GlobalWorkerOptions.workerSrc = pathToFileURL(path.join(root, 'vendor/pdfjs/pdf.worker.min.mjs')).href;
  Object.assign(h.c, {
    PDF_EDITOR_MAX_PAGES: 300, PDF_A4_WIDTH_PT: 595.2756, PDF_A4_HEIGHT_PT: 841.8898, PDF_A4_TOLERANCE_PT: 1, PDF_A4_INVALID_MESSAGE: 'A4 required',
    ensurePdfJsLibrary: async () => pdfjs, editorAuthorizedAssetUrl: () => 'fixture-only',
    fetchEditorAuthorizedBlob: async () => new Blob([syntheticThreePagePdf()], { type: 'application/pdf' }),
  });
  vm.runInContext(['stageUploadedEditorAuthorizedAssets', 'discardUploadedEditorStagedAssets', 'validateUploadedPdfDocument', 'readPdfA4Pages', 'pdfA4PageReport', 'requirePdfPagesA4'].map(implementation).join('\n'), h.c);
  const staged = await h.c.stageUploadedEditorAuthorizedAssets(h.state, {}, {});
  assert.equal(staged.length, 1);
  assert.equal(staged[0].preparation.pdfDocument.numPages, 3);
  assert.equal(h.runtime.pdfDocuments.size, 0, 'staging must not replace the active PDF');
  await h.c.hydrateUploadedEditorAuthorizedAssets({}, staged);
  assert.equal(h.runtime.pdfDocuments.get('pdf'), staged[0].preparation.pdfDocument);
  h.c.discardUploadedEditorStagedAssets(staged);
  assert.equal((await h.runtime.pdfDocuments.get('pdf').getPage(1)).pageNumber, 1, 'installed proxy must not be destroyed');
  await assert.rejects(h.c.stageUploadedEditorAuthorizedAssets({ ...h.state, pages: [{ ...h.page, sourcePageIndex: 99 }] }, {}, {}), /頁面對應/);
  await h.runtime.pdfDocuments.get('pdf').destroy();
});
