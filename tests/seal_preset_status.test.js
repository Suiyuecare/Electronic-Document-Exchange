const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const matches = [...source.matchAll(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n.*?^\\}`, 'msg'))];
  assert.ok(matches.length, name);
  return matches.at(-1)[0];
}

function harness() {
  function control(value = '') {
    return { value, innerHTML: '', textContent: '', disabled: false,
      toggleAttribute(name, force) { if (name === 'disabled') this.disabled = force; },
      querySelectorAll() { return []; } };
  }
  const nodes = Object.fromEntries([
    'uploadedSealCompany', 'uploadedEditorSeamGroups', 'uploadedEditorSeamSealSelect',
    'uploadedSeamPresetStatus', 'uploadedEditorSeamAddBtn', 'uploadedEditorSeamPages',
    'uploadedEditorSeamStatus',
  ].map(id => ['#' + id, control()]));
  nodes['#uploadedSealCompany'].value = 'fixture-company';
  nodes['#uploadedEditorSeamSealSelect'].value = 'fixture-primary-large';
  const c = {
    document: { querySelector: selector => nodes[selector] || null }, nodes,
    authState: { token: 'fixture-token' }, actorScope: 'fixture-actor',
    uploadedSealCatalogState: { scope: 'fixture-actor', token: 'fixture-token', companyId: 'fixture-company', status: 'ready' },
    uploadedSealEditorRuntime: { reviewMode: 'edited', documentId: 'fixture-document' },
    uploadedSealApplicationRuntime: { companyId: 'fixture-company', editable: true },
    uploadedSealEditorState: { pages: [{ pageId: 'fixture-page' }], elements: [] },
    uploadedSealOptions: [{ id: 'fixture-primary-large', company_id: 'fixture-company',
      owner_kind: 'company', seal_category: 'establishment_seal', seal_size_type: 'large_seal',
      seal_name: '合成測試大章', selectable: true, is_active: true }],
    EDOCSeam: { groups: () => new Map() },
    companySealSelectable: seal => seal.selectable === true,
    escapeDraftHtml: value => String(value),
  };
  c.frontendSessionScope = () => c.actorScope;
  vm.createContext(c);
  vm.runInContext([
    'uploadedSealCatalogReady', 'uploadedSealCatalogMessage', 'companySealCatalogUnavailableReason',
    'uploadedSealCompanyRecords', 'uploadedSealPickerReadOnly', 'uploadedSeamPrimaryLargeSeal',
    'selectedUploadedSeamSeal', 'renderUploadedSeamGroups',
  ].map(implementation).join('\n'), c);
  return c;
}

test('available primary large seal remains honestly described during temporary read-only states', () => {
  for (const runtime of [
    { uploading: true }, { companyChanging: true }, { directoryLoading: true },
    { sealOptionsLoading: true }, { draftCreatePromise: {} }, { locked: true },
    { reviewMode: 'original' }, { reviewMode: 'prepared' },
  ]) {
    const c = harness();
    Object.assign(c.uploadedSealEditorRuntime, runtime);
    c.renderUploadedSeamGroups();
    assert.match(c.nodes['#uploadedEditorSeamSealSelect'].innerHTML, /fixture-primary-large/);
    assert.match(c.nodes['#uploadedSeamPresetStatus'].textContent, /已載入.*暫時無法放章/);
    assert.doesNotMatch(c.nodes['#uploadedSeamPresetStatus'].textContent, /尚無可用/);
    assert.equal(c.nodes['#uploadedEditorSeamSealSelect'].disabled, true);
    assert.equal(c.nodes['#uploadedEditorSeamAddBtn'].disabled, true);
    assert.equal(c.selectedUploadedSeamSeal(), null);
  }
});

test('application read-only and submission busy do not turn a known seal into an empty inventory', () => {
  for (const application of [{ editable: false }, { submissionBusy: true }]) {
    const c = harness();
    Object.assign(c.uploadedSealApplicationRuntime, application);
    c.renderUploadedSeamGroups();
    assert.match(c.nodes['#uploadedSeamPresetStatus'].textContent, /已載入/);
    assert.doesNotMatch(c.nodes['#uploadedSeamPresetStatus'].textContent, /尚無可用/);
    assert.equal(c.nodes['#uploadedEditorSeamSealSelect'].disabled, true);
    assert.equal(c.nodes['#uploadedEditorSeamAddBtn'].disabled, true);
  }
});

test('catalog loading, transport failure and permission denial retain distinct instructions', () => {
  for (const [status, message] of [['loading', /正在更新印章清單/], ['error', /更新失敗/], ['forbidden', /公司權限/]]) {
    const c = harness();
    c.uploadedSealCatalogState.status = status;
    if (status === 'forbidden') c.uploadedSealOptions = [];
    c.renderUploadedSeamGroups();
    assert.match(c.nodes['#uploadedSeamPresetStatus'].textContent, message);
    assert.doesNotMatch(c.nodes['#uploadedSeamPresetStatus'].textContent, /此單位尚無可用/);
    assert.equal(c.nodes['#uploadedEditorSeamSealSelect'].disabled, true);
    assert.equal(c.nodes['#uploadedEditorSeamAddBtn'].disabled, true);
  }
});

test('only the current scoped catalog can display choices and allow placement', () => {
  for (const change of [c => { c.actorScope = 'another-actor'; }, c => { c.authState.token = 'another-token'; },
    c => { c.nodes['#uploadedSealCompany'].value = 'another-company'; }]) {
    const c = harness();
    change(c);
    c.renderUploadedSeamGroups();
    assert.doesNotMatch(c.nodes['#uploadedEditorSeamSealSelect'].innerHTML, /fixture-primary-large/);
    assert.match(c.nodes['#uploadedSeamPresetStatus'].textContent, /尚未載入/);
    assert.equal(c.nodes['#uploadedEditorSeamSealSelect'].disabled, true);
    assert.equal(c.nodes['#uploadedEditorSeamAddBtn'].disabled, true);
  }
});

test('genuinely empty or non-primary-only inventory does not offer a seam stamp', () => {
  for (const options of [[], [{ id: 'fixture-small', company_id: 'fixture-company', owner_kind: 'company',
    seal_category: 'establishment_seal', seal_size_type: 'small_seal', selectable: true }]]) {
    const c = harness();
    c.uploadedSealOptions = options;
    c.renderUploadedSeamGroups();
    assert.match(c.nodes['#uploadedSeamPresetStatus'].textContent, /此單位尚無可用/);
    assert.equal(c.nodes['#uploadedEditorSeamSealSelect'].disabled, true);
    assert.equal(c.nodes['#uploadedEditorSeamAddBtn'].disabled, true);
    assert.equal(c.selectedUploadedSeamSeal(), null);
  }
});

test('ready catalog exposes independent seam choice and requires a PDF only for placement', () => {
  const c = harness();
  c.uploadedSealEditorState.pages = [];
  c.renderUploadedSeamGroups();
  assert.equal(c.nodes['#uploadedEditorSeamSealSelect'].disabled, false);
  assert.equal(c.nodes['#uploadedEditorSeamAddBtn'].disabled, true);
  assert.match(c.nodes['#uploadedSeamPresetStatus'].textContent, /每 5 頁一組.*分開選擇/);
  assert.equal(c.selectedUploadedSeamSeal().id, 'fixture-primary-large');
  c.uploadedSealEditorState.pages = [{ pageId: 'fixture-page' }];
  c.renderUploadedSeamGroups();
  assert.equal(c.nodes['#uploadedEditorSeamAddBtn'].disabled, false);
  assert.equal(c.nodes['#uploadedEditorSeamSealSelect'].value, 'fixture-primary-large');
});
