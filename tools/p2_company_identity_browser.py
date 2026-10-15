"""P2-02 synthetic HTTP/browser evidence; no production accounts or writes."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import Browser, require_local_origin
from tests.test_five_account_http_acceptance import FiveAccountHttpAcceptanceTest as F
import backend


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("before", "after"), default="after")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    F.setUpClass()
    require_local_origin(F.origin)
    config = Path(F.tmp.name) / "company-browser.json"
    config.write_text(json.dumps({"headed": False}))
    browser = Browser(config, session="p2-company-" + args.mode, namespace="p2-company-" + args.mode)
    original = F._expect_json.__func__
    report = {"mode": args.mode, "scope": "localhost_synthetic_not_production_or_real_sso", "cases": []}
    captured = {}

    class SeedComplete(Exception):
        pass

    def capture(cls, method, path, expected, **kwargs):
        value = original(cls, method, path, expected, **kwargs)
        if method == "POST" and path.endswith("/submit"):
            captured["detail"] = value
            raise SeedComplete()
        return value

    try:
        for company in ("CO-001", "CO-002"):
            case = dict(next(row for row in F.case_definitions if row["company_id"] == company))
            case.update(route="D", category="採購合約", orientations=("portrait",))
            token = F._portal_session(case["email"])
            F._expect_json = classmethod(capture)
            try:
                F._run_case(case, {case["ordinal"]: token})
            except SeedComplete:
                pass
            finally:
                F._expect_json = classmethod(original)
            detail = captured["detail"]
            step = next(row for row in detail["approval_steps"] if row["step_key"] == detail["current_step"])
            token = F._token_for_user_id(step["approver_user_id"])
            auth = {**F._expect_json("GET", "/api/auth/me", 200, token=token), "token": token}
            directory = F._expect_json("GET", "/api/finance-directory", 200, token=token)
            expected_name = next(row["name"] for row in directory["companies"] if row["id"] == company)
            browser.run("open", F.origin + "/assets/favicon-32.png")
            browser.evaluate("localStorage.clear();sessionStorage.clear();localStorage.setItem('suiyuecare-edoc-session'," + json.dumps(json.dumps(auth)) + ");true")
            browser.run("open", F.origin + "/#approvalLog")
            browser.until("typeof hasAuthenticatedBackendSession==='function'&&hasAuthenticatedBackendSession()&&!document.querySelector('#moduleEntryProgress')?.getClientRects().length&&financeDirectoryState.status==='synced'")
            doc = detail["id"]
            browser.evaluate("(async()=>{await openOfficialCaseFromNavigation(" + json.dumps(doc) + ",{tab:'pending'});return true})()")
            browser.until("officialDocumentDetailReady.has(" + json.dumps(doc) + ")")
            for width in (1440, 390):
                browser.run("set", "viewport", str(width), "1000" if width > 600 else "844")
                browser.evaluate("document.querySelector('#approvalLog').dataset.mobileDetail='true';document.querySelector('#approvalLogDetail .approval-secondary-meta').open=true;document.querySelector('#approvalLogDetail .approval-secondary-meta').scrollIntoView({block:'center',behavior:'instant'});true")
                summary = browser.evaluate("({text:document.querySelector('#approvalLogDetail .approval-secondary-meta').innerText,overflow:document.documentElement.scrollWidth>innerWidth+1})")
                browser.run("screenshot", str(args.output / f"{company}-{width}-summary.png"), "--full")
                browser.click_visible('#approvalLogDetail [data-progress-official-action="approve"]')
                browser.click_visible('[data-decision-evidence="application"]')
                browser.evaluate("document.querySelector('#officialDecisionApplicationDetails').scrollIntoView({block:'center',behavior:'instant'});true")
                dialog = browser.evaluate("({text:document.querySelector('#officialDecisionApplicationDetails').innerText,overflow:document.querySelector('#officialDecisionForm').scrollWidth>document.querySelector('#officialDecisionForm').clientWidth+1})")
                browser.run("screenshot", str(args.output / f"{company}-{width}-dialog.png"), "--full")
                if args.mode == "after":
                    assert expected_name in summary["text"], summary
                    assert expected_name in dialog["text"], dialog
                    assert "申請部門" in dialog["text"] and "用印單位" in dialog["text"], dialog
                    assert not summary["overflow"] and not dialog["overflow"], (summary, dialog)
                report["cases"].append({"companyId": company, "viewport": width, "expectedName": expected_name, "summary": summary, "dialog": dialog})
                browser.click_visible("#officialDecisionCancelBtn")
            if args.mode == "after" and company == "CO-002":
                # Exercise degraded directory state against the actual authorized
                # case and shipping renderers, without altering any case value.
                browser.click_visible('#approvalLogDetail [data-progress-official-action="approve"]')
                browser.click_visible('[data-decision-evidence="application"]')
                browser.run("fill", "#officialApprovalComment", "隔離驗收意見保持不變")
                browser.evaluate("stopFinanceDirectoryAutoRefresh();window.__companyTestDirectory={state:{...financeDirectoryState},companies:companySealCompanies};companySealCompanies=[];true")
                report["directoryStates"] = []
                for state, label in (("syncing", "單位資料載入中"), ("error", "單位資料暫時無法載入"), ("synced", "單位資料未提供")):
                    browser.evaluate("financeDirectoryState.status=" + json.dumps(state) + ";renderFinanceDirectorySyncStatus();true")
                    text = browser.evaluate("document.querySelector('#officialDecisionApplicationDetails').innerText")
                    assert label in text and expected_name not in text, text
                    assert browser.evaluate("document.querySelector('#officialApprovalComment').value") == "隔離驗收意見保持不變"
                    report["directoryStates"].append({"state": state, "label": label, "commentPreserved": True})
                browser.evaluate("companySealCompanies=window.__companyTestDirectory.companies;financeDirectoryState.contentScope='ANOTHER-SESSION';renderFinanceDirectorySyncStatus();true")
                assert "單位資料未提供" in browser.evaluate("document.querySelector('#officialDecisionApplicationDetails').innerText")
                report["staleDirectoryIgnored"] = True
                browser.run("screenshot", str(args.output / "stale-directory-mobile.png"), "--full")
                browser.evaluate("financeDirectoryState=window.__companyTestDirectory.state;companySealCompanies=window.__companyTestDirectory.companies;renderFinanceDirectorySyncStatus();delete window.__companyTestDirectory;true")
                browser.click_visible("#officialDecisionCancelBtn")
                # Change only this temporary fixture's recorded name snapshot;
                # fetch it through the actual authenticated detail API again.
                long_name = "隔離驗收長照股份有限公司附設新北市私立專案服務驗收居家長照機構（歷史核准名稱）"
                with backend.connect() as conn:
                    metadata = json.loads(conn.execute("SELECT metadata_json FROM official_documents WHERE id=?", (doc,)).fetchone()[0])
                    metadata["company_name"] = long_name
                    conn.execute("UPDATE official_documents SET metadata_json=? WHERE id=?", (json.dumps(metadata, ensure_ascii=False), doc))
                browser.evaluate("(async()=>{officialDocumentDetailReady.delete(" + json.dumps(doc) + ");await ensureOfficialDocumentDetail(" + json.dumps(doc) + ");renderApprovalLog();return true})()")
                browser.click_visible('#approvalLogDetail [data-progress-official-action="approve"]')
                browser.click_visible('[data-decision-evidence="application"]')
                browser.evaluate("document.querySelector('#officialDecisionApplicationDetails').scrollIntoView({block:'center',behavior:'instant'});true")
                long_state = browser.evaluate("({text:document.querySelector('#officialDecisionApplicationDetails').innerText,overflow:document.querySelector('#officialDecisionForm').scrollWidth>document.querySelector('#officialDecisionForm').clientWidth+1})")
                assert long_name in long_state["text"] and not long_state["overflow"], long_state
                report["longInstitutionSnapshot"] = long_state
                browser.run("screenshot", str(args.output / "long-institution-mobile.png"), "--full")
                browser.click_visible("#officialDecisionCancelBtn")
        report["passed"] = args.mode == "after"
    finally:
        F._expect_json = classmethod(original)
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        try:
            browser.run("close")
        finally:
            F.tearDownClass()
    print(json.dumps({"mode": args.mode, "cases": len(report["cases"]), "passed": report.get("passed", False)}))


if __name__ == "__main__":
    main()
