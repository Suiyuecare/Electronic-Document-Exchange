// Execute shipping functions only; synthetic, in-memory DOM/identity fixtures.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const matches = [...source.matchAll(new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n[\\s\\S]*?^\\}`, 'gm'))];
  assert.ok(matches.length, name); return matches.at(-1)[0];
}
function node() {
  const listeners = new Map();
  return { hidden: false, disabled: false, value: '', classList: { contains: () => true },
    addEventListener(type, fn) { if (!listeners.has(type)) listeners.set(type, new Set()); listeners.get(type).add(fn); },
    removeEventListener(type, fn) { listeners.get(type)?.delete(fn); },
    dispatch(type, event = {}) { for (const fn of [...(listeners.get(type) || [])]) fn(event); }, focus() {} };
}
function decisionHarness() {
  const nodes = Object.fromEntries(['Modal','Input','SubmitBtn','CancelBtn','Label','Title','Description'].map(key => ['#workspaceTypedConfirm'+key, node()]));
  const events = [];
  const context = { document: { querySelector: key => nodes[key] || null },
    visibleWorkspaceModals: () => [], hasMinimumText: (value, length) => value.length >= length,
    showWorkspaceModal: () => events.push('show'), hideWorkspaceModal: () => events.push('hide'), trapWorkspaceModalFocus: () => {} };
  vm.createContext(context);
  vm.runInContext(['requestWorkspaceDecision','requestWorkspaceConfirmation','requestWorkspaceTypedConfirmation'].map(implementation).join('\n'), context);
  return { nodes, events, context };
}
test('missing or already active shared dialog fails closed', async () => {
  const h = decisionHarness(); delete h.nodes['#workspaceTypedConfirmModal'];
  assert.equal(await h.context.requestWorkspaceConfirmation('Synthetic', 'No mutation'), false);
  assert.deepEqual(h.events, []);
});
test('cancel returns null, clears reason and finishes exactly once', async () => {
  const h = decisionHarness(), operation = h.context.requestWorkspaceDecision('Synthetic', 'Reason', { reason: true, initialValue: 'Synthetic reason' });
  h.nodes['#workspaceTypedConfirmCancelBtn'].dispatch('click');
  h.nodes['#workspaceTypedConfirmSubmitBtn'].dispatch('click');
  assert.equal(await operation, null);
  assert.equal(h.nodes['#workspaceTypedConfirmInput'].value, '');
  assert.deepEqual(h.events, ['show', 'hide']);
});
test('confirm-only modal needs no text, does not accept twice', async () => {
  const h = decisionHarness(), operation = h.context.requestWorkspaceConfirmation('Delete', 'Synthetic page');
  assert.equal(h.nodes['#workspaceTypedConfirmInput'].hidden, true);
  h.nodes['#workspaceTypedConfirmSubmitBtn'].dispatch('click'); h.nodes['#workspaceTypedConfirmSubmitBtn'].dispatch('click');
  assert.equal(await operation, true); assert.deepEqual(h.events, ['show', 'hide']);
});
test('IME completion cannot submit or Escape-cancel until composition ends', async () => {
  const h = decisionHarness(), operation = h.context.requestWorkspaceTypedConfirmation('Synthetic', 'Typed', '確認');
  const input = h.nodes['#workspaceTypedConfirmInput'], modal = h.nodes['#workspaceTypedConfirmModal'];
  input.dispatch('compositionstart'); input.value = '確認'; input.dispatch('input');
  assert.equal(h.nodes['#workspaceTypedConfirmSubmitBtn'].disabled, true);
  let prevented = 0;
  modal.dispatch('keydown', {key:'Escape',isComposing:true,preventDefault(){prevented++;},stopPropagation(){}});
  assert.deepEqual(h.events, ['show']);
  input.dispatch('compositionend'); assert.equal(h.nodes['#workspaceTypedConfirmSubmitBtn'].disabled, false);
  modal.dispatch('keydown', {key:'Escape',isComposing:false,preventDefault(){prevented++;},stopPropagation(){}});
  assert.equal(await operation, false); assert.equal(prevented, 1);
});
test('legacy confirmation adapters use the shared dialog and missing DOM fails closed', async () => {
  const h = decisionHarness(); delete h.nodes['#workspaceTypedConfirmModal'];
  vm.runInContext(['confirmOperation','requireTypedConfirm'].map(implementation).join('\n'), h.context);
  assert.equal(await h.context.confirmOperation('x','y'), false); assert.equal(await h.context.requireTypedConfirm('x','y','z'), false);
});
test('shipping product UI has no native dialogs and every legacy adapter caller awaits consent', () => {
  assert.equal(/\b(?:window\.)?(?:confirm|prompt|alert)\s*\(/.test(source), false);
  for (const name of ['confirmOperation', 'requireTypedConfirm']) {
    const adapter = implementation(name);
    assert.ok(adapter.startsWith('async function '), name);
    const withoutDeclaration = source.replace(adapter, '');
    const matches = [...withoutDeclaration.matchAll(new RegExp(`\\b${name}\\s*\\(`, 'g'))];
    assert.ok(matches.length > 0, name + ' has shipping callers');
    for (const match of matches) {
      const prefix = withoutDeclaration.slice(Math.max(0, match.index - 24), match.index);
      assert.match(prefix, /await\s+$/, name + ' must never authorize through Promise truthiness');
    }
  }
});
test('an existing modal blocks another decision without replacing its handlers', async () => {
  const h = decisionHarness();
  h.context.visibleWorkspaceModals = () => [{}];
  assert.equal(await h.context.requestWorkspaceConfirmation('Synthetic', 'No mutation'), false);
  assert.deepEqual(h.events, []);
});
test('identity or route changed during shared confirmation cannot authorize a mutation', async () => {
  const h = decisionHarness(); let actor = 'synthetic-A'; h.context.frontendSessionScope = () => actor;
  const decision = h.context.confirmOperation ? h.context.confirmOperation('x','y') : h.context.requestWorkspaceConfirmation('x','y');
  actor = 'synthetic-B'; h.nodes['#workspaceTypedConfirmSubmitBtn'].dispatch('click');
  assert.equal(await decision, false);
});
test('provisional binding preserves page ids, edits, undo and maps', () => {
  const state = {sourceFiles:[{assetId:'LOCAL-S'}],pages:[{pageId:'stable-page',sourceAssetId:'LOCAL-S'}],elements:[{id:'text',pageId:'stable-page',properties:{text:'Synthetic'}}]};
  const history = structuredClone(state), pending = {editorLoaded:true,localAssetId:'LOCAL-S'};
  const runtime = {pendingFinalization:pending,undoStack:[history],redoStack:[],pdfDocuments:new Map([['LOCAL-S',{}]]),assetFiles:new Map([['LOCAL-S',{}]]),assetUrls:new Map([['LOCAL-S','blob:synthetic']]),pageProxies:new Map([['stable-page',{assetId:'LOCAL-S'}]])};
  const context = {uploadedSealEditorState:state,uploadedSealEditorRuntime:runtime,uploadedSealPdf:{assetId:'LOCAL-S'},assertEditorUploadCurrent(){},syncLegacyUploadedEditorCollections(){}};
  vm.createContext(context); vm.runInContext(implementation('bindUploadedEditorLocalAsset'), context);
  context.bindUploadedEditorLocalAsset(pending,{asset_id:'SERVER-S'});
  assert.equal(state.pages[0].pageId,'stable-page'); assert.equal(state.pages[0].sourceAssetId,'SERVER-S');
  assert.equal(state.elements[0].properties.text,'Synthetic'); assert.equal(history.sourceFiles[0].assetId,'SERVER-S');
  assert.equal(runtime.assetUrls.get('SERVER-S'),'blob:synthetic'); assert.equal(runtime.assetUrls.has('LOCAL-S'),false);
  assert.equal(runtime.pageProxies.get('stable-page').assetId,'SERVER-S');
});
test('unknown intent outcome is not recreated by retry', async () => {
  let calls = 0; const error = Object.assign(new Error('Synthetic uncertain response'),{outcomeUnknown:true});
  const pending = {file:{},intent:{localOnly:true,sha256:'Synthetic'}};
  const context = {requestEditorUpload:()=>{calls++;return Promise.reject(error);},bindUploadedEditorLocalAsset(){throw Error('must not bind');}};
  vm.createContext(context); vm.runInContext(implementation('preparePendingEditorPdfIntent'),context);
  await assert.rejects(context.preparePendingEditorPdfIntent(pending)); await assert.rejects(context.preparePendingEditorPdfIntent(pending));
  assert.equal(calls,1); assert.equal(pending.intentOutcomeUnknown,true);
});
test('performance samples are bounded and contain no supplied sensitive metadata', () => {
  const payloads = [], context = {hasAuthenticatedBackendSession:()=>true,frontendSessionScope:()=> 'synthetic-scope',performance:{now:()=>2000},uiPerformanceWindow:{scope:'',startedAt:0,count:0,samples:[]},trackUiUsage:(kind,payload)=>payloads.push({kind,payload}),Set,Number};
  vm.createContext(context); vm.runInContext(implementation('recordUiPerformance'),context);
  for(let i=0;i<40;i++) context.recordUiPerformance('pdf_local_editable',1000,'success',{file:{name:'PRIVATE.pdf',size:100},pageCount:2,url:'https://private.invalid',content:'PRIVATE'});
  assert.equal(payloads.length,30); assert.equal(context.uiPerformanceWindow.samples.length,30);
  assert.deepEqual(Object.keys(payloads[0].payload.performance).sort(),['cacheState','durationMs','fileSizeBucket','outcome','pageCountBucket','stage']);
  assert.equal(JSON.stringify(payloads).includes('PRIVATE'),false); assert.equal(JSON.stringify(payloads).includes('private.invalid'),false);
  context.recordUiPerformance('invalid',1000); assert.equal(payloads.length,30);
});
test('A4 local path starts intent in parallel and never awaits it before loading', () => {
  const body = implementation('handleUploadedSealPdfChange');
  const a4 = body.slice(body.indexOf('if (preparation.report.valid)'),body.indexOf('// Non-A4 documents'));
  assert.ok(a4.indexOf('pending.intentPromise = requestEditorUpload') < a4.indexOf('await loadUploadedPdfIntoEditor'));
  assert.ok(!a4.includes('await requestEditorUpload'));
  assert.ok(a4.includes('finalizingAsset = true')); assert.ok(a4.includes('localOnly: true'));
  assert.ok(implementation('saveUploadedEditorState').includes('finalizingAsset || uploadedSealEditorRuntime.finalizationError'));
});
