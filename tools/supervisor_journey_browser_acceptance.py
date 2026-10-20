"""SUP01/SUP02: real Chromium, independent sessions, disposable loopback data.

Never authenticates real employees, contacts hosted APIs, or sends exchange/mail.
Viewport/touch geometry and synthetic 200% text are not physical-device proof.
No forced clicks or disabled-control bypasses. Faults affect only local fetches.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(os.environ.get("EDOC_ACCEPTANCE_SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT))
import backend
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as Fixture, QuietAcceptanceHandler
from tests.support.five_account_browser_fixture import isolated_browser_session
from tools.ux_complete_browser_acceptance import BRIDGE, TELEMETRY, require_local_origin
import tools.backup_drill_browser_acceptance as transport

DEVICES = [("desktop", 1440, 1000), ("tablet", 820, 1100), ("mobile", 390, 844)]
COMMENT = "隔離主管本次意見，尚未送出時必須保留參考。"
GEOMETRY = r"""(()=>{
 const panel=document.querySelector('#approvalLogDetailPanel'), p=panel.getBoundingClientRect();
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const regions=['.approval-log-summary','.approval-log-summary-head','.approval-review-evidence','.official-file-list','.official-file-row','.official-human-progress','.approval-review-decisions'];
 const wide=[...panel.querySelectorAll('*')].filter(visible).filter(e=>!e.closest('.approval-log-trail')).flatMap(e=>{
   const r=e.getBoundingClientRect(), parent=e.parentElement, q=parent.getBoundingClientRect();
   const inRegion=e.closest(regions.join(','));
   const outside=r.left<p.left-1||r.right>p.right+1||r.left< -1||r.right>innerWidth+1;
   const childOverflow=inRegion&&getComputedStyle(parent).display!=='inline'&&(r.left<q.left-1||r.right>q.right+1);
   return outside||childOverflow?[{tag:e.tagName,id:e.id,class:e.className,width:r.width,left:r.left,right:r.right,parentWidth:q.width,parentClass:parent.className,text:e.textContent.trim().slice(0,100)}]:[];
 });
 const targets=[...panel.querySelectorAll('button:not(:disabled),a[href]')].filter(visible).map(e=>{const r=e.getBoundingClientRect();return {text:e.textContent.trim(),width:r.width,height:r.height}});
 return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,panel:p.toJSON(),wide,targets};
})()"""
LIST_GEOMETRY = r"""(()=>{
 const list=document.querySelector('#approvalLogList'),p=list.getBoundingClientRect();
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const wide=[...list.querySelectorAll('.approval-case-card,.approval-case-card *')].filter(visible).flatMap(e=>{
   const r=e.getBoundingClientRect(),parent=e.parentElement,q=parent.getBoundingClientRect();
   const outside=r.left<p.left-1||r.right>p.right+1||r.left< -1||r.right>innerWidth+1;
   const overflow=getComputedStyle(parent).display!=='inline'&&(r.left<q.left-1||r.right>q.right+1);
   return outside||overflow?[{tag:e.tagName,class:e.className,width:r.width,left:r.left,right:r.right,parentWidth:q.width,text:e.textContent.trim().slice(0,100)}]:[];
 });
 const targets=[...list.querySelectorAll('button:not(:disabled)')].filter(visible).map(e=>{const r=e.getBoundingClientRect();return {text:e.textContent.trim(),width:r.width,height:r.height}});
 return {visible:visible(list),viewport:innerWidth,list:p.toJSON(),wide,targets};
})()"""


def bridge():
    executable = os.environ.get("EDOC_TEST_BROWSER_PATH")
    if not executable:
        candidates = sorted((Path.home()/"Library/Caches/ms-playwright").glob("chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell"), reverse=True)
        executable = str(candidates[0]) if candidates else ""
    result = BRIDGE
    if executable:
        result = result.replace("process.env.EDOC_TEST_BROWSER_PATH||process.argv[3]", json.dumps(executable))
    return result


class DiagnosticBrowser(transport.LocalPlaywrightBrowser):
    """Retain only local test selectors/conditions, never auth/eval payloads."""
    def click_visible(self, selector):
        # The native Playwright locator re-resolves a target after re-render and
        # scrolls it into view while checking visible/enabled/stable/hit-target.
        # The legacy helper scrolled once then polled the old center forever if
        # background rendering moved the target. Never force or dispatch a click.
        self.run("click", selector)

    def run(self, *args, script=None):
        if args and args[0] in {"click", "fill", "select", "press"}:
            self.last_control = {"command": args[0], "selector": str(args[1])}
        return super().run(*args, script=script)

    def until(self, expression, timeout=25):
        self.last_condition = expression
        return super().until(expression, timeout)


def run(output, devices=None, cases=None):
    output = output.resolve()
    os.chdir(ROOT)
    output.mkdir(parents=True, exist_ok=True)
    files = ("app.js", "styles.css", "index.html", "backend.py")
    hashes = lambda: {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}
    report = {"scope":"loopback_synthetic_two_session_chromium", "humanSSOVerified":False,
              "hostedVerified":False, "physicalDeviceVerified":False, "externalRequestsAllowed":False,
              "governmentExchange":"DISABLED", "sourceRoot":str(ROOT), "sourceHashesAtStart":hashes(), "cases":[]}
    html = (ROOT/"index.html").read_bytes().replace(b"<head>", b"<head>"+TELEMETRY.encode(), 1)
    original = QuietAcceptanceHandler.send_head
    def head(handler):
        if urlparse(handler.path).path not in {"/", "/index.html"}:
            return original(handler)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(html)))
        handler.end_headers()
        return io.BytesIO(html)
    def persist():
        (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    browsers=[]
    with mock.patch.object(QuietAcceptanceHandler,"send_head",head), mock.patch.object(transport,"PLAYWRIGHT_BRIDGE",bridge()):
        Fixture.setUpClass()
        require_local_origin(Fixture.origin)
        try:
            applicant=isolated_browser_session(Fixture,"staff",entity_id="E1")
            A=DiagnosticBrowser(Fixture.origin); browsers.append(A)
            B=DiagnosticBrowser(Fixture.origin); browsers.append(B)
            def document(label, long=False):
                doc_id="OD-SUP-"+hashlib.sha256(label.encode()).hexdigest()[:32]
                title=("合成長內容_"+"ContractReference0123456789"*5+"_跨機構公文附件驗收") if long else "合成主管驗收 "+label
                draft=Fixture._expect_json("POST","/api/official-documents",201,token=applicant["token"],json_body={
                    "id":doc_id,"source_type":"blank_editor","company_id":applicant["user"]["company_id"],
                    "document_type":"outgoing_official_document","output_mode":"electronic","title":title,"subject":title,
                    "description":"一、本件為去識別化隔離驗收，不向任何真實單位寄送或交換。",
                    "recipient":"合成驗收收文單位", "request_reason":"隔離測試", "document_category":"主管機關 申請或回覆文件（與 費用、法令無關）",
                    "dispatch_method":"email_by_general_affairs","submit":False,
                    "metadata":{"source":"compose_form","contact_owner":"合成申請人","contact_phone":"02-00000000 #999","contact_email":"fixture@example.invalid"}})
                if long:
                    Fixture._expect_json("POST","/api/official-documents/"+doc_id+"/files",201,token=applicant["token"],json_body={
                        "file_name":"合成超長附件_"+"ContractReference0123456789"*4+"_驗收.pdf",
                        "file_mime_type":"application/pdf","content_base64":base64.b64encode(Fixture._make_attachment_pdf(77)).decode("ascii")})
                    draft=Fixture._expect_json("GET","/api/official-documents/"+doc_id,200,token=applicant["token"])
                return Fixture._expect_json("POST","/api/official-documents/"+doc_id+"/submit",200,token=applicant["token"],json_body={"expected_content_revision":draft["content_revision"]})
            def sessions(doc):
                step=next(s for s in doc["approval_steps"] if s["step_key"]==doc["current_step"])
                with backend.connect() as conn:
                    person=conn.execute("SELECT * FROM users WHERE id=?",(step["approver_user_id"],)).fetchone()
                    identity=Fixture.identity_by_email[person["email"].lower()]
                    backend.sync_sqlite_finance_snapshot(conn,Fixture.snapshots_by_email[identity["email"]],auth_user_id=identity["auth_user_id"],expected_user_id=person["id"])
                    person=conn.execute("SELECT * FROM users WHERE id=?",(step["approver_user_id"],)).fetchone()
                    a=backend.create_session(conn,person,"Synthetic supervisor A","127.0.0.1","supervisor-browser-A")
                    b=backend.create_session(conn,person,"Synthetic supervisor B","127.0.0.1","supervisor-browser-B")
                    conn.commit()
                assert a["token"]!=b["token"] and a["user"]["id"]==b["user"]["id"]
                return a,b
            def login(browser,auth,width,height):
                browser.run("open",Fixture.origin+"/assets/favicon-32.png")
                browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session',"+json.dumps(json.dumps(auth))+");true")
                browser.run("set","viewport",str(width),str(height))
                browser.run("media","reduce")
                browser.run("open",Fixture.origin+"/?supervisor="+str(time.monotonic_ns())+"#approvalLog")
                browser.until("window.__fixtureTiming?.appInteractiveMs&&!officialWorkflowPage.loading",timeout=45)
            def open_case(browser,doc):
                browser.evaluate("(async()=>{await openOfficialCaseFromNavigation("+json.dumps(doc["id"])+",{tab:'pending'});return true})()")
                browser.until("officialDocumentDetailReady.has("+json.dumps(doc["id"])+")&&!officialWorkflowPage.loading")
                time.sleep(.2)
            def header_action(browser,action):
                desktop={"refresh":"#headerRefreshBtn","logout":"#logoutBtn"}[action]
                if browser.evaluate("!!document.querySelector("+json.dumps(desktop)+").getClientRects().length"):
                    browser.click_visible(desktop)
                else:
                    browser.click_visible("#mobileMenuButton")
                    browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<.5")
                    browser.click_visible({"refresh":"#mobileDrawerRefreshBtn","logout":"#mobileDrawerLogoutBtn"}[action])
            def dialog(browser,doc):
                open_case(browser,doc)
                browser.click_visible('#approvalLogDetail [data-progress-official-action="approve"]')
                browser.until("!!document.querySelector('#officialDecisionModal').getClientRects().length")
            def review(browser):
                for kind in ("application","source","attachments","editor"):
                    browser.click_visible('[data-decision-evidence="'+kind+'"]')
                    browser.until("document.querySelector('[data-decision-evidence="+kind+"]').classList.contains('complete')")
                for field in ("Original","Attachments","Edited"):
                    browser.click_visible("label:has(#officialReview"+field+")")
                browser.run("fill","#officialApprovalComment",COMMENT)
                browser.until("!document.querySelector('#officialDecisionSubmitBtn').disabled")
            def shot(row,suffix="",browser=A):
                name=row["device"]+"-"+row["case"]+suffix+".png"
                browser.run("screenshot",str(output/name));row.setdefault("screenshots",[]).append(name)
            def check(row,name,value): row["checks"][name]=bool(value)
            def detail(doc,auth): return Fixture._expect_json("GET","/api/official-documents/"+doc["id"],200,token=auth["token"])
            def state(browser=A):
                return browser.evaluate("({modal:!!document.querySelector('#officialDecisionModal').getClientRects().length,submitEnabled:!document.querySelector('#officialDecisionSubmitBtn').disabled,requirements:document.querySelector('#officialDecisionRequirements')?.textContent||'',recovery:officialDecisionState.recovery?.status||'',error:document.querySelector('#officialDecisionError').hidden?'':document.querySelector('#officialDecisionError').textContent,reference:document.querySelector('#officialDecisionUnsentComment')?.value||document.querySelector('#officialDecisionUnsentComment')?.textContent||'',notice:document.querySelector('#officialDecisionRecoveryStatus')?.textContent||'',acknowledged:[...document.querySelectorAll('#officialDecisionModal input[type=checkbox]')].some(e=>e.checked),evidenceComplete:officialDecisionEvidenceComplete(),currentStep:officialWorkflowItems.find(x=>x.id===officialDecisionState.documentId)?.current_step})")
            def intercept(browser,doc,mode):
                browser.evaluate("window.__supervisorGoodFetch=window.fetch;window.__supervisorPosts=[];window.__supervisorGets=[];window.__supervisorMode="+json.dumps(mode)+";window.__supervisorDocument="+json.dumps(doc["id"])+";window.fetch=async(i,o={})=>{const u=new URL(typeof i==='string'?i:i.url,location.href),match=u.pathname==='/api/official-documents/'+window.__supervisorDocument;if(u.pathname==='/api/official-documents/'+window.__supervisorDocument+'/approve'&&o.method==='POST'){window.__supervisorPosts.push(JSON.parse(o.body));if(window.__supervisorMode==='mutation503')return new Response(JSON.stringify({error:'synthetic_unavailable'}),{status:503,headers:{'Content-Type':'application/json'}});if(window.__supervisorMode==='forbidden')return new Response(JSON.stringify({error:'access_denied'}),{status:403,headers:{'Content-Type':'application/json'}})}if(match&&(!o.method||o.method==='GET')){window.__supervisorGets.push(u.pathname);if(window.__supervisorMode==='refresh503')return new Response(JSON.stringify({error:'synthetic_unavailable'}),{status:503,headers:{'Content-Type':'application/json'}});if(window.__supervisorMode==='refresh403')return new Response(JSON.stringify({error:'access_denied'}),{status:403,headers:{'Content-Type':'application/json'}});if(window.__supervisorMode==='holdRefresh')await new Promise(r=>window.__supervisorRelease=r)}return window.__supervisorGoodFetch(i,o)};true")
            def stale(row,doc,auth_a,auth_b,mode=""):
                dialog(A,doc);review(A)
                old_step=doc["current_step"]
                dialog(B,doc);review(B)
                B.click_visible("#officialDecisionSubmitBtn")
                B.until("!document.querySelector('#officialDecisionModal').getClientRects().length")
                after_b=detail(doc,auth_b)
                check(row,"independentSessionBAdvancedStep",after_b["current_step"]!=old_step)
                intercept(A,doc,"refresh503" if mode=="refresh503back" else mode)
                A.click_visible("#officialDecisionSubmitBtn")
                A.until("!officialDecisionState.busy&&!officialDecisionState.recovery?.loading",timeout=30)
                current=detail(doc,auth_a)
                check(row,"exactlyOneApprovalHistory",sum(x.get("action")=="approve" for x in current["logs"])==1)
                check(row,"onlyOneStepAdvanced",current["current_step"]==after_b["current_step"])
                check(row,"staleRequestUsesOpenedStep",A.evaluate("window.__supervisorPosts[0]?.expected_step_id") == next(s["id"] for s in doc["approval_steps"] if s["step_key"]==old_step))
                s=state();row["state"]=s
                check(row,"staleConfirmationDisabled",not s["submitEnabled"])
                check(row,"staleReviewAcknowledgementsCleared",not s["acknowledged"] and not s["evidenceComplete"])
                check(row,"unsentCommentClearlyRetained",COMMENT in s["reference"])
                if mode in {"refresh503","refresh503back"}:
                    check(row,"refreshFailureIsRecoverable",s["recovery"]=="failed")
                    check(row,"retryAndBackVisible",A.evaluate("['officialDecisionRecoveryRetryBtn','officialDecisionRecoveryBackBtn'].every(id=>!!document.getElementById(id)?.getClientRects().length)"))
                    shot(row,"-failed")
                    if mode=="refresh503back":
                        if s["recovery"]=="failed":
                            A.click_visible("#officialDecisionRecoveryBackBtn")
                            check(row,"backClosesRecovery",not A.evaluate("!!document.querySelector('#officialDecisionModal').getClientRects().length"))
                            check(row,"backReturnsToList",A.evaluate("activeRouteTarget==='approvalLog'&&!document.querySelector('#approvalLog').dataset.mobileDetail"))
                            check(row,"backDoesNotResubmit",A.evaluate("window.__supervisorPosts.length===1"))
                            A.evaluate("window.__supervisorMode='';true")
                            A.click_visible('[data-approval-log-filter="acted"]')
                            A.until("!officialWorkflowPage.loading")
                            header_action(A,"refresh")
                            A.until("!officialWorkflowPage.loading&&!!document.querySelector('[data-approval-log-select="+doc["id"]+"]')")
                            A.click_visible('[data-approval-log-select="'+doc["id"]+'"]')
                            A.until("officialDocumentDetailReady.has("+json.dumps(doc["id"])+")&&!officialCaseNavigation.loading")
                            check(row,"refreshBackCaseDiscoverableInActed",A.evaluate("officialCaseNavigation.detail?.id==="+json.dumps(doc["id"])))
                            check(row,"refreshBackLoadsAuthoritativeNextStep",A.evaluate("officialCaseNavigation.detail?.current_step==="+json.dumps(current["current_step"])))
                            check(row,"refreshBackCannotReuseOldApproval",not A.evaluate("!!document.querySelector('#approvalLogDetail [data-progress-official-action=approve]')"))
                            check(row,"refreshBackStillOneMutation",A.evaluate("window.__supervisorPosts.length===1"))
                            shot(row,"-returned-list-reopened")
                        return
                    if s["recovery"]=="failed":
                        A.evaluate("window.__supervisorMode='';true")
                        A.click_visible("#officialDecisionRecoveryRetryBtn")
                        A.until("officialDecisionState.recovery?.status==='ready'")
                        check(row,"retryDoesNotResubmit",A.evaluate("window.__supervisorPosts.length===1"))
                elif mode=="refresh403":
                    check(row,"permissionRevokeStopsRecovery",s["recovery"]=="forbidden")
                    check(row,"revokedCaseNotCached",A.evaluate("!officialDocumentDetailReady.has("+json.dumps(doc["id"])+")&&!officialWorkflowItems.some(x=>x.id==="+json.dumps(doc["id"])+")"))
                    shot(row)
                    return
                ready=state();row["readyState"]=ready
                check(row,"authorizedLatestReady",ready["recovery"]=="ready")
                next_step=next(s for s in current["approval_steps"] if s["step_key"]==current["current_step"])
                row["nextActor"]=next_step.get("approver_name") or next_step.get("approver_user_name") or ""
                check(row,"nextActorExplained",bool(row["nextActor"]) and row["nextActor"] in ready["notice"])
                shot(row)
                if ready["recovery"]=="ready":
                    A.click_visible("#officialDecisionRecoveryOpenBtn")
                    A.until("!document.querySelector('#officialDecisionModal').getClientRects().length")
                    A.until("!officialCaseNavigation.loading")
                    check(row,"latestCaseHasNoStaleApprove",not A.evaluate("!!document.querySelector('#approvalLogDetail [data-progress-official-action=approve]')"))
                    check(row,"latestCaseKeepsSameId",A.evaluate("officialCaseNavigation.detail?.id==="+json.dumps(doc["id"])))
            def background_change(row,doc,auth_a,auth_b):
                dialog(A,doc);review(A);dialog(B,doc);review(B)
                B.click_visible("#officialDecisionSubmitBtn")
                B.until("!document.querySelector('#officialDecisionModal').getClientRects().length")
                intercept(A,doc,"")
                # The production background list loader performs a real authorized GET.
                # It may update capabilities while an already reviewed dialog is open.
                A.evaluate("(async()=>{await loadOfficialWorkflow(officialWorkflowScope,{view:'acted',source:'approvalLog'});return true})()")
                A.click_visible("#officialDecisionSubmitBtn")
                A.until("officialDecisionState.recovery?.status==='ready'")
                s=state();row["state"]=s
                check(row,"backgroundChangeNoStaleMutation",A.evaluate("window.__supervisorPosts.length===0"))
                check(row,"backgroundChangeKeepsUnsentComment",COMMENT in s["reference"])
                check(row,"backgroundChangeResetsEvidence",not s["acknowledged"] and not s["evidenceComplete"] and not s["submitEnabled"])
                check(row,"backgroundChangeExactlyOneHistory",sum(x.get("action")=="approve" for x in detail(doc,auth_a)["logs"])==1)
                shot(row)
            def recovery_race(row,doc,auth_a,auth_b,signout=False,history=False):
                other=document(row["device"]+row["case"]+" separate-case-race")
                dialog(A,doc);review(A);dialog(B,doc);review(B)
                B.click_visible("#officialDecisionSubmitBtn")
                B.until("!document.querySelector('#officialDecisionModal').getClientRects().length")
                intercept(A,doc,"holdRefresh")
                A.click_visible("#officialDecisionSubmitBtn")
                A.until("typeof window.__supervisorRelease==='function'")
                if history:
                    # Browser navigation, not a synthetic state reset: invalidates the
                    # open operation before its deferred authorized GET can complete.
                    A.evaluate("location.hash='dashboard';true")
                    A.until("activeRouteTarget==='dashboard'")
                else:
                    A.click_visible("#officialDecisionRecoveryBackBtn")
                A.until("!document.querySelector('#officialDecisionModal').getClientRects().length")
                if history:
                    A.evaluate("window.__supervisorRelease();true")
                    time.sleep(.7)
                    check(row,"hashNavigationKeepsDialogClosed",not A.evaluate("!!document.querySelector('#officialDecisionModal').getClientRects().length"))
                    check(row,"hashNavigationDoesNotReturnToCase",A.evaluate("activeRouteTarget==='dashboard'"))
                    check(row,"hashNavigationClearsOldOperation",A.evaluate("!officialDecisionState.documentId&&!officialDecisionState.recovery"))
                elif signout:
                    header_action(A,"logout")
                    A.until("!hasAuthenticatedBackendSession()")
                    row["signedOutBeforeLateRefresh"]=A.evaluate("({items:officialWorkflowItems.map(x=>x.id),detailId:officialCaseNavigation.detail?.id||'',detailReady:[...officialDocumentDetailReady],recovery:officialDecisionState.recovery,appHidden:document.querySelector('#appShell').classList.contains('hidden')})")
                    A.evaluate("window.__supervisorRelease();true")
                    time.sleep(.7)
                    row["signedOutAfterLateRefresh"]=A.evaluate("({items:officialWorkflowItems.map(x=>x.id),detailId:officialCaseNavigation.detail?.id||'',detailReady:[...officialDocumentDetailReady],recovery:officialDecisionState.recovery,appHidden:document.querySelector('#appShell').classList.contains('hidden')})")
                    check(row,"lateRefreshAfterLogoutCannotAuthenticate",not A.evaluate("hasAuthenticatedBackendSession()"))
                    check(row,"lateRefreshAfterLogoutCannotRestoreCase",row["signedOutBeforeLateRefresh"]==row["signedOutAfterLateRefresh"] and not row["signedOutAfterLateRefresh"]["detailId"] and doc["id"] not in row["signedOutAfterLateRefresh"]["items"])
                    row["existingUnrelatedLogoutCacheRetained"]=bool(row["signedOutAfterLateRefresh"]["items"])
                    check(row,"lateRefreshAfterLogoutCannotOpenDialog",not A.evaluate("!!document.querySelector('#officialDecisionModal').getClientRects().length"))
                else:
                    dialog(A,other)
                    A.run("fill","#officialApprovalComment","合成另一案件未送出意見")
                    before=A.evaluate("officialDecisionState.operationId")
                    A.evaluate("window.__supervisorRelease();true")
                    time.sleep(.7)
                    check(row,"lateRefreshCannotReplaceOtherDialog",A.evaluate("officialDecisionState.documentId==="+json.dumps(other["id"])+"&&officialDecisionState.operationId==="+json.dumps(before)+"&&!!document.querySelector('#officialDecisionModal').getClientRects().length"))
                    check(row,"lateRefreshPreservesOtherComment",A.evaluate("document.querySelector('#officialApprovalComment').value==='合成另一案件未送出意見'"))
                    check(row,"otherCaseRequiresNewEvidence",A.evaluate("!officialDecisionEvidenceComplete()&&document.querySelector('#officialDecisionSubmitBtn').disabled"))
                    check(row,"otherCaseNoMutation",not any(x.get("action")=="approve" for x in detail(other,auth_a)["logs"]))
                check(row,"raceNeverReplaysOriginalMutation",A.evaluate("window.__supervisorPosts.length===1"))
                shot(row)
            def layout(row,doc,text_scale):
                open_case(A,doc)
                if A.evaluate("matchMedia('(max-width:1120px)').matches"):
                    A.click_visible("#approvalLogBackBtn")
                    A.until("!document.querySelector('#approvalLog').dataset.mobileDetail")
                A.until("!!document.querySelector('[data-approval-log-select="+doc["id"]+"]')")
                if text_scale==2:
                    A.evaluate("[...document.querySelectorAll('#approvalLogList,#approvalLogList *')].map(e=>[e,parseFloat(getComputedStyle(e).fontSize)]).forEach(([e,s])=>e.style.fontSize=(s*2)+'px');true")
                row["listGeometry"]=A.evaluate(LIST_GEOMETRY)
                check(row,"listVisibleWithoutCardOrChildOverflow",row["listGeometry"]["visible"] and not row["listGeometry"]["wide"])
                check(row,"listActions44px",bool(row["listGeometry"]["targets"]) and all(x["width"]>=43.9 and x["height"]>=43.9 for x in row["listGeometry"]["targets"]))
                check(row,"listFullSubjectNotTruncated",A.evaluate("(()=>{const e=document.querySelector('[data-workflow-row="+doc["id"]+"]>span'),s=getComputedStyle(e);return e.textContent==="+json.dumps(doc["subject"])+"&&s.textOverflow!=='ellipsis'&&(!s.webkitLineClamp||s.webkitLineClamp==='none')})()"))
                A.evaluate("document.querySelector('[data-workflow-row="+doc["id"]+"]').scrollIntoView({block:'start',behavior:'instant'});window.scrollBy(0,-96);true")
                A.run("mouse","move","0","0")
                A.until("!document.querySelector('#toast').classList.contains('show')",timeout=8)
                shot(row,"-list")
                A.click_visible('[data-approval-log-select="'+doc["id"]+'"]')
                A.until("officialCaseNavigation.detail?.id==="+json.dumps(doc["id"])+"&&!officialCaseNavigation.loading")
                check(row,"listViewActionReopensCorrectCase",A.evaluate("officialCaseNavigation.detail?.id==="+json.dumps(doc["id"])))
                A.evaluate("document.querySelectorAll('#approvalLogDetail details').forEach(e=>e.open=true);true")
                if text_scale==2:
                    A.evaluate("[...document.querySelectorAll('#approvalLogDetailPanel,#approvalLogDetailPanel *')].map(e=>[e,parseFloat(getComputedStyle(e).fontSize)]).forEach(([e,s])=>e.style.fontSize=(s*2)+'px');true")
                row["geometry"]=A.evaluate(GEOMETRY)
                check(row,"noPageOverflow",row["geometry"]["documentWidth"]<=row["geometry"]["viewport"]+1)
                check(row,"noCardOrChildOverflow",not row["geometry"]["wide"])
                check(row,"allActions44px",all(x["width"]>=43.9 and x["height"]>=43.9 for x in row["geometry"]["targets"]))
                row["fileNames"]=A.evaluate("[...document.querySelectorAll('#approvalLogDetail .official-file-row strong')].map(e=>e.textContent)")
                check(row,"longFileNameRendered",any(len(x)>80 for x in row["fileNames"]))
                check(row,"subjectFullTextAvailable",A.evaluate("document.querySelector('#approvalLogDetail').textContent.includes("+json.dumps(doc["subject"])+")"))
                A.run("mouse","move","0","0")
                A.until("!document.querySelector('#toast').classList.contains('show')",timeout=8)
                A.evaluate("document.querySelector('.approval-log-summary-head').scrollIntoView({block:'start',behavior:'instant'});window.scrollBy(0,-96);true")
                shot(row)
                A.click_visible('#approvalLogDetail [data-progress-official-action="approve"]')
                A.until("!!document.querySelector('#officialDecisionModal').getClientRects().length")
                contained=[]
                for _ in range(12):
                    A.run("press","Tab");contained.append(A.evaluate("document.querySelector('#officialDecisionModal').contains(document.activeElement)"))
                check(row,"keyboardFocusContained",all(contained))
                A.run("press","Escape")
                check(row,"escapeReturnsToCase",not A.evaluate("!!document.querySelector('#officialDecisionModal').getClientRects().length"))
                A.evaluate("[...document.querySelectorAll('.official-file-row')].find(e=>(e.querySelector('strong')?.textContent.length||0)<=80).scrollIntoView({block:'center',behavior:'instant'});true")
                shot(row,"-files")
                A.evaluate("[...document.querySelectorAll('.official-file-row')].find(e=>e.textContent.includes('合成超長附件')).querySelector('[data-official-download]').scrollIntoView({block:'center',behavior:'instant'});true")
                shot(row,"-long-file-action")
            def mutation503(row,doc,auth_a):
                dialog(A,doc);review(A);intercept(A,doc,"mutation503")
                A.click_visible("#officialDecisionSubmitBtn");A.until("!officialDecisionState.busy")
                s=state();row["state"]=s
                check(row,"failureKeepsReason",A.evaluate("document.querySelector('#officialApprovalComment').value")==COMMENT)
                check(row,"failureAllowsExplicitRetry",s["submitEnabled"] and bool(s["error"]))
                check(row,"noApprovalOn503",not any(x.get("action")=="approve" for x in detail(doc,auth_a)["logs"]))
                A.evaluate("window.__supervisorMode='';true")
                A.click_visible("#officialDecisionSubmitBtn");A.until("!document.querySelector('#officialDecisionModal').getClientRects().length")
                check(row,"retryCommitsOnce",sum(x.get("action")=="approve" for x in detail(doc,auth_a)["logs"])==1)
                shot(row)
            def forbidden(row,doc,auth_a):
                dialog(A,doc);review(A);intercept(A,doc,"forbidden")
                A.click_visible("#officialDecisionSubmitBtn");A.until("!officialDecisionState.busy")
                s=state();row["state"]=s
                check(row,"generic403NotReinterpretedAsConflict",s["recovery"]=="forbidden")
                check(row,"generic403NoDetailFetch",A.evaluate("window.__supervisorGets.length===0"))
                check(row,"generic403CannotResubmit",not s["submitEnabled"])
                check(row,"generic403PurgesCase",A.evaluate("!officialWorkflowItems.some(x=>x.id==="+json.dumps(doc["id"])+")&&!officialDocumentDetailReady.has("+json.dumps(doc["id"])+")"))
                check(row,"generic403NoHiddenCaseSummary",not A.evaluate("document.querySelector('#approvalLogDetail').textContent.includes("+json.dumps(doc["subject"])+")"))
                check(row,"generic403NoMutation",not any(x.get("action")=="approve" for x in detail(doc,auth_a)["logs"]))
                shot(row)
            plan=["SUP01", "SUP01-text200", "SUP02", "SUP02-refresh503", "SUP02-refresh503back", "SUP02-refresh403", "SUP02-generic403", "SUP02-mutation503", "SUP02-background-change", "SUP02-case-race", "SUP02-session-race", "SUP02-history-race"]
            for device,width,height in DEVICES:
                if devices and device not in devices: continue
                for case in plan:
                    if cases and case not in cases: continue
                    row={"device":device,"case":case,"checks":{}};report["cases"].append(row)
                    print(json.dumps({"device":device,"case":case,"stage":"start"}),flush=True)
                    try:
                        doc=document(device+" "+case,long=case.startswith("SUP01"));aa,ab=sessions(doc)
                        row["documentId"]=doc["id"];row["twoDistinctSessionsSameActor"]=aa["token"]!=ab["token"] and aa["user"]["id"]==ab["user"]["id"]
                        login(A,aa,width,height);login(B,ab,width,height)
                        if case.startswith("SUP01"): layout(row,doc,2 if case.endswith("text200") else 1)
                        elif case in {"SUP02-case-race","SUP02-session-race","SUP02-history-race"}: recovery_race(row,doc,aa,ab,signout=case.endswith("session-race"),history=case.endswith("history-race"))
                        elif case=="SUP02-background-change": background_change(row,doc,aa,ab)
                        elif case=="SUP02-generic403": forbidden(row,doc,aa)
                        elif case=="SUP02-mutation503": mutation503(row,doc,aa)
                        else: stale(row,doc,aa,ab,case.removeprefix("SUP02-") if case!="SUP02" else "")
                        check(row,"noUnhandledBrowserErrors",A.evaluate("window.__fixtureErrors.length===0") and B.evaluate("window.__fixtureErrors.length===0"))
                    except Exception as error:
                        row["runnerError"]={"type":type(error).__name__,"code":str(error)[:180],"lastCommand":A.last_command}
                        row["runnerDiagnostics"]={label:{"lastControl":getattr(browser,"last_control",{}),"lastCondition":getattr(browser,"last_condition","")} for label,browser in (("A",A),("B",B))}
                        try:row["failureState"]=state();shot(row,"-runner-error")
                        except Exception:pass
                        try:row["otherWindowFailureState"]=state(B)
                        except Exception:pass
                    row["passed"]=bool(row["checks"]) and all(row["checks"].values()) and "runnerError" not in row
                    persist();print(json.dumps({"device":device,"case":case,"passed":row["passed"],"failed":[k for k,v in row["checks"].items() if not v],"runnerError":row.get("runnerError")}),flush=True)
        finally:
            for browser in browsers:
                try:browser.run("close")
                except Exception:browser._stop()
            Fixture.tearDownClass()
    report["sourceHashesAtEnd"]=hashes();report["sourceStableDuringRun"]=report["sourceHashesAtStart"]==report["sourceHashesAtEnd"]
    report["passed"]=bool(report["cases"]) and all(x["passed"] for x in report["cases"]) and report["sourceStableDuringRun"]
    persist();return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--devices",nargs="*")
    parser.add_argument("--cases",nargs="*")
    args=parser.parse_args()
    args.output=args.output.resolve()
    result=run(args.output,args.devices,args.cases)
    print(json.dumps({"passed":result["passed"],"cases":len(result["cases"]),"report":str(args.output.resolve()/"report.json")}))
    raise SystemExit(0 if result["passed"] else 1)
