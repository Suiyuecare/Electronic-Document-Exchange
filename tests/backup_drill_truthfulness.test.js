// Shipping backup UI functions with synthetic, deidentified runner evidence.
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
  return source.slice(start.index, start.index + start[0].length + next.index);
}
function fixture(result, request) {
  const nodes = new Map();
  for (const [selector, value] of Object.entries({
    '#backupDrillScope': '全部資料表', '#backupDrillTarget': '測試沙盒',
    '#backupDrillRtoTarget': '30', '#backupDrillRpoTarget': '15',
    '#complianceOwnerSelect': '合成維護者', '#backupDrillRunBtn': '',
    '#complianceDrillBtn': '', '#backupDrillSummaryGrid': '',
    '#backupDrillStepList': '', '#backupDrillRecordList': '',
    '#complianceMapStatus': '', '#complianceMapNote': '', '#complianceDocStatus': '',
    '#complianceDocNote': '', '#complianceReviewStatus': '', '#complianceReviewNote': '',
    '#complianceDrillStatus': '', '#complianceDrillNote': '',
  })) nodes.set(selector, { value, innerHTML: '', disabled: false, attrs: {},
    setAttribute(key, value) { this.attrs[key] = value; },
    removeAttribute(key) { delete this.attrs[key]; } });
  const c = { console, document: { querySelector: selector => nodes.get(selector) },
    latestBackupDrill: null, backupRestoreDrills: [], opsBackups: [],
    latestComplianceAttestation: null, complianceLastReview: '', complianceControls: [{ status: '已落地' }],
    complianceDocuments: [], explicitFrontendFixturesEnabled: () => false,
    backupRestoreDrillPending: false, complianceLastDrill: 'prior-success',
    opsState: { environment: 'synthetic' }, toasts: [], audits: [], requests: [],
    requestWorkspaceTypedConfirmation: async () => true, blockOperation: () => {},
    renderOps: () => {}, renderComplianceOps: () => {},
    addOpsAudit: (...args) => c.audits.push(args),
    addComplianceAudit: (...args) => c.audits.push(args),
    showToast: text => c.toasts.push(text),
    escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    backendRequest: (url, options) => { c.requests.push({ url, options }); return request ? request() : Promise.resolve(result); },
  };
  vm.createContext(c);
  vm.runInContext(['backupDrillSteps', 'renderBackupDrillPanel', 'normalizeBackupDrill', 'runBackupRestoreDrill', 'renderComplianceSummary'].map(implementation).join('\n'), c);
  return { c, nodes };
}
const blocked = { id: 'DRILL-SYNTHETIC', ok: false, blocked: true, result: 'blocked',
  checks: { database_restored: false, storage_restored: false, hash_match: false } };
const success = { id: 'DRILL-SYNTHETIC', ok: true, result: '通過',
  backup: { backup: 'synthetic.db', sha256: 'a'.repeat(64) },
  rto_minutes: 1, rpo_minutes: 0,
  checks: Object.fromEntries(['integrity', 'counts_match', 'hash_match', 'storage_restored', 'pdf_open_sample', 'rto_ok', 'rpo_ok'].map(key => [key, true])) };

test('blocked result never manufactures successful snapshot or restore', () => {
  const { c } = fixture(blocked);
  const drill = c.normalizeBackupDrill(blocked);
  assert.equal(drill.passed, false); assert.equal(drill.backupCreated, false);
  assert.equal(drill.rtoMinutes, null); assert.equal(drill.rpoMinutes, null);
  assert.match(drill.result, /已阻擋/);
  for (const step of Object.values(drill.steps)) assert.doesNotMatch(step, /已建立|還原完成|比對通過/);
});
test('server truthiness or incomplete success does not earn a pass', () => {
  const { c } = fixture();
  for (const report of [{ ok: 'true' }, { ok: true, checks: {} }, { ...success, blocked: true }, { ...success, result: 'blocked' }]) {
    assert.equal(c.normalizeBackupDrill(report).passed, false);
  }
});
test('measured zero RPO is preserved while missing and nonfinite values are unknown', () => {
  const { c } = fixture();
  assert.equal(c.normalizeBackupDrill(success).rpoMinutes, 0);
  for (const value of [undefined, null, NaN, Infinity, '0', -1]) {
    assert.equal(c.normalizeBackupDrill({ rto_minutes: value }).rtoMinutes, null);
  }
});
test('blocked attempt is retained but not counted as a backup or successful drill date', async () => {
  const { c, nodes } = fixture(blocked);
  await c.runBackupRestoreDrill(); c.renderBackupDrillPanel();
  assert.equal(c.backupRestoreDrills.length, 1); assert.equal(c.opsBackups.length, 0);
  assert.equal(c.complianceLastDrill, 'prior-success');
  assert.match(c.toasts[0], /已阻擋/); assert.doesNotMatch(c.toasts[0], /演練完成/);
  assert.doesNotMatch(nodes.get('#backupDrillStepList').innerHTML, /step ok/);
  assert.match(nodes.get('#backupDrillSummaryGrid').innerHTML, /未量測/);
});
test('verified local success updates backup and successful drill date', async () => {
  const { c } = fixture(success);
  await c.runBackupRestoreDrill();
  assert.equal(c.latestBackupDrill.passed, true); assert.equal(c.opsBackups.length, 1);
  assert.notEqual(c.complianceLastDrill, 'prior-success');
  assert.equal(c.toasts[0], '備份還原演練通過。');
});
test('verified remote restore without a snapshot record never invents one', async () => {
  const { c } = fixture({ ok: true, checks: Object.fromEntries([
    'database_restored', 'storage_restored', 'hash_match', 'target_isolated', 'receipt_valid', 'rto_ok', 'rpo_ok',
  ].map(key => [key, true])), rto_minutes: 2, rpo_minutes: 0 });
  await c.runBackupRestoreDrill();
  assert.equal(c.latestBackupDrill.passed, true); assert.equal(c.opsBackups.length, 0);
  assert.equal(c.latestBackupDrill.steps.snapshot, '快照證據未提供');
});
test('validated remote receipt records its concrete backup file without inventing another ID', async () => {
  const { c } = fixture({ ok: true, backup: { file: 'snapshot.enc', sha256: 'b'.repeat(64) },
    checks: Object.fromEntries(['database_restored', 'storage_restored', 'hash_match',
      'target_isolated', 'receipt_valid', 'rto_ok', 'rpo_ok'].map(key => [key, true])),
    rto_minutes: 2, rpo_minutes: 0 });
  await c.runBackupRestoreDrill();
  assert.equal(c.latestBackupDrill.passed, true); assert.equal(c.opsBackups.length, 1);
  assert.equal(c.latestBackupDrill.backupId, 'snapshot.enc');
});
test('pending backup is perceivable and duplicate activation sends only once', async () => {
  let resolve;
  const { c, nodes } = fixture(null, () => new Promise(done => { resolve = done; }));
  const pending = c.runBackupRestoreDrill();
  await c.runBackupRestoreDrill();
  assert.equal(c.requests.length, 1); assert.equal(c.requests[0].options.timeoutMs, 120000);
  assert.equal(nodes.get('#backupDrillRunBtn').disabled, true);
  assert.equal(nodes.get('#backupDrillRunBtn').attrs['aria-busy'], 'true');
  resolve(blocked); await pending;
  assert.equal(c.backupRestoreDrillPending, false);
  assert.equal(nodes.get('#backupDrillRunBtn').disabled, false);
  assert.equal(nodes.get('#backupDrillRunBtn').attrs['aria-busy'], undefined);
});
test('uncertain timeout does not claim completed or allow an automatic duplicate', async () => {
  const { c } = fixture(null, async () => { throw Object.assign(new Error('synthetic timeout'), { outcomeUnknown: true }); });
  await c.runBackupRestoreDrill();
  assert.equal(c.requests.length, 1); assert.equal(c.backupRestoreDrills.length, 0);
  assert.equal(c.complianceLastDrill, 'prior-success');
  assert.match(c.toasts[0], /尚未確認/); assert.equal(c.backupRestoreDrillPending, false);
});
test('runner strings are escaped and cannot create a false success state', () => {
  const { c, nodes } = fixture();
  c.latestBackupDrill = c.normalizeBackupDrill({ ...blocked, id: '<img src=x>', steps: { snapshot: '通過' } });
  c.backupRestoreDrills.push(c.latestBackupDrill); c.renderBackupDrillPanel();
  assert.doesNotMatch(nodes.get('#backupDrillRecordList').innerHTML, /<img/);
  assert.match(nodes.get('#backupDrillRecordList').innerHTML, /&lt;img/);
  assert.doesNotMatch(nodes.get('#backupDrillStepList').innerHTML, /step ok/);
});
test('operator templates cannot masquerade as production acceptance and latest failure stays visible', () => {
  const { c, nodes } = fixture();
  c.latestBackupDrill = c.normalizeBackupDrill(blocked);
  c.renderComplianceSummary();
  assert.equal(nodes.get('#complianceMapStatus').textContent, '待驗收');
  assert.match(nodes.get('#complianceDrillStatus').textContent, /已阻擋/);
  assert.equal(nodes.get('#complianceDrillNote').textContent, '上次通過：prior-success');
});
