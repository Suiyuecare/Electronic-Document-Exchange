"""Offline compose confirmation and Finance-readiness contracts with synthetic data."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

from tests.test_compose_output_contract import function


ROOT = Path(__file__).resolve().parents[1]


class ComposeSubmissionDialogContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")

    def evaluate(self, names, body):
        def isolated_function(name):
            if name == "confirmComposeSubmission":
                start = self.js.index("async function confirmComposeSubmission(")
                end = self.js.index('\ndocument.querySelector("#composeForm").addEventListener', start)
                return self.js[start:end]
            return function(self.js, name)

        source = "\n".join(isolated_function(name) for name in names)
        result = subprocess.run(
            ["node", "-e", source + "\n" + body],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_finance_is_still_the_authoritative_submission_gate(self):
        result = self.evaluate(["workflowReadinessAllowsSubmit"], r'''
const hasAuthenticatedBackendSession=()=>true;
const explicitFrontendFixturesEnabled=()=>false;
const selection={approvalRouteCode:"A"};
console.log(JSON.stringify({
  ready:workflowReadinessAllowsSubmit(selection,{submitAllowed:true,sourceOfTruth:"finance"}),
  incomplete:workflowReadinessAllowsSubmit(selection,{submitAllowed:false,sourceOfTruth:"finance"}),
  wrongSource:workflowReadinessAllowsSubmit(selection,{submitAllowed:true,sourceOfTruth:"local"}),
  noRoute:workflowReadinessAllowsSubmit({}, {submitAllowed:true,sourceOfTruth:"finance"})
}));
''')
        self.assertEqual(result, {
            "ready": True,
            "incomplete": False,
            "wrongSource": False,
            "noRoute": False,
        })

    def test_submit_button_checks_finance_then_opens_dialog_without_mutating(self):
        result = self.evaluate(["workflowReadinessAllowsSubmit", "handleComposeSubmitRequest"], r'''
const events=[];let composeSubmitInFlight=false, activeComposeStep="confirm", ready=false;
const hasAuthenticatedBackendSession=()=>true,explicitFrontendFixturesEnabled=()=>false;
const flushComposeInputUpdates=()=>true,validateComposeStep=()=>true;
const composePayload=()=>({subject:"去識別化測試主旨"});
const setComposeStep=()=>events.push("edit"),advanceComposeStep=()=>events.push("next");
const setComposeSubmitBusy=value=>{composeSubmitInFlight=value;events.push(`busy:${value}`)};
const workflowReadinessSelection=()=>({approvalRouteCode:"A"});
const loadOfficialWorkflowReadiness=async()=>({submitAllowed:ready,sourceOfTruth:"finance"});
const renderWorkflowReadinessContext=()=>events.push("blocked");
const notice={scrollIntoView(){events.push("scroll")},focus(){events.push("focus")}};
const document={querySelector:()=>notice};
const openComposeSubmitDialog=()=>events.push("dialog");
const showToast=message=>events.push(message);
(async()=>{
  await handleComposeSubmitRequest({preventDefault(){events.push("prevent")}});
  const blocked=[...events];events.length=0;ready=true;
  await handleComposeSubmitRequest({preventDefault(){events.push("prevent")}});
  console.log(JSON.stringify({blocked,ready:events}));
})().catch(error=>{console.error(error);process.exitCode=1});
''')
        self.assertIn("blocked", result["blocked"])
        self.assertNotIn("dialog", result["blocked"])
        self.assertIn("dialog", result["ready"])
        self.assertNotIn("blocked", result["ready"])

    def test_cancelling_dialog_restores_focus_to_the_submit_trigger(self):
        result = self.evaluate(["hideComposeSubmitDialog", "openComposeSubmitDialog"], r'''
const events=[];
const modal={id:"composeSubmitModal",classList:{contains:name=>name==="hidden"?false:false}};
const trigger={id:"submitDispatchBtn",focus(){events.push("focused-submit")}};
const error={hidden:false};
const document={querySelector:selector=>({
  "#composeSubmitModal":modal,
  "#submitDispatchBtn":trigger,
  "#composeSubmitModalError":error
})[selector]||null};
const workspaceModalReturnFocus=new Map();
let composeSubmitModalFingerprint="";
const composePayload=()=>({subject:"去識別化測試主旨"});
const showWorkspaceModal=target=>{events.push(`opened:${target.id}`);workspaceModalReturnFocus.set(target,{id:"body"})};
const hideWorkspaceModal=target=>{workspaceModalReturnFocus.get(target)?.focus?.();workspaceModalReturnFocus.delete(target)};
openComposeSubmitDialog();
const mappedTrigger=workspaceModalReturnFocus.get(modal)?.id;
hideComposeSubmitDialog();
console.log(JSON.stringify({events,mappedTrigger,fingerprint:composeSubmitModalFingerprint,errorHidden:error.hidden}));
''')
        self.assertEqual(result, {
            "events": ["opened:composeSubmitModal", "focused-submit"],
            "mappedTrigger": "submitDispatchBtn",
            "fingerprint": "",
            "errorHidden": True,
        })

    def test_modal_confirmation_is_the_only_step_that_mutates_or_confirms(self):
        result = self.evaluate(["workflowReadinessAllowsSubmit", "confirmComposeSubmission"], r'''
const events=[];let composeSubmitInFlight=false,draftConfirmed=false,activeComposeStep="confirm";
const hasAuthenticatedBackendSession=()=>true,explicitFrontendFixturesEnabled=()=>false;
const composePayload=()=>({subject:"去識別化測試主旨"});
let composeSubmitModalFingerprint=JSON.stringify(composePayload());
const setComposeSubmitBusy=value=>{composeSubmitInFlight=value;events.push(`busy:${value}`)};
const workflowReadinessSelection=()=>({approvalRouteCode:"A"});
const loadOfficialWorkflowReadiness=async()=>({submitAllowed:true,sourceOfTruth:"finance"});
const setDraftConfirmed=value=>{draftConfirmed=value;events.push(`confirmed:${value}`)};
const createDispatchFromForm=async status=>{events.push(`create:${status}:${draftConfirmed}`);return {id:"OD-SYNTHETIC"}};
const hideComposeSubmitDialog=()=>events.push("close");
const addDispatchAudit=()=>events.push("audit"),renderComposeStepper=()=>{};
const showToast=()=>{},setView=view=>events.push(`view:${view}`),isRouteAllowed=()=>true;
const document={querySelector:()=>null};
(async()=>{await confirmComposeSubmission();console.log(JSON.stringify(events))})().catch(error=>{console.error(error);process.exitCode=1});
''')
        self.assertLess(result.index("confirmed:true"), result.index("create:待清稿:true"))
        self.assertLess(result.index("create:待清稿:true"), result.index("audit"))
        self.assertIn("view:approvalLog", result)

    def test_modal_confirmation_does_not_mutate_when_finance_is_blocked(self):
        result = self.evaluate(["workflowReadinessAllowsSubmit", "confirmComposeSubmission"], r'''
const events=[];let composeSubmitInFlight=false;
const hasAuthenticatedBackendSession=()=>true,explicitFrontendFixturesEnabled=()=>false;
const composePayload=()=>({subject:"去識別化測試主旨"});
let composeSubmitModalFingerprint=JSON.stringify(composePayload());
const setComposeSubmitBusy=value=>{composeSubmitInFlight=value};
const workflowReadinessSelection=()=>({approvalRouteCode:"A"});
const loadOfficialWorkflowReadiness=async()=>({submitAllowed:false,sourceOfTruth:"finance"});
const hideComposeSubmitDialog=()=>events.push("close");
const renderWorkflowReadinessContext=()=>events.push("blocked");
const document={querySelector:()=>({focus(){events.push("focus")}})};
const setDraftConfirmed=()=>events.push("confirmed");
const createDispatchFromForm=async()=>{events.push("mutated");return {id:"unexpected"}};
const showToast=()=>{};
(async()=>{await confirmComposeSubmission();console.log(JSON.stringify(events))})().catch(error=>{console.error(error);process.exitCode=1});
''')
        self.assertEqual(result, ["close", "blocked", "focus"])

    def test_failed_submission_keeps_dialog_and_surfaces_the_actual_reason(self):
        result = self.evaluate(["workflowReadinessAllowsSubmit", "confirmComposeSubmission"], r'''
const events=[];let composeSubmitInFlight=false,draftConfirmed=false;
const hasAuthenticatedBackendSession=()=>true,explicitFrontendFixturesEnabled=()=>false;
const composePayload=()=>({subject:"去識別化測試主旨"});
let composeSubmitModalFingerprint=JSON.stringify(composePayload());
const setComposeSubmitBusy=value=>{composeSubmitInFlight=value};
const workflowReadinessSelection=()=>({approvalRouteCode:"A"});
const loadOfficialWorkflowReadiness=async()=>({submitAllowed:true,sourceOfTruth:"finance"});
const setDraftConfirmed=value=>{draftConfirmed=value;events.push(`confirmed:${value}`)};
const createDispatchFromForm=async()=>{events.push("submit-attempt");return null};
const composeSaveState={tone:"error",detail:"隔離測試：簽核關卡暫無核定人。"};
const modalError={hidden:true,textContent:""};
const document={querySelector:selector=>selector==="#composeSubmitModalError"?modalError:null};
const hideComposeSubmitDialog=()=>events.push("close"),showToast=()=>{};
(async()=>{await confirmComposeSubmission();console.log(JSON.stringify({events,error:modalError.textContent,hidden:modalError.hidden,confirmed:draftConfirmed}))})().catch(error=>{console.error(error);process.exitCode=1});
''')
        self.assertEqual(result["events"], ["confirmed:true", "submit-attempt", "confirmed:false"])
        self.assertIn("隔離測試：簽核關卡暫無核定人", result["error"])
        self.assertFalse(result["hidden"])
        self.assertFalse(result["confirmed"])

    def test_finance_blocker_is_visible_on_confirm_page(self):
        result = self.evaluate(["workflowReadinessAllowsSubmit", "renderWorkflowReadinessContext"], r'''
const base={dataset:{},textContent:""},confirm={dataset:{},textContent:"",hidden:true};
const hasAuthenticatedBackendSession=()=>true,explicitFrontendFixturesEnabled=()=>false;
const ensureWorkflowReadinessNotice=()=>base;
const workflowReadinessSelection=()=>({approvalRouteCode:"A"});
const workflowReadinessCacheKey=()=>"fixture-A";
const officialWorkflowReadinessRequests=new Map();
const officialWorkflowReadinessByRoute=new Map([["fixture-A",{submitAllowed:false,sourceOfTruth:"finance",error:"測試簽核關係未完整"}]]);
const workflowReadinessIssueLabels=()=>["虛構主管尚未設定"];
const applyWorkflowReadinessSubmitGuards=()=>{};
const activeComposeStep="confirm";
const document={querySelector:selector=>selector==="#composeConfirmWorkflowReadinessNotice"?confirm:null};
renderWorkflowReadinessContext("compose");
console.log(JSON.stringify({state:confirm.dataset.state,text:confirm.textContent,hidden:confirm.hidden}));
''')
        self.assertEqual(result["state"], "blocked")
        self.assertIn("虛構主管尚未設定", result["text"])
        self.assertFalse(result["hidden"])


if __name__ == "__main__":
    unittest.main()
