// Shipping transport functions; deidentified URLs and synthetic response bodies.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const start = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(start, `Shipping function ${name} exists`);
  const rest = source.slice(start.index + start[0].length);
  const next = /^\n(?:async )?function \w+\(/m.exec(rest);
  assert.ok(next);
  return source.slice(start.index, start.index + start[0].length + next.index);
}
const names = ['fetchWithDeadline', 'backendRequest', 'editorTusResponseError',
  'waitForTusRetry', 'editorTusRemoteOffset', 'performTusUpload',
  'fetchEditorAuthorizedBlob', 'isRetryableAuthError', 'waitForAuthRetry',
  'backendAuthRequestWithTransientRetry'];
const settle = () => new Promise(resolve => setImmediate(resolve));
const never = () => new Promise(() => {});
function response(status = 204, headers = {}, body = '') {
  return { ok: status >= 200 && status < 300, status,
    headers: { get: name => headers[name] ?? null },
    text: async () => body, blob: async () => new Blob([body]) };
}
function harness(fetch = never) {
  const timers = new Map(); let nextTimer = 0; const calls = [];
  const clock = {
    setTimeout(fn, ms) { const id = ++nextTimer; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  const c = {
    console, URL, Blob, File, AbortController, TypeError, ...clock,
    window: { ...clock, location: { href: 'https://fixture.invalid/', origin: 'https://fixture.invalid' } },
    backendApiBase: '/api', authState: { token: '' }, isHeaderSafeToken: () => false,
    friendlyBackendErrorMessage: message => message,
    assertEditorUploadCurrent() {},
    validateEditorTusEndpoint: intent => intent.upload_url,
    editorTusIntentHeaders: () => ({}), tusMetadataValue: value => String(value),
    fetch: (url, options) => { calls.push({ url, options }); return fetch(url, options); },
  };
  vm.createContext(c); vm.runInContext(names.map(implementation).join('\n'), c);
  async function fire(ms) {
    await settle();
    const entry = [...timers].find(([, timer]) => timer.ms === ms);
    assert.ok(entry, `timer ${ms} exists`);
    timers.delete(entry[0]); entry[1].fn(); await settle();
  }
  return { c, calls, timers, fire };
}
const timeoutError = error => error.name === 'TimeoutError' && error.retryable === true;
const cancelled = error => error.name === 'AbortError' && error.retryable === false;
const file = new File(['deidentified'], 'fixture.pdf', { type: 'application/pdf' });
const intent = { protocol: 'tus', upload_url: 'https://fixture.invalid/storage/v1/upload/resumable/sign',
  bucket: 'fixture', path: 'deidentified.pdf' };

test('fetch which ignores abort is rejected by deadline and clears timer', async () => {
  const h = harness(); const pending = h.c.fetchWithDeadline('/fixture', {}, { timeoutMs: 25 });
  const rejection = assert.rejects(pending, timeoutError);
  await h.fire(25); await rejection;
  assert.equal(h.calls[0].options.signal.aborted, true);
  assert.equal(h.timers.size, 0);
});
test('deadline covers response body, not merely response headers', async () => {
  const h = harness(async () => ({ text: never }));
  const pending = h.c.fetchWithDeadline('/fixture', {}, { timeoutMs: 30, read: r => r.text() });
  const rejection = assert.rejects(pending, timeoutError);
  await h.fire(30); await rejection;
});
test('external cancellation rejects a noncooperative fetch without retry', async () => {
  const h = harness(); const controller = new AbortController();
  const pending = h.c.fetchWithDeadline('/fixture', { signal: controller.signal });
  const rejection = assert.rejects(pending, cancelled);
  await settle(); controller.abort(); await rejection;
  assert.equal(h.calls.length, 1); assert.equal(h.timers.size, 0);
});
test('already cancelled request never reaches fetch', async () => {
  const h = harness(); const controller = new AbortController(); controller.abort();
  await assert.rejects(h.c.fetchWithDeadline('/fixture', { signal: controller.signal }), cancelled);
  assert.equal(h.calls.length, 0); assert.equal(h.timers.size, 0);
});
test('successful read removes deadline and preserves body result', async () => {
  const h = harness(async () => response(200, {}, 'synthetic'));
  assert.equal(await h.c.fetchWithDeadline('/fixture', {}, { read: r => r.text() }), 'synthetic');
  assert.equal(h.timers.size, 0); assert.equal(h.calls[0].options.signal.aborted, false);
});
test('metadata mutation times out without automatic duplicate POST', async () => {
  const h = harness(); const pending = h.c.backendRequest('/fixture', { method: 'POST', timeoutMs: 40, body: '{}' });
  const rejection = assert.rejects(pending, error => timeoutError(error) && error.outcomeUnknown === true && error.message.includes('避免重複送出'));
  await h.fire(40); await rejection;
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].options.method, 'POST');
  assert.equal('timeoutMs' in h.calls[0].options, false);
});
test('metadata reads default to20s and heavy mutations to120s', async () => {
  for (const [path, method, deadline] of [['/fixture', 'GET', 20000],
    ['/fixture/editor-preflight', 'POST', 120000], ['/fixture/convert-a4', 'POST', 120000],
    ['/fixture/editor-uploads/UP/finalize', 'POST', 120000], ['/pdf/generate', 'POST', 120000],
    ['/fixture/submit', 'POST', 120000]]) {
    const h = harness(); const pending = h.c.backendRequest(path, { method });
    const rejection = assert.rejects(pending, timeoutError);
    await h.fire(deadline); await rejection;
    assert.equal(h.calls.length, 1);
  }
});
test('prefetched metadata body is bounded without a second fetch', async () => {
  const h = harness(); const pending = h.c.backendRequest('/fixture', { timeoutMs: 50 }, { text: never });
  const rejection = assert.rejects(pending, timeoutError);
  await h.fire(50); await rejection; assert.equal(h.calls.length, 0);
});
test('TUS creation timeout leaves a fresh intent decision to caller', async () => {
  const h = harness(); const pending = h.c.performTusUpload(file, { ...intent });
  const rejection = assert.rejects(pending, timeoutError);
  await h.fire(120000); await rejection;
  assert.deepEqual(h.calls.map(call => call.options.method), ['POST']);
});
test('TUS chunk timeout probes offset and continues only unsent bytes', async () => {
  let patchCount = 0;
  const h = harness(async (_url, options) => {
    if (options.method === 'POST') return response(201, { Location: '/storage/v1/upload/resumable/sign/fixture' });
    if (options.method === 'HEAD') return response(200, { 'Upload-Offset': '3' });
    if (++patchCount === 1) return never();
    return response(204, { 'Upload-Offset': String(file.size) });
  });
  const pending = h.c.performTusUpload(file, { ...intent });
  await h.fire(120000); await h.fire(1000);
  const result = await pending;
  assert.equal(result.offset, file.size);
  assert.deepEqual(h.calls.map(call => call.options.method), ['POST', 'PATCH', 'HEAD', 'PATCH']);
  assert.equal(h.calls.at(-1).options.headers['Upload-Offset'], '3');
  assert.equal(h.calls.at(-1).options.body.size, file.size - 3);
  assert.equal(h.timers.size, 0);
});
test('cancelled TUS chunk does not retry or probe offset', async () => {
  const h = harness(async (_url, options) => options.method === 'POST'
    ? response(201, { Location: '/storage/v1/upload/resumable/sign/fixture' }) : never());
  const controller = new AbortController();
  const pending = h.c.performTusUpload(file, { ...intent }, () => {}, { signal: controller.signal });
  const rejection = assert.rejects(pending, cancelled);
  await settle(); controller.abort(); await rejection;
  assert.deepEqual(h.calls.map(call => call.options.method), ['POST', 'PATCH']);
});
test('cancelled retry backoff ends immediately and makes no HEAD request', async () => {
  const h = harness(async (_url, options) => options.method === 'POST'
    ? response(201, { Location: '/storage/v1/upload/resumable/sign/fixture' }) : response(503));
  const controller = new AbortController();
  const pending = h.c.performTusUpload(file, { ...intent }, () => {}, { signal: controller.signal });
  const rejection = assert.rejects(pending, cancelled);
  await settle(); assert.ok([...h.timers.values()].some(timer => timer.ms === 1000));
  controller.abort(); await rejection;
  assert.deepEqual(h.calls.map(call => call.options.method), ['POST', 'PATCH']);
  assert.equal(h.timers.size, 0);
});
test('TUS HEAD timeout and authorization errors keep their classifications', async () => {
  const h = harness(); const pending = h.c.editorTusRemoteOffset(intent.upload_url, {});
  const rejection = assert.rejects(pending, timeoutError);
  await h.fire(120000); await rejection;
  const denied = harness(async () => response(403));
  await assert.rejects(denied.c.editorTusRemoteOffset(intent.upload_url, {}),
    error => error.code === 'editor_tus_signature_expired' && error.status === 403);
});
test('retry after final PATCH commits but cancellation hides response resumes same resource', async () => {
  const uploadIntent = { ...intent }; let stored = false;
  const controller = new AbortController();
  const h = harness(async (_url, options) => {
    if (options.method === 'POST') {
      if (stored) return response(409);
      return response(201, { Location: '/storage/v1/upload/resumable/sign/committed-fixture' });
    }
    if (options.method === 'PATCH') { stored = true; controller.abort(); return never(); }
    if (options.method === 'HEAD') return response(200, { 'Upload-Offset': String(file.size) });
    throw Error('unexpected transport');
  });
  await assert.rejects(h.c.performTusUpload(file, uploadIntent, () => {}, { signal: controller.signal }), cancelled);
  assert.equal(stored, true);
  assert.equal(uploadIntent.tusUploadUrl, 'https://fixture.invalid/storage/v1/upload/resumable/sign/committed-fixture');
  const result = await h.c.performTusUpload(file, uploadIntent);
  assert.equal(result.offset, file.size);
  assert.deepEqual(h.calls.map(call => call.options.method), ['POST', 'PATCH', 'HEAD']);
  assert.equal(h.calls[1].url, h.calls[2].url);
  assert.equal(h.timers.size, 0);
});
test('same-session retry resumes partial offset without repeating committed bytes', async () => {
  const uploadIntent = { ...intent, tusUploadUrl: 'https://fixture.invalid/storage/v1/upload/resumable/sign/partial-fixture' };
  const h = harness(async (_url, options) => options.method === 'HEAD'
    ? response(200, { 'Upload-Offset': '4' }) : response(204, { 'Upload-Offset': String(file.size) }));
  await h.c.performTusUpload(file, uploadIntent);
  assert.deepEqual(h.calls.map(call => call.options.method), ['HEAD', 'PATCH']);
  assert.equal(h.calls[1].options.headers['Upload-Offset'], '4');
  assert.equal(h.calls[1].options.body.size, file.size - 4);
});
test('foreign stored resource and cancelled resume never create a new session', async () => {
  const foreign = harness();
  await assert.rejects(foreign.c.performTusUpload(file, { ...intent, tusUploadUrl: 'https://foreign.invalid/storage/v1/upload/resumable/sign/x' }),
    error => error.code === 'editor_tus_location_invalid');
  assert.equal(foreign.calls.length, 0);
  const h = harness(); const controller = new AbortController(); controller.abort();
  await assert.rejects(h.c.performTusUpload(file,
    { ...intent, tusUploadUrl: 'https://fixture.invalid/storage/v1/upload/resumable/sign/existing' }, () => {}, { signal: controller.signal }), cancelled);
  assert.equal(h.calls.length, 0);
});
test('stored resource with invalid server offset fails closed instead of succeeding', async () => {
  for (const offset of [null, '', '-1', 'not-a-number', String(file.size + 1)]) {
    const h = harness(async () => response(200, { 'Upload-Offset': offset }));
    await assert.rejects(h.c.performTusUpload(file,
      { ...intent, tusUploadUrl: 'https://fixture.invalid/storage/v1/upload/resumable/sign/existing' }),
      error => error.code === 'editor_tus_offset_invalid');
    assert.deepEqual(h.calls.map(call => call.options.method), ['HEAD']);
  }
});
test('PDF deadline covers blob consumption and supports cancellation', async () => {
  const h = harness(async () => ({ ok: true, blob: never }));
  const pending = h.c.fetchEditorAuthorizedBlob('/fixture.pdf');
  const rejection = assert.rejects(pending, timeoutError);
  await h.fire(45000); await rejection;
  const cancelledDownload = harness(); const controller = new AbortController();
  const aborted = cancelledDownload.c.fetchEditorAuthorizedBlob('/fixture.pdf', { signal: controller.signal });
  const abortRejection = assert.rejects(aborted, cancelled);
  await settle(); controller.abort(); await abortRejection;
});
test('authentication retains its own six-second deadline and bounded attempts', async () => {
  const h = harness();
  const pending = h.c.backendAuthRequestWithTransientRetry('/auth/me', {}, { attempts: 1 });
  const rejection = assert.rejects(pending, error => error.name === 'TimeoutError');
  await h.fire(6000); await rejection;
  assert.equal(h.calls.length, 1); assert.equal(h.timers.size, 0);
});
