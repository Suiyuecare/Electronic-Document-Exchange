"""Execute the real general-document picker against synthetic DOM and seals."""
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GeneralDocumentSealPickerTest(unittest.TestCase):
    FUNCTIONS = [
        "uploadedSealPickerReadOnly", "uploadedSealCompanyRecords",
        "uploadedSealPickerCategoryOptions", "renderUploadedSealOptions",
        "changeUploadedSealPickerSelection", "selectedUploadedSeal",
        "focusUploadedSealCompany", "officialSealHasCurrentFile",
        "addUploadedStamp", "addUploadedSeamGroups", "loadUploadedSealOptions",
    ]
    SETUP = r'''
const assert=require('node:assert/strict');
function node(value='') { return {value,dataset:{},hidden:false,disabled:false,options:[],textContent:'',
  set innerHTML(html) {this.options=[...html.matchAll(/<option value="([^"]*)"([^>]*)>(.*?)<\/option>/g)].map(m=>({value:m[1],disabled:m[2].includes('disabled'),textContent:m[3]}));this.value=this.options.find(o=>!o.disabled)?.value||'';},
  get selectedOptions(){return this.options.filter(o=>o.value===this.value)},
  focus(){this.focused=true},scrollIntoView(){this.scrolled=true}}; }
const nodes={};
for(const id of ['uploadedSealCompany','uploadedSealCategorySelect','uploadedSealSizeSelect','uploadedSealSealSelect','uploadedSealRecordLabel','uploadedSealPickerCompany','uploadedSealCompanyFocusBtn','uploadedSealPickerStatus','uploadedSealApplicationFields','uploadedEditorSeamPages'])nodes['#'+id]=node();
nodes['#uploadedSealCompany'].options=[{value:'A',textContent:'合成公司 A'},{value:'B',textContent:'合成公司 B'}];
nodes['#uploadedSealCompany'].value='A';
const document={querySelector:id=>nodes[id]||null};
const uploadedSealEditorRuntime={reviewMode:'edited',locked:false,uploading:false,companyChanging:false,directoryLoading:false,selectedIds:new Set()};
const uploadedSealApplicationRuntime={editable:true,submissionBusy:false};
const uploadedSealEditorState={elements:[],pages:[{pageId:'P1',widthPt:595,heightPt:842},{pageId:'P2',widthPt:595,heightPt:842},{pageId:'P3',widthPt:595,heightPt:842}]};
const PDF_EDITOR_MAX_ELEMENTS=1000;
let uploadedSealOptions=[],uploadedSealOptionsRequestNo=0,toasts=[],renders=0,placements=[],changes=0;
const refs=[{code:'general_seal',name:'便章'},{code:'bank_seal',name:'銀行印鑑章'},{code:'establishment_seal',name:'設立'},{code:'official_seal',name:'圖記'},{code:'other',name:'其他'}];
const companySealRefOptions=()=>refs, companySealRefName=(type,code)=>refs.find(x=>x.code===code)?.name||code;
const escapeDraftHtml=value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const companySealFixedGeometry=seal=>({widthMm:seal.widthMm||30,heightMm:seal.heightMm||30});
const formatCompanySealMeasurement=value=>Number(value).toFixed(2);
const companySealCurrentVersionSnapshot=seal=>({sealFileId:seal.current_file_id,sealFileSha256:seal.hash});
const renderUploadedSealWorkbench=()=>renders++,renderUploadedSealApplicationDisclosure=()=>{};
const currentUploadedEditorPage=()=>uploadedSealEditorState.pages[1];
const addUploadedEditorElement=(kind,point,props,pages)=>placements.push({kind,point,pages,seal:selectedUploadedSeal()?.id});
const showToast=value=>toasts.push(value);
const commitUploadedEditorMutation=callback=>{changes++;callback(uploadedSealEditorState);return true};
const parseUploadedEditorPageRange=raw=>raw.split(',').map(Number);
const editorDefaultElement=(kind,page,point,props)=>({id:'new-'+uploadedSealEditorState.elements.length,pageId:page.pageId,kind,height:85,properties:{...props,sealId:selectedUploadedSeal()?.id,...companySealCurrentVersionSnapshot(selectedUploadedSeal())}});
globalThis.EDOCSeam={groups:()=>new Map(),displayHeight:page=>page.heightPt,initialTopMm:(height,index)=>100+index*40,position:(state,id,top)=>state.elements.filter(e=>e.properties.seamGroupId===id).forEach(e=>e.y=top)};
const hasAuthenticatedBackendSession=()=>true,frontendSessionScope=()=> 'userA';
const normalizeUploadedEditorSealGeometry=()=>false;
let backendRequest=async()=>[];
function seal(id,category='general_seal',size='large_seal',company='A',ready=true) {return {id,company_id:company,seal_name:'合成 '+id,seal_category:category,seal_size_type:size,is_active:true,current_file_id:ready?'FILE-'+id:'',hash:'HASH-'+id,widthMm:size==='small_seal'?18:30};}
function select(category,size) {nodes['#uploadedSealCategorySelect'].value=category;nodes['#uploadedSealSizeSelect'].value=size;changeUploadedSealPickerSelection();}
'''

    def run_js(self, body):
        source = (ROOT / "app.js").read_text()
        functions = []
        for name in self.FUNCTIONS:
            start = list(re.finditer(r"^(?:async )?function " + name + r"\(", source, re.M))[-1].start()
            end = re.search(r"\n(?:async )?function \w+\(", source[start:]).start() + start
            functions.append(source[start:end])
        script = self.SETUP + "\n" + "\n".join(functions) + "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_initial_company_defaults_to_ready_general_seal_and_size(self):
        value = self.run_js('uploadedSealOptions=[seal("BANK","bank_seal"),seal("GENERAL"),seal("SMALL","general_seal","small_seal")];renderUploadedSealOptions();console.log(JSON.stringify({id:selectedUploadedSeal().id,category:nodes["#uploadedSealCategorySelect"].value,size:nodes["#uploadedSealSizeSelect"].value,status:nodes["#uploadedSealPickerStatus"].textContent,company:nodes["#uploadedSealPickerCompany"].textContent}));')
        self.assertEqual(value["id"], "GENERAL")
        self.assertEqual(value["category"], "general_seal")
        self.assertEqual(value["size"], "large_seal")
        self.assertIn("30.00 × 30.00 mm", value["status"])
        self.assertEqual(value["company"], "合成公司 A")

    def test_initial_loading_does_not_force_unavailable_general_before_bank_arrives(self):
        value = self.run_js('backendRequest=async()=>[seal("BANK","bank_seal","small_seal")];await loadUploadedSealOptions("A");console.log(JSON.stringify({id:selectedUploadedSeal().id,size:nodes["#uploadedSealSizeSelect"].value}));')
        self.assertEqual(value, {"id": "BANK", "size": "small_seal"})

    def test_user_selected_missing_size_never_falls_back_to_bank_or_large(self):
        value = self.run_js('uploadedSealOptions=[seal("GENERAL"),seal("BANK","bank_seal","small_seal")];renderUploadedSealOptions();select("general_seal","small_seal");renderUploadedSealOptions();console.log(JSON.stringify({id:selectedUploadedSeal()?.id||null,value:nodes["#uploadedSealSealSelect"].value,disabled:nodes["#uploadedSealSealSelect"].disabled,status:nodes["#uploadedSealPickerStatus"].textContent}));')
        self.assertIsNone(value["id"])
        self.assertEqual(value["value"], "")
        self.assertTrue(value["disabled"])
        self.assertIn("一般章小章", value["status"])

    def test_size_and_category_change_only_selects_exact_match(self):
        value = self.run_js('uploadedSealOptions=[seal("GENERAL"),seal("BANK-S","bank_seal","small_seal"),seal("EST-L","establishment_seal")];renderUploadedSealOptions();select("bank_seal","small_seal");const small=selectedUploadedSeal().id;select("establishment_seal","large_seal");console.log(JSON.stringify({small,large:selectedUploadedSeal().id}));')
        self.assertEqual(value, {"small": "BANK-S", "large": "EST-L"})

    def test_company_change_cannot_keep_another_companys_stamp(self):
        value = self.run_js('uploadedSealOptions=[seal("A-GENERAL"),seal("B-BANK","bank_seal","small_seal","B")];renderUploadedSealOptions();nodes["#uploadedSealCompany"].value="B";const stale=selectedUploadedSeal();renderUploadedSealOptions();console.log(JSON.stringify({stale,selected:selectedUploadedSeal().id,options:nodes["#uploadedSealSealSelect"].options.map(x=>x.value)}));')
        self.assertIsNone(value["stale"])
        self.assertEqual(value["selected"], "B-BANK")
        self.assertEqual(value["options"], ["B-BANK"])

    def test_inactive_unversioned_and_unscoped_records_are_not_usable(self):
        value = self.run_js('uploadedSealOptions=[{...seal("INACTIVE"),is_active:false},seal("EMPTY","general_seal","large_seal","A",false),{...seal("UNSCOPED"),company_id:""}];renderUploadedSealOptions();console.log(JSON.stringify({selected:selectedUploadedSeal(),status:nodes["#uploadedSealPickerStatus"].dataset.state,options:nodes["#uploadedSealSealSelect"].options.map(x=>x.value)}));')
        self.assertIsNone(value["selected"])
        self.assertEqual(value["status"], "empty")
        self.assertEqual(value["options"], ["", "EMPTY"])

    def test_record_selector_only_appears_for_multiple_matching_records(self):
        value = self.run_js('uploadedSealOptions=[seal("ONE"),seal("BANK","bank_seal")];renderUploadedSealOptions();const one=nodes["#uploadedSealRecordLabel"].hidden;uploadedSealOptions.push(seal("TWO"));renderUploadedSealOptions();nodes["#uploadedSealSealSelect"].value="TWO";changeUploadedSealPickerSelection();console.log(JSON.stringify({one,multiple:nodes["#uploadedSealRecordLabel"].hidden,selected:selectedUploadedSeal().id}));')
        self.assertEqual(value, {"one": True, "multiple": False, "selected": "TWO"})

    def test_server_categories_are_kept_without_coercion_and_labels_are_escaped(self):
        value = self.run_js('uploadedSealOptions=[seal("CUSTOM","custom<&kind")];renderUploadedSealOptions();console.log(JSON.stringify({category:nodes["#uploadedSealCategorySelect"].value,id:selectedUploadedSeal()?.id||null,options:uploadedSealPickerCategoryOptions().map(x=>x.code)}));')
        self.assertEqual(value["category"], "custom<&kind")
        self.assertEqual(value["id"], "CUSTOM")
        self.assertIn("custom<&kind", value["options"])

    def test_each_readonly_busy_state_disables_controls_and_prevents_additions(self):
        for mutation in ("locked=true", "uploading=true", "companyChanging=true", "directoryLoading=true", "sealOptionsLoading=true", "draftCreatePromise=Promise.resolve()", 'reviewMode="original"'):
            with self.subTest(mutation=mutation):
                value = self.run_js('uploadedSealOptions=[seal("GENERAL")];renderUploadedSealOptions();uploadedSealEditorRuntime.' + mutation + ';renderUploadedSealOptions();addUploadedStamp();addUploadedSeamGroups();console.log(JSON.stringify({disabled:["uploadedSealCategorySelect","uploadedSealSizeSelect","uploadedSealSealSelect","uploadedSealCompanyFocusBtn"].every(id=>nodes["#"+id].disabled),selected:selectedUploadedSeal(),changes,placements:placements.length}));')
                self.assertEqual(value, {"disabled": True, "selected": None, "changes": 0, "placements": 0})
        for mutation in ("editable=false", "submissionBusy=true"):
            with self.subTest(mutation=mutation):
                value = self.run_js('uploadedSealOptions=[seal("GENERAL")];renderUploadedSealOptions();uploadedSealApplicationRuntime.' + mutation + ';renderUploadedSealOptions();console.log(JSON.stringify({disabled:nodes["#uploadedSealCategorySelect"].disabled,selected:selectedUploadedSeal()}));')
                self.assertEqual(value, {"disabled": True, "selected": None})

    def test_current_and_all_pages_keep_the_selected_small_bank_seal(self):
        value = self.run_js('uploadedSealOptions=[seal("GENERAL"),seal("BANK-S","bank_seal","small_seal")];renderUploadedSealOptions();select("bank_seal","small_seal");addUploadedStamp("current_page",{x:123,y:234});addUploadedStamp("all_pages",{x:45,y:67});console.log(JSON.stringify(placements));')
        self.assertEqual(value, [{"kind": "seal", "point": {"x": 123, "y": 234}, "pages": ["P2"], "seal": "BANK-S"}, {"kind": "seal", "point": {"x": 45, "y": 67}, "pages": ["P1", "P2", "P3"], "seal": "BANK-S"}])

    def test_seam_pairs_share_selected_seal_and_keep_independent_positions(self):
        value = self.run_js('uploadedSealOptions=[seal("GENERAL"),seal("BANK-S","bank_seal","small_seal")];renderUploadedSealOptions();select("bank_seal","small_seal");addUploadedSeamGroups();console.log(JSON.stringify(uploadedSealEditorState.elements));')
        self.assertEqual(len(value), 4)
        self.assertEqual([item["y"] for item in value], [100, 100, 140, 140])
        self.assertTrue(all(item["properties"]["sealId"] == "BANK-S" for item in value))
        self.assertTrue(all(item["properties"]["sealFileId"] == "FILE-BANK-S" for item in value))

    def test_company_jump_reveals_only_existing_company_control(self):
        value = self.run_js('nodes["#uploadedSealApplicationFields"].hidden=true;focusUploadedSealCompany();console.log(JSON.stringify({hidden:nodes["#uploadedSealApplicationFields"].hidden,focused:nodes["#uploadedSealCompany"].focused,value:nodes["#uploadedSealCompany"].value,changes}));')
        self.assertEqual(value, {"hidden": False, "focused": True, "value": "A", "changes": 0})

    def test_late_old_company_response_cannot_replace_current_picker(self):
        value = self.run_js('let release;backendRequest=path=>path.includes("/A/")?new Promise(resolve=>release=resolve):Promise.resolve([seal("B","bank_seal","large_seal","B")]);const old=loadUploadedSealOptions("A");nodes["#uploadedSealCompany"].value="B";await loadUploadedSealOptions("B");release([seal("A")]);await old;console.log(JSON.stringify({id:selectedUploadedSeal().id,loading:uploadedSealEditorRuntime.sealOptionsLoading,records:uploadedSealOptions.map(x=>x.id)}));')
        self.assertEqual(value, {"id": "B", "loading": False, "records": ["B"]})

    def test_catalogue_completion_refreshes_toolbar_even_when_geometry_is_unchanged(self):
        value = self.run_js('let release;backendRequest=()=>new Promise(resolve=>release=resolve);const pending=loadUploadedSealOptions("A");const loading=uploadedSealPickerReadOnly();release([seal("GENERAL")]);await pending;console.log(JSON.stringify({loading,after:uploadedSealPickerReadOnly(),renders,selected:selectedUploadedSeal().id}));')
        self.assertEqual(value, {"loading": True, "after": False, "renders": 1, "selected": "GENERAL"})

    def test_failed_catalogue_load_releases_busy_state_without_using_stale_seals(self):
        value = self.run_js('uploadedSealOptions=[seal("GENERAL")];renderUploadedSealOptions();backendRequest=async()=>{throw new Error("synthetic offline")};await loadUploadedSealOptions("A");console.log(JSON.stringify({loading:uploadedSealEditorRuntime.sealOptionsLoading,selected:selectedUploadedSeal(),records:uploadedSealOptions.length,renders,toasts}));')
        self.assertFalse(value["loading"])
        self.assertIsNone(value["selected"])
        self.assertEqual(value["records"], 0)
        self.assertEqual(value["renders"], 1)
        self.assertTrue(value["toasts"])


if __name__ == "__main__":
    unittest.main()
