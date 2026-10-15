"""Dispatch UX regressions with real shipping functions and synthetic data."""
import json
from pathlib import Path
import subprocess
import unittest

from tests.test_inbound_lazy_loading import extract_function

ROOT = Path(__file__).resolve().parents[1]


class DispatchFrontendP1Tests(unittest.TestCase):
    def run_js(self, names, body):
        source = (ROOT / "app.js").read_text()
        functions = "\n".join(extract_function(source, name) for name in names)
        script = """
const vm=require('node:vm'),assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const stored=new Map();
const c={console,JSON,String,Array,Number,Boolean,Map,Set,Promise,Error,URLSearchParams,TextEncoder,
 crypto:webcrypto,scope:'actor-a:company-a',authState:{user:{id:'actor-a'},token:'synthetic-a'},
 frontendSessionScope:()=>c.scope,hasAuthenticatedBackendSession:()=>true,
 readScopedSessionJson:(name,fallback)=>stored.has(c.scope+name)?JSON.parse(stored.get(c.scope+name)):fallback,
 writeScopedSessionJson:(name,value)=>stored.set(c.scope+name,JSON.stringify(value)),
 newInboundIdempotencyKey:prefix=>prefix+'-'+webcrypto.randomUUID(),
 internalDispatchItems:[],internalDispatchLoadGeneration:0,internalDispatchLoadStatus:'idle',
 internalDispatchCreateIntents:new Map(),
 internalDispatchPageState:{scope:'',cursor:'',nextCursor:null,hasMore:false,count:null,history:[],request:null,requestKey:''},
 internalDispatchRecipientDirectory:[],selectedInternalDispatchId:'',canCreateInternalDispatch:()=>true,
 document:{querySelector:()=>null,querySelectorAll:()=>[]},
 renderInternalDispatchModule(){},refreshDashboardWorkEntryPoints(){},notices:[],showToast:text=>c.notices.push(text)};
vm.createContext(c);vm.runInContext(JSON.parse(process.argv[1]),c);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const page=items=>({items,hasMore:false,nextCursor:null,count:items.length,scopeComplete:true});
(async()=>{BODY})().catch(error=>{console.error(error);process.exitCode=1});
""".replace("BODY", body)
        result = subprocess.run(["node", "-e", script, json.dumps(functions)], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_retry_intent_is_stable_private_and_actor_scoped(self):
        self.run_js(["canonicalizeInboundMutationValue", "internalDispatchCreateIntent", "clearInternalDispatchCreateIntent"], """
const payload={subject:'sensitive synthetic subject',body:'private synthetic content',recipients:[{user_id:'A',action_required:true}]};
const one=await c.internalDispatchCreateIntent(payload);
const two=await c.internalDispatchCreateIntent({...payload});
assert.equal(one.key,two.key);assert.match(one.digest,/^[0-9a-f]{64}$/);
assert.ok(![...stored.values()].join('').includes(payload.subject));
assert.ok(![...stored.values()].join('').includes(payload.body));
const changed=await c.internalDispatchCreateIntent({...payload,subject:'another synthetic subject'});
assert.notEqual(one.key,changed.key);
c.scope='actor-b:company-a';const other=await c.internalDispatchCreateIntent(payload);assert.notEqual(one.key,other.key);
c.scope='actor-a:company-a';const retry=await c.internalDispatchCreateIntent(payload);assert.equal(retry.key,one.key);
c.clearInternalDispatchCreateIntent(one.digest,one.key);
const next=await c.internalDispatchCreateIntent(payload);assert.notEqual(next.key,one.key);
""")

    def test_required_reply_blocks_close_but_informed_only_does_not(self):
        self.run_js(["internalDispatchPendingReplies"], """
assert.equal(c.internalDispatchPendingReplies({reply_required:true,recipients:[{action_required:true,status:'pending'},{action_required:false,status:'pending'},{action_required:true,status:'replied'}]}).length,1);
assert.equal(c.internalDispatchPendingReplies({reply_required:false,recipients:[{action_required:true,status:'pending'}]}).length,0);
assert.equal(c.internalDispatchPendingReplies({reply_required:true,recipients:[{action_required:false,status:'pending'}]}).length,0);
""")

    def test_retry_remains_stable_when_browser_storage_is_unavailable(self):
        self.run_js(["canonicalizeInboundMutationValue", "internalDispatchCreateIntent", "clearInternalDispatchCreateIntent"], """
c.readScopedSessionJson=(_name,fallback)=>fallback;c.writeScopedSessionJson=()=>{};
const first=await c.internalDispatchCreateIntent({subject:'synthetic'});
assert.equal((await c.internalDispatchCreateIntent({subject:'synthetic'})).key,first.key);
c.clearInternalDispatchCreateIntent(first.digest,first.key);
assert.notEqual((await c.internalDispatchCreateIntent({subject:'synthetic'})).key,first.key);
""")

    def test_new_handover_responsibility_wins_over_same_person_old_reply(self):
        self.run_js(["internalDispatchRecipientForCurrentUser", "internalDispatchCurrentRecipient", "canReplyInternalDispatch", "internalDispatchNeedsMyReply"], """
const item={reply_required:true,status:'sent',recipients:[{id:'old',recipient_user_id:'actor-a',action_required:true,status:'replied'},{id:'transferred',recipient_user_id:'actor-a',action_required:false,status:'reassigned'},{id:'new',recipient_user_id:'actor-a',action_required:true,status:'pending'}]};
assert.equal(c.internalDispatchCurrentRecipient(item).id,'new');assert.equal(c.canReplyInternalDispatch(item),true);assert.equal(c.internalDispatchNeedsMyReply(item),true);
item.recipients[2].status='replied';assert.equal(c.canReplyInternalDispatch(item),false);
item.recipients=item.recipients.filter(x=>x.status==='reassigned');assert.equal(c.internalDispatchCurrentRecipient(item),null);assert.equal(c.canReplyInternalDispatch(item),false);
""")

    def test_loader_uses_scoped_pages_and_keeps_page_on_failure(self):
        self.run_js(["loadInternalDispatches"], """
c.calls=[];c.backendRequest=path=>{c.calls.push(path);return Promise.resolve({items:[{id:'D1'}],hasMore:true,nextCursor:'opaque-next',count:70,scopeComplete:true})};
await c.loadInternalDispatches(false,{includeDirectory:false});
assert.match(c.calls[0],/paginated=1/);assert.match(c.calls[0],/page_size=50/);
assert.equal(c.internalDispatchItems[0].id,'D1');assert.equal(c.internalDispatchPageState.hasMore,true);
c.backendRequest=path=>{c.calls.push(path);return Promise.resolve(page([{id:'D2'}]))};
await c.loadInternalDispatches(false,{includeDirectory:false,cursor:'opaque-next',direction:'next'});
assert.match(c.calls.at(-1),/cursor=opaque-next/);assert.equal(c.internalDispatchItems[0].id,'D2');assert.equal(c.internalDispatchPageState.history.length,1);
c.backendRequest=()=>Promise.reject(new Error('offline'));
await c.loadInternalDispatches(false,{includeDirectory:false,cursor:'',direction:'previous'});
assert.equal(c.internalDispatchItems[0].id,'D2');assert.equal(c.internalDispatchPageState.cursor,'opaque-next');assert.equal(c.internalDispatchPageState.history.length,1);assert.equal(c.internalDispatchLoadStatus,'error');
""")

    def test_old_session_response_cannot_replace_current_list(self):
        self.run_js(["loadInternalDispatches"], """
const old=deferred();c.backendRequest=()=>old.promise;
const request=c.loadInternalDispatches(false,{includeDirectory:false});
c.scope='actor-b:company-b';c.authState.token='synthetic-b';
c.backendRequest=()=>Promise.resolve(page([{id:'D-B'}]));
await c.loadInternalDispatches(false,{includeDirectory:false});
old.resolve(page([{id:'D-A'}]));await request;
assert.equal(c.internalDispatchItems.length,1);assert.equal(c.internalDispatchItems[0].id,'D-B');
""")

    def test_pending_reply_filter_is_server_scoped_and_failure_preserves_previous_scope(self):
        self.run_js(["loadInternalDispatches"], """
c.backendRequest=()=>Promise.resolve(page([{id:'ALL'}]));await c.loadInternalDispatches(false,{includeDirectory:false});
c.backendRequest=()=>Promise.reject(new Error('offline'));await c.loadInternalDispatches(false,{includeDirectory:false,reset:true,needsReply:true});
assert.equal(c.internalDispatchItems[0].id,'ALL');assert.equal(c.internalDispatchPageState.needsReply,false);
c.backendRequest=path=>{assert.match(path,/needs_reply=1/);return Promise.resolve(page([{id:'OLDER-PENDING'}]))};
await c.loadInternalDispatches(false,{includeDirectory:false,reset:true,needsReply:true});
assert.equal(c.internalDispatchPageState.needsReply,true);assert.equal(c.internalDispatchItems[0].id,'OLDER-PENDING');
""")

    def test_close_cancel_and_pending_reply_make_no_mutation(self):
        self.run_js(["internalDispatchCurrentItem", "internalDispatchPendingReplies", "canCloseInternalDispatch", "performCloseInternalDispatch"], """
const item={id:'D1',subject:'synthetic',sender_user_id:'actor-a',status:'sent',reply_required:true,recipients:[{action_required:true,status:'pending'}]};
c.internalDispatchItems=[item];c.selectedInternalDispatchId='D1';c.calls=[];c.backendRequest=path=>{c.calls.push(path);return Promise.resolve({...item,status:'closed'})};
c.requestWorkspaceConfirmation=async()=>{throw new Error('must not offer premature close')};
await c.performCloseInternalDispatch('D1');assert.equal(c.calls.length,0);assert.match(c.notices.at(-1),/回覆/);
item.recipients[0].status='replied';c.requestWorkspaceConfirmation=async()=>false;
await c.performCloseInternalDispatch('D1');assert.equal(c.calls.length,0);
c.requestWorkspaceConfirmation=async()=>{c.authState.token='new-session';return true};
await c.performCloseInternalDispatch('D1');assert.equal(c.calls.length,0);
""")

    def test_create_retry_reuses_key_then_fresh_send_gets_new_intent(self):
        self.run_js(["canonicalizeInboundMutationValue", "internalDispatchCreateIntent", "clearInternalDispatchCreateIntent", "performCreateInternalDispatchFromForm"], """
const payload={inbound_document_id:'I1',title:'synthetic subject',subject:'synthetic subject',body:'synthetic body',reply_required:true,reply_due_days:3,recipients:[{user_id:'B',action_required:true}]};
c.internalDispatchFormPayload=()=>({...payload});
const nodes={};c.document.querySelector=selector=>nodes[selector]??(nodes[selector]={hidden:true,textContent:'',value:'draft'});
c.loadInternalDispatches=async()=>{};c.calls=[];
c.backendRequest=async(path,options)=>{c.calls.push(JSON.parse(options.body));if(c.calls.length===1)throw new Error('response lost');return {id:'D1',...payload}};
await c.performCreateInternalDispatchFromForm();
assert.equal(nodes['#internalDispatchTitleInput'],undefined,'unknown response preserves form');
assert.match(nodes['#internalDispatchCreateNotice'].textContent,/相同內容重試/);
await c.performCreateInternalDispatchFromForm();
assert.equal(c.calls[0].idempotency_key,c.calls[1].idempotency_key);
assert.equal(nodes['#internalDispatchTitleInput'].value,'');assert.equal(c.selectedInternalDispatchId,'D1');
await c.performCreateInternalDispatchFromForm();assert.notEqual(c.calls[2].idempotency_key,c.calls[1].idempotency_key);
""")

    def test_create_late_response_cannot_clear_next_session_form(self):
        self.run_js(["performCreateInternalDispatchFromForm"], """
const payload={inbound_document_id:'I1',title:'subject',body:'body',reply_required:false,recipients:[{user_id:'B'}]};
c.internalDispatchFormPayload=()=>payload;c.internalDispatchCreateIntent=async()=>({key:'retry',digest:'digest'});
c.clearInternalDispatchCreateIntent=()=>{throw new Error('must not clear another session intent')};
const old=deferred();c.backendRequest=()=>old.promise;const request=c.performCreateInternalDispatchFromForm();await new Promise(resolve=>setTimeout(resolve,0));
c.scope='new-user:new-company';c.authState.token='new-token';c.selectedInternalDispatchId='NEW';old.resolve({id:'OLD'});await request;
assert.equal(c.selectedInternalDispatchId,'NEW');assert.equal(c.internalDispatchItems.length,0);
""")


if __name__ == "__main__":
    unittest.main()
