// Shipping frontend functions with synthetic PDF.js/transport promises only.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const matches = [...source.matchAll(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n[\\s\\S]*?^\\}`, 'gm'))];
  assert.ok(matches.length, name);
  return matches.at(-1)[0];
}
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const settle = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const events = [];
  const canvas = { width: 0, height: 0, style: {}, getContext: () => ({ canvas }), hidden: false };
  const stage = { style: { removeProperty(key) { delete this[key]; } }, hidden: false };
  const runtime = { documentId: 'A', currentPageId: 'P1', renderNonce: 0, renderTask: null, canvasPaint: null, reviewMode: 'edited', zoom: 1, fitPage: false, preparedFileId: 'prepared-A', preparedSha256: 'HASH-A' };
  const h = { events, canvas, stage, runtime, page: { pageId: 'P1', sourceAssetId: 'SOURCE-A', rotation: 0, widthPt: 600, heightPt: 840 }, fitScale: 1 };
  const proxy = () => ({
    getViewport: ({ scale, rotation }) => ({ width: 600 * scale, height: 840 * scale, scale, rotation, transform: [scale, 0, 0, -scale, 0, 840 * scale] }),
    render: () => { events.push('paint'); return { promise: Promise.resolve(), cancel: () => events.push('cancel') }; },
  });
  h.proxy = proxy();h.newProxy = proxy;
  const context = {
    console, session: 'actor-A', document: { querySelector: key => ({ '#uploadedPdfCanvas': canvas, '#uploadedPdfStage': stage })[key] || null },
    window: { devicePixelRatio: 1, pdfjsLib: { AnnotationMode: { DISABLE: 0 } } },
    uploadedSealEditorRuntime: runtime, uploadedSealApplicationRuntime: { epoch: 1 },
    frontendSessionScope: () => context.session,
    currentUploadedEditorPage: () => h.page, uploadedEditorPageRuntime: () => ({ proxy: h.proxy }),
    calculateUploadedEditorFitScale: () => h.fitScale,
    renderUploadedEditorSvgLayer: () => events.push('overlay'), renderUploadedEditorChangeSummary: () => {},
    showToast: message => events.push(['toast', message]),
  };
  vm.createContext(context);
  vm.runInContext(['uploadedSealApplicationScopeSnapshot', 'uploadedSealApplicationScopeIsCurrent', 'paintUploadedPdfCanvas', 'renderUploadedPdfPage', 'renderUploadedReadOnlyPdfProxy'].map(implementation).join('\n'), context);
  h.context = context;return h;
}

test('20 same-page workbench updates paint the immutable PDF once, not 20 times', async () => {
  const h = harness();
  for (let index = 0; index < 20; index++) await h.context.renderUploadedPdfPage();
  assert.equal(h.events.filter(event => event === 'paint').length, 1);
  assert.equal(h.events.filter(event => event === 'overlay').length, 20);
  assert.equal(h.events.filter(event => event === 'cancel').length, 0);
});

test('CSSOM-normalized fractional pixels reuse paint but changed serialized size invalidates it', async () => {
  const h = harness(), values = {};
  for (const property of ['width', 'height']) Object.defineProperty(h.canvas.style, property, {
    get: () => values[property] || '',
    set: value => { values[property] = `${Number(Number.parseFloat(value).toFixed(3))}px`; },
  });
  h.proxy.getViewport = ({ scale, rotation }) => ({
    width: 509.0908952691908 * scale, height: 720 * scale, scale, rotation,
    transform: [scale, 0, 0, -scale, 0, 720 * scale],
  });
  for (let index = 0; index < 20; index++) await h.context.renderUploadedPdfPage();
  assert.equal(h.canvas.style.width, '509.091px');
  assert.equal(h.events.filter(event => event === 'paint').length, 1);
  assert.equal(h.events.filter(event => event === 'cancel').length, 0);
  h.canvas.style.width = '509.092px';
  await h.context.renderUploadedPdfPage();
  assert.equal(h.events.filter(event => event === 'paint').length, 2);
  assert.equal(h.canvas.style.width, '509.091px');
});

test('same-key concurrent updates share the unfinished paint instead of cancelling it', async () => {
  const h = harness(), gate = deferred();
  h.proxy.render = () => { h.events.push('paint'); return { promise: gate.promise, cancel: () => h.events.push('cancel') }; };
  const tasks = Array.from({ length: 20 }, () => h.context.renderUploadedPdfPage());
  assert.equal(h.events.filter(event => event === 'paint').length, 1);
  assert.equal(h.events.filter(event => event === 'cancel').length, 0);
  gate.resolve();await Promise.all(tasks);
  assert.equal(h.events.filter(event => event === 'overlay').length, 1);
});

test('changed page, proxy, rotation, zoom, DPR, fit width or canvas size repaints', async () => {
  const mutations = [
    h => { h.runtime.currentPageId = 'P2';h.page.pageId = 'P2'; },
    h => { h.proxy = h.newProxy(); }, h => { h.page.rotation = 90; },
    h => { h.runtime.zoom = 1.5; }, h => { h.context.window.devicePixelRatio = 2; },
    h => { h.runtime.fitPage = true;h.fitScale = 0.75; },
    h => { h.canvas.width = 1; }, h => { h.canvas.style.width = '1px'; },
  ];
  for (const mutate of mutations) {
    const h = harness();await h.context.renderUploadedPdfPage();mutate(h);await h.context.renderUploadedPdfPage();
    assert.equal(h.events.filter(event => event === 'paint').length, 2);
  }
});

test('different document, epoch or actor cannot reuse the old cached canvas', async () => {
  for (const mutate of [h => { h.runtime.documentId = 'B'; }, h => { h.context.uploadedSealApplicationRuntime.epoch++; }, h => { h.context.session = 'actor-B'; }]) {
    const h = harness();await h.context.renderUploadedPdfPage();mutate(h);await h.context.renderUploadedPdfPage();
    assert.equal(h.events.filter(event => event === 'paint').length, 2);
  }
});

test('new page waits for cancelled old task and old completion cannot poison new cache', async () => {
  const h = harness(), old = deferred();
  h.proxy.render = () => { h.events.push('old-paint'); return { promise: old.promise, cancel: () => h.events.push('old-cancel') }; };
  const first = h.context.renderUploadedPdfPage();
  h.runtime.documentId = 'B';h.runtime.currentPageId = 'P2';h.page.pageId = 'P2';h.proxy = h.newProxy();
  const second = h.context.renderUploadedPdfPage(), third = h.context.renderUploadedPdfPage();
  assert.equal(h.events.filter(event => event === 'paint').length, 0);
  old.reject(Object.assign(new Error('cancelled'), { name: 'RenderingCancelledException' }));
  await Promise.all([first, second, third]);
  assert.equal(h.events.filter(event => event === 'paint').length, 1);
  assert.equal(h.runtime.canvasPaint.proxy, h.proxy);
  await h.context.renderUploadedPdfPage();assert.equal(h.events.filter(event => event === 'paint').length, 1);
  assert.equal(h.events.filter(Array.isArray).length, 0);
});

test('failed and cancelled paint invalidate the cache and allow a real retry', async () => {
  for (const error of [new Error('synthetic renderer failure'), Object.assign(new Error('cancelled'), { name: 'RenderingCancelledException' })]) {
    const h = harness();let attempt = 0;
    h.proxy.render = () => ({ promise: ++attempt === 1 ? Promise.reject(error) : Promise.resolve(), cancel() {} });
    await h.context.renderUploadedPdfPage();assert.equal(h.runtime.canvasPaint, null);
    await h.context.renderUploadedPdfPage();assert.equal(attempt, 2);assert.ok(h.runtime.canvasPaint);
  }
});

test('clearing sensitive previews during paint prevents cache resurrection and stale errors', async () => {
  const h = harness(), gate = deferred();
  h.proxy.render = () => ({ promise: gate.promise, cancel() {} });
  const task = h.context.renderUploadedPdfPage();
  h.runtime.canvasPaint = null;h.runtime.renderNonce++;h.context.uploadedSealApplicationRuntime.epoch++;
  gate.reject(new Error('old private document failed'));await task;
  assert.equal(h.runtime.canvasPaint, null);assert.equal(h.events.filter(Array.isArray).length, 0);
});

test('read-only prepared preview also reuses same version but repaints changed locked version', async () => {
  const h = harness();h.runtime.reviewMode = 'prepared';
  for (let index = 0; index < 5; index++) await h.context.renderUploadedReadOnlyPdfProxy(h.proxy, 0, 'preview', 0, 'prepared');
  assert.equal(h.events.filter(event => event === 'paint').length, 1);
  h.runtime.preparedFileId = 'prepared-B';await h.context.renderUploadedReadOnlyPdfProxy(h.proxy, 0, 'preview', 0, 'prepared');
  assert.equal(h.events.filter(event => event === 'paint').length, 2);
});

function uploadHarness() {
  const draft = deferred(), hash = deferred(), calls = [], events = [];
  const runtime = { documentId: '' };
  const context = {
    session: 'actor-A', uploadedSealEditorRuntime: runtime, uploadedSealApplicationRuntime: { epoch: 1 },
    frontendSessionScope: () => context.session,
    ensureUploadedEditorDraft: async () => { events.push('draft-start');const id = await draft.promise;runtime.documentId = id;return id; },
    hashBlob: () => { events.push('hash-start');return hash.promise; },
    backendRequest: async (url, options) => { calls.push({ url, payload: JSON.parse(options.body) });return { upload_id: 'UPLOAD' }; },
  };
  vm.createContext(context);
  vm.runInContext(['uploadedSealApplicationScopeSnapshot', 'uploadedSealApplicationScopeIsCurrent', 'requestEditorUpload'].map(implementation).join('\n'), context);
  return { context, draft, hash, calls, events, file: { name: 'synthetic.pdf', type: 'application/pdf', size: 10 } };
}

test('draft and hash start together; intent waits for both and posts exactly once', async () => {
  const h = uploadHarness(), task = h.context.requestEditorUpload(h.file);
  assert.deepEqual(h.events, ['draft-start', 'hash-start']);
  h.draft.resolve('A');await settle();assert.equal(h.calls.length, 0);
  h.hash.resolve('HASH');const intent = await task;
  assert.equal(h.calls.length, 1);assert.equal(h.calls[0].url, '/official-documents/A/editor-uploads');
  assert.equal(h.calls[0].payload.sha256, 'HASH');assert.equal(intent.documentId, 'A');
});

test('hash finishing first still cannot request an intent before draft authorization', async () => {
  const h = uploadHarness(), task = h.context.requestEditorUpload(h.file);
  h.hash.resolve('HASH');await settle();assert.equal(h.calls.length, 0);
  h.draft.resolve('A');await task;assert.equal(h.calls.length, 1);
});

test('either preparation failure stops intent creation, and both failures are observed', async () => {
  const h = uploadHarness(), task = h.context.requestEditorUpload(h.file);
  h.hash.reject(new Error('hash failed'));h.draft.reject(new Error('permission denied'));
  await assert.rejects(task, /permission denied/);assert.equal(h.calls.length, 0);
  const another = uploadHarness(), second = another.context.requestEditorUpload(another.file);
  another.draft.reject(new Error('permission denied'));another.hash.resolve('HASH');
  await assert.rejects(second, /permission denied/);assert.equal(another.calls.length, 0);
});

test('hash failure waits for started draft to settle so late success cannot overwrite error UI', async () => {
  const h = uploadHarness(), task = h.context.requestEditorUpload(h.file);let finished = false;
  task.catch(() => { finished = true; });h.hash.reject(new Error('hash failed'));await settle();assert.equal(finished, false);
  h.draft.resolve('A');await assert.rejects(task, /hash failed/);assert.equal(h.calls.length, 0);
});

test('scope change while preparing never creates an upload intent for the new session', async () => {
  const h = uploadHarness(), task = h.context.requestEditorUpload(h.file);
  h.context.session = 'actor-B';h.draft.resolve('A');h.hash.resolve('HASH');
  await assert.rejects(task, /登入或草稿已切換/);assert.equal(h.calls.length, 0);
});

test('created draft never claims the pending upload is saved while authorization is unfinished', async () => {
  const h = uploadHarness(), authorization = deferred(), statuses = [], requests = [];
  Object.assign(h.context, {
    uploadedSealEditorState: { revisionNo: 0 },
    uploadedEditorDraftPrerequisiteIssue: () => null,
    uploadedEditorV2FeatureEnabled: () => true,
    editorDraftPayload: () => ({ company_id: 'company-A' }),
    rememberUploadedEditorSavedSealBindings() {},
    uploadedSealApplicationKey: () => 'APPLICATION-A',
    scheduleUploadedSealApplicationSave() {},
    setUploadedEditorSaveStatus: (...args) => statuses.push(args),
    backendRequest: async url => {
      requests.push(url);
      if (url === '/official-documents/editor-drafts') return { document_id: 'A' };
      return authorization.promise;
    },
  });
  h.context.uploadedSealEditorRuntime.uploading = true;
  vm.runInContext(implementation('ensureUploadedEditorDraft'), h.context);
  const task = h.context.requestEditorUpload(h.file);
  h.hash.resolve('HASH');await settle();
  assert.deepEqual(requests, ['/official-documents/editor-drafts', '/official-documents/A/editor-uploads']);
  assert.equal(statuses.at(-1)[0], 'checking');
  assert.match(statuses.at(-1)[1], /正在準備上傳/);
  assert.equal(statuses.some(([state]) => state === 'saved'), false);
  authorization.resolve({ upload_id: 'UPLOAD' });await task;

  // Creating an independent, non-uploading draft retains its saved feedback.
  h.context.uploadedSealEditorRuntime.documentId = '';
  h.context.uploadedSealEditorRuntime.uploading = false;
  await h.context.ensureUploadedEditorDraft();
  assert.deepEqual(statuses.at(-1), ['saved', '私密草稿已建立']);
});
