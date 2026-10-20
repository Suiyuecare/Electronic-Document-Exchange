const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
const extract = name => { const m = new RegExp(`^(?:async )?function ${name}\\([^\\n]*\\) \\{\\n.*?^\\}`, 'ms').exec(source); assert.ok(m, name); return m[0]; };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function harness() {
  const attrs = {}; const status = {textContent:''};
  const c = {JSON, Promise, Map, String, Boolean, Error, clearTimeout, composeCloudTimer:null, scope:'A', epoch:1, snapshot:{subject:'saved'},
    composeCloudDraftId:'C', currentComposeDraftId:'', composeCloudOperation:null, composeCloudConflict:false,
    composeCloudSavedSnapshots:new Map([['C', JSON.stringify({subject:'saved'})]]), composeCloudRevisions:new Map([['C',1]]),composeCloudRows:[],
    workspaceDraftState:{rows:[{key:'cloud:C',id:'C',kind:'cloud',revision:1,can_archive:true,title:'Synthetic'}]},
    calls:[],resetCount:0,composeSaveState:{},
    workspaceDraftScope:()=>c.scope,composeRequestScope:()=>c.scope+'|'+c.epoch,composeRawSnapshot:()=>c.snapshot,composeInputIsComposing:()=>false,
    requestWorkspaceConfirmation:async()=>true, backendRequest:(path,opts)=>{c.calls.push({path,opts});return Promise.resolve({id:'C',archived:true,revision:2});},
    resetComposeAsyncScope:()=>{c.resetCount++;c.composeCloudDraftId='';},renderComposeSaveStatus(){},renderDraftPreview(){},applyComposeContactDefaults(){},
    readComposeAutosave:()=>null,clearComposeAutosave(){},loadWorkspaceDrafts:async()=>{},refreshWorkspaceDraftCount:async()=>{},showToast(){},
    document:{querySelector:s=>s==='#workspaceDraftActionStatus'?status:s==='#composeForm'?{reset(){}}: {setAttribute:(k,v)=>{attrs[k]=v;},focus(){}}},
    status};
  vm.createContext(c);vm.runInContext(extract('changeWorkspaceDraftArchive'),c);return c;
}
test('archive confirmation cancel is zero mutations and leaves editor intact',async()=>{
 const c=harness();c.requestWorkspaceConfirmation=async()=>false;await c.changeWorkspaceDraftArchive('cloud:C',true);
 assert.equal(c.calls.length,0);assert.equal(c.resetCount,0);assert.equal(c.workspaceDraftState.actionPending,false);
});
test('unsaved or in-flight edits refuse archive before confirming',async()=>{
 for(const change of [c=>c.snapshot={subject:'later'},c=>c.composeCloudOperation=Promise.resolve()]){
  const c=harness();change(c);await c.changeWorkspaceDraftArchive('cloud:C',true);assert.equal(c.calls.length,0);assert.match(c.status.textContent,/未同步/);assert.equal(c.resetCount,0);
 }
});
test('typing or switching draft during confirmation does not mutate or reset',async()=>{
 for(const change of [c=>c.snapshot={subject:'later'},c=>c.epoch++]){
  const c=harness(), d=deferred();c.requestWorkspaceConfirmation=()=>d.promise;const p=c.changeWorkspaceDraftArchive('cloud:C',true);change(c);d.resolve(true);await p;
  assert.equal(c.calls.length,0);assert.equal(c.resetCount,0);assert.match(c.status.textContent,/變更/);
 }
});
test('later typing during archive response is preserved, never silently reset',async()=>{
 const c=harness(), d=deferred();c.backendRequest=(path,opts)=>{c.calls.push({path,opts});return d.promise;};
 const p=c.changeWorkspaceDraftArchive('cloud:C',true);await new Promise(setImmediate);c.snapshot={subject:'later typing'};d.resolve({id:'C',archived:true});await p;
 assert.equal(c.calls.length,1);assert.equal(c.resetCount,0);assert.equal(c.snapshot.subject,'later typing');assert.equal(c.composeCloudConflict,true);assert.match(c.status.textContent,/後來的編輯/);
});
test('new actor or other draft is not reset by old successful response',async()=>{
 for(const change of [c=>c.scope='B',c=>{c.epoch++;c.composeCloudDraftId='OTHER';c.snapshot={subject:'other'};}]){
  const c=harness(),d=deferred();c.backendRequest=()=>d.promise;const p=c.changeWorkspaceDraftArchive('cloud:C',true);await new Promise(setImmediate);change(c);d.resolve({id:'C',archived:true});await p;assert.equal(c.resetCount,0);
 }
});
test('archive failure remains inline and does not remove rows or reset data',async()=>{
 const c=harness();c.backendRequest=async()=>{throw Object.assign(new Error('down'),{status:503});};await c.changeWorkspaceDraftArchive('cloud:C',true);
 assert.equal(c.workspaceDraftState.rows.length,1);assert.equal(c.resetCount,0);assert.match(c.status.textContent,/未確認/);
});
test('background draft loader does not consume composing search',async()=>{
 const c={authState:{token:'t'},isRouteAllowed:()=>true,workspaceDraftState:{searchComposing:true},calls:0,backendRequest:()=>{c.calls++;}};
 vm.createContext(c);vm.runInContext(extract('loadWorkspaceDrafts'),c);await c.loadWorkspaceDrafts();assert.equal(c.calls,0);
});
