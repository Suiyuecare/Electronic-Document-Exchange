// Shipping implementations with de-identified assets; no production traffic.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const matches = [...source.matchAll(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n[\\s\\S]*?^\\}`, 'gm'))];
  assert.ok(matches.length, name); return matches.at(-1)[0];
}
function load(context, names) { vm.createContext(context); vm.runInContext(names.map(implementation).join('\n'), context); return context; }
const tick = () => new Promise(setImmediate);
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const round = value => Math.round(value * 10000) / 10000;

test('delayed compact inspector focus never interrupts a field or focuses a closed drawer', () => {
  const frames = [], editor = { dataset: {} }, field = {}, trigger = {};
  let closeFocus = 0;
  const node = { setAttribute() {}, removeAttribute() {}, contains: element => element === field,
    querySelector: () => ({ focus: () => closeFocus++ }) };
  const c = load({ uploadedEditorMobileDrawerIsCompact: () => true, uploadedEditorMobileDrawerReturnFocus: null,
    document: { activeElement: trigger, body: { classList: { add() {} } }, querySelector: selector => selector === '#uploadedPdfEditor' ? editor : node },
    window: { requestAnimationFrame: callback => frames.push(callback) },
  }, ['setUploadedEditorMobileDrawer']);
  c.setUploadedEditorMobileDrawer('properties', true, trigger);
  c.document.activeElement = field; frames.shift()(); assert.equal(closeFocus, 0);
  c.document.activeElement = trigger; c.setUploadedEditorMobileDrawer('properties', true, trigger);
  editor.dataset.propertiesOpen = 'false'; frames.shift()(); assert.equal(closeFocus, 0);
  c.setUploadedEditorMobileDrawer('properties', true, trigger); frames.shift()(); assert.equal(closeFocus, 1);
});

test('portrait, landscape and square images retain their intrinsic ratio and fit the page', () => {
  const c = load({}, ['uploadedEditorImageGeometry']);
  for (const size of [{ width: 400, height: 100 }, { width: 100, height: 600 }, { width: 300, height: 300 }]) {
    for (const page of [{ widthPt: 595, heightPt: 842 }, { widthPt: 842, heightPt: 595 }]) {
      const result = c.uploadedEditorImageGeometry(size, page);
      assert.ok(Math.abs(result.width / result.height - size.width / size.height) < 1e-9);
      assert.ok(result.x >= 0 && result.y >= 0 && result.x + result.width <= page.widthPt && result.y + result.height <= page.heightPt);
    }
  }
});

test('PDF Y and all displayed quarter-turn corners proportionally resize text, including font', () => {
  const c = load({ roundEditorPoint: round }, ['resizeUploadedEditorElement']);
  const start = { x: 200, y: 200, width: 120, height: 60, properties: { fontSize: 12 } };
  // Displayed bottom-right may map to any PDF corner on rotated pages.
  for (const point of [{ x: 320, y: 200 }, { x: 320, y: 260 }, { x: 200, y: 260 }, { x: 200, y: 200 }]) {
    const center = { x: 260, y: 230 };
    const element = { ...structuredClone(start), kind: 'text' };
    const target = { x: center.x + 3 * (point.x - center.x), y: center.y + 3 * (point.y - center.y) };
    c.resizeUploadedEditorElement(element, start, point, target, { widthPt: 800, heightPt: 900 });
    assert.equal(element.width, 240); assert.equal(element.height, 120); assert.equal(element.properties.fontSize, 24);
    assert.equal(element.width / element.height, 2);
  }
});

test('page bounds and font bounds stop proportional resize without stretching', () => {
  const c = load({ roundEditorPoint: round }, ['resizeUploadedEditorElement']);
  const start = { x: 20, y: 20, width: 120, height: 60, properties: { fontSize: 12 } };
  const element = { ...structuredClone(start), kind: 'text' };
  c.resizeUploadedEditorElement(element, start, { x: 140, y: 20 }, { x: 20000, y: -20000 }, { widthPt: 595, heightPt: 842 });
  assert.ok(Math.abs(element.width / element.height - 2) < 0.0001);
  assert.ok(element.x >= 0 && element.y >= 0 && element.x + element.width <= 595.001 && element.y + element.height <= 842.001);
  assert.ok(element.properties.fontSize >= 6 && element.properties.fontSize <= 144);
});

function imageHarness() {
  const state = { schemaVersion: 2, revisionNo: 1, sourceFiles: [{ assetId: 'pdf', kind: 'source_pdf' }],
    pages: [{ pageId: 'p1', widthPt: 595, heightPt: 842 }], elements: [] };
  const runtime = { documentId: 'doc', reviewMode: 'edited', selectedIds: new Set(), imageUrls: new Map(), undoStack: [], redoStack: [], clipboard: [], dirtyGeneration: 0, savedGeneration: 0 };
  const transport = deferred(), finalized = deferred(); const calls = [];
  const c = { File, AbortController, Uint8Array, crypto: require('node:crypto').webcrypto, URL: { createObjectURL: () => 'blob:synthetic', revokeObjectURL() {} },
    window: { clearTimeout() {} }, document: { querySelector: () => null }, navigator: { onLine: true },
    uploadedSealEditorState: state, uploadedSealEditorRuntime: runtime, uploadedSealApplicationRuntime: {},
    PDF_EDITOR_MAX_IMAGE_BYTES: 10485760, actor: 'A', uploadedSealApplicationScopeSnapshot: () => ({ actor: c.actor, documentId: runtime.documentId }), uploadedSealApplicationScopeIsCurrent: scope => scope.actor === c.actor && scope.documentId === runtime.documentId,
    currentUploadedEditorPage: () => state.pages[0], readUploadedEditorImageSize: async () => ({ width: 400, height: 200 }),
    editorDefaultElement: (kind, page, point, properties) => ({ id: 'img', kind, pageId: page.pageId, properties }),
    commitUploadedEditorMutation: mutate => { runtime.undoStack.push(structuredClone(state)); mutate(state); runtime.dirtyGeneration++; return true; },
    renderUploadedSealWorkbench() {}, renderUploadedEditorSubmissionActions() {}, setUploadedEditorSaveStatus() {},
    showToast: message => calls.push(['toast', message]), syncLegacyUploadedEditorCollections() {}, scheduleUploadedSealApplicationSave() {},
    markUploadedEditorDirty: () => runtime.dirtyGeneration++, finishUploadedEditorPointerAction() {},
    requestEditorUpload: async () => { calls.push(['intent']); return { asset_id: 'final-image', sha256: 'image-hash' }; },
    performTusUpload: () => { calls.push(['transfer']); return transport.promise; },
    finalizeEditorUpload: () => { calls.push(['finalize']); return finalized.promise; },
    assertEditorUploadCurrent() {}, applyEditorRevisionFromResponse: result => { calls.push(['revision']); state.revisionNo = result.revisionNo; },
    backendRequest: () => { throw new Error('unexpected write'); },
  };
  load(c, ['uploadedEditorImageGeometry', 'uploadedEditorPendingImageIsCurrent', 'renderUploadedEditorImageSync', 'mapUploadedEditorLocalImage',
    'discardUploadedEditorPendingImage', 'syncUploadedEditorPendingImage', 'handleUploadedEditorImage', 'saveUploadedEditorState', 'preflightUploadedEditor', 'uploadedEditorDraftSaveIssue']);
  return { c, state, runtime, transport, finalized, calls, file: new File(['synthetic image'], 'fixture.png', { type: 'image/png' }) };
}

test('image is editable before delayed transport; save and preflight cannot send a provisional image', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  assert.equal(h.state.elements.length, 1); assert.equal(h.runtime.uploading, undefined); assert.ok(h.runtime.pendingImage);
  assert.equal(h.state.elements[0].width / h.state.elements[0].height, 2);
  assert.equal(await h.c.saveUploadedEditorState(), null);
  await assert.rejects(h.c.preflightUploadedEditor(), /圖片尚未同步/);
  assert.match(h.c.uploadedEditorDraftSaveIssue(), /圖片尚未同步/);
  h.c.discardUploadedEditorPendingImage(); h.transport.resolve(); await tick();
});

test('delayed image finalization retains latest position and remaps current, undo, redo, clipboard and live drag', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  h.state.elements[0].x = 222;
  h.runtime.undoStack.push(structuredClone(h.state)); h.runtime.redoStack.push(structuredClone(h.state));
  h.runtime.clipboard = [structuredClone(h.state.elements[0])];
  h.runtime.pointerAction = { previousState: structuredClone(h.state), startElement: structuredClone(h.state.elements[0]), startElements: { img: structuredClone(h.state.elements[0]) } };
  const pending = h.runtime.pendingImage;
  h.transport.resolve(); await tick(); h.state.elements[0].x = 333;
  h.finalized.resolve({ asset: { id: 'final-image' }, revisionNo: 2 }); await pending.promise;
  assert.equal(h.runtime.pendingImage, null); assert.equal(h.state.elements[0].x, 333); assert.equal(h.state.revisionNo, 2);
  for (const element of [h.state.elements[0], h.runtime.undoStack.at(-1).elements[0], h.runtime.redoStack[0].elements[0], h.runtime.clipboard[0], h.runtime.pointerAction.startElement, h.runtime.pointerAction.startElements.img]) {
    assert.equal(element.properties.assetId, 'final-image'); assert.equal(element.properties.localPending, undefined);
  }
  assert.equal(h.runtime.imageUrls.get('final-image'), 'blob:synthetic');
  assert.equal(h.calls.filter(call => call[0] === 'intent').length, 1);
});

test('finalize failure keeps local work and retries the same immutable upload, without re-upload', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  const pending = h.runtime.pendingImage; h.transport.resolve(); await tick();
  h.finalized.reject(Object.assign(new Error('temporary'), { status: 503 })); await pending.promise;
  assert.equal(h.state.elements.length, 1); assert.ok(pending.error); h.state.elements[0].x = 123;
  h.c.finalizeEditorUpload = async () => ({ asset: { id: 'final-image' }, revisionNo: 2 });
  await h.c.syncUploadedEditorPendingImage();
  assert.equal(h.state.elements[0].x, 123); assert.equal(h.runtime.pendingImage, null);
  assert.equal(h.calls.filter(call => call[0] === 'intent').length, 1); assert.equal(h.calls.filter(call => call[0] === 'transfer').length, 1);
});

test('uncertain intent failure is not replayed as a new upload', async () => {
  const h = imageHarness(); let intents = 0;
  h.c.requestEditorUpload = async () => { intents++; throw Object.assign(new Error('unknown commit'), { outcomeUnknown: true }); };
  await h.c.handleUploadedEditorImage(h.file); await tick();
  assert.ok(h.runtime.pendingImage.error); await h.c.syncUploadedEditorPendingImage();
  assert.equal(intents, 1); assert.equal(h.state.elements.length, 1);
});

test('switching account while an image finalizes never adopts old revision or pixels', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  const pending = h.runtime.pendingImage; h.transport.resolve(); await tick();
  h.c.actor = 'B'; h.runtime.pendingImage = null; h.runtime.imageUrls.clear(); h.state.elements = [];
  h.finalized.resolve({ asset: { id: 'old-user-image' }, revisionNo: 99 }); await pending.promise;
  assert.equal(h.state.revisionNo, 1); assert.equal(h.state.elements.length, 0); assert.equal(h.runtime.imageUrls.size, 0);
});

test('removing an unsynced image cleans history so redo cannot reintroduce its provisional asset', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  h.runtime.redoStack.push(structuredClone(h.state)); h.runtime.clipboard = structuredClone(h.state.elements);
  h.c.discardUploadedEditorPendingImage();
  assert.equal(h.state.elements.length, 0); assert.equal(h.runtime.redoStack[0].elements.length, 0); assert.equal(h.runtime.clipboard.length, 0);
  assert.equal(h.state.sourceFiles.length, 1); assert.equal(h.runtime.pendingImage, null);
  h.transport.resolve(); await tick(); assert.equal(h.calls.some(call => call[0] === 'finalize'), false);
});

test('removing during finalization keeps the write barrier, adopts the cursor and never restores the image', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  const pending = h.runtime.pendingImage; h.transport.resolve(); await tick();
  assert.equal(pending.finalizing, true);
  h.c.discardUploadedEditorPendingImage();
  assert.equal(h.state.elements.length, 0); assert.equal(h.runtime.pendingImage, pending);
  assert.equal(await h.c.saveUploadedEditorState(), null);
  await assert.rejects(h.c.preflightUploadedEditor(), /圖片尚未同步/);
  h.state.elements.push({ id: 'latest-text', kind: 'text', x: 250 });
  h.finalized.resolve({ asset: { id: 'final-image' }, revisionNo: 2 }); await pending.promise;
  assert.equal(h.runtime.pendingImage, null); assert.equal(h.state.revisionNo, 2);
  assert.deepEqual(h.state.elements, [{ id: 'latest-text', kind: 'text', x: 250 }]);
  assert.equal(h.state.sourceFiles.length, 1); assert.equal(h.runtime.imageUrls.size, 0);
});

test('removed image with an uncertain finalize stays gated until retry reconciles the same immutable intent', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  const pending = h.runtime.pendingImage; h.transport.resolve(); await tick();
  h.c.discardUploadedEditorPendingImage();
  h.finalized.reject(Object.assign(new Error('response lost'), { outcomeUnknown: true })); await pending.promise;
  assert.equal(h.runtime.pendingImage, pending); assert.ok(pending.error);
  assert.equal(await h.c.saveUploadedEditorState(), null);
  h.c.finalizeEditorUpload = async () => ({ asset: { id: 'final-image' }, revisionNo: 3 });
  await h.c.syncUploadedEditorPendingImage();
  assert.equal(h.runtime.pendingImage, null); assert.equal(h.state.revisionNo, 3);
  assert.equal(h.state.elements.length, 0); assert.equal(h.runtime.imageUrls.size, 0);
  assert.equal(h.calls.filter(call => call[0] === 'intent').length, 1);
  assert.equal(h.calls.filter(call => call[0] === 'transfer').length, 1);
});

test('definitive image-validation rejection permits removing the image without a permanent write barrier', async () => {
  for (const detail of ['editor_image_invalid', 'editor_upload_hash_mismatch', 'editor_upload_new_intent_required']) {
    const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
    const pending = h.runtime.pendingImage; h.transport.resolve(); await tick();
    h.finalized.reject(Object.assign(new Error('invalid image'), { status: 400, code: 'request_rejected', detail }));
    await pending.promise;
    assert.equal(pending.finalizing, false); assert.equal(h.state.revisionNo, 1);
    h.c.discardUploadedEditorPendingImage();
    assert.equal(h.runtime.pendingImage, null); assert.equal(h.state.elements.length, 0);
    assert.equal(h.state.sourceFiles.length, 1); assert.equal(h.runtime.imageUrls.size, 0);
    const writes = [];
    Object.assign(h.c, { normalizeUploadedEditorSealGeometry: () => false,
      cloneUploadedEditorValue: structuredClone, calculateUploadedEditorManifest: async () => 'new-manifest',
      applyUploadedEditorCanonicalSaveResponse: () => false,
      backendRequest: async (path, options) => { writes.push({ path, body: JSON.parse(options.body) }); return { revisionNo: 2, manifestSha256: 'new-manifest' }; },
    });
    await h.c.saveUploadedEditorState({ immediate: true });
    assert.equal(writes.length, 1); assert.equal(writes[0].path, '/official-documents/doc/editor-state');
    assert.equal(writes[0].body.state.sourceFiles.length, 1); assert.equal(writes[0].body.state.elements.length, 0);
    assert.equal(h.runtime.savedGeneration, h.runtime.dirtyGeneration);
  }
});

test('unknown finalize followed by generic 400 stays gated, then terminal same-intent rejection releases removed image', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  const pending = h.runtime.pendingImage; h.transport.resolve(); await tick();
  h.c.discardUploadedEditorPendingImage();
  h.finalized.reject(Object.assign(new Error('response lost'), { outcomeUnknown: true })); await pending.promise;
  h.c.finalizeEditorUpload = async () => { throw Object.assign(new Error('generic rejection'), { status: 400, detail: 'unknown_request_failure' }); };
  await h.c.syncUploadedEditorPendingImage();
  assert.equal(h.runtime.pendingImage, pending); assert.equal(pending.finalizing, true);
  assert.equal(await h.c.saveUploadedEditorState(), null);
  h.c.finalizeEditorUpload = async () => { throw Object.assign(new Error('terminal immutable intent'), { status: 400, detail: 'editor_upload_new_intent_required' }); };
  await h.c.syncUploadedEditorPendingImage();
  assert.equal(h.runtime.pendingImage, null); assert.equal(h.state.revisionNo, 1);
  assert.equal(h.state.elements.length, 0); assert.equal(h.calls.filter(call => call[0] === 'intent').length, 1);
});

test('unknown outcome never unlocks solely because a terminal-looking code is present', async () => {
  const h = imageHarness(); await h.c.handleUploadedEditorImage(h.file); await tick();
  const pending = h.runtime.pendingImage; h.transport.resolve(); await tick();
  h.finalized.reject(Object.assign(new Error('uncertain transport'), { status: 400, detail: 'editor_image_invalid', outcomeUnknown: true }));
  await pending.promise; h.c.discardUploadedEditorPendingImage();
  assert.equal(h.runtime.pendingImage, pending); assert.equal(pending.finalizing, true);
});

test('120 pointer notifications coalesce to one animation frame and only selected nodes update', () => {
  const callbacks = []; const first = { dataset: { editorElementId: 'selected' }, setAttribute() {}, replaceChildren() { this.replaced = (this.replaced || 0) + 1; } };
  const second = { dataset: { editorElementId: 'untouched' } };
  const svg = { children: [first, second], querySelectorAll: () => [], append() {} };
  const runtime = { currentPageId: 'p1', pointerAction: {}, reviewMode: 'edited', guides: [], pointerRenderIds: new Set() };
  const c = load({ uploadedSealEditorRuntime: runtime, window: { requestAnimationFrame: callback => { callbacks.push(callback); return callbacks.length; } },
    document: { querySelector: () => svg }, editorElementById: id => ({ id, pageId: 'p1' }),
    uploadedEditorViewportRect: () => ({ left: 1, top: 2, width: 3, height: 4 }), appendEditorElementVisual() {}, currentUploadedEditorPage: () => ({ pageId: 'p1' })
  }, ['queueUploadedEditorPointerRender', 'flushUploadedEditorPointerRender']);
  for (let i = 0; i < 120; i++) c.queueUploadedEditorPointerRender(['selected']);
  assert.equal(callbacks.length, 1); callbacks[0](); assert.equal(first.replaced, 1); assert.equal(svg.children[1], second); assert.equal(second.replaced, undefined);
});

test('seal placement has no real seal transport even with a valid immutable binding', async () => {
  const c = load({ backendRequest() { throw new Error('must not fetch seal'); }, fetch() { throw new Error('must not fetch seal'); } }, ['loadSealPreviewUrl']);
  assert.equal(await c.loadSealPreviewUrl('seal', 'file', 'hash'), '');
});

test('seven-page seams initialize 5+2 at one height, keep 10mm margins and move only their own group', () => {
  const seam = require('../editor-seam.js');
  const pages = Array.from({ length: 7 }, (_, i) => ({ pageId: `p${i + 1}`, widthPt: 595, heightPt: 842, rotation: 0 }));
  const ordinary = { id: 'small', seal_size_type: 'small_seal' }, large = { id: 'large', seal_size_type: 'large_seal', owner_kind: 'company' };
  const state = { pages, elements: [] };
  const c = load({ EDOCSeam: seam, crypto: require('node:crypto').webcrypto, PDF_EDITOR_MAX_ELEMENTS: 1000,
    uploadedSealEditorState: state, uploadedSealPickerReadOnly: () => false, selectedUploadedSeamSeal: () => large, selectedUploadedSeal: () => ordinary,
    officialSealHasCurrentFile: () => true, uploadedSeamPrimaryLargeSeal: seal => seal === large,
    companySealCurrentVersionSnapshot: () => ({ sealFileId: 'file', sealFileSha256: 'hash' }), document: { querySelector: () => null },
    commitUploadedEditorMutation: callback => { callback(state); return true; }, showToast() {},
    editorDefaultElement: (kind, page, point, properties, seal) => ({ id: `s${state.elements.length}-${page.pageId}`, kind, pageId: page.pageId,
      x: 0, y: 0, width: 84, height: 84, properties: { ...properties, sealId: seal.id, sealFileId: 'file', sealFileSha256: 'hash' } }),
  }, ['addUploadedSeamGroups']);
  c.addUploadedSeamGroups();
  const groups = [...seam.groups(state)]; assert.deepEqual(groups.map(([, members]) => members.length), [5, 2]);
  assert.ok(state.elements.every(item => item.properties.sealId === 'large'));
  const first = seam.offsetPt(pages[0], groups[0][1][0]), second = seam.offsetPt(pages[5], groups[1][1][0]);
  assert.ok(Math.abs(first - second) < 0.001);
  seam.position(state, groups[1][0], -100, 'right');
  assert.ok(Math.abs(seam.offsetPt(pages[5], groups[1][1][0]) - 10 * seam.ptPerMm) < 0.001);
  assert.equal(seam.offsetPt(pages[0], groups[0][1][0]), first);
  seam.position(state, groups[1][0], 10000, 'right');
  assert.ok(Math.abs(842 - 84 - seam.offsetPt(pages[5], groups[1][1][0]) - 10 * seam.ptPerMm) < 0.001);
  assert.equal(seam.position(state, groups[1][0], 50, 'top'), false);
});

test('ordinary and fractional seam positions are synthetic outlined shapes with no image href', () => {
  const seam = require('../editor-seam.js'); const nodes = [];
  const c = load({ EDOCSeam: seam, uploadedSealEditorState: { pages: [{ pageId: 'p', rotation: 0 }] },
    svgEditorNode: (name, attributes = {}) => ({ name, attributes, textContent: '' }),
  }, ['uploadedEditorSealPositionRect', 'appendUploadedSealPlaceholder']);
  const group = { append: node => nodes.push(node) }, rect = { left: 500, top: 200, width: 80, height: 80 };
  c.appendUploadedSealPlaceholder(group, { pageId: 'p', properties: { sealName: 'synthetic' } }, rect);
  assert.equal(nodes[0].attributes.width, 80); assert.equal(nodes[0].attributes['data-seal-position'], 'true');
  nodes.length = 0;
  c.appendUploadedSealPlaceholder(group, { pageId: 'p', properties: { seamGroupId: 'g', seamMode: 'grouped', seamPartCount: 5, seamPartIndex: 2, seamEdge: 'right', seamPolicyVersion: seam.CURRENT_POLICY } }, rect);
  assert.equal(nodes[0].attributes.width, 16); assert.equal(nodes[0].attributes.x, 564); assert.equal(nodes[1].textContent, '3/5');
  assert.equal(nodes.some(node => node.name === 'image' || node.attributes.href), false);
});
