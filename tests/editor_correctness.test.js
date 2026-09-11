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
