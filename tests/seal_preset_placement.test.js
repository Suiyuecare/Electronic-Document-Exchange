// Real placement functions, synthetic page/seal metadata only. No hosted access.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const matches = [...source.matchAll(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n[\\s\\S]*?^\\}`, 'gm'))];
  assert.ok(matches.length, name);
  return matches.at(-1)[0];
}

function harness() {
  const state = { elements: [], pages: Array.from({ length: 7 }, (_, i) => ({ pageId: `p${i + 1}`, widthPt: 595, heightPt: 842, rotation: 0 })) };
  const runtime = { currentPageId: 'p1', selectedIds: new Set(), tool: 'select', mode: 'general', reviewMode: 'edited' };
  const small = { id: 'small-A', owner_kind: 'company', seal_size_type: 'small_seal', seal_name: 'Synthetic small', seal_category: 'establishment_seal', size: 42 };
  const large = { id: 'large-A', owner_kind: 'company', seal_size_type: 'large_seal', seal_name: 'Synthetic large', seal_category: 'establishment_seal', size: 84 };
  const frames = [], toasts = [], history = [];
  let serial = 0;
  const nodes = new Map();
  function node(value = '') { return { value, dataset: {}, focus() { c.document.activeElement = this; }, scrollIntoView() { this.scrolled = true; } }; }
  const trigger = node();
  const layer = node();
  layer.querySelectorAll = () => state.elements.map(e => ({ dataset: { editorElementId: e.id }, scrollIntoView() { c.scrolled = e.id; } }));
  nodes.set('#uploadedEditorSvgLayer', layer);
  nodes.set('#uploadedSealStampType', node('current_page'));
  nodes.set('#uploadedEditorSeamPages', node());
  nodes.set('#uploadedPdfEmptyUploadBtn', node());
  nodes.set('#uploadedSealCategorySelect', node());
  nodes.set('#uploadedEditorSeamSealSelect', node());
  const c = {
    EDOCSeam: require('../editor-seam.js'), crypto: require('node:crypto').webcrypto,
    PDF_EDITOR_MAX_ELEMENTS: 1000, PDF_EDITOR_ALLOWED_KINDS: new Set(['seal']), PDF_EDITOR_DEFAULT_FONT_FAMILY: 'Synthetic',
    uploadedSealEditorState: state, uploadedSealEditorRuntime: runtime, uploadedSealPlacementMode: 'select',
    ordinary: small, large, scope: 'actor-A:case-A', blocked: false,
    document: { activeElement: trigger, querySelector: selector => nodes.get(selector) || null },
    window: { requestAnimationFrame: callback => frames.push(callback) },
    uploadedSealPickerReadOnly: () => c.blocked,
    uploadedSealApplicationScopeSnapshot: () => c.scope,
    uploadedSealApplicationScopeIsCurrent: scope => c.scope === scope,
    selectedUploadedSeal: () => c.ordinary,
    selectedUploadedSeamSeal: () => c.large,
    uploadedSeamPrimaryLargeSeal: seal => seal === large,
    officialSealHasCurrentFile: seal => Boolean(seal),
    companySealCurrentVersionSnapshot: seal => ({ sealFileId: `file-${seal.id}`, sealFileSha256: `hash-${seal.id}` }),
    currentUploadedEditorPage: () => state.pages.find(p => p.pageId === runtime.currentPageId),
    editorElementById: id => state.elements.find(e => e.id === id),
    setUploadedSealPage: id => { runtime.currentPageId = id; },
    selectUploadedEditorElement: id => { runtime.selectedIds = new Set([id]); },
    setUploadedEditorTool: kind => { runtime.tool = kind; },
    closeUploadedEditorDisclosures() {}, finishUploadedEditorTextEdit: () => true,
    renderUploadedSealWorkbench() {},
    focusWorkspaceConstraintControl: control => { c.guided = control; control?.focus(); },
    showToast: message => { toasts.push(message); },
    parseUploadedEditorPageRange: raw => raw.split(',').map(Number),
    commitUploadedEditorMutation: mutate => { history.push(structuredClone(state)); mutate(state); return true; },
    editorDefaultElement: (kind, page, point, props, choice = c.ordinary) => ({ id: `element-${++serial}`, pageId: page.pageId, kind,
      x: (point?.x || 0) - choice.size / 2, y: (point?.y || 0) - choice.size / 2, width: choice.size, height: choice.size,
      properties: { ...props, sealId: choice.id, sealFileId: `file-${choice.id}`, sealFileSha256: `hash-${choice.id}`, sizeLocked: true } }),
  };
  vm.createContext(c);
  vm.runInContext(['placeUploadedSealPreset', 'addUploadedStamp', 'addUploadedStampAtPoint', 'addUploadedSeamGroups', 'addUploadedEditorElement'].map(implementation).join('\n'), c);
  return { c, state, runtime, nodes, frames, toasts, history, small, large, layer, trigger };
}

test('one ordinary action creates the selected small seal, centers and selects its schematic', () => {
  const h = harness();
  h.c.placeUploadedSealPreset('seal');
  assert.equal(h.state.elements.length, 1);
  const placed = h.state.elements[0];
  assert.equal(placed.properties.sealId, h.small.id);
  assert.equal(placed.x + placed.width / 2, 595 / 2);
  assert.equal(placed.y + placed.height / 2, 842 / 2);
  assert.deepEqual([...h.runtime.selectedIds], [placed.id]);
  assert.equal(h.runtime.tool, 'select');
  h.frames.shift()();
  assert.equal(h.c.document.activeElement, h.layer);
  assert.equal(h.c.scrolled, placed.id);
  assert.equal(h.history.length, 1);
});

test('all pages is honored by toolbar and legacy canvas placement; overflow is atomic', () => {
  const h = harness();
  h.nodes.get('#uploadedSealStampType').value = 'all_pages';
  h.c.placeUploadedSealPreset('seal');
  assert.equal(h.state.elements.length, 7);
  assert.equal(new Set(h.state.elements.map(e => e.pageId)).size, 7);
  h.c.uploadedEditorClientPoint = () => ({ x: 50, y: 80 });
  h.c.addUploadedStampAtPoint(10, 20);
  assert.equal(h.state.elements.length, 14);
  assert.ok(h.state.elements.slice(7).every(e => e.x === 29 && e.y === 59));
  h.c.PDF_EDITOR_MAX_ELEMENTS = 15;
  h.c.placeUploadedSealPreset('seal');
  assert.equal(h.state.elements.length, 14);
  assert.equal(h.history.length, 2);
});

test('seam action uses independent large seal, creates 5+2 once, then reselects without mutation', () => {
  const h = harness();
  h.c.placeUploadedSealPreset('seam');
  assert.equal(h.state.elements.length, 7);
  const groups = [...h.c.EDOCSeam.groups(h.state).values()];
  assert.deepEqual(groups.map(group => group.length), [5, 2]);
  assert.ok(h.state.elements.every(e => e.properties.sealId === h.large.id && e.properties.seamEdge === 'right'));
  assert.equal(h.c.ordinary.id, h.small.id);
  const before = JSON.stringify(h.state);
  h.runtime.currentPageId = 'p7';
  h.c.placeUploadedSealPreset('seam');
  assert.equal(JSON.stringify(h.state), before);
  assert.equal(h.history.length, 1);
  assert.equal(h.c.editorElementById([...h.runtime.selectedIds][0]).pageId, 'p7');
});

test('restricted seam page range selects its first page instead of unrelated current page', () => {
  const h = harness();
  h.nodes.get('#uploadedEditorSeamPages').value = '6,7';
  h.c.placeUploadedSealPreset('seam');
  assert.equal(h.runtime.currentPageId, 'p6');
  assert.equal(h.state.elements.length, 2);
  assert.ok(h.state.elements.every(e => e.properties.seamPartCount === 2));
});

test('changing a preset never rewrites immutable existing bindings', () => {
  const h = harness();
  h.c.placeUploadedSealPreset('seal');
  const before = JSON.stringify(h.state.elements[0]);
  h.c.ordinary = h.large;
  h.c.placeUploadedSealPreset('seal');
  assert.equal(JSON.stringify(h.state.elements[0]), before);
  assert.equal(h.state.elements[1].properties.sealFileId, `file-${h.large.id}`);
});

test('unavailable, readonly and missing PDF do not place anything and give a usable next step', () => {
  const h = harness();
  h.c.blocked = true; h.c.placeUploadedSealPreset(); h.c.placeUploadedSealPreset('seam');
  assert.equal(h.state.elements.length, 0);
  h.c.blocked = false; h.c.ordinary = null; h.c.placeUploadedSealPreset();
  assert.equal(h.c.guided, h.nodes.get('#uploadedSealCategorySelect'));
  h.c.large = null; h.c.placeUploadedSealPreset('seam');
  assert.equal(h.c.guided, h.nodes.get('#uploadedEditorSeamSealSelect'));
  h.state.pages = []; h.c.placeUploadedSealPreset();
  assert.equal(h.c.document.activeElement, h.nodes.get('#uploadedPdfEmptyUploadBtn'));
  assert.equal(h.history.length, 0);
});

test('delayed focus cannot jump from a new field, selection, case or permission state', () => {
  for (const change of ['focus', 'selection', 'scope', 'blocked']) {
    const h = harness(); h.c.placeUploadedSealPreset();
    if (change === 'focus') h.c.document.activeElement = {};
    if (change === 'selection') h.runtime.selectedIds.clear();
    if (change === 'scope') h.c.scope = 'actor-B:case-B';
    if (change === 'blocked') h.c.blocked = true;
    const owner = h.c.document.activeElement;
    h.frames.shift()();
    assert.equal(h.c.document.activeElement, owner, change);
    assert.equal(h.c.scrolled, undefined, change);
  }
});

test('toolbar action delegates exactly once; canvas seal mode honors page scope', () => {
  const choose = implementation('chooseUploadedEditorTool');
  assert.equal((choose.match(/placeUploadedSealPreset\("seal"\)/g) || []).length, 1);
  assert.match(implementation('beginUploadedEditorPointer'), /tool === "seal"\) return addUploadedStampAtPoint/);
  assert.match(source, /#uploadedEditorSeamToggleBtn"\)\?\.addEventListener\("click", \(\) => placeUploadedSealPreset\("seam"\)\)/);
});

function reopenHarness() {
  let resolveLoad, rejectLoad;
  const loadGate = new Promise((resolve, reject) => { resolveLoad = resolve; rejectLoad = reject; });
  const calls = { renders: [], reviews: [], failures: [], disposals: 0, loads: 0, scrolls: 0, toasts: [] };
  const app = { openPromise: null, openAbortController: null };
  const preview = {
    progress() {}, assetReady() {}, commit() {},
    dispose() { calls.disposals++; }, failure(error) { calls.failures.push(error.message); },
  };
  const c = {
    AbortController, performance: { now: () => 1 },
    actor: 'fixture-actor', authState: { token: 'fixture-token' }, activeRouteTarget: 'electronicSeal', approvalLogFilter: 'mine',
    uploadedSealApplicationRuntime: app, uploadedSealEditorState: { pages: [{ pageId: 'fixture-page' }] },
    frontendSessionScope: () => c.actor,
    setView: route => { c.activeRouteTarget = route; },
    writeWorkspaceCaseRoute() {}, renderUploadedSealNavigation() {},
    createUploadedEditorOpeningPreview: () => preview,
    refreshFinanceDirectory: async () => {},
    loadUploadedEditorState: () => { calls.loads++; return loadGate; },
    showUploadedEditorReview: async mode => { calls.reviews.push(mode); },
    recordUiPerformance() {}, showToast: message => { calls.toasts.push(message); },
    renderUploadedSealWorkbench: () => calls.renders.push({
      openPromise: app.openPromise, actor: c.actor, token: c.authState.token, route: c.activeRouteTarget,
    }),
    document: { querySelector: selector => selector === '#electronicSeal' ? { scrollTo() { calls.scrolls++; } } : null },
  };
  vm.createContext(c);
  vm.runInContext(implementation('openOfficialDocumentEditorReview'), c);
  return { c, app, calls, resolveLoad, rejectLoad };
}

test('reopen completion clears its busy operation before refreshing actionable editor controls', async () => {
  const h = reopenHarness();
  const opening = h.c.openOfficialDocumentEditorReview('fixture-document', 'edited');
  assert.ok(h.app.openPromise);
  assert.ok(h.app.openAbortController);
  assert.equal(h.calls.renders.length, 0);
  h.resolveLoad();
  assert.equal(await opening, true);
  assert.equal(h.app.openPromise, null);
  assert.equal(h.app.openAbortController, null);
  assert.equal(h.calls.renders.length, 1);
  assert.equal(h.calls.renders[0].openPromise, null);
  assert.deepEqual(h.calls.reviews, ['edited']);
  assert.equal(h.calls.disposals, 1);
});

test('failed or cancelled reopening releases busy state and refreshes retained same-scope work', async () => {
  for (const cancelled of [false, true]) {
    const h = reopenHarness();
    const opening = h.c.openOfficialDocumentEditorReview('fixture-document', 'prepared');
    if (cancelled) h.app.openAbortController.abort();
    h.rejectLoad(Object.assign(new Error('synthetic reopening failure'), { name: cancelled ? 'AbortError' : 'Error' }));
    assert.equal(await opening, false);
    assert.equal(h.app.openPromise, null);
    assert.equal(h.app.openAbortController, null);
    assert.equal(h.calls.renders.length, 1);
    assert.equal(h.calls.renders[0].openPromise, null);
    assert.equal(h.calls.reviews.length, 0);
    assert.equal(h.calls.failures.length, cancelled ? 0 : 1);
  }
});

test('old reopening cannot repaint after actor, token or route changes on either outcome', async () => {
  for (const change of ['actor', 'token', 'route']) {
    for (const failed of [false, true]) {
      const h = reopenHarness();
      const opening = h.c.openOfficialDocumentEditorReview('fixture-document');
      if (change === 'actor') h.c.actor = 'other-actor';
      if (change === 'token') h.c.authState.token = 'other-token';
      if (change === 'route') h.c.activeRouteTarget = 'approvalLog';
      if (failed) h.rejectLoad(new Error('stale failure')); else h.resolveLoad();
      assert.equal(await opening, false);
      assert.equal(h.app.openPromise, null);
      assert.equal(h.app.openAbortController, null);
      assert.equal(h.calls.renders.length, 0, `${change}/${failed}`);
      assert.equal(h.calls.reviews.length, 0, `${change}/${failed}`);
      assert.equal(h.calls.scrolls, 0, `${change}/${failed}`);
    }
  }
});

test('a replaced opening operation retains its newer promise and controller without stale cleanup repaint', async () => {
  for (const failed of [false, true]) {
    const h = reopenHarness();
    const opening = h.c.openOfficialDocumentEditorReview('fixture-document');
    const replacement = Promise.resolve('newer operation');
    const replacementController = new AbortController();
    h.app.openPromise = replacement;
    h.app.openAbortController = replacementController;
    if (failed) h.rejectLoad(new Error('replaced failure')); else h.resolveLoad();
    await opening;
    assert.equal(h.app.openPromise, replacement);
    assert.equal(h.app.openAbortController, replacementController);
    assert.equal(h.calls.renders.length, 0);
  }
});

test('a concurrent second reopen is rejected without replacing or repainting the first operation', async () => {
  const h = reopenHarness();
  const opening = h.c.openOfficialDocumentEditorReview('fixture-first');
  const ownedPromise = h.app.openPromise;
  const ownedController = h.app.openAbortController;
  assert.equal(await h.c.openOfficialDocumentEditorReview('fixture-second'), false);
  assert.equal(h.app.openPromise, ownedPromise);
  assert.equal(h.app.openAbortController, ownedController);
  assert.equal(h.calls.loads, 1);
  assert.equal(h.calls.renders.length, 0);
  h.resolveLoad();
  assert.equal(await opening, true);
  assert.equal(h.calls.renders.length, 1);
});
