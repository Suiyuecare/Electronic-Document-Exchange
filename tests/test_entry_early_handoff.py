"""The head probe must preserve the app's one-time handoff and error semantics."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

from tests.test_electronic_seal_editor_ui_contract import javascript_function


ROOT = Path(__file__).resolve().parents[1]


class EntryEarlyHandoffTest(unittest.TestCase):
    def run_case(self, case: str) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for entry handoff lifecycle tests")
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        bootstrap = (ROOT / "entry-bootstrap.js").read_text(encoding="utf-8")
        functions = "\n".join(javascript_function(source, name) for name in (
            "readCookieValue", "isProductionEdocHost", "edocReturnUrlForPortal",
            "buildLoggingPortalUrl", "redirectToLoggingPortal", "clearPostedHandoffMarker",
            "resumePostedHandoffSession", "backendRequest", "isRetryableAuthError",
            "waitForAuthRetry", "backendAuthRequestWithTransientRetry",
        ))
        harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const host = bootstrapSource.match(/hostname !== "([^"]+)"/)[1];
const loggingPortalUrl = appSource.match(/const loggingPortalUrl = "([^"]+)"/)[1];
const authStorageKey = 'suiyuecare-edoc-session';
const edocHandoffMarkerCookieKey = 'suiyuecare-edoc-handoff-pending';
const backendApiBase = `https://${host}/api`;
let authState = null;
let storage = new Map(), requests = [], redirects = [], entered = [], persisted = [], retryDelays = [], progress = [], warnings = [];
let responseFactory = () => new Response(JSON.stringify({error:'handoff_session_missing'}), {status:401});
const location = {hostname:host, href:`https://${host}/?localLogin=1&tab=work#compose`, search:'?localLogin=1&tab=work', pathname:'/', hash:'#compose', replace: value => redirects.push(value)};
global.window = {location, name:'', localStorage:{getItem:key=>storage.get(key)||null,removeItem:key=>storage.delete(key)},setTimeout:(fn,delay)=>{retryDelays.push(delay);queueMicrotask(fn);}};
global.document = {cookie:'',querySelector:()=>null,documentElement:{}};
global.localStorage = window.localStorage;
global.MutationObserver = class {observe(){} disconnect(){}};
global.fetch = async (...args) => {requests.push(args);return await responseFactory(requests.length);};
global.console = {...console,warn: message=>warnings.push(message)};
const isHeaderSafeToken = token => typeof token==='string' && /^[\x21-\x7e]+$/.test(token);
const friendlyBackendErrorMessage = text=>text;
const setModuleEntryProgress = (...value)=>progress.push(value);
const persistAuthenticatedSession = session=>persisted.push(session);
const rejectNonSetupUserDuringLaunchSetup = async()=>false;
const runAuthenticatedEntryStep = (name,fn)=>fn();
const syncUserAccountFromSession = ()=>{};
const recordLogin = ()=>{};
const addAccountAudit = ()=>{};
const enterAuthenticatedAppSafely = value=>{entered.push(value);return true;};
const resetCachedSessionShellReveal = ()=>{};
const portalSsoFailureCode = error=>isRetryableAuthError(error)?'sso_unavailable':'sso_denied';
const returnToLoggingPortalModulePicker = code=>redirects.push({moduleError:code});
const runBootstrap = ()=>vm.runInThisContext(bootstrapSource);
const tick = ()=>new Promise(resolve=>setImmediate(resolve));
const session = {token:'synthetic-session',user:{id:'synthetic-user',name:'Synthetic Employee',email:'employee@example.test'}};
'''
        program = (
            "const bootstrapSource=" + json.dumps(bootstrap) + ";\n"
            "const appSource=" + json.dumps(source) + ";\n"
            + harness + "\n" + functions + "\n(async()=>{\n" + case
            + "\n})().catch(error=>{process.stderr.write(String(error.stack));process.exitCode=1;});"
        )
        result = subprocess.run([node], input=program, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_session_probes_before_app_and_redirects_to_identical_safe_portal_target(self):
        self.run_case("""
runBootstrap(); await tick();
assert.equal(requests.length,1); assert.equal(requests[0][0],'/api/auth/handoff-session');
assert.deepEqual(requests[0][1],{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-EDOC-Handoff-Exchange':'1'},body:'{}'});
assert.deepEqual(redirects,[buildLoggingPortalUrl()]);
const destination=new URL(redirects[0]),next=new URL(destination.searchParams.get('next'));
assert.equal(destination.searchParams.get('module'),'edoc');assert.equal(next.hash,'');
assert.equal(next.searchParams.has('localLogin'),false);assert.equal(next.searchParams.get('tab'),'work');
assert.equal(entered.length,0);assert.equal(persisted.length,0);
assert.equal(await resumePostedHandoffSession(),null);assert.equal(requests.length,1);
""")

    def test_invisible_http_only_session_success_is_consumed_exactly_once_by_app(self):
        self.run_case("""
let response;responseFactory=()=>response=new Response(JSON.stringify(session));
runBootstrap();await tick();assert.equal(requests.length,1);assert.equal(redirects.length,0);
assert.equal(response.bodyUsed,false);assert.equal(entered.length,0);assert.equal(persisted.length,0);
assert.equal(await resumePostedHandoffSession(),true);
assert.equal(requests.length,1);assert.equal(response.bodyUsed,true);assert.deepEqual(authState,session);
assert.equal(entered.length,1);assert.equal(persisted.length,1);assert.equal(window.__edocEarlyHandoffResponse,null);
assert.equal(await resumePostedHandoffSession(),null);assert.equal(requests.length,1);
""")

    def test_app_claiming_pending_probe_prevents_head_redirect_or_duplicate_request(self):
        self.run_case("""
let release;responseFactory=()=>new Promise(resolve=>release=resolve);
runBootstrap();await tick();const resumed=resumePostedHandoffSession();
release(new Response(JSON.stringify({error:'handoff_session_missing'}),{status:401}));
assert.equal(await resumed,null);await tick();
assert.equal(requests.length,1);assert.equal(redirects.length,0);assert.equal(entered.length,0);
""")

    def test_early_temporary_failure_reuses_original_response_then_normal_retry(self):
        self.run_case("""
responseFactory=attempt=>new Response(JSON.stringify(attempt===1?{error:'auth_busy',retryable:true}:session),{status:attempt===1?503:200});
runBootstrap();await tick();assert.equal(requests.length,1);assert.equal(redirects.length,0);
assert.equal(await resumePostedHandoffSession(),true);
assert.equal(requests.length,2);assert.deepEqual(retryDelays,[350]);assert.deepEqual(authState,session);
assert.equal(redirects.length,0);assert.equal(entered.length,1);
""")

    def test_exhausted_transient_error_retains_existing_retry_policy(self):
        self.run_case("""
responseFactory=()=>new Response(JSON.stringify({error:'auth_busy'}),{status:503});
runBootstrap();await tick();assert.equal(redirects.length,0);
assert.equal(await resumePostedHandoffSession(),true);
assert.equal(requests.length,3);assert.deepEqual(retryDelays,[350,900]);
assert.deepEqual(redirects,[{moduleError:'sso_unavailable'}]);assert.equal(document.cookie,'');
assert.equal(entered.length,0);assert.equal(persisted.length,0);
""")

    def test_only_exact_missing_401_may_redirect_before_app(self):
        for status, body in [(401, '{"error":"session_expired"}'), (403, '{"error":"handoff_session_missing"}'), (500, '{"error":"handoff_session_missing"}'), (401, 'not-json')]:
            with self.subTest(status=status, body=body):
                self.run_case("""
responseFactory=()=>new Response(%s,{status:%d});
runBootstrap();await tick();assert.equal(redirects.length,0);assert.equal(entered.length,0);
assert.equal(await resumePostedHandoffSession(),true);assert.equal(requests.length,1);
assert.deepEqual(redirects,[{moduleError:'sso_denied'}]);assert.equal(persisted.length,0);
""" % (json.dumps(body), status))

    def test_network_rejection_is_preserved_without_unhandled_rejection_or_early_redirect(self):
        self.run_case("""
let unhandled=[];process.on('unhandledRejection',error=>unhandled.push(error));
const networkError=new TypeError('synthetic network failure');responseFactory=()=>Promise.reject(networkError);
runBootstrap();await tick();await tick();assert.equal(unhandled.length,0);assert.equal(redirects.length,0);
assert.equal(await resumePostedHandoffSession(),true);assert.equal(requests.length,1);
assert.deepEqual(redirects,[{moduleError:'sso_denied'}]);assert.equal(entered.length,0);
""")

    def test_cached_session_marker_and_legacy_bridges_remain_with_main_flow(self):
        setups = [
            "storage.set(authStorageKey,JSON.stringify(session));",
            "document.cookie='suiyuecare-edoc-handoff-pending=1';",
            "document.cookie='suiyue_hris_quick_login_user=encoded';",
            "window.name='suiyue_hris_quick_login_user:'+JSON.stringify({user:{id:'synthetic'}});",
            "window.name='suiyue_hris_quick_login_user:'+encodeURIComponent(JSON.stringify({user:{id:'synthetic'}}));",
        ] + ["storage.set(%s,JSON.stringify({user:{id:'synthetic'}}));" % json.dumps(key) for key in (
            "suiyue-hris-quick-login-user", "suiyuecare-logging-session", "suiyue-logging-session", "suiyue-platform-session",
        )]
        for setup in setups:
            with self.subTest(setup=setup):
                self.run_case(setup + "\nrunBootstrap();await tick();assert.equal(requests.length,0);assert.equal(redirects.length,0);assert.equal(window.__edocEarlyHandoffResponse,undefined);")

    def test_fresh_session_or_bridge_arriving_during_probe_prevents_head_redirect(self):
        setups = [
            "storage.set(authStorageKey,JSON.stringify(session));",
            "storage.set('suiyuecare-logging-session',JSON.stringify({session:{id:'synthetic'}}));",
            "window.name='suiyue_hris_quick_login_user:'+encodeURIComponent(JSON.stringify({user:{id:'synthetic'}}));",
            "document.cookie='suiyuecare-edoc-handoff-pending=1';",
            "document.cookie='suiyue_hris_quick_login_user=encoded';",
        ]
        for setup in setups:
            with self.subTest(setup=setup):
                self.run_case("""
let release;responseFactory=()=>new Promise(resolve=>release=resolve);
runBootstrap();await tick();
""" + setup + """
release(new Response(JSON.stringify({error:'handoff_session_missing'}),{status:401}));await tick();
assert.equal(requests.length,1);assert.equal(redirects.length,0);assert.equal(entered.length,0);
assert.equal(persisted.length,0);
""")

    def test_new_marker_after_exact_early_missing_response_reprobes_new_http_only_handoff(self):
        self.run_case("""
let release;responseFactory=attempt=>attempt===1?new Promise(resolve=>release=resolve):new Response(JSON.stringify(session));
runBootstrap();await tick();document.cookie='suiyuecare-edoc-handoff-pending=1';
release(new Response(JSON.stringify({error:'handoff_session_missing'}),{status:401}));await tick();
assert.equal(redirects.length,0);assert.equal(requests.length,1);
assert.equal(await resumePostedHandoffSession(),true);
assert.equal(requests.length,2);assert.deepEqual(authState,session);
assert.equal(entered.length,1);assert.equal(persisted.length,1);assert.equal(redirects.length,0);
assert.equal(document.cookie.includes('Max-Age=0'),true);assert.deepEqual(retryDelays,[]);
""")

    def test_new_marker_does_not_discard_successful_or_non_missing_error_response(self):
        for status, body in [(200, '{"token":"synthetic-session","user":{"name":"Synthetic Employee","email":"employee@example.test"}}'), (403, '{"error":"handoff_session_missing"}'), (401, '{"error":"session_expired"}'), (401, 'not-json')]:
            with self.subTest(status=status, body=body):
                self.run_case("""
let release;responseFactory=()=>new Promise(resolve=>release=resolve);
runBootstrap();await tick();document.cookie='suiyuecare-edoc-handoff-pending=1';
release(new Response(%s,{status:%d}));await tick();
assert.equal(redirects.length,0);assert.equal(await resumePostedHandoffSession(),true);
assert.equal(requests.length,1);assert.deepEqual(retryDelays,[]);
assert.equal(entered.length,%d);assert.equal(persisted.length,%d);
""" % (json.dumps(body), status, 1 if status == 200 else 0, 1 if status == 200 else 0))

    def test_marker_arriving_after_main_claims_pending_probe_is_checked_after_response(self):
        self.run_case("""
let release;responseFactory=attempt=>attempt===1?new Promise(resolve=>release=resolve):new Response(JSON.stringify(session));
runBootstrap();await tick();const resumed=resumePostedHandoffSession();
document.cookie='suiyuecare-edoc-handoff-pending=1';
release(new Response(JSON.stringify({error:'handoff_session_missing'}),{status:401}));
assert.equal(await resumed,true);await tick();
assert.equal(requests.length,2);assert.deepEqual(authState,session);
assert.equal(entered.length,1);assert.equal(persisted.length,1);assert.equal(redirects.length,0);
""")

    def test_new_marker_retains_transient_response_as_first_normal_retry_attempt(self):
        self.run_case("""
let release;responseFactory=attempt=>attempt===1?new Promise(resolve=>release=resolve):new Response(JSON.stringify(session));
runBootstrap();await tick();document.cookie='suiyuecare-edoc-handoff-pending=1';
release(new Response(JSON.stringify({error:'auth_busy'}),{status:503}));await tick();
assert.equal(redirects.length,0);assert.equal(await resumePostedHandoffSession(),true);
assert.equal(requests.length,2);assert.deepEqual(retryDelays,[350]);
assert.equal(entered.length,1);assert.equal(persisted.length,1);
""")

    def test_malformed_or_encoded_storage_matches_main_json_only_reader(self):
        for raw in ('not-json', '%7B%22user%22%3A%7B%22id%22%3A%22synthetic%22%7D%7D', '{}'):
            with self.subTest(raw=raw):
                self.run_case("storage.set('suiyuecare-logging-session'," + json.dumps(raw) + ");\nrunBootstrap();await tick();assert.equal(requests.length,1);assert.equal(redirects.length,1);")

    def test_duplicate_bootstrap_and_untrusted_query_handoff_do_not_exchange_twice(self):
        self.run_case("""
responseFactory=()=>new Response(JSON.stringify(session));
runBootstrap();runBootstrap();await tick();assert.equal(requests.length,1);
""")
        self.run_case("""
location.search='?token=synthetic-secret';location.href=`https://${host}/?token=synthetic-secret`;
runBootstrap();await tick();assert.equal(requests.length,0);assert.equal(redirects.length,1);
assert.equal(new URL(redirects[0]).searchParams.get('moduleError'),'sso_denied');
assert.equal(redirects[0].includes('synthetic-secret'),false);
""")

    def test_non_production_host_does_not_probe(self):
        self.run_case("""
location.hostname='localhost';runBootstrap();await tick();
assert.equal(requests.length,0);assert.equal(redirects.length,0);
""")

    def test_head_script_is_cache_busted_and_precedes_main_bundle(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("entry-bootstrap.js?v=20260914-early-handoff-r1", html)
        self.assertIn("app.js?v=20260922-workflow-audit-r1", html)
        self.assertLess(html.index('src="entry-bootstrap.js'), html.index('src="app.js'))


if __name__ == "__main__":
    unittest.main()
