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
  const control = () => ({ textContent: '', className: '', title: '', attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; } });
  const nodes = Object.fromEntries(['uploadedEditorSaveStatus', 'uploadedEditorToolbarSaveStatus',
    'uploadedEditorPreflightStatus'].map(id => ['#' + id, control()]));
  const c = {
    nodes, document: { querySelector: selector => nodes[selector] || null },
    authState: { token: 'synthetic-token' }, actorScope: 'synthetic-actor',
    uploadedSealEditorRuntime: { documentId: 'synthetic-case', revisionId: 'synthetic-revision',
      locked: false, hydrating: false, reviewMode: 'edited', dirtyGeneration: 0, savedGeneration: 0 },
    uploadedSealApplicationRuntime: { epoch: 1, editable: true },
    uploadedSealEditorState: { schemaVersion: 2, revisionNo: 8, pages: [], sourceFiles: [], elements: [] },
    officialStatusLabels: { draft: '草稿', approved: '已核准', pending_supervisor: '主管' },
  };
  c.frontendSessionScope = () => c.actorScope;
  vm.createContext(c);
  vm.runInContext(['uploadedEditorStatusScope', 'uploadedEditorBusinessStatus', 'setUploadedEditorSaveStatus',
    'setUploadedEditorPreflightStatus', 'renderUploadedEditorSaveStatusPresentation',
    'renderUploadedEditorPreflightStatusPresentation', 'uploadedEditorReadOnlyPresentation',
    'invalidateUploadedEditorSubmissionPreview', 'uploadedSealApplicationScopeSnapshot',
    'uploadedSealApplicationScopeIsCurrent'].map(implementation).join('\n'), c);
  c.render = () => {
    c.renderUploadedEditorSaveStatusPresentation(true);
    c.renderUploadedEditorPreflightStatusPresentation();
  };
  return c;
}

test('temporary hydration labels restore the actual saved revision in both status locations', () => {
  const c = harness();
  c.setUploadedEditorSaveStatus('saved', '已載入 revision 8');
  c.setUploadedEditorPreflightStatus('尚未產生送簽確認版');
  const saved = c.uploadedSealEditorRuntime.saveStatus;
  c.uploadedSealEditorRuntime.locked = c.uploadedSealEditorRuntime.hydrating = true;
  c.render();
  assert.match(c.nodes['#uploadedEditorSaveStatus'].textContent, /正在載入文件/);
  assert.match(c.nodes['#uploadedEditorPreflightStatus'].textContent, /正在載入文件/);
  assert.doesNotMatch(c.nodes['#uploadedEditorPreflightStatus'].textContent, /已送出簽核/);
  assert.equal(c.uploadedSealEditorRuntime.saveStatus, saved);
  c.uploadedSealEditorRuntime.locked = c.uploadedSealEditorRuntime.hydrating = false;
  c.render();
  for (const id of ['#uploadedEditorSaveStatus', '#uploadedEditorToolbarSaveStatus']) {
    assert.equal(c.nodes[id].textContent, '已保存');
    assert.equal(c.nodes[id].title, '已載入 revision 8');
  }
  assert.equal(c.nodes['#uploadedEditorPreflightStatus'].textContent, '尚未產生送簽確認版');
});

test('errors, offline, conflict, unsaved and in-progress business states survive display overlays', () => {
  for (const [kind, message] of [['error', '儲存失敗，請重試'], ['offline', '離線中，尚未同步'],
    ['conflict', '另一裝置已更新，請保留為新草稿'], ['saving', '草稿暫存中…'], ['dirty', '尚未儲存']]) {
    const c = harness();
    c.setUploadedEditorSaveStatus(kind, message);
    c.uploadedSealEditorRuntime.directoryLoading = true;
    c.render();
    assert.match(c.nodes['#uploadedEditorSaveStatus'].textContent, /正在載入公司/);
    c.uploadedSealEditorRuntime.directoryLoading = false;
    c.uploadedSealEditorRuntime.locked = true;
    c.render();
    c.uploadedSealEditorRuntime.locked = false;
    c.render();
    assert.equal(c.nodes['#uploadedEditorSaveStatus'].className, `pdf-editor-save-status ${kind}`);
    assert.equal(c.nodes['#uploadedEditorSaveStatus'].textContent, message);
    assert.equal(c.nodes['#uploadedEditorToolbarSaveStatus'].textContent, message);
    assert.doesNotMatch(c.nodes['#uploadedEditorSaveStatus'].textContent, /已保存/);
  }
});

test('a real error arriving during temporary read-only replaces prior business state, not vice versa', () => {
  const c = harness();
  c.setUploadedEditorSaveStatus('saving', '儲存中');
  c.setUploadedEditorPreflightStatus('後端正在產生精準確認版…');
  c.uploadedSealEditorRuntime.locked = c.uploadedSealEditorRuntime.hydrating = true;
  c.render();
  c.setUploadedEditorSaveStatus('error', '儲存失敗，請重試');
  c.setUploadedEditorPreflightStatus('確認版產生失敗，目前未送簽。');
  c.render();
  c.uploadedSealEditorRuntime.locked = c.uploadedSealEditorRuntime.hydrating = false;
  c.render();
  assert.equal(c.nodes['#uploadedEditorSaveStatus'].textContent, '儲存失敗，請重試');
  assert.equal(c.nodes['#uploadedEditorPreflightStatus'].textContent, '確認版產生失敗，目前未送簽。');
});

test('preflight progress and review instructions survive preview modes without false submission claims', () => {
  for (const message of ['後端正在產生精準確認版…', '請檢查確認版；確認後再按送簽。', '確認版檢查失敗']) {
    const c = harness();
    c.setUploadedEditorPreflightStatus(message);
    for (const mode of ['prepared', 'original', 'changes', 'edited']) {
      c.uploadedSealEditorRuntime.reviewMode = mode;
      c.render();
      assert.equal(c.nodes['#uploadedEditorPreflightStatus'].textContent, message);
      assert.equal(c.uploadedSealEditorRuntime.locked, false);
      assert.equal(c.uploadedSealApplicationRuntime.editable, true);
    }
  }
});

test('scope changes never restore another actor, token, epoch or document status', () => {
  for (const change of [c => { c.actorScope = 'different-actor'; }, c => { c.authState.token = 'new-token'; },
    c => { c.uploadedSealApplicationRuntime.epoch += 1; }, c => { c.uploadedSealEditorRuntime.documentId = 'different-case'; }]) {
    const c = harness();
    c.setUploadedEditorSaveStatus('saved', '已載入 revision 8');
    c.setUploadedEditorPreflightStatus('原案件送簽失敗');
    c.uploadedSealEditorRuntime.locked = c.uploadedSealEditorRuntime.hydrating = true;
    c.render();
    change(c);
    c.uploadedSealEditorRuntime.locked = c.uploadedSealEditorRuntime.hydrating = false;
    c.render();
    assert.equal(c.nodes['#uploadedEditorSaveStatus'].textContent, '');
    assert.equal(c.nodes['#uploadedEditorToolbarSaveStatus'].textContent, '');
    assert.equal(c.nodes['#uploadedEditorPreflightStatus'].textContent, '');
    c.setUploadedEditorSaveStatus('error', '目前案件未完成同步');
    c.render();
    assert.equal(c.nodes['#uploadedEditorSaveStatus'].textContent, '目前案件未完成同步');
  }
});

test('new draft and missing DOM never fabricate saved state or lose a known business error', () => {
  const c = harness();
  c.uploadedSealEditorRuntime.documentId = '';
  c.render();
  assert.equal(c.nodes['#uploadedEditorSaveStatus'].textContent, '尚未建立草稿');
  c.renderUploadedEditorSaveStatusPresentation(false);
  assert.match(c.nodes['#uploadedEditorSaveStatus'].textContent, /尚未取得/);
  const node = c.nodes['#uploadedEditorSaveStatus'];
  delete c.nodes['#uploadedEditorSaveStatus'];
  c.setUploadedEditorSaveStatus('error', '儲存服務未回應');
  c.nodes['#uploadedEditorSaveStatus'] = node;
  c.render();
  assert.equal(node.textContent, '儲存服務未回應');
});

test('real case read-only status remains authoritative and never changes edit permissions', () => {
  const c = harness();
  c.setUploadedEditorSaveStatus('saved', '已載入 revision 8');
  c.setUploadedEditorPreflightStatus('確認版已完成');
  c.uploadedSealApplicationRuntime.editable = false;
  c.uploadedSealEditorRuntime.applicationSnapshot = { id: 'synthetic-case', status: 'approved' };
  c.render();
  assert.match(c.nodes['#uploadedEditorSaveStatus'].textContent, /已核准・唯讀/);
  assert.match(c.nodes['#uploadedEditorPreflightStatus'].textContent, /已核准・唯讀/);
  assert.equal(c.uploadedSealApplicationRuntime.editable, false);
  c.uploadedSealEditorRuntime.locked = true;
  c.uploadedSealEditorRuntime.hydrationError = 'Synthetic failed hydration';
  c.render();
  assert.match(c.nodes['#uploadedEditorSaveStatus'].textContent, /載入失敗/);
  assert.equal(c.nodes['#uploadedEditorSaveStatus'].className, 'pdf-editor-save-status error');
  assert.equal(c.uploadedSealEditorRuntime.locked, true);
});

test('preview invalidation updates editable state but cannot overwrite business errors while locked', () => {
  const c = harness();
  c.setUploadedEditorPreflightStatus('確認版產生失敗');
  c.uploadedSealApplicationRuntime.submissionPreview = 'synthetic-preview';
  c.uploadedSealEditorRuntime.locked = true;
  c.invalidateUploadedEditorSubmissionPreview();
  assert.equal(c.uploadedSealEditorRuntime.preflightStatus.message, '確認版產生失敗');
  assert.equal(c.uploadedSealApplicationRuntime.submissionPreview, null);
  c.uploadedSealEditorRuntime.locked = false;
  c.uploadedSealApplicationRuntime.submissionPreview = 'synthetic-preview';
  c.invalidateUploadedEditorSubmissionPreview();
  assert.match(c.nodes['#uploadedEditorPreflightStatus'].textContent, /內容已變更/);
});

function loadingHarness(options = {}) {
  const c = harness();
  const result = { revisionNo: 12, revision_id: 'loaded-revision', status: 'draft',
    state: { schemaVersion: 2, sourceFiles: [], pages: [{ pageId: 'loaded-page' }], elements: [] } };
  const application = { id: 'loaded-case', company_id: 'synthetic-company', current_status: 'draft' };
  Object.assign(c, {
    PDF_EDITOR_SCHEMA_VERSION: 2, structuredClone,
    flushUploadedSealDraftBeforeSwitch: async () => {},
    uploadedSealApplicationKey: () => 'unchanged-application',
    backendRequest: async url => url.endsWith('/editor-state') ? result : application,
    stageUploadedEditorAuthorizedAssets: async () => [],
    clearUploadedEditorSensitivePreviews: () => {
      c.uploadedSealApplicationRuntime.epoch += 1;
      Object.assign(c.uploadedSealEditorRuntime, { documentId: '', saveStatus: null, preflightStatus: null });
    },
    emptyUploadedSealEditorState: () => ({ pages: [], elements: [], sourceFiles: [] }),
    cloneUploadedEditorValue: structuredClone, applyEditorRevisionFromResponse: () => {},
    editorPreparedAuthorizedUrl: () => '', officialDocumentIsApplicant: () => true,
    restoreUploadedSealApplication: value => { c.uploadedSealEditorRuntime.applicationSnapshot = { id: value.id, status: value.current_status }; },
    rememberUploadedEditorSavedSealBindings: () => {}, normalizeUploadedEditorSealGeometry: () => Boolean(options.normalized),
    renderUploadedSealWorkbench: () => c.render(),
    hydrateUploadedEditorAuthorizedAssets: async () => {
      assert.match(c.nodes['#uploadedEditorSaveStatus'].textContent, /正在載入文件/);
      assert.doesNotMatch(c.nodes['#uploadedEditorPreflightStatus'].textContent, /已送出簽核/);
      if (options.failHydration) throw new Error('Synthetic hydration failure');
      if (options.switchActor) c.actorScope = 'another-actor';
    },
    syncLegacyUploadedEditorCollections: () => {},
    ensureUploadedEditorPagesA4: () => { if (options.nonA4) throw new Error('Synthetic non-A4'); },
    markUploadedEditorDirty: () => { c.setUploadedEditorSaveStatus('dirty', '尚未儲存'); },
    loadUploadedSealOptions: async () => {}, refreshWorkflowReadinessForContext: async () => {},
    discardUploadedEditorStagedAssets: () => {},
  });
  vm.runInContext(implementation('loadUploadedEditorState'), c);
  return c;
}

test('actual draft reopen records verified loaded revision and removes temporary read-only status', async () => {
  const c = loadingHarness();
  await c.loadUploadedEditorState('loaded-case');
  assert.equal(c.uploadedSealEditorRuntime.hydrating, false);
  assert.equal(c.uploadedSealEditorRuntime.locked, false);
  assert.equal(c.nodes['#uploadedEditorSaveStatus'].textContent, '已保存');
  assert.equal(c.nodes['#uploadedEditorSaveStatus'].title, '已載入 revision 12');
  assert.equal(c.nodes['#uploadedEditorToolbarSaveStatus'].textContent, '已保存');
  assert.equal(c.nodes['#uploadedEditorPreflightStatus'].textContent, '');
});

test('actual reopen does not replace A4 failures or normalized unsaved changes with saved', async () => {
  for (const [options, expected] of [[{ nonA4: true }, /非 A4/], [{ normalized: true }, /尚未儲存/]]) {
    const c = loadingHarness(options);
    await c.loadUploadedEditorState('loaded-case');
    assert.match(c.nodes['#uploadedEditorSaveStatus'].textContent, expected);
    assert.doesNotMatch(c.nodes['#uploadedEditorSaveStatus'].textContent, /已保存/);
  }
});

test('failed or stale actual hydration never records successful loading or enables the draft', async () => {
  for (const options of [{ failHydration: true }, { switchActor: true }]) {
    const c = loadingHarness(options);
    await assert.rejects(c.loadUploadedEditorState('loaded-case'));
    assert.notEqual(c.uploadedSealEditorRuntime.saveStatus?.kind, 'saved');
    assert.equal(c.uploadedSealEditorRuntime.locked, true);
    assert.doesNotMatch(c.nodes['#uploadedEditorSaveStatus'].textContent, /已保存/);
  }
});
