"""Narrow presentation regressions; production mutation APIs remain untouched."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"(?:async )?function " + re.escape(name) + r"\([^\n]*\) \{\n.*?\n\}", source, re.S)
    if not match:
        raise AssertionError(name)
    return match.group(0)


class FourPageSimplificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (ROOT / "app.js").read_text()
        cls.html = (ROOT / "index.html").read_text()
        cls.css = (ROOT / "styles.css").read_text()

    def run_js(self, names, script):
        source = "\n".join(function(self.js, name) for name in names)
        result = subprocess.run(["node", "-e", "const assert=require('node:assert/strict');\n" + source + "\n" + script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_single_inbound_create_entry_uses_existing_tab_handler(self):
        start = self.html.index('<section class="view" id="inbound">')
        end = self.html.index('<section class="view"', start + 10)
        html = self.html[start:end]
        self.assertEqual(html.count('>新增收錄</button>'), 1)
        self.assertEqual(html.count('id="openInboundArchiveBtn"'), 1)
        self.assertIn('role="tab" data-inbound-section="archive"', html)
        self.assertNotIn('querySelector("#openInboundArchiveBtn")?.addEventListener', self.js)
        self.assertLess(html.index('id="inboundSearch"'), html.index('data-inbound-filter="all"'))
        self.assertIn("[data-approval-log-filter], [data-inbound-section]", self.js)

    def test_no_duplicate_source_ids_and_native_disclosures(self):
        ids = []
        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                ids.extend(value for key, value in attrs if key == "id")
        Parser().feed(self.html)
        self.assertEqual([key for key, count in Counter(ids).items() if count > 1], [])
        for name in ("approval-secondary-meta", "approval-step-history"):
            self.assertIn(f'<details class="{name}"><summary>', self.js)
        self.assertIn('expandButton.setAttribute("aria-expanded", String(dailyActionExpanded))', self.js)
        self.assertIn('min-height: 44px;', self.css)

    def test_settings_keep_four_groups_and_move_technical_controls(self):
        body = function(self.js, "initializeSettingsProgressiveDisclosure")
        self.assertIn('["company_people", "公司與人員", ["accounts", "seals"]]', body)
        self.assertIn('["security_operations", "安全與維運", ["__base__",', body)
        self.assertEqual(len(re.findall(r'\["(?:company_people|approval_rules|notifications_dispatch|security_operations)",', body)), 4)
        self.assertIn('notificationDetails.dataset.integratedBase = "settings"', body)
        self.assertIn('notificationGroup.append(notificationDetails)', body)
        self.assertIn('setAttribute("aria-live", "polite")', body)
        self.assertIn('baseContent.prepend(baseControls)', function(self.js, "initializeIntegratedMajorPages"))
        self.assertIn('controls.hidden = !canViewSettingsBase', function(self.js, "applyRoleNavigation"))

    def test_settings_row_selection_has_named_44px_label_without_new_handlers(self):
        for name, checkbox, label in (
            ("renderAccountRows", "account-check", "選取帳號"),
            ("renderSealRequests", "seal-request-check", "選取用印申請"),
            ("renderFileSecurityRows", "file-security-check", "選取檔案"),
        ):
            body = function(self.js, name)
            self.assertRegex(body, r'<label class="settings-row-selection"><input class="' + checkbox + r'"[^>]*aria-label="' + label)
            self.assertNotIn('settings-row-selection")', body)
            self.assertEqual(body.count('class="' + checkbox + '"'), 1)
        rule = re.search(r"#settings \.settings-row-selection \{([^}]+)", self.css)
        self.assertIsNotNone(rule)
        self.assertIn("min-width: 44px;", rule.group(1))
        self.assertIn("min-height: 44px;", rule.group(1))

    def test_home_expansion_does_not_duplicate_handlers_or_hide_issue_count(self):
        self.run_js(["renderDailyActionCenter"], r'''
let dailyActionCache=[],dailyActionExpanded=false,internalDispatchLoadStatus='idle',homeRenders=0;
const items=Array.from({length:8},(_,i)=>({tone:i===7?'issue':'normal',badge:'fixture',title:'Case '+i,meta:'m',body:'b',action:'View'}));
const dailyActionItems=()=>items,escapeHtml=x=>String(x),renderHomeMyCases=()=>homeRenders++;
const grid={innerHTML:'',querySelector:()=>null},count={},expand={setAttribute(k,v){this[k]=v}};
const document={querySelector:s=>({'#dailyActionGrid':grid,'#dailyActionCount':count,'#dailyActionExpandBtn':expand}[s]||null),querySelectorAll:()=>[]};
renderDailyActionCenter();assert.equal(dailyActionCache.length,5);assert.match(count.textContent,/8 件.*1 件需優先/);assert.equal(expand['aria-expanded'],'false');
renderDailyActionCenter();expand.onclick();assert.equal(dailyActionCache.length,8);assert.equal(expand['aria-expanded'],'true');
expand.onclick();assert.equal(dailyActionCache.length,5);assert.equal(homeRenders,4);
''')

    def test_mobile_detail_focus_is_presentation_only(self):
        self.run_js(["openApprovalLogMobileDetail"], r'''
let mobile=true,focused=0,scrolled=0;
const page={dataset:{}},panel={setAttribute(k,v){this[k]=v},focus(){focused++},scrollIntoView(){scrolled++}};
const window={matchMedia:()=>({matches:mobile})},document={querySelector:s=>s==='#approvalLog'?page:panel};
openApprovalLogMobileDetail();assert.equal(page.dataset.mobileDetail,'true');assert.equal(panel.tabindex,'-1');assert.equal(focused,1);assert.equal(scrolled,1);
mobile=false;openApprovalLogMobileDetail();assert.equal(focused,1);assert.equal(scrolled,1);
''')

    def test_mobile_detail_return_reveals_selected_case_and_preserves_desktop_scroll(self):
        self.run_js(["closeApprovalLogMobileDetail"], r'''
let mobile=true,selectedWorkflowTaskId='case-12',removed=0,focused=0,scrolled=0,hasSelection=true;
const page={removeAttribute(name){assert.equal(name,'data-mobile-detail');removed++}};
const button={focus(options){assert.deepEqual(options,{preventScroll:true});focused++},scrollIntoView(options){assert.equal(removed,1);assert.deepEqual(options,{block:'center',behavior:'instant'});scrolled++}};
const list={querySelector(selector){assert.equal(selector,'[data-approval-log-select="case-12"]');return hasSelection?button:null}};
const CSS={escape:value=>value},window={matchMedia:()=>({matches:mobile})},document={querySelector:selector=>({'#approvalLog':page,'#approvalLogList':list}[selector]||null)};
closeApprovalLogMobileDetail();assert.equal(removed,1);assert.equal(focused,1);assert.equal(scrolled,1);
mobile=false;closeApprovalLogMobileDetail();assert.equal(removed,2);assert.equal(focused,2);assert.equal(scrolled,1);
mobile=true;hasSelection=false;closeApprovalLogMobileDetail();assert.equal(removed,3);assert.equal(focused,2);assert.equal(scrolled,1);
''')

    def test_approval_evidence_precedes_decision_and_empty_has_one_surface(self):
        self.run_js(["closeApprovalLogMobileDetail", "renderApprovalLog"], r'''
const node=()=>({innerHTML:'',textContent:'',hidden:false,dataset:{},classList:{toggle(){}},querySelectorAll:()=>[],querySelector:()=>null,removeAttribute(){}});
const list=node(),detail=node(),full=node(),panel=node(),page=node(),layout=node(),back=node();full.parentElement=node();
const nodes={'#approvalLogList':list,'#approvalLogDetail':detail,'#approvalLogOpenWorkflowBtn':full,'#approvalLogCount':node(),'#approvalLogScope':node(),'#approvalLogDetailPanel':panel,'.approval-log-layout':layout,'#approvalLogBackBtn':back,'#approvalLog':page};
const document={querySelector:s=>nodes[s]||null,querySelectorAll:()=>[]};
let selectedWorkflowTaskId='case1',approvalLogFilter='my_pending';
const official={id:'case1',current_status:'pending',current_step:'manager',can_act:true,approval_steps:[{id:'step1',step_key:'manager',status:'pending'}]};
let records=[{task:{id:'case1',title:'Synthetic',role:'Manager',step:'Manager',status:'待簽核'},doc:{subject:'Synthetic'},steps:[],officialDocument:official,requester:'Applicant'}];
const approvalLogRecords=()=>records,filteredApprovalLogRecords=()=>records,isRouteAllowed=()=>false,canSeeCompanyWideDocs=()=>false,approvalProgressCategory=()=> 'my_pending';
const escapeHtml=x=>String(x||''),escapeDraftHtml=escapeHtml,approvalRecordTimeMeta=()=>({label:'送出時間',value:'fixture',actorLabel:'申請人',progress:'0/1 關'}),approvalRecordIsOverdue=()=>false;
const officialDocumentDetailReady=new Set(['case1']),officialDocumentIsApplicant=()=>false,renderOfficialHumanProgress=()=>'',officialDocumentHasEditorV2=()=>false;
const officialApplicationFiles=()=>[],renderOfficialFiles=()=>'<div data-fixture-evidence>file.pdf</div>',renderOfficialFinalStampedDownload=()=>'',safeHtmlClassToken=x=>x;
renderApprovalLog();assert.equal(panel.hidden,false);assert.ok(detail.innerHTML.indexOf('data-fixture-evidence')<detail.innerHTML.indexOf('data-progress-official-action="approve"'));assert.match(detail.innerHTML,/approval-review-decisions/);
official.can_act=false;renderApprovalLog();assert.doesNotMatch(detail.innerHTML,/data-progress-official-action="approve"/);
records=[];renderApprovalLog();assert.equal(panel.hidden,true);assert.equal(detail.innerHTML,'');assert.equal((list.innerHTML.match(/ux-empty-state/g)||[]).length,1);assert.equal(full.disabled,true);
''')


if __name__ == "__main__":
    unittest.main()
