const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
const extract = name => { const match = new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n.*?^\\}`, 'ms').exec(source); assert.ok(match, name); return match[0]; };
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; }
function harness() {
  const nodes = { '#workspaceDraftSearch': { value: '' }, '#draftNavCount': { textContent: '', setAttribute(k,v) {this[k]=v;} } };
  const c = { Map, Set, Promise, Date, Error, Number, URLSearchParams, scope: 'A', authState: { token: 't1', user: {id:'A'} }, requests: [], nodes,
    workspaceDraftState: { scope:'', total:null, rows:[], cursor:'', hasMore:false, loading:false, error:'', search:'', generation:0, updatedAt:0 }, workspaceDraftSummaryRequest:null,
    frontendSessionScope:()=>c.scope, isRouteAllowed:()=>true, renderWorkspaceDrafts(){}, document:{querySelector:selector=>nodes[selector]||null}, activeRouteTarget:'compose',
    backendRequest(path) {const d=deferred();c.requests.push({path,...d});return d.promise;}
  };
  vm.createContext(c); vm.runInContext(['workspaceDraftScope','resetWorkspaceDrafts','renderWorkspaceDraftCount','refreshWorkspaceDraftCount','loadWorkspaceDrafts','invalidateWorkspaceDrafts'].map(extract).join('\n'),c); return c;
}
test('exact badge total is not first 25 rows and search total never replaces it', async()=>{
  const c=harness(), first=c.loadWorkspaceDrafts();
  c.requests[0].resolve({items:[{key:'a'}],total:83,has_more:true,next_cursor:'next'});await first;
  assert.equal(c.nodes['#draftNavCount'].textContent,'83');
  c.nodes['#workspaceDraftSearch'].value='needle';const search=c.loadWorkspaceDrafts();
  c.requests[1].resolve({items:[{key:'b'}],total:1,has_more:false});await search;
  assert.equal(c.workspaceDraftState.filteredTotal,1);assert.equal(c.nodes['#draftNavCount'].textContent,'83');
});
test('late old actor or old search results cannot overwrite private draft list',async()=>{
  const c=harness(), old=c.loadWorkspaceDrafts();c.authState.token='t2';c.scope='B';
  const newer=c.loadWorkspaceDrafts();c.requests[1].resolve({items:[{key:'B'}],total:1,has_more:false});await newer;
  c.requests[0].resolve({items:[{key:'A'}],total:99,has_more:false});await old;
  assert.equal(c.workspaceDraftState.rows[0].key,'B');assert.equal(c.workspaceDraftState.total,1);
  c.nodes['#workspaceDraftSearch'].value='old';const oldSearch=c.loadWorkspaceDrafts();
  c.nodes['#workspaceDraftSearch'].value='new';const newSearch=c.loadWorkspaceDrafts();
  c.requests[3].resolve({items:[{key:'new'}],total:1,has_more:false});await newSearch;
  c.requests[2].resolve({items:[{key:'old'}],total:1,has_more:false});await oldSearch;
  assert.equal(c.workspaceDraftState.rows[0].key,'new');
});
test('summary shares pending read, caches 30 seconds and mutation invalidates old response',async()=>{
  const c=harness(), a=c.refreshWorkspaceDraftCount(), b=c.refreshWorkspaceDraftCount();assert.equal(c.requests.length,1);
  c.requests[0].resolve({total:40});await Promise.all([a,b]);await c.refreshWorkspaceDraftCount();assert.equal(c.requests.length,1);
  c.invalidateWorkspaceDrafts();assert.equal(c.requests.length,2);
  c.requests[1].resolve({total:39});await c.workspaceDraftSummaryRequest.promise;assert.equal(c.workspaceDraftState.total,39);
});
test('summary permission loss clears private cached count, not just the rows endpoint',async()=>{
  const c=harness(), initial=c.refreshWorkspaceDraftCount();c.requests[0].resolve({total:31});await initial;
  const retry=c.refreshWorkspaceDraftCount({force:true});c.requests[1].reject(Object.assign(Error('forbidden'),{status:403}));await retry;
  assert.equal(c.workspaceDraftState.total,null);assert.equal(c.nodes['#draftNavCount'].textContent,'—');
});
test('new compose preserves typing during save and ignores a changed draft or actor',async()=>{
  const saved=deferred();const c={snapshot:{values:{subject:'before'}},scope:'A',inputScope:'one',composeCloudDraftId:'draft',composeCloudSavedSnapshots:new Map(),resets:0,toasts:[],
    document:{querySelector:()=>null},
    workspaceDraftScope:()=>c.scope,composeRequestScope:()=>c.inputScope,composeRawSnapshot:()=>c.snapshot,composeSnapshotHasMeaningfulContent:()=>true,saveComposeCloudDraft:()=>saved.promise,
    resetComposeAsyncScope:()=>{c.resets++;throw Error('must not clear later content')},showToast:m=>c.toasts.push(m)};
  vm.createContext(c);vm.runInContext(extract('startNewWorkspaceCompose'),c);
  const p=c.startNewWorkspaceCompose();c.snapshot.values.subject='typed during save';saved.resolve({id:'draft'});await p;
  assert.equal(c.resets,0);assert.match(c.toasts[0],/保留目前輸入/);
  const later=deferred();c.saveComposeCloudDraft=()=>later.promise;const switched=c.startNewWorkspaceCompose();c.inputScope='two';later.resolve({id:'draft'});await switched;assert.equal(c.resets,0);
});
test('attachment-only new compose requires confirmation and cancellation keeps selected files',async()=>{
  const file={name:'local.pdf'}, input={files:[file]}, decision=deferred();
  const c={document:{querySelector:s=>s==='#attachments'?input:null},workspaceDraftScope:()=> 'A',composeRequestScope:()=> 'draft',composeRawSnapshot:()=>({values:{}}),
    requestWorkspaceConfirmation:()=>decision.promise,composeSnapshotHasMeaningfulContent:()=>false,resetComposeAsyncScope:()=>{throw Error('cancel must not reset')}};
  vm.createContext(c);vm.runInContext(extract('startNewWorkspaceCompose'),c);
  const p=c.startNewWorkspaceCompose();decision.resolve(false);await p;assert.equal(input.files[0],file);
});
test('failed read preserves existing rows but 403 clears sensitive rows and unknown is not zero',async()=>{
  const c=harness(), initial=c.loadWorkspaceDrafts();c.requests[0].resolve({items:[{key:'a'}],total:1,has_more:false});await initial;
  const retry=c.loadWorkspaceDrafts();c.requests[1].reject(Error('offline'));await retry;assert.equal(c.workspaceDraftState.rows.length,1);
  const forbidden=c.loadWorkspaceDrafts();c.requests[2].reject(Object.assign(Error('forbidden'),{status:403}));await forbidden;
  assert.equal(c.workspaceDraftState.rows.length,0);assert.equal(c.nodes['#draftNavCount'].textContent,'—');
});
test('load-more dedupes by stable kind/id key and retains full total',async()=>{
  const c=harness(), a=c.loadWorkspaceDrafts();c.requests[0].resolve({items:[{key:'cloud:a'}],total:2,has_more:true,next_cursor:'cursor'});await a;
  const b=c.loadWorkspaceDrafts({append:true});assert.match(c.requests[1].path,/cursor=cursor/);c.requests[1].resolve({items:[{key:'cloud:a'},{key:'official:b'}],total:2,has_more:false});await b;
  assert.equal(c.workspaceDraftState.rows.length,2);
});
test('assigned approver cannot become acted and operations/delegated remain reachable',()=>{
  const c={authState:{user:{id:'A'}},officialDocumentIsApplicant:item=>item.applicant_id==='A',hasAuthenticatedBackendSession:()=>true,approvalRecordIsOverdue:()=>true};vm.createContext(c);vm.runInContext(extract('approvalRecordMatchesView'),c);
  assert.equal(c.approvalRecordMatchesView({officialDocument:{applicant_id:'A',approval_steps:[{approver_user_id:'A',status:'approved'}]}},'acted'),false);
  assert.equal(c.approvalRecordMatchesView({officialDocument:{approval_views:{acted:true}}},'acted'),true);
  assert.equal(c.approvalRecordMatchesView({officialDocument:{can_manage_dispatch:true}},'pending','operations'),true);
  assert.equal(c.approvalRecordMatchesView({officialDocument:{can_act:true,delegation_id:'D'}},'pending','delegated'),true);
});
test('compose entry does not restore or list old snapshots and company precedes department',()=>{
  assert.doesNotMatch(extract('prepareComposeDraftRecovery'),/restoreComposeAutosave|refreshComposeCloudDrafts|renderComposeRecoveryPrompt/);
  const html=fs.readFileSync(require('node:path').join(__dirname,'..','index.html'),'utf8');
  assert.ok(html.indexOf('id="uploadedSealCompany"')<html.indexOf('id="uploadedSealDepartment"'));
  for(const key of ['pending','mine','acted','rejected'])assert.match(html,new RegExp(`data-approval-log-filter="${key}"`));
});
