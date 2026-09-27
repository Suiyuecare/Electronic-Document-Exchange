// Synthetic data only; no real PDFs, stamp assets, credentials or network.
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

function libraryHarness(testImport) {
  const context = { window: {}, testImport };
  vm.createContext(context);
  vm.runInContext(implementation('ensurePdfJsLibrary').replace(/import\((`[^`]*`)\)/, 'testImport($1)'), context);
  return context;
}

test('a failed PDF module load retries a fresh URL and then reuses the loaded library', async () => {
  const urls = [];
  const library = { getDocument() {}, GlobalWorkerOptions: {} };
  const context = libraryHarness(url => {
    urls.push(url);
    return urls.length === 1 ? Promise.reject(new Error('synthetic offline')) : Promise.resolve(library);
  });
  await assert.rejects(context.ensurePdfJsLibrary(), /載入失敗/);
  assert.equal(context.window.pdfjsLibPromise, null);
  assert.equal(await context.ensurePdfJsLibrary(), library);
  assert.equal(await context.ensurePdfJsLibrary(), library);
  assert.deepEqual(urls, ['./vendor/pdfjs/pdf.min.mjs?v=4.2.67', './vendor/pdfjs/pdf.min.mjs?v=4.2.67&retry=1']);
  assert.equal(library.GlobalWorkerOptions.workerSrc, 'vendor/pdfjs/pdf.worker.min.mjs?v=4.2.67');
});

test('concurrent PDF module requests share one import', async () => {
  let attempts = 0, resolve;
  const library = { getDocument() {}, GlobalWorkerOptions: {} };
  const context = libraryHarness(() => { attempts += 1; return new Promise(done => { resolve = done; }); });
  const first = context.ensurePdfJsLibrary(), second = context.ensurePdfJsLibrary();
  assert.equal(attempts, 1);
  resolve(library);
  assert.equal(await first, library);
  assert.equal(await second, library);
});

test('PDF module retries are bounded and offer a page refresh after three failures', async () => {
  const urls = [];
  const context = libraryHarness(url => { urls.push(url); return Promise.reject(new Error('synthetic offline')); });
  for (let i = 0; i < 3; i += 1) await assert.rejects(context.ensurePdfJsLibrary(), /載入失敗/);
  await assert.rejects(context.ensurePdfJsLibrary(), /重新整理/);
  assert.equal(urls.length, 3);
  assert.equal(new Set(urls).size, 3);
});

test('an externally preloaded rejected promise is released and its failed URL is not reused', async () => {
  const urls = [];
  const library = { getDocument() {}, GlobalWorkerOptions: {} };
  const context = libraryHarness(url => { urls.push(url); return Promise.resolve(library); });
  context.window.pdfjsLibPromise = Promise.reject(new Error('synthetic rejected bootstrap'));
  await assert.rejects(context.ensurePdfJsLibrary(), /載入失敗/);
  assert.equal(context.window.pdfjsLibPromise, null);
  assert.equal(context.window.pdfjsLibLoadAttempts, 1);
  assert.equal(await context.ensurePdfJsLibrary(), library);
  assert.deepEqual(urls, ['./vendor/pdfjs/pdf.min.mjs?v=4.2.67&retry=1']);
});

test('the actual bootstrap consumes preload failure and shares the bounded retry budget', async () => {
  const urls = [];
  const library = { getDocument() {}, GlobalWorkerOptions: {} };
  const context = libraryHarness(url => {
    urls.push(url);
    return urls.length < 3 ? Promise.reject(new Error('synthetic offline')) : Promise.resolve(library);
  });
  const bootstrap = fs.readFileSync(path.join(__dirname, '..', 'pdfjs-bootstrap.mjs'), 'utf8');
  vm.runInContext(bootstrap.replace(/import\((`[^`]*`)\)/, 'testImport($1)'), context);
  const preload = context.window.pdfjsLibPromise;
  await assert.rejects(preload, /synthetic offline/);
  assert.equal(context.window.pdfjsLibPromise, null);
  assert.equal(context.window.pdfjsLibLoadAttempts, 1);
  await assert.rejects(context.ensurePdfJsLibrary(), /載入失敗/);
  assert.equal(await context.ensurePdfJsLibrary(), library);
  assert.deepEqual(urls, [
    './vendor/pdfjs/pdf.min.mjs?v=4.2.67',
    './vendor/pdfjs/pdf.min.mjs?v=4.2.67&retry=1',
    './vendor/pdfjs/pdf.min.mjs?v=4.2.67&retry=2',
  ]);
  assert.equal(context.window.pdfjsLibLoadAttempts, 3);
  assert.equal(library.GlobalWorkerOptions.workerSrc, 'vendor/pdfjs/pdf.worker.min.mjs?v=4.2.67');
  vm.runInContext(bootstrap.replace(/import\((`[^`]*`)\)/, 'testImport($1)'), context);
  assert.equal(urls.length, 3, 'loaded bootstrap does not import twice');
});

test('failed bootstrap plus two editor failures exhaust three total loads', async () => {
  const urls = [];
  const context = libraryHarness(url => { urls.push(url); return Promise.reject(new Error('synthetic offline')); });
  const bootstrap = fs.readFileSync(path.join(__dirname, '..', 'pdfjs-bootstrap.mjs'), 'utf8');
  vm.runInContext(bootstrap.replace(/import\((`[^`]*`)\)/, 'testImport($1)'), context);
  await assert.rejects(context.window.pdfjsLibPromise, /synthetic offline/);
  for (let i = 0; i < 2; i += 1) await assert.rejects(context.ensurePdfJsLibrary(), /載入失敗/);
  await assert.rejects(context.ensurePdfJsLibrary(), /重新整理/);
  vm.runInContext(bootstrap.replace(/import\((`[^`]*`)\)/, 'testImport($1)'), context);
  assert.equal(urls.length, 3);
});

const fallbackFixture = {
  item: { id: 'TEST-DOC', source_type: 'uploaded_pdf', current_status: 'stamped', stamped_file_id: 'TEST-FINAL', can_download: true },
  files: [{ id: 'TEST-FINAL', document_id: 'TEST-DOC', file_type: 'stamped_pdf' }]
};
const fixture = process.env.EDOC_FILE_VISIBILITY_FIXTURE ? JSON.parse(process.env.EDOC_FILE_VISIBILITY_FIXTURE) : fallbackFixture;

function queueHarness(item = fixture.item) {
  const buttons = [];
  const list = { innerHTML: '', querySelectorAll: selector => selector === '[data-electronic-seal-download]' ? buttons : [] };
  const count = { textContent: '' };
  const context = {
    officialWorkflowItems: [structuredClone(item)], officialWorkflowPage: { hasMore: false },
    document: { querySelector: selector => selector === '#electronicSealWorkQueueList' ? list : selector === '#electronicSealWorkQueueCount' ? count : null },
    ensureElectronicSealWorkQueue() {}, officialDocumentPriority: () => 0, officialDocumentHasEditorV2: () => false,
    escapeHtml: String, officialStatusLabel: String, officialDocumentCanConfirm: () => false,
    officialDocumentIsApplicant: () => false,
  };
  vm.createContext(context);
  vm.runInContext(['electronicSealWorkflowItems', 'renderElectronicSealWorkQueue'].map(implementation).join('\n'), context);
  return { context, list, buttons };
}

test('a real slim listing row exposes its committed download without file collections', () => {
  assert.equal(Object.hasOwn(fixture.item, 'files'), false);
  assert.ok(fixture.files.some(file => file.id === fixture.item.stamped_file_id));
  const { context, list } = queueHarness();
  context.renderElectronicSealWorkQueue();
  assert.match(list.innerHTML, /data-electronic-seal-download="TEST-FINAL"/);
  assert.match(list.innerHTML, /data-document-id="TEST-DOC"/);
});

test('the queue hides download for missing permissions or uncommitted candidates', () => {
  for (const item of [{ ...fixture.item, can_download: false }, { ...fixture.item, can_download: undefined }, { ...fixture.item, stamped_file_id: '' }]) {
    const { context, list } = queueHarness(item);
    context.renderElectronicSealWorkQueue();
    assert.doesNotMatch(list.innerHTML, /data-electronic-seal-download=/);
  }
});

function downloadHarness(detail) {
  let scope = 'synthetic-session';
  const calls = [], notices = [];
  const context = {
    authState: { token: 'synthetic-session-token' },
    frontendSessionScope: () => scope, backendRequest: async url => { calls.push(['detail', url]); return detail; },
    downloadOfficialWorkflowFile: async (...args) => { calls.push(['download', ...args]); return true; },
    showToast: message => notices.push(message),
  };
  vm.createContext(context);
  vm.runInContext(['officialApplicationFiles', 'officialIsElectronicCompose', 'latestOfficialStampedFile', 'downloadElectronicSealFinalFile'].map(implementation).join('\n'), context);
  return { context, calls, notices, changeSession: () => { scope = 'other-session'; } };
}

function detailedItem(overrides = {}) {
  return { ...fixture.item, files: [{ id: 'TEST-NEWER-CANDIDATE', document_id: 'TEST-DOC', file_type: 'stamped_pdf' }, ...fixture.files], ...overrides };
}

test('fresh detail authorizes only the exact committed final file, not a newer candidate', async () => {
  const h = downloadHarness(detailedItem());
  assert.equal(await h.context.downloadElectronicSealFinalFile('TEST-DOC', 'TEST-FINAL'), true);
  assert.deepEqual(h.calls, [['detail', '/official-documents/TEST-DOC'], ['download', 'TEST-DOC', 'TEST-FINAL']]);
});

test('revoked access, different cases and missing exact final files fail closed', async () => {
  for (const detail of [
    detailedItem({ can_download: false }), detailedItem({ id: 'OTHER-CASE' }),
    detailedItem({ files: [] }), detailedItem({ stamped_file_id: 'TEST-NEWER-CANDIDATE' }),
    detailedItem({ files: [{ id: 'TEST-FINAL', file_type: 'prepared_pdf' }] }),
    detailedItem({ files: [{ id: 'TEST-FINAL', document_id: 'OTHER-CASE', file_type: 'stamped_pdf' }] }),
  ]) {
    const h = downloadHarness(detail);
    assert.equal(await h.context.downloadElectronicSealFinalFile('TEST-DOC', 'TEST-FINAL'), false);
    assert.equal(h.calls.filter(call => call[0] === 'download').length, 0);
    assert.equal(h.notices.length, 1);
  }
});

test('a session change while fresh detail is pending does not download old-session evidence', async () => {
  const h = downloadHarness(detailedItem());
  h.context.backendRequest = async () => { h.changeSession(); return detailedItem(); };
  assert.equal(await h.context.downloadElectronicSealFinalFile('TEST-DOC', 'TEST-FINAL'), false);
  assert.equal(h.calls.length, 0);
  assert.equal(h.notices.length, 0);
});

test('same-account re-login during fresh detail blocks the prior session download', async () => {
  const h = downloadHarness(detailedItem());
  h.context.backendRequest = async () => {
    h.context.authState = null;
    h.context.authState = { token: 'new-synthetic-session-token' };
    return detailedItem();
  };
  assert.equal(await h.context.downloadElectronicSealFinalFile('TEST-DOC', 'TEST-FINAL'), false);
  assert.equal(h.calls.length, 0);
  assert.equal(h.notices.length, 0);
});

test('electronic compose final output validates a committed generated PDF', async () => {
  const h = downloadHarness(detailedItem({ source_type: 'blank_editor', output_mode: 'electronic', document_type: 'outgoing_official_document', requires_stamp: false, files: [{ ...fixture.files[0], file_type: 'generated_pdf' }] }));
  assert.equal(await h.context.downloadElectronicSealFinalFile('TEST-DOC', 'TEST-FINAL'), true);
});

test('download entry disables duplicate clicks and restores its label after a failure', async () => {
  const h = queueHarness();
  let click, release, requests = 0;
  const button = { disabled: false, isConnected: true, textContent: '下載用印後檔案', dataset: { documentId: 'TEST-DOC', electronicSealDownload: 'TEST-FINAL' }, addEventListener: (_, callback) => { click = callback; } };
  h.buttons.push(button);
  h.context.downloadElectronicSealFinalFile = () => { requests += 1; return new Promise(done => { release = done; }); };
  h.context.renderElectronicSealWorkQueue();
  const pending = click();
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, '準備下載…');
  await click();
  assert.equal(requests, 1);
  release(false);
  await pending;
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, '下載用印後檔案');
});

const settle = () => new Promise(resolve => setImmediate(resolve));
function workflowDownloadHarness(fetch) {
  let scope = 'session-A', timerId = 0;
  const timers = new Map(), calls = [], notices = [], events = [], anchors = [];
  const clock = {
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  const c = {
    AbortController, ...clock, window: { ...clock }, backendApiBase: '/api',
    authState: { token: 'synthetic-token' }, isHeaderSafeToken: () => true,
    frontendSessionScope: () => scope, showToast: message => notices.push(message),
    fetch: async (...args) => { calls.push(args); return fetch(...args); },
    URL: { createObjectURL: () => { events.push('create-url'); return 'blob:synthetic'; }, revokeObjectURL: () => events.push('revoke-url') },
    document: {
      createElement: () => {
        const anchor = { click: () => events.push('click'), remove: () => events.push('remove') };
        anchors.push(anchor); return anchor;
      },
      body: { append: () => events.push('append') },
    },
  };
  vm.createContext(c);
  vm.runInContext(['fetchWithDeadline', 'downloadOfficialWorkflowFile'].map(implementation).join('\n'), c);
  const changeSession = () => { scope = 'session-B'; c.authState.token = 'other-token'; };
  async function fire(ms) {
    await settle();
    const entry = [...timers].find(([, timer]) => timer.ms === ms);
    assert.ok(entry, `timer ${ms} exists`);
    timers.delete(entry[0]); entry[1].fn(); await settle();
  }
  return { c, calls, notices, events, anchors, timers, fire, changeSession };
}
function downloadResponse(disposition = '', overrides = {}) {
  return { ok: true, status: 200, headers: { get: () => disposition }, blob: async () => ({ syntheticPdf: true }), text: async () => '', ...overrides };
}

test('a stalled download body is bounded and never creates a download target', async () => {
  const h = workflowDownloadHarness(async () => downloadResponse('', { blob: () => new Promise(() => {}) }));
  const pending = h.c.downloadOfficialWorkflowFile('TEST-DOC', 'TEST-FINAL');
  await h.fire(45000);
  assert.equal(await pending, false);
  assert.equal(h.calls[0][1].signal.aborted, true);
  assert.equal(h.notices.length, 1);
  assert.deepEqual(h.events, []);
  assert.equal(h.timers.size, 0);
});

test('logout while a download body is pending suppresses the old-session file and notices', async () => {
  let release;
  const h = workflowDownloadHarness(async () => downloadResponse('', { blob: () => new Promise(resolve => { release = resolve; }) }));
  const pending = h.c.downloadOfficialWorkflowFile('TEST-DOC', 'TEST-FINAL');
  await settle(); h.changeSession(); release({ syntheticPdf: true });
  assert.equal(await pending, false);
  assert.deepEqual(h.events, []);
  assert.equal(h.notices.length, 0);
  assert.equal(h.timers.size, 0);
});

test('same-account re-login during body read cannot download the earlier session response', async () => {
  let release;
  const h = workflowDownloadHarness(async () => downloadResponse('', { blob: () => new Promise(resolve => { release = resolve; }) }));
  const pending = h.c.downloadOfficialWorkflowFile('TEST-DOC', 'TEST-FINAL');
  await settle();
  h.c.authState = null;
  h.c.authState = { token: 'new-synthetic-session-token' };
  release({ syntheticPdf: true });
  assert.equal(await pending, false);
  assert.deepEqual(h.events, []);
  assert.equal(h.notices.length, 0);
});

test('session changes before headers or before anchor click fail closed with cleanup', async () => {
  let bodyReads = 0;
  const headers = workflowDownloadHarness(async () => {
    headers.changeSession();
    return downloadResponse('', { blob: async () => { bodyReads += 1; return {}; } });
  });
  assert.equal(await headers.c.downloadOfficialWorkflowFile('TEST-DOC', 'TEST-FINAL'), false);
  assert.equal(bodyReads, 0);
  assert.equal(headers.events.length, 0);
  const anchor = workflowDownloadHarness(async () => downloadResponse());
  anchor.c.document.body.append = () => { anchor.events.push('append'); anchor.changeSession(); };
  assert.equal(await anchor.c.downloadOfficialWorkflowFile('TEST-DOC', 'TEST-FINAL'), false);
  assert.deepEqual(anchor.events, ['create-url', 'append', 'remove']);
  await anchor.fire(1000);
  assert.equal(anchor.events.at(-1), 'revoke-url');
});

test('download filenames handle RFC5987, legacy names and unsafe path characters', async () => {
  for (const [disposition, expected] of [
    ["attachment; filename=legacy.pdf; filename*=UTF-8''%E5%90%88%E7%B4%84.pdf", '合約.pdf'],
    ['attachment; filename="%E6%B8%AC%E8%A9%A6.pdf"', '測試.pdf'],
    ['attachment; filename="bad%ZZ.pdf"', 'bad%ZZ.pdf'],
    ['attachment; filename="../nested\\name%0A.pdf"', 'name.pdf'],
    ['', 'official-document.pdf'],
  ]) {
    const h = workflowDownloadHarness(async () => downloadResponse(disposition));
    assert.equal(await h.c.downloadOfficialWorkflowFile('TEST / DOC', 'TEST / FINAL'), true);
    assert.equal(h.anchors[0].download, expected);
    assert.deepEqual(h.events, ['create-url', 'append', 'click', 'remove']);
    assert.equal(h.calls[0][0], '/api/official-documents/TEST%20%2F%20DOC/files/TEST%20%2F%20FINAL/download');
    assert.equal(h.calls[0][1].headers.Authorization, 'Bearer synthetic-token');
    assert.equal(h.calls[0][1].cache, 'no-store');
    await h.fire(1000);
    assert.equal(h.events.at(-1), 'revoke-url');
    assert.equal(h.notices.length, 0);
  }
});

test('a revoked download fails without a file and a stalled error body is also bounded', async () => {
  for (const stalled of [false, true]) {
    const h = workflowDownloadHarness(async () => downloadResponse('', {
      ok: false, status: 403,
      text: stalled ? () => new Promise(() => {}) : async () => 'Access revoked',
    }));
    const pending = h.c.downloadOfficialWorkflowFile('TEST-DOC', 'TEST-FINAL');
    if (stalled) await h.fire(45000);
    assert.equal(await pending, false);
    assert.equal(h.notices.length, 1);
    assert.equal(h.events.length, 0);
  }
});

function uncertainUploadHarness() {
  const calls = [], nodes = new Map();
  let reloads = 0;
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, { value: '', hidden: false, disabled: false, textContent: '', click() { calls.push('picker'); }, setAttribute() {}, removeAttribute() {} });
    return nodes.get(selector);
  };
  const uncertain = Object.assign(new Error('Mutation response lost; reload to confirm'), { outcomeUnknown: true, retryable: true, code: 'request_timeout' });
  const c = {
    File, performance, console, PDF_EDITOR_MAX_FILE_BYTES: 50 * 1024 * 1024,
    document: { querySelector: node }, window: { location: { reload: () => { reloads += 1; } } },
    uploadedSealEditorRuntime: { documentId: '', reviewMode: 'edited', savedGeneration: 0, dirtyGeneration: 0 },
    uploadedSealEditorState: { pages: [] }, uploadedSealApplicationRuntime: {},
    uploadedPdfUploadBlockingMessage: () => '', uploadedEditorDraftPrerequisiteIssue: () => null,
    uploadedEditorV2FeatureEnabled: () => true, editorDraftPayload: () => ({ synthetic: true }),
    uploadedSealApplicationScopeSnapshot: () => ({ session: 'fixture' }), uploadedSealApplicationScopeIsCurrent: () => true,
    backendRequest: async path => { calls.push(path); throw uncertain; }, hashBlob: async () => 'synthetic-sha',
    confirmUploadedPdfConversion: async () => ({ report: { valid: true }, sha256: 'synthetic-sha' }),
    saveUploadedEditorState: async () => {}, discardUploadedPdfPreparation() {},
    assertEditorUploadCurrent() {},
    renderUploadedSealWorkbench() {}, setUploadedPdfUploadProgress() {}, setUploadedPdfA4Status() {}, setUploadedEditorSaveStatus() {},
    showToast() {}, pdfA4UiErrorMessage: error => error.message,
    clearUploadedEditorUploadError: () => { c.uploadedSealEditorRuntime.uploadRetry = null; },
    openUploadedPdfPicker: () => calls.push('picker'),
  };
  vm.createContext(c);
  vm.runInContext(['ensureUploadedEditorDraft', 'requestEditorUpload', 'reportEditorUploadFailure',
    'showUploadedEditorUploadError', 'retryUploadedEditorUpload', 'handleUploadedSealPdfChange',
    'handleUploadedEditorImportPdf'].map(implementation).join('\n'), c);
  const file = new File(['synthetic'], 'fixture.pdf', { type: 'application/pdf' });
  return { c, calls, node, file, uncertain, reloads: () => reloads };
}

test('unknown draft creation offers explicit reconciliation, not another create or file picker', async () => {
  for (const mode of ['source', 'import']) {
    const h = uncertainUploadHarness();
    const pending = mode === 'source' ? h.c.handleUploadedSealPdfChange(h.file) : h.c.handleUploadedEditorImportPdf([h.file]);
    if (mode === 'source') await pending;
    else await assert.rejects(pending, error => error === h.uncertain);
    assert.deepEqual(h.calls, ['/official-documents/editor-drafts']);
    assert.equal(h.reloads(), 0, 'never auto reload');
    assert.equal(h.node('#uploadedEditorRetryUploadBtn').textContent, '重新載入確認');
    assert.equal(h.c.uploadedSealEditorRuntime.uploading, false);
    await h.c.retryUploadedEditorUpload();
    assert.equal(h.reloads(), 1);
    assert.deepEqual(h.calls, ['/official-documents/editor-drafts'], 'recovery did not recreate or quarantine');
  }
});

test('a response-lost non-A4 finalization is not reported as failed or retried as a new upload', async () => {
  const h = uncertainUploadHarness();
  const intent = { documentId: 'TEST-DOC', upload_id: 'TEST-UPLOAD', scope: { session: 'fixture' } };
  h.c.confirmUploadedPdfConversion = async () => ({ report: { valid: false } });
  h.c.requestEditorUpload = async () => intent;
  h.c.AbortController = AbortController;
  h.c.performTusUpload = async () => { h.calls.push('TUS'); };
  h.c.finalizeEditorUpload = async () => { h.calls.push('finalize'); throw h.uncertain; };
  await h.c.handleUploadedSealPdfChange(h.file);
  assert.deepEqual(h.calls, ['TUS', 'finalize']);
  assert.equal(h.node('#uploadedEditorRetryUploadBtn').textContent, '重新載入確認');
  await h.c.retryUploadedEditorUpload();
  assert.equal(h.reloads(), 1);
  assert.deepEqual(h.calls, ['TUS', 'finalize']);
});

test('failure reporting preserves unknown server outcomes but still reports definite failure', async () => {
  const h = uncertainUploadHarness();
  const intent = { documentId: 'TEST-DOC', upload_id: 'TEST-UPLOAD', scope: { session: 'fixture' } };
  await h.c.reportEditorUploadFailure(intent, h.uncertain);
  assert.equal(h.calls.length, 0);
  h.c.editorUploadFailureCode = () => 'editor_upload_client_failed';
  h.c.backendRequest = async path => { h.calls.push(path); };
  await h.c.reportEditorUploadFailure(intent, new Error('definite validation failure'));
  assert.deepEqual(h.calls, ['/official-documents/TEST-DOC/editor-uploads/TEST-UPLOAD/fail']);
});

test('pending finalization recovery retains its exact intent and does not reload or re-upload', async () => {
  const h = uncertainUploadHarness();
  const pending = { intent: { documentId: 'TEST-DOC', upload_id: 'TEST-UPLOAD' } };
  h.c.uploadedSealEditorRuntime.pendingFinalization = pending;
  h.c.finishPendingEditorPdfFinalization = async actual => { assert.equal(actual, pending); h.calls.push('same-intent-finalize'); };
  await h.c.retryUploadedEditorUpload();
  assert.deepEqual(h.calls, ['same-intent-finalize']);
  assert.equal(h.reloads(), 0);
});
