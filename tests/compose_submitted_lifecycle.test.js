const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
const extract = name => {
  const match = new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n.*?^\\}`, 'ms').exec(source);
  assert.ok(match, name); return match[0];
};

function harness() {
  const storage = new Map();
  const c = { authState: {user:{id:'employee',company_id:'company'}}, composeSubmittedState:{scope:'',documentId:''},
    storage, frontendSessionScope:()=>`${c.authState.user.id}:${c.authState.user.company_id}`,
    readScopedSessionJson:(key,fallback)=>storage.get(`${c.frontendSessionScope()}:${key}`)??fallback,
    writeScopedSessionJson:(key,value)=>storage.set(`${c.frontendSessionScope()}:${key}`,value),
    document:{querySelector:()=>null}, showToast:()=>{}, clearTimeout, composeCloudTimer:null,
  };
  vm.createContext(c);
  vm.runInContext(['composeSubmittedDocumentId','rememberComposeSubmittedDocument','clearComposeSubmittedDocument'].map(extract).join('\n'),c);
  return c;
}

test('submitted identity survives reload, remains actor/company scoped and contains no document contents',()=>{
  const c=harness(); c.rememberComposeSubmittedDocument('OD-original');
  assert.equal(c.composeSubmittedDocumentId(),'OD-original');
  assert.equal(JSON.stringify([...c.storage.values()]), '[{"documentId":"OD-original"}]');
  c.composeSubmittedState={scope:'',documentId:''};
  assert.equal(c.composeSubmittedDocumentId(),'OD-original');
  c.authState.user.id='other'; assert.equal(c.composeSubmittedDocumentId(),'');
  c.authState.user.id='employee'; c.authState.user.company_id='other-company'; assert.equal(c.composeSubmittedDocumentId(),'');
  c.authState.user.company_id='company'; assert.equal(c.composeSubmittedDocumentId(),'OD-original');
  c.clearComposeSubmittedDocument(); c.composeSubmittedState={scope:'',documentId:''}; assert.equal(c.composeSubmittedDocumentId(),'');
});

test('blocked storage retains same-session submitted guard and explicit new-document clear',()=>{
  const c=harness(); c.writeScopedSessionJson=()=>{};
  c.rememberComposeSubmittedDocument('OD-original'); assert.equal(c.composeSubmittedDocumentId(),'OD-original');
  c.clearComposeSubmittedDocument(); assert.equal(c.composeSubmittedDocumentId(),'');
});

test('invalid stored identity never becomes a navigation authority',()=>{
  const c=harness(); c.storage.set('employee:company:compose-submitted-case',{documentId:'https://invalid.example'});
  assert.equal(c.composeSubmittedDocumentId(),'');
  c.rememberComposeSubmittedDocument('not-an-official-id'); assert.equal(c.composeSubmittedDocumentId(),'');
});

test('late input, cloud save, formal save and next cannot mutate a submitted form',async()=>{
  const c=harness(); c.rememberComposeSubmittedDocument('OD-original');
  c.setView=route=>{c.navigated=route;};
  vm.runInContext(['writeComposeAutosave','saveComposeCloudDraft','createDispatchFromForm','saveComposeDraft','advanceComposeStep'].map(extract).join('\n'),c);
  // All lower-level mutation dependencies deliberately absent: no path may reach them.
  c.writeComposeAutosave();
  assert.equal(await c.saveComposeCloudDraft(),null);
  assert.equal(await c.createDispatchFromForm('草稿'),null);
  assert.equal(await c.createDispatchFromForm('待清稿'),null);
  assert.equal(await c.saveComposeDraft(),null);
  await c.advanceComposeStep(); assert.equal(c.navigated,'compose');
});

test('history compose navigation reauthorizes original case before touching compose DOM',()=>{
  const c=harness(); c.rememberComposeSubmittedDocument('OD-original');
  c.bindWorkspaceDraftControls=()=>{}; c.performance={now:()=>0}; c.isRouteAllowed=()=>true;
  c.openOfficialCaseFromNavigation=(id,options)=>{c.opened={id,...options};};
  vm.runInContext(extract('setView'),c); c.setView('compose');
  assert.equal(c.opened.id,'OD-original'); assert.equal(c.opened.tab,'mine'); assert.equal(c.opened.replace,true);
});

test('new compose reapplies current identity/company, resets manual default markers and never resaves submitted text',async()=>{
  const c=harness(); c.rememberComposeSubmittedDocument('OD-original');
  const fields=Object.fromEntries(['contactAddress','contactOwner','contactPhone','contactFax','contactEmail','copyRecipients','originalRecipients','recipient','subject','bodyText','documentPurpose','attachmentDetails','dispatchNo','dispatchDate'].map(id=>[`#${id}`,{value:'old',dataset:{autoDefault:'false',defaultCompany:'old-company',attachmentTextEdited:'true',attachmentFileNames:'old.pdf'}}]));
  const form={reset(){for(const field of Object.values(fields))field.value='';}};
  c.document={querySelector:s=>s==='#composeForm'?form:fields[s]||null};
  Object.assign(c,{composeSubmitInFlight:false,composeSaveInFlight:null,workspaceDraftScope:()=> 'scope',composeRequestScope:()=> 'input',
    composeRawSnapshot:()=>({values:{subject:'submitted text'}}),composeSnapshotHasMeaningfulContent:()=>true,
    saveComposeCloudDraft:()=>{throw Error('must not resave submitted form');},resetComposeAsyncScope:()=>c.clearComposeSubmittedDocument(),
    composeTodayDate:()=> '2026-10-18',renderComposeCompanyOptions:()=>{},renderApprovalCategorySelect:()=>{},
    applyComposeContactDefaults(force){assert.equal(force,true);assert.equal(fields['#copyRecipients'].dataset.autoDefault,'true');
      assert.equal(fields['#copyRecipients'].dataset.defaultCompany,undefined);
      fields['#contactOwner'].value='Current employee'; fields['#copyRecipients'].value='Current company';},
    composeSealPlacements:{large:{},small:{},single:{}},renderComposeSaveStatus:()=>{},renderDraftPreview:()=>{},setView:()=>{},invalidateWorkspaceDrafts:()=>{}
  });
  vm.runInContext(extract('startNewWorkspaceCompose'),c); await c.startNewWorkspaceCompose();
  assert.equal(c.composeSubmittedDocumentId(),''); assert.equal(fields['#subject'].value,'');
  assert.equal(fields['#contactOwner'].value,'Current employee'); assert.equal(fields['#copyRecipients'].value,'Current company');
  assert.equal(fields['#attachmentDetails'].dataset.attachmentTextEdited,undefined);
});
