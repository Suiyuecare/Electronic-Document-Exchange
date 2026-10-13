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
        "uploadedSealCatalogReady", "uploadedSealCatalogMessage", "companySealCatalogUnavailableReason",
        "uploadedSealPickerCategoryOptions", "uploadedSeamPrimaryLargeSeal", "renderUploadedSealOptions",
        "changeUploadedSealPickerSelection", "selectedUploadedSeal", "selectedUploadedSeamSeal",
        "focusUploadedSealCompany", "officialSealHasCurrentFile",
        "companySealSelectable", "companySealCategoryLabel", "uploadedSealApplicationMetadataReadOnly",
        "addUploadedStamp", "addUploadedSeamGroups", "loadUploadedSealOptions",
    ]
    SETUP = r'''
const assert=require('node:assert/strict');
function node(value='') { return {value,dataset:{},hidden:false,disabled:false,options:[],textContent:'',
  set innerHTML(html) {this.options=[...html.matchAll(/<option value="([^"]*)"([^>]*)>(.*?)<\/option>/g)].map(m=>({value:m[1],disabled:m[2].includes('disabled'),textContent:m[3]}));this.value=this.options.find(o=>!o.disabled)?.value||'';},
  get selectedOptions(){return this.options.filter(o=>o.value===this.value)},
  focus(){this.focused=true},scrollIntoView(){this.scrolled=true}}; }
const nodes={};
for(const id of ['uploadedSealCompany','uploadedSealCategorySelect','uploadedSealSizeSelect','uploadedSealSealSelect','uploadedSealRecordLabel','uploadedSealPickerCompany','uploadedSealCompanyFocusBtn','uploadedSealPickerStatus','uploadedSealApplicationFields','uploadedEditorSeamPages','uploadedEditorSeamPanel','uploadedEditorSeamEdge','uploadedEditorSeamSealSelect'])nodes['#'+id]=node();
nodes['#uploadedEditorSeamPanel'].hidden=true;nodes['#uploadedEditorSeamEdge'].value='right';
nodes['#uploadedSealCompany'].options=[{value:'A',textContent:'合成公司 A'},{value:'B',textContent:'合成公司 B'}];
nodes['#uploadedSealCompany'].value='A';
const document={querySelector:id=>nodes[id]||null};
const uploadedSealEditorRuntime={reviewMode:'edited',locked:false,uploading:false,companyChanging:false,directoryLoading:false,selectedIds:new Set()};
const uploadedSealApplicationRuntime={editable:true,metadataEditable:true,companyEditable:true,submissionBusy:false,companyId:'A'};
const uploadedSealEditorState={elements:[],pages:[{pageId:'P1',widthPt:595,heightPt:842},{pageId:'P2',widthPt:595,heightPt:842},{pageId:'P3',widthPt:595,heightPt:842}]};
const PDF_EDITOR_MAX_ELEMENTS=1000;
let uploadedSealOptions=[],uploadedSealOptionsRequestNo=0,toasts=[],renders=0,placements=[],changes=0;
const authState={token:'synthetic-session'};
let uploadedSealCatalogState={scope:'userA',token:authState.token,companyId:'A',status:'ready',request:null};
const refs=[{code:'general_seal',name:'便章'},{code:'bank_seal',name:'銀行印鑑章'},{code:'establishment_seal',name:'設立'},{code:'official_seal',name:'圖記'},{code:'continuous_seal',name:'連續章'},{code:'other',name:'其他'}];
const companySealRefOptions=()=>refs, companySealRefName=(type,code)=>refs.find(x=>x.code===code)?.name||code;
const escapeDraftHtml=value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const companySealFixedGeometry=seal=>({widthMm:seal.widthMm||30,heightMm:seal.heightMm||30});
const formatCompanySealMeasurement=value=>Number(value).toFixed(2);
const companySealCurrentVersionSnapshot=seal=>({sealFileId:seal.current_file_id,sealFileSha256:seal.hash});
const renderUploadedSealWorkbench=()=>{renders++;renderUploadedSealOptions()},renderUploadedSealApplicationDisclosure=()=>{};
const currentUploadedEditorPage=()=>uploadedSealEditorState.pages[1];
const addUploadedEditorElement=(kind,point,props,pages)=>placements.push({kind,point,pages,seal:selectedUploadedSeal()?.id});
const showToast=value=>toasts.push(value);
const commitUploadedEditorMutation=callback=>{changes++;callback(uploadedSealEditorState);return true};
const parseUploadedEditorPageRange=raw=>raw.split(',').map(Number);
let nextElementId=0;
const editorDefaultElement=(kind,page,point,props,override)=>({id:'new-'+(++nextElementId),pageId:page.pageId,kind,width:85,height:85,properties:{...props,sealId:(override||selectedUploadedSeal())?.id,...companySealCurrentVersionSnapshot(override||selectedUploadedSeal())}});
/* LOAD_REAL_SEAM */
const hasAuthenticatedBackendSession=()=>true,frontendSessionScope=()=> 'userA';
const normalizeUploadedEditorSealGeometry=()=>false;
let backendRequest=async()=>[];
function seal(id,category='general_seal',size='large_seal',company='A',ready=true) {return {id,company_id:company,seal_name:'合成 '+id,seal_category:category,seal_size_type:size,is_active:true,current_file_id:ready?'FILE-'+id:'',current_file:ready?{id:'FILE-'+id,usable:true,is_current:true}:null,owner_kind:category==='official_seal'?'institution':'company',selectable:ready,hash:'HASH-'+id,widthMm:size==='small_seal'?18:30};}
function select(category,size) {nodes['#uploadedSealCategorySelect'].value=category;nodes['#uploadedSealSizeSelect'].value=size;changeUploadedSealPickerSelection();}
'''

    def run_js(self, body):
        source = (ROOT / "app.js").read_text()
        functions = []
        for name in self.FUNCTIONS:
            start = list(re.finditer(r"^(?:async )?function " + name + r"\(", source, re.M))[-1].start()
            end = re.search(r"\n(?:async )?function \w+\(", source[start:]).start() + start
            functions.append(source[start:end])
        setup = self.SETUP.replace("/* LOAD_REAL_SEAM */", "globalThis.EDOCSeam=require(" + json.dumps(str(ROOT / "editor-seam.js")) + ");")
        script = setup + "\n" + "\n".join(functions) + "\n(async()=>{" + body + "})().catch(e=>{console.error(e);process.exit(1)});"
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_initial_company_defaults_to_ready_general_seal_and_size(self):
        value = self.run_js('uploadedSealOptions=[seal("BANK","official_seal"),seal("GENERAL"),seal("SMALL","general_seal","small_seal")];renderUploadedSealOptions();console.log(JSON.stringify({id:selectedUploadedSeal().id,category:nodes["#uploadedSealCategorySelect"].value,size:nodes["#uploadedSealSizeSelect"].value,status:nodes["#uploadedSealPickerStatus"].textContent,company:nodes["#uploadedSealPickerCompany"].textContent}));')
        self.assertEqual(value["id"], "GENERAL")
        self.assertEqual(value["category"], "general_seal")
        self.assertEqual(value["size"], "large_seal")
        self.assertIn("30.00 × 30.00 mm", value["status"])
        self.assertEqual(value["company"], "合成公司 A")

    def test_initial_loading_does_not_force_unavailable_general_before_bank_arrives(self):
        value = self.run_js('backendRequest=async()=>[seal("BANK","official_seal","small_seal")];await loadUploadedSealOptions("A");console.log(JSON.stringify({id:selectedUploadedSeal().id,size:nodes["#uploadedSealSizeSelect"].value}));')
        self.assertEqual(value, {"id": "BANK", "size": "small_seal"})

    def test_missing_size_is_not_offered_and_available_seal_remains_selected(self):
        value = self.run_js('uploadedSealOptions=[seal("GENERAL"),seal("BANK","official_seal","small_seal")];renderUploadedSealOptions();select("general_seal","small_seal");renderUploadedSealOptions();console.log(JSON.stringify({id:selectedUploadedSeal()?.id||null,value:nodes["#uploadedSealSealSelect"].value,disabled:nodes["#uploadedSealSealSelect"].disabled,status:nodes["#uploadedSealPickerStatus"].textContent}));')
        self.assertEqual(value["id"], "GENERAL")
        self.assertEqual(value["value"], "GENERAL")
        self.assertFalse(value["disabled"])
        self.assertIn("便章 · 大章", value["status"])

    def test_size_and_category_change_only_selects_exact_match(self):
        value = self.run_js('uploadedSealOptions=[seal("GENERAL"),seal("BANK-S","official_seal","small_seal"),seal("EST-L","establishment_seal")];renderUploadedSealOptions();select("official_seal","small_seal");const small=selectedUploadedSeal().id;select("establishment_seal","large_seal");console.log(JSON.stringify({small,large:selectedUploadedSeal().id}));')
        self.assertEqual(value, {"small": "BANK-S", "large": "EST-L"})

    def test_company_change_cannot_keep_another_companys_stamp(self):
        value = self.run_js('uploadedSealOptions=[seal("A-GENERAL"),seal("B-BANK","official_seal","small_seal","B")];renderUploadedSealOptions();nodes["#uploadedSealCompany"].value="B";const stale=selectedUploadedSeal();backendRequest=async()=>[seal("B-BANK","official_seal","small_seal","B")];await loadUploadedSealOptions("B");console.log(JSON.stringify({stale,selected:selectedUploadedSeal().id,options:nodes["#uploadedSealSealSelect"].options.map(x=>x.value)}));')
        self.assertIsNone(value["stale"])
        self.assertEqual(value["selected"], "B-BANK")
        self.assertEqual(value["options"], ["B-BANK"])

    def test_inactive_unversioned_and_unscoped_records_are_not_usable(self):
        value = self.run_js('uploadedSealOptions=[{...seal("INACTIVE"),is_active:false},seal("EMPTY","general_seal","large_seal","A",false),{...seal("UNSCOPED"),company_id:""}];renderUploadedSealOptions();console.log(JSON.stringify({selected:selectedUploadedSeal(),status:nodes["#uploadedSealPickerStatus"].dataset.state,options:nodes["#uploadedSealSealSelect"].options.map(x=>x.value)}));')
        self.assertIsNone(value["selected"])
        self.assertEqual(value["status"], "empty")
        self.assertEqual(value["options"], [""])

    def test_only_current_company_seal_categories_and_sizes_are_offered(self):
        value = self.run_js('uploadedSealOptions=[seal("BANK-S","official_seal","small_seal"),seal("EMPTY","general_seal","large_seal","A",false),{...seal("OTHER","official_seal"),company_id:"B"}];renderUploadedSealOptions();console.log(JSON.stringify({categories:nodes["#uploadedSealCategorySelect"].options.map(x=>x.value),sizes:nodes["#uploadedSealSizeSelect"].options.map(x=>x.value),seals:nodes["#uploadedSealSealSelect"].options.map(x=>x.value),selected:selectedUploadedSeal()?.id||null}));')
        self.assertEqual(value, {"categories": ["official_seal"], "sizes": ["small_seal"], "seals": ["BANK-S"], "selected": "BANK-S"})

    def test_record_selector_only_appears_for_multiple_matching_records(self):
        value = self.run_js('uploadedSealOptions=[seal("ONE"),seal("BANK","official_seal")];renderUploadedSealOptions();const one=nodes["#uploadedSealRecordLabel"].hidden;uploadedSealOptions.push(seal("TWO"));renderUploadedSealOptions();nodes["#uploadedSealSealSelect"].value="TWO";changeUploadedSealPickerSelection();console.log(JSON.stringify({one,multiple:nodes["#uploadedSealRecordLabel"].hidden,selected:selectedUploadedSeal().id}));')
        self.assertEqual(value, {"one": True, "multiple": False, "selected": "TWO"})

    def test_unknown_server_categories_are_not_new_application_choices(self):
        value = self.run_js('uploadedSealOptions=[seal("CUSTOM","custom<&kind")];renderUploadedSealOptions();console.log(JSON.stringify({category:nodes["#uploadedSealCategorySelect"].value,id:selectedUploadedSeal()?.id||null,options:uploadedSealPickerCategoryOptions().map(x=>x.code)}));')
        self.assertEqual(value["category"], "")
        self.assertIsNone(value["id"])
        self.assertEqual(value["options"], [])

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
        value = self.run_js('uploadedSealOptions=[seal("GENERAL"),seal("BANK-S","official_seal","small_seal")];renderUploadedSealOptions();select("official_seal","small_seal");addUploadedStamp("current_page",{x:123,y:234});addUploadedStamp("all_pages",{x:45,y:67});console.log(JSON.stringify(placements));')
        self.assertEqual(value, [{"kind": "seal", "point": {"x": 123, "y": 234}, "pages": ["P2"], "seal": "BANK-S"}, {"kind": "seal", "point": {"x": 45, "y": 67}, "pages": ["P1", "P2", "P3"], "seal": "BANK-S"}])

    def test_grouped_seams_use_company_large_in_five_plus_two_independent_groups(self):
        value = self.run_js('uploadedSealEditorState.pages=Array.from({length:7},(_,i)=>({pageId:"P"+(i+1),widthPt:595,heightPt:842}));uploadedSealOptions=[seal("GENERAL"),seal("COMPANY-L","establishment_seal"),seal("COMPANY-S","establishment_seal","small_seal"),seal("BANK-S","official_seal","small_seal")];nodes["#uploadedEditorSeamPanel"].hidden=false;renderUploadedSealOptions();addUploadedSeamGroups();const groups=[...EDOCSeam.groups(uploadedSealEditorState)];console.log(JSON.stringify({category:nodes["#uploadedSealCategorySelect"].value,sizes:nodes["#uploadedSealSizeSelect"].options.map(x=>x.value),groups:groups.map(([id,members])=>({count:members.length,parts:members.map(e=>e.properties.seamPartIndex),edge:members.map(e=>e.properties.seamEdge),offset:EDOCSeam.offsetPt(uploadedSealEditorState.pages.find(p=>p.pageId===members[0].pageId),members[0]),bindings:members.map(e=>({seal:e.properties.sealId,file:e.properties.sealFileId}))}))}));')
        self.assertEqual(value["category"], "general_seal")  # Ordinary picker is not hijacked by seam mode.
        self.assertEqual(value["sizes"], ["large_seal"])
        self.assertEqual([group["count"] for group in value["groups"]], [5, 2])
        self.assertEqual([group["parts"] for group in value["groups"]], [list(range(5)), [0, 1]])
        self.assertEqual(value["groups"][0]["offset"], value["groups"][1]["offset"])
        self.assertTrue(all(binding == {"seal": "COMPANY-L", "file": "FILE-COMPANY-L"} for group in value["groups"] for binding in group["bindings"]))

    def test_grouped_seams_reject_wrong_owner_category_small_and_unavailable_primary(self):
        for owner,category,size in (("company","general_seal","large_seal"),("company","establishment_seal","small_seal"),
            ("company","official_seal","large_seal"),("institution","establishment_seal","large_seal"),
            ("institution","general_seal","large_seal"),("institution","bank_seal","large_seal"),
            ("institution","continuous_seal","single_seal"),("institution","official_seal","small_seal"),
            ("unclassified","official_seal","large_seal")):
            with self.subTest(owner=owner,category=category,size=size):
                record='({...seal("INVALID",'+json.dumps(category)+','+json.dumps(size)+'),owner_kind:'+json.dumps(owner)+'})'
                value=self.run_js('uploadedSealOptions=['+record+'];nodes["#uploadedEditorSeamPanel"].hidden=false;renderUploadedSealOptions();addUploadedSeamGroups();console.log(JSON.stringify({count:uploadedSealEditorState.elements.length,selected:selectedUploadedSeamSeal(),category:nodes["#uploadedSealCategorySelect"].value,toasts}));')
                self.assertEqual(value["count"],0)
                self.assertIsNone(value["selected"])
                self.assertIn("請先選擇可用的印章版本。",value["toasts"])

    def test_institution_primary_picker_uses_only_selected_unit_official_large(self):
        self.SETUP += '\nuploadedSealCatalogState.companyId="CO-INST";\n'
        value=self.run_js('nodes["#uploadedSealCompany"].options.push({value:"CO-INST",textContent:"合成機構"});nodes["#uploadedSealCompany"].value="CO-INST";uploadedSealApplicationRuntime.companyId="CO-INST";uploadedSealOptions=[{...seal("INST-L","official_seal","large_seal","CO-INST"),owner_kind:"institution",widthMm:20,heightMm:40},{...seal("INST-S","official_seal","small_seal","CO-INST"),owner_kind:"institution"},{...seal("GENERAL","general_seal","large_seal","CO-INST"),owner_kind:"institution"},{...seal("WRONG","establishment_seal","large_seal","CO-INST"),owner_kind:"institution"},seal("FOREIGN","establishment_seal","large_seal","A")];nodes["#uploadedEditorSeamPanel"].hidden=false;renderUploadedSealOptions();addUploadedSeamGroups();console.log(JSON.stringify({id:selectedUploadedSeal()?.id,category:nodes["#uploadedSealCategorySelect"].value,sizes:nodes["#uploadedSealSizeSelect"].options.map(o=>o.value),seals:nodes["#uploadedSealSealSelect"].options.map(o=>o.value),bindings:uploadedSealEditorState.elements.map(e=>e.properties.sealId),status:nodes["#uploadedSealPickerStatus"].textContent,toasts}));')
        self.assertEqual(value["id"],"GENERAL")
        self.assertEqual(value["category"],"general_seal")
        self.assertEqual(value["sizes"],["large_seal"])
        self.assertEqual(value["seals"],["GENERAL"])
        self.assertEqual(value["bindings"],["INST-L"]*3)
        self.assertIn("30.00 × 30.00 mm",value["status"])
        self.assertTrue(any("圖記大章" in text for text in value["toasts"]))

    def test_institution_primary_missing_current_or_invalid_dimensions_is_not_offered(self):
        for patch in ('current_file:null,current_file_id:""','current_file:{usable:false,is_current:true},selectable:false',
                      'current_file:{usable:true,is_current:false}','is_active:false','company_id:"FOREIGN"'):
            with self.subTest(patch=patch):
                value=self.run_js('uploadedSealOptions=[{...seal("INST-L","official_seal"),owner_kind:"institution",'+patch+'}];nodes["#uploadedEditorSeamPanel"].hidden=false;renderUploadedSealOptions();addUploadedSeamGroups();console.log(JSON.stringify({selected:selectedUploadedSeal(),count:uploadedSealEditorState.elements.length,disabled:nodes["#uploadedSealSealSelect"].disabled}));')
                self.assertEqual(value,{"selected":None,"count":0,"disabled":True})

    def test_company_jump_reveals_only_existing_company_control(self):
        value = self.run_js('nodes["#uploadedSealApplicationFields"].hidden=true;focusUploadedSealCompany();console.log(JSON.stringify({hidden:nodes["#uploadedSealApplicationFields"].hidden,focused:nodes["#uploadedSealCompany"].focused,value:nodes["#uploadedSealCompany"].value,changes}));')
        self.assertEqual(value, {"hidden": False, "focused": True, "value": "A", "changes": 0})

    def test_opening_seam_keeps_small_company_and_institution_seal_selected(self):
        for category, owner in (("establishment_seal", "company"), ("official_seal", "institution")):
            with self.subTest(owner=owner):
                body = 'uploadedSealOptions=[seal("BIG",CATEGORY,"large_seal"),seal("SMALL",CATEGORY,"small_seal")];uploadedSealOptions.forEach(s=>s.owner_kind=OWNER);renderUploadedSealOptions();select(CATEGORY,"small_seal");nodes["#uploadedEditorSeamPanel"].hidden=false;renderUploadedSealOptions();addUploadedSeamGroups();console.log(JSON.stringify({ordinary:selectedUploadedSeal().id,seam:selectedUploadedSeamSeal().id,sizes:nodes["#uploadedSealSizeSelect"].options.map(x=>x.value),placed:uploadedSealEditorState.elements.map(e=>e.properties.sealId)}));'
                value = self.run_js(body.replace("CATEGORY", json.dumps(category)).replace("OWNER", json.dumps(owner)))
                self.assertEqual(value, {"ordinary": "SMALL", "seam": "BIG", "sizes": ["large_seal", "small_seal"], "placed": ["BIG"] * 3})

    def test_late_old_company_response_cannot_replace_current_picker(self):
        value = self.run_js('let release;backendRequest=path=>path.includes("/A/")?new Promise(resolve=>release=resolve):Promise.resolve([seal("B","official_seal","large_seal","B")]);const old=loadUploadedSealOptions("A");nodes["#uploadedSealCompany"].value="B";await loadUploadedSealOptions("B");release([seal("A")]);await old;console.log(JSON.stringify({id:selectedUploadedSeal().id,loading:uploadedSealEditorRuntime.sealOptionsLoading,records:uploadedSealOptions.map(x=>x.id)}));')
        self.assertEqual(value, {"id": "B", "loading": False, "records": ["B"]})

    def test_catalogue_completion_refreshes_toolbar_even_when_geometry_is_unchanged(self):
        value = self.run_js('let release;backendRequest=()=>new Promise(resolve=>release=resolve);const pending=loadUploadedSealOptions("A");const loading=uploadedSealPickerReadOnly();release([seal("GENERAL")]);await pending;console.log(JSON.stringify({loading,after:uploadedSealPickerReadOnly(),renders,selected:selectedUploadedSeal().id}));')
        self.assertEqual(value, {"loading": True, "after": False, "renders": 2, "selected": "GENERAL"})

    def test_failed_catalogue_load_releases_busy_state_without_using_stale_seals(self):
        value = self.run_js('uploadedSealOptions=[seal("GENERAL")];renderUploadedSealOptions();backendRequest=async()=>{throw new Error("synthetic offline")};await loadUploadedSealOptions("A");console.log(JSON.stringify({loading:uploadedSealEditorRuntime.sealOptionsLoading,selected:selectedUploadedSeal(),records:uploadedSealOptions.length,renders,toasts}));')
        self.assertFalse(value["loading"])
        self.assertIsNone(value["selected"])
        self.assertEqual(value["records"], 1)
        self.assertEqual(value["renders"], 2)
        self.assertFalse(value["toasts"])


if __name__ == "__main__":
    unittest.main()
