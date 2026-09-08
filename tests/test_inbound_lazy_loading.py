from pathlib import Path
import json
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


def extract_function(source, name):
    match = re.search(r"(?:async )?function " + re.escape(name) + r"\([^\n]*\) \{\n.*?\n\}", source, re.S)
    if not match:
        raise AssertionError(f"missing_function:{name}")
    return match.group(0)


class InboundLazyLoadingTest(unittest.TestCase):
    def test_live_loader_preserves_scope_and_failure_state(self):
        source = (ROOT / "app.js").read_text()
        functions = "\n".join(extract_function(source, name) for name in (
            "renderInboundLoadStatus", "renderInboundRows", "loadInboundDocuments"))
        script = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const funcs=JSON.parse(process.argv[1]);
function setup(){
 const nodes={};
 for(const id of ['#inboundLoadNotice','#inboundReloadBtn','#inboundCount','#inboundRows'])nodes[id]={hidden:true,disabled:false,textContent:'',innerHTML:'',classList:{toggle(){}},addEventListener(){}};
 const c={console,Promise,Error,Array,Number,Boolean,hasAuthenticatedBackendSession:()=>c.authenticated,frontendSessionScope:()=>c.scope,
 document:{querySelector:s=>nodes[s]||null,querySelectorAll:()=>[]},
 inboundDocs:[],inboundDocumentLoadState:{scope:'',status:'idle',request:null,generation:0},selectedInboundId:'',routeBackendDataLoaded:new Set(['inbound']),
 scope:'employee:company-a',authenticated:true,calls:[],notices:[],nodes,
 escapeHtml:s=>String(s||''),safeHtmlClassToken:s=>s,badgeClass:()=>'',inboundSourceLabel:()=>'',
 renderInboundDetail(){},openInboundModal(){},renderInternalDispatchDocumentOptions(){},refreshDashboardWorkEntryPoints(){},
 showToast:s=>c.notices.push(s),filteredInboundDocs:()=>c.inboundDocs,
 backendRequest:p=>{c.calls.push(p);return Promise.resolve([])},
 applyPersistentInboundDocuments:rows=>{c.inboundDocs.splice(0,c.inboundDocs.length,...rows);c.renderInboundRows()}};
 vm.createContext(c);vm.runInContext(funcs,c);return c;
}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
(async()=>{
 let passed=0,c=setup();let d=deferred();c.backendRequest=p=>{c.calls.push(p);return d.promise};
 let first=c.loadInboundDocuments(),second=c.loadInboundDocuments();
 assert.equal(c.calls.length,1);assert.equal(c.calls[0],'/inbound-documents');assert.equal(c.nodes['#inboundReloadBtn'].disabled,true);
 d.resolve([{id:'IN-1',subject:'synthetic'}]);await Promise.all([first,second]);
 assert.equal(c.inboundDocs.length,1);assert.equal(c.inboundDocumentLoadState.status,'loaded');assert.equal(c.nodes['#inboundReloadBtn'].disabled,false);passed++;

 c.backendRequest=()=>Promise.reject(new Error('offline'));
 await assert.rejects(c.loadInboundDocuments(false));assert.equal(c.inboundDocs.length,1);
 assert.equal(c.inboundDocumentLoadState.status,'error');assert.match(c.nodes['#inboundCount'].textContent,/上次資料/);
 assert.match(c.nodes['#inboundLoadNotice'].textContent,/保留/);assert.equal(c.routeBackendDataLoaded.has('inbound'),false);passed++;

 c=setup();c.backendRequest=()=>Promise.reject(new Error('offline'));await assert.rejects(c.loadInboundDocuments());
 assert.equal(c.nodes['#inboundCount'].textContent,'尚未載入');assert.match(c.nodes['#inboundRows'].innerHTML,/載入失敗/);
 assert.doesNotMatch(c.nodes['#inboundRows'].innerHTML,/目前沒有/);assert.match(c.nodes['#inboundLoadNotice'].textContent,/不代表沒有/);passed++;
 c.backendRequest=()=>Promise.resolve([{id:'IN-RETRY'}]);await c.loadInboundDocuments();assert.equal(c.inboundDocs[0].id,'IN-RETRY');assert.equal(c.nodes['#inboundLoadNotice'].hidden,true);passed++;

 c=setup();d=deferred();c.backendRequest=()=>d.promise;first=c.loadInboundDocuments();c.scope='employee:company-b';
 let newer=deferred();c.backendRequest=()=>newer.promise;second=c.loadInboundDocuments();newer.resolve([{id:'IN-B'}]);await second;
 d.resolve([{id:'IN-A'}]);await first;assert.equal(c.inboundDocs.length,1);assert.equal(c.inboundDocs[0].id,'IN-B');passed++;

 c=setup();d=deferred();c.backendRequest=()=>d.promise;first=c.loadInboundDocuments();c.authenticated=false;
 d.resolve([{id:'IN-OLD'}]);await first;assert.equal(c.inboundDocs.length,0);passed++;

 c=setup();c.backendRequest=()=>Promise.resolve({rows:[]});await assert.rejects(c.loadInboundDocuments(),/inbound_list_response_invalid/);
 assert.equal(c.inboundDocumentLoadState.status,'error');passed++;

 c=setup();c.authenticated=false;await c.loadInboundDocuments();assert.equal(c.calls.length,0);passed++;
 process.stdout.write(JSON.stringify({passed}));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run(["node", "-e", script, json.dumps(functions)], cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["passed"], 8)

    def test_route_uses_narrow_loader_and_exposes_retry(self):
        source = (ROOT / "app.js").read_text()
        route = extract_function(source, "loadRouteBackendData")
        inbound = re.search(r'if \(target === "inbound"\) \{(.*?)\n    \}', route, re.S).group(1)
        self.assertIn("loadInboundDocuments(silent)", inbound)
        self.assertNotIn("syncDatabaseFromBackend", inbound)
        self.assertIn('document.querySelector("#inboundReloadBtn")?.addEventListener("click"', source)
        html = (ROOT / "index.html").read_text()
        self.assertRegex(html, r'id="inboundLoadNotice" role="status" aria-live="polite"')
        self.assertIn('id="inboundReloadBtn" type="button"', html)

    def test_mobile_record_cards_preserve_columns_and_actions(self):
        source = (ROOT / "app.js").read_text()
        render = extract_function(source, "renderInboundRows")
        for label in ("收文號", "收錄來源", "來文單位", "主旨", "狀態", "承辦"):
            self.assertIn(f'data-label="{label}"', render)
        self.assertIn('data-select-inbound="${escapeHtml(doc.id)}"', render)
        self.assertIn('event.key !== "Enter" && event.key !== " "', render)
        css = (ROOT / "styles.css").read_text()
        self.assertRegex(css, r'\.inbound-list-panel table\s*\{\s*min-width: 1040px;')
        self.assertIn('@media (max-width: 760px) {\n  .inbound-list-panel .table-wrap', css)
        self.assertIn('.inbound-list-panel tbody td:nth-child(4)', css)
        self.assertRegex(css, r'#inbound \.internal-dispatch-recipient-action\s*\{\s*font-size: 16px;')


if __name__ == "__main__":
    unittest.main()
