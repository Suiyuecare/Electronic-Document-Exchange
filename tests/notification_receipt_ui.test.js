const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function shipping(name) {
  const start = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(start);
  const rest = source.slice(start.index + start[0].length);
  const next = /^\n(?:async )?function \w+\(/m.exec(rest);
  return source.slice(start.index, start.index + start[0].length + next.index);
}
function render(report) {
  const grid = { innerHTML: '' }, detail = { innerHTML: '' };
  const context = { notificationGatewayState: { lastTestReport: report },
    document: { querySelector: id => id === '#notificationTestReportGrid' ? grid : detail },
    escapeHtml: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;') };
  vm.createContext(context);
  vm.runInContext(shipping('notificationReceiptLabel') + '\n' + shipping('renderNotificationTestReport'), context);
  context.renderNotificationTestReport();
  return { context, grid, detail };
}
test('provider acceptance never claims recipient delivery or read status', () => {
  const { grid } = render({ ok: true, success: 1, total: 1, results: [] });
  assert.match(grid.innerHTML, /通道已接受/);
  assert.doesNotMatch(grid.innerHTML, /全部送達|已讀/);
  assert.doesNotMatch(render({ ok: 'true' }).grid.innerHTML, /通道已接受/);
});
test('receipt errors are actionable without suggesting a duplicate send', () => {
  const { detail } = render({ results: [{ error: 'notification_delivery_evidence_unknown' }] });
  assert.match(detail.innerHTML, /需確認上次寄送結果，暫不重送/);
  assert.doesNotMatch(detail.innerHTML, /notification_delivery_evidence_unknown/);
});
test('untrusted report fields cannot render active HTML', () => {
  const canary = '<img src=x onerror=alert(1)>';
  const { grid, detail } = render({ target_email: canary, checked_at: canary,
    results: [{ channel: canary, status: canary, target: canary, receipt: canary, duration_ms: canary }] });
  assert.doesNotMatch(grid.innerHTML + detail.innerHTML, /<img/);
  assert.match(grid.innerHTML + detail.innerHTML, /&lt;img/);
});
test('immutable identity survives readback and resend without role guessing', () => {
  const context = {};
  vm.createContext(context);
  vm.runInContext(shipping('mapBackendNotification') + '\n' + shipping('notificationPayload'), context);
  const item = context.mapBackendNotification({ id: 'NTF-1', target_role: '主管',
    target_user_id: 'U-2', target_company_id: 'CO-2', target_email: 'exact@example.invalid' });
  const payload = context.notificationPayload(item);
  assert.equal(payload.target_user_id, 'U-2');
  assert.equal(payload.target_company_id, 'CO-2');
  assert.equal(payload.target_email, 'exact@example.invalid');
  assert.doesNotMatch(source, /function roleEmail\(/);
});
test('inbound reminders resolve only matching internal case references', () => {
  const context = { URLSearchParams };
  vm.createContext(context);
  vm.runInContext(shipping('notificationSourceReference'), context);
  const item = { source: 'INB-1', actionUrl: '/#inbound?document=INB-1&reminder_source=inbound_documents' };
  assert.equal(context.notificationSourceReference(item).sourceType, 'inbound_documents');
  assert.equal(context.notificationSourceReference({ ...item, source: 'INB-OTHER' }).sourceType, '');
  assert.equal(context.notificationSourceReference({ ...item, actionUrl: 'https://other.invalid/#inbound?document=INB-1&reminder_source=inbound_documents' }).sourceType, '');
});
test('manual notice creation names an exact recipient and blocks duplicate activation', async () => {
  let finish;
  const calls = [];
  const button = { disabled: false, setAttribute() {}, removeAttribute() {} };
  const inputs = { '#notificationType': { value: '收文' }, '#notificationTarget': { value: 'exact@example.invalid' },
    '#notificationChannel': { value: '系統通知' }, '#notificationBody': { value: 'Synthetic notice' }, '#notificationAddBtn': button };
  const context = { notificationCreatePending: false, selectedNotificationId: '', crypto: { randomUUID: () => 'synthetic-uuid' },
    document: { querySelector: id => inputs[id] }, backendRequest: (_path, options) => {
      calls.push(JSON.parse(options.body)); return new Promise(resolve => { finish = resolve; });
    }, syncNotificationsFromBackend: async () => {}, addNotificationAudit() {}, showToast() {} };
  vm.createContext(context);
  vm.runInContext(shipping('notificationPayload') + '\n' + shipping('addNotificationFromForm'), context);
  const first = context.addNotificationFromForm();
  await context.addNotificationFromForm();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].id, 'NTF-synthetic-uuid');
  assert.equal(calls[0].target_email, 'exact@example.invalid');
  assert.equal(button.disabled, true);
  finish({ id: 'NTF-synthetic-uuid' }); await first;
  assert.equal(button.disabled, false);
  assert.equal(context.notificationCreatePending, false);
});
