const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
const implementation = /^async function beginOfficialCorrection\([^\n]*\) \{\n.*?^\}/ms.exec(source)[0];

function harness() {
  const c = {
    actor: 'employee', scope: 'employee:company:draft', submittedMarker: 'OD-submitted',
    edits: [], opened: [], notices: [], requests: [], officialWorkflowItems: [],
    officialDocumentIsApplicant: item => item.applicant_id === c.actor,
    composeRequestScope: () => c.scope,
    officialComposeMetadata: item => item.metadata || {},
    showToast: message => c.notices.push(message),
    backendRequest: async path => { c.requests.push(path); return c.detail; },
    beginComposeOfficialCorrection: async item => { c.edits.push(item); c.submittedMarker = ''; },
    openOfficialCaseFromNavigation: async (id, options) => c.opened.push({ id, ...options }),
  };
  c.cached = { id: 'OD-draft', applicant_id: 'employee', current_status: 'draft' };
  c.detail = { ...c.cached, metadata: { source: 'compose_form' } };
  vm.createContext(c);
  vm.runInContext(implementation, c);
  return c;
}

test('a draft submitted elsewhere opens authorized detail without clearing the submitted guard', async () => {
  const c = harness();
  c.detail.current_status = 'pending_supervisor';
  await c.beginOfficialCorrection(c.cached);
  assert.equal(c.edits.length, 0);
  assert.equal(c.submittedMarker, 'OD-submitted');
  assert.deepEqual(c.opened, [{ id: 'OD-draft', replace: true }]);
});

test('fresh ownership, not stale list ownership, controls the correction editor', async () => {
  const c = harness();
  c.detail.applicant_id = 'other-employee';
  await c.beginOfficialCorrection(c.cached);
  assert.equal(c.edits.length, 0);
  assert.equal(c.submittedMarker, 'OD-submitted');
  assert.equal(c.opened[0].id, 'OD-draft');
});

test('403 and mismatched responses preserve current input and submitted guard', async () => {
  for (const reason of ['403', 'mismatched']) {
    const c = harness();
    if (reason === '403') c.backendRequest = async () => { throw Object.assign(Error('forbidden'), { status: 403 }); };
    else c.detail.id = 'OD-another';
    await c.beginOfficialCorrection(c.cached);
    assert.equal(c.edits.length, 0);
    assert.equal(c.opened.length, 0);
    assert.equal(c.submittedMarker, 'OD-submitted');
    assert.equal(c.notices.length, 1);
  }
});

test('an account or draft switched during authorization ignores the late response', async () => {
  const c = harness();
  let resolve;
  c.backendRequest = () => new Promise(done => { resolve = done; });
  const pending = c.beginOfficialCorrection(c.cached);
  c.actor = 'other-employee';
  c.scope = 'other-employee:company:new-draft';
  resolve(c.detail);
  await pending;
  assert.equal(c.edits.length, 0);
  assert.equal(c.opened.length, 0);
  assert.equal(c.notices.length, 0);
  assert.equal(c.submittedMarker, 'OD-submitted');
});

test('fresh owned drafts and returned-for-correction cases still reach the editor', async () => {
  for (const status of ['draft', 'rejected']) {
    const c = harness();
    c.detail.current_status = status;
    await c.beginOfficialCorrection(c.cached);
    assert.equal(c.requests.length, 1);
    assert.equal(c.edits.length, 1);
    assert.equal(c.edits[0].current_status, status);
    assert.equal(c.opened.length, 0);
    assert.equal(c.submittedMarker, '');
  }
});
