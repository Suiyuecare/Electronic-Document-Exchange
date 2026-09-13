"""Progressive-disclosure controls retain the PDF editor's capabilities.

These contracts intentionally inspect the shipping HTML and run the shipping
tool chooser. They do not substitute a mock renderer or change API permissions.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_electronic_seal_editor_ui_contract import html_element, javascript_function


ROOT = Path(__file__).resolve().parents[1]


class SimplifiedEditorControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")
        cls.editor = html_element(cls.html, "uploadedPdfEditor")

    def test_common_tools_are_direct_and_advanced_tools_have_one_closed_disclosure(self) -> None:
        more = html_element(self.editor, "uploadedEditorMoreTools")
        self.assertRegex(more, r"^<details\b")
        self.assertNotRegex(more.split(">", 1)[0], r"\bopen(?:\s|=|$)")
        self.assertRegex(more, r"<summary\b[^>]*>[^<]*更多")
        for kind in ("replacement", "image", "shape", "checkmark", "highlight", "redaction"):
            button = re.search(rf'<button\b[^>]*data-editor-tool="{kind}"[^>]*>', more)
            self.assertIsNotNone(button, kind)
            self.assertNotIn("advanced-only", button.group(0), kind)
        for kind in ("select", "text", "seal"):
            self.assertNotIn(f'data-editor-tool="{kind}"', more)
            self.assertEqual(self.editor.count(f'data-editor-tool="{kind}"'), 1)
        for kind in ("replacement", "image", "shape", "checkmark", "highlight", "redaction"):
            self.assertEqual(self.editor.count(f'data-editor-tool="{kind}"'), 1)
        self.assertEqual(self.editor.count('id="uploadedEditorSeamToggleBtn"'), 1)
        self.assertNotRegex(self.editor, r'<button\b[^>]*data-editor-mode=')

    def test_page_management_and_version_details_remain_available_without_dominating_canvas(self) -> None:
        pages = html_element(self.editor, "uploadedEditorThumbnailPane")
        actions = html_element(pages, "uploadedEditorPageActions")
        self.assertEqual(
            re.findall(r'data-editor-page-action="([^"]+)"', actions),
            ["move-up", "move-down", "rotate-left", "rotate-right", "delete"],
        )
        self.assertNotIn("advanced-only", actions)
        self.assertIn('id="uploadedEditorImportPdfBtn"', pages)
        self.assertIn('id="uploadedEditorImportPdfInput"', pages)
        view = html_element(self.editor, "uploadedEditorViewOptions")
        self.assertRegex(view, r"^<details\b")
        self.assertNotRegex(view.split(">", 1)[0], r"\bopen(?:\s|=|$)")
        for element_id in ("uploadedEditorReviewSelect", "uploadedEditorZoom", "uploadedPdfGeometryLabel"):
            self.assertIn(f'id="{element_id}"', view)
        self.assertEqual(
            re.findall(r'<option value="([^"]+)">', html_element(view, "uploadedEditorReviewSwitch")),
            ["edited", "original", "prepared", "changes"],
        )
        strip = html_element(self.editor, "uploadedPdfPageStrip")
        self.assertRegex(strip, r'<select\b[^>]*id="uploadedEditorPageSelect"')
        self.assertIn('aria-label=', strip)

    def test_seam_panel_defaults_closed_and_never_becomes_an_independent_mode(self) -> None:
        panel = html_element(self.editor, "uploadedEditorSeamPanel")
        self.assertRegex(panel.split(">", 1)[0], r"\bhidden(?:\s|=|$)")
        self.assertIn('id="uploadedEditorSeamPages"', panel)
        self.assertIn('id="uploadedEditorSeamGroups"', panel)
        self.assertIn('aria-expanded="false" aria-controls="uploadedEditorSeamPanel"', self.editor)
        self.assertNotIn('data-editor-tool="seam"', self.editor)

    def test_editor_controls_are_not_duplicated_by_the_new_layout(self) -> None:
        ids = re.findall(r'\bid="([^"]+)"', self.editor)
        self.assertEqual(len(ids), len(set(ids)), "Editor IDs must remain unique after moving controls")
        for preserved_id in (
            "uploadedSealPdfInput", "uploadedSealSealSelect", "uploadedSealStampType",
            "uploadedSealTextInput", "uploadedSealFontSize", "addUploadedTextBtn",
            "uploadedEditorImageInput", "uploadedEditorCopyPagesBtn", "uploadedEditorUndoBtn",
            "uploadedEditorRedoBtn", "uploadedPdfPrevBtn", "uploadedPdfNextBtn",
            "uploadedEditorConflictCopyBtn", "uploadedEditorResolveConflictBtn",
            "uploadedEditorUploadError", "uploadedEditorRetryUploadBtn", "submitUploadedSealBtn",
        ):
            self.assertIn(preserved_id, ids)

    def test_visible_tool_buttons_use_the_mode_aware_chooser_exactly_once(self) -> None:
        callbacks = re.findall(
            r'document\.querySelectorAll\("\[data-editor-tool\]"\)\.forEach\(\(button\)\s*=>\s*button\.addEventListener\("click",\s*\(\)\s*=>\s*(\w+)\(button\.dataset\.editorTool\)\)\)',
            self.js,
        )
        self.assertEqual(callbacks, ["chooseUploadedEditorTool"])

    def test_summary_is_separate_from_failures_and_saved_revision_data(self) -> None:
        self.assertIn('id="uploadedEditorFileMeta"', self.editor)
        status = html_element(self.editor, "uploadedEditorSaveStatus")
        self.assertIn('role="status"', status)
        self.assertIn('aria-live="polite"', status)
        alert = html_element(self.editor, "uploadedEditorUploadError")
        self.assertIn('role="alert"', alert)
        self.assertIn('id="uploadedEditorUploadErrorMessage"', alert)
        # Progressive disclosure is display state, never persisted revision data.
        for name in ("editorDraftPayload", "calculateUploadedEditorManifest"):
            source = javascript_function(self.js, name)
            for ui_key in ("uploadedEditorMoreTools", "uploadedEditorViewOptions", "thumbnailsOpen"):
                self.assertNotIn(ui_key, source)

    def test_mutations_still_enforce_locked_upload_and_read_only_reviews(self) -> None:
        mutation = javascript_function(self.js, "commitUploadedEditorMutation")
        for guard in ("uploadedSealEditorRuntime.locked", "uploadedSealEditorRuntime.uploading", 'uploadedSealEditorRuntime.reviewMode !== "edited"'):
            self.assertIn(guard, mutation)
        page_action = javascript_function(self.js, "runUploadedEditorPageAction")
        self.assertIn("commitUploadedEditorMutation", page_action)
        self.assertIn("confirm", page_action)
        self.assertIn("commitUploadedEditorMutation", javascript_function(self.js, "addUploadedSeamGroups"))
        submission = javascript_function(self.js, "uploadedEditorSubmissionPreviewIsCurrent")
        self.assertIn("uploadedEditorSubmissionFingerprint()", submission)
        self.assertIn('uploadedSealEditorRuntime.reviewMode === "prepared"', submission)
        self.assertIn("!uploadedSealEditorRuntime.conflict", submission)

    def run_javascript(self, case: str) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for shipping editor function tests")
        names = (
            "setUploadedEditorMode", "setUploadedEditorTool", "chooseUploadedEditorTool",
            "closeUploadedEditorSeamPanel", "closeUploadedEditorDisclosures",
            "setUploadedEditorSaveStatus", "runUploadedEditorPageAction",
        )
        functions = "\n".join(javascript_function(self.js, name) for name in names)
        harness = r'''
const assert = require('node:assert/strict');
const counts = {renders:0, imagePicker:0, commits:0, confirms:0};
const PDF_EDITOR_ALLOWED_KINDS = new Set(['seal','text','replacement','image','shape','checkmark','highlight','redaction']);
const uploadedSealEditorState = {
  schemaVersion:2, revisionNo:7, manifestSha256:'immutable-manifest',
  sourceFiles:[{assetId:'fixture',kind:'source_pdf',sha256:'immutable-source'}],
  pages:[{pageId:'p1',widthPt:595,heightPt:842,rotation:0,order:1},{pageId:'p2',widthPt:595,heightPt:842,rotation:0,order:2}],
  elements:[{id:'existing',pageId:'p1',kind:'text',properties:{text:'Synthetic retained content'}}],
};
const uploadedSealEditorRuntime = {
  documentId:'OD-SYNTHETIC', revisionId:'REV-SYNTHETIC', mode:'general', tool:'select',
  locked:false, uploading:false, reviewMode:'edited', currentPageId:'p1',
  selectedIds:new Set(['existing']), undoStack:[{snapshot:'unchanged'}], redoStack:[],
  dirtyGeneration:4, savedGeneration:4,
};
let uploadedSealPlacementMode='select';
function element(){return {
  dataset:{}, hidden:false, attributes:{}, classList:{toggle(){}},
  setAttribute(k,v){this.attributes[k]=v;},
  focus(){document.activeElement=this;},
};}
const nodes=new Map();
for(const id of ['uploadedPdfEditor','uploadedEditorSeamPanel','uploadedEditorSeamToggleBtn','uploadedSealTextInput','uploadedEditorImageInput','uploadedEditorSaveStatus'])nodes.set('#'+id,element());
nodes.get('#uploadedEditorImageInput').click=()=>counts.imagePicker++;
const tools=[...PDF_EDITOR_ALLOWED_KINDS,'select'].map(kind=>Object.assign(element(),{dataset:{editorTool:kind}}));
function disclosure(){const summary=element();const child=element();return {open:true,summary,child,contains:(item)=>item===child||item===summary,querySelector:()=>summary};}
const disclosures=[disclosure(),disclosure()];
const document={activeElement:null,
  querySelector:selector=>nodes.get(selector)||null,
  querySelectorAll:selector=>selector==='[data-editor-tool]'?tools:selector==='[data-editor-mode]'?[]:selector==='#uploadedPdfEditor .editor-disclosure[open]'?disclosures.filter(d=>d.open):[],
};
const window={confirm:()=>{counts.confirms++;return true;}};
function renderUploadedSealWorkbench(){counts.renders++;}
function currentUploadedEditorPageIndex(){return uploadedSealEditorState.pages.findIndex(p=>p.pageId===uploadedSealEditorRuntime.currentPageId);}
function currentUploadedEditorPage(){return uploadedSealEditorState.pages[currentUploadedEditorPageIndex()];}
function commitUploadedEditorMutation(fn){counts.commits++;fn(uploadedSealEditorState);}
function normalizeEditorDegrees(value){return (value+360)%360;}
function showToast(){}
'''
        result = subprocess.run(
            [node, "-e", harness + functions + "\n" + case],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_more_tool_selection_promotes_compat_mode_without_editing_saved_content(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
const history=JSON.stringify(uploadedSealEditorRuntime.undoStack);
for(const kind of ['replacement','image','shape','checkmark','highlight','redaction']){
  uploadedSealEditorRuntime.mode='general';uploadedSealEditorRuntime.tool='select';
  nodes.get('#uploadedEditorSeamPanel').hidden=false;
  disclosures.forEach(d=>d.open=true);
  chooseUploadedEditorTool(kind);
  assert.equal(uploadedSealEditorRuntime.mode,'advanced');
  assert.equal(uploadedSealEditorRuntime.tool,kind);
  assert.equal(uploadedSealPlacementMode,kind);
  assert.equal(nodes.get('#uploadedEditorSeamPanel').hidden,true);
  assert.ok(disclosures.every(d=>!d.open));
  assert.equal(JSON.stringify(uploadedSealEditorState),before);
  assert.equal(JSON.stringify(uploadedSealEditorRuntime.undoStack),history);
  assert.deepEqual([...uploadedSealEditorRuntime.selectedIds],['existing']);
  assert.equal(uploadedSealEditorRuntime.dirtyGeneration,4);
}
assert.equal(counts.imagePicker,1);assert.equal(counts.commits,0);
''')

    def test_locked_upload_and_non_edited_reviews_cannot_activate_hidden_tools(self) -> None:
        self.run_javascript(r'''
for(const changes of [{locked:true},{uploading:true},{reviewMode:'original'},{reviewMode:'prepared'},{reviewMode:'changes'}]){
  Object.assign(uploadedSealEditorRuntime,{locked:false,uploading:false,reviewMode:'edited',mode:'general',tool:'select'},changes);
  const before=JSON.stringify(uploadedSealEditorState);
  chooseUploadedEditorTool('image');
  assert.equal(uploadedSealEditorRuntime.mode,'general');
  assert.equal(uploadedSealEditorRuntime.tool,'select');
  assert.equal(JSON.stringify(uploadedSealEditorState),before);
}
assert.equal(counts.imagePicker,0);assert.equal(counts.renders,0);assert.equal(counts.commits,0);
''')

    def test_text_tool_focuses_input_once_without_creating_an_empty_object(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
chooseUploadedEditorTool('text');
assert.equal(uploadedSealEditorRuntime.mode,'general');
assert.equal(uploadedSealEditorRuntime.tool,'text');
assert.equal(document.activeElement,nodes.get('#uploadedSealTextInput'));
assert.equal(JSON.stringify(uploadedSealEditorState),before);
assert.equal(counts.commits,0);
''')

    def test_closing_disclosures_restores_keyboard_focus_without_touching_the_document(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
document.activeElement=disclosures[0].child;
closeUploadedEditorDisclosures(disclosures[1],true);
assert.equal(disclosures[0].open,false);
assert.equal(disclosures[1].open,true);
assert.equal(document.activeElement,disclosures[0].summary);
assert.equal(JSON.stringify(uploadedSealEditorState),before);
assert.equal(counts.commits,0);
''')

    def test_compact_success_label_never_hides_failure_or_conflict_details(self) -> None:
        self.run_javascript(r'''
const status=nodes.get('#uploadedEditorSaveStatus');
for(const message of ['已保存 · revision 7','已載入 revision 7']){
  setUploadedEditorSaveStatus('saved',message);
  assert.equal(status.textContent,'已保存');assert.equal(status.title,message);
}
for(const [kind,message] of [['conflict','另一裝置已更新，請選擇如何繼續'],['error','上傳失敗：ERR-SYNTHETIC'],['offline','離線中，尚未同步'],['saved','此公司尚未開啟編輯權限']]){
  setUploadedEditorSaveStatus(kind,message);
  assert.equal(status.textContent,message);
  assert.equal(status.className,'pdf-editor-save-status '+kind);
}
assert.equal(uploadedSealEditorState.revisionNo,7);
''')

    def test_page_delete_confirmation_precedes_single_mutation_and_preserves_original(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
window.confirm=()=>{counts.confirms++;return false;};
runUploadedEditorPageAction('delete');
assert.equal(counts.commits,0);assert.equal(JSON.stringify(uploadedSealEditorState),before);
window.confirm=()=>{counts.confirms++;return true;};
runUploadedEditorPageAction('delete');
assert.equal(counts.commits,1);
assert.deepEqual(uploadedSealEditorState.pages.map(p=>p.pageId),['p2']);
assert.equal(uploadedSealEditorRuntime.currentPageId,'p2');
assert.equal(uploadedSealEditorState.sourceFiles[0].sha256,'immutable-source');
assert.equal(uploadedSealEditorState.elements.length,0);
runUploadedEditorPageAction('delete');
assert.equal(counts.commits,1);assert.equal(counts.confirms,2);
''')

    def run_thumbnail_javascript(self, case: str) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for shipping thumbnail function tests")
        functions = "\n".join(javascript_function(self.js, name) for name in (
            "renderUploadedEditorThumbnail", "renderUploadedEditorThumbnails",
        ))
        harness = r'''
const assert=require('node:assert/strict');
const counters={domWrites:0,renders:0,observes:0,unobserves:0};
const uploadedSealEditorState={pages:[{pageId:'p1',rotation:0,sourceAssetId:'asset',widthPt:842,heightPt:595}],elements:[]};
const uploadedSealEditorRuntime={currentPageId:'p1',thumbnailObserver:null};
const runtimes=new Map();
const uploadedEditorPageRuntime=id=>runtimes.get(id);
const thumbnail={dataset:{},style:{},getContext:()=>({}),closest:()=>button};
const button={dataset:{pageId:'p1'},attributes:{},classList:{toggle(){}},setAttribute(k,v){this.attributes[k]=v;},addEventListener(){}};
const list={dataset:{},get innerHTML(){return '';},set innerHTML(value){counters.domWrites++;},querySelectorAll:s=>s==='canvas'?[thumbnail]:s==='[data-page-id]'?[button]:[]};
const document={querySelector:s=>s==='#uploadedPdfThumbnailList'?list:null};
const window={devicePixelRatio:1,pdfjsLib:{AnnotationMode:{DISABLE:0}}};
const escapeDraftHtml=String;
function setUploadedSealPage(){}function reorderUploadedEditorPage(){}
let renderMode='success', releaseRender=null;
const proxy={
  getViewport:({scale})=>({width:842*scale,height:595*scale}),
  render(){counters.renders++;return {promise:renderMode==='error'?Promise.reject(new Error('synthetic transient renderer failure')):renderMode==='pending'?new Promise(resolve=>releaseRender=resolve):Promise.resolve()};}
};
class IntersectionObserver{
  constructor(callback){this.callback=callback;this.observed=new Set();}
  observe(canvas){counters.observes++;this.observed.add(canvas);}
  unobserve(canvas){counters.unobserves++;this.observed.delete(canvas);}
  disconnect(){this.observed.clear();}
  emit(canvas=thumbnail){this.callback([{target:canvas,isIntersecting:true}]);}
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
'''
        result = subprocess.run(
            [node, "-e", harness + functions + "\n(async()=>{\n" + case + "\n})().catch(error=>{console.error(error);process.exitCode=1;});"],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cached_thumbnail_reobserves_after_late_asset_hydration_without_rebuilding_dom(self) -> None:
        self.run_thumbnail_javascript(r'''
renderUploadedEditorThumbnails();
const observer=uploadedSealEditorRuntime.thumbnailObserver;
observer.emit();await settle();
assert.equal(counters.renders,0);
assert.equal(counters.unobserves,0,'Missing runtime is not successful rendering');
assert.equal(observer.observed.has(thumbnail),true);
renderUploadedEditorThumbnails();
assert.equal(counters.domWrites,1);assert.equal(counters.observes,1);
runtimes.set('p1',{proxy});
renderUploadedEditorThumbnails();
assert.equal(counters.domWrites,1,'Hydration retry preserves the existing canvas');
assert.equal(counters.observes,2);assert.equal(observer.observed.has(thumbnail),true);
observer.emit();await settle();
assert.equal(counters.renders,1);assert.equal(thumbnail.dataset.rendered,'0');
assert.equal(observer.observed.has(thumbnail),false);
const observed=counters.observes;
renderUploadedEditorThumbnails();
assert.equal(counters.observes,observed,'Successful thumbnail is reused');
assert.equal(button.attributes['aria-current'],'page');
''')

    def test_thumbnail_error_remains_retryable_and_only_success_is_unobserved(self) -> None:
        self.run_thumbnail_javascript(r'''
runtimes.set('p1',{proxy});renderMode='error';
renderUploadedEditorThumbnails();
const observer=uploadedSealEditorRuntime.thumbnailObserver;
observer.emit();await settle();
assert.equal(thumbnail.dataset.rendered,'error');
assert.equal(thumbnail.dataset.rendering,undefined);
assert.equal(counters.unobserves,0);
assert.equal(observer.observed.has(thumbnail),true);
renderMode='success';renderUploadedEditorThumbnails();
assert.equal(counters.domWrites,1);
observer.emit();await settle();
assert.equal(counters.renders,2);assert.equal(thumbnail.dataset.rendered,'0');
assert.equal(observer.observed.has(thumbnail),false);
''')

    def test_inflight_thumbnail_render_blocks_duplicate_canvas_use_and_cache_retry(self) -> None:
        self.run_thumbnail_javascript(r'''
runtimes.set('p1',{proxy});renderMode='pending';
renderUploadedEditorThumbnails();
const rendering=renderUploadedEditorThumbnail('p1',thumbnail);
assert.equal(thumbnail.dataset.rendering,'0');
await renderUploadedEditorThumbnail('p1',thumbnail);
assert.equal(counters.renders,1,'PDF.js cannot render the same canvas concurrently');
const observed=counters.observes,unobserved=counters.unobserves;
renderUploadedEditorThumbnails();
assert.equal(counters.observes,observed);assert.equal(counters.unobserves,unobserved);
releaseRender();await rendering;
assert.equal(thumbnail.dataset.rendering,undefined);
assert.equal(thumbnail.dataset.rendered,'0');
''')

    def test_mobile_focus_trap_includes_summary_but_excludes_collapsed_details_controls(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for shipping focus-trap tests")
        anchor = self.js.index('const drawerOpen = editor?.dataset.thumbnailsOpen')
        start = self.js.rfind('document.addEventListener("keydown", (event) => {', 0, anchor)
        end = self.js.index('\n});', anchor) + len('\n});')
        self.assertGreaterEqual(start, 0)
        listener = self.js[start:end]
        harness = r'''
const assert=require('node:assert/strict');
class HTMLElement{
  constructor(name){this.name=name;this.offsetParent={};this.closed=null;}
  closest(){return this.closed;}
  contains(element){return element===this;}
  focus(){document.activeElement=this;}
}
const first=new HTMLElement('close'),summary=new HTMLElement('closed-summary'),hiddenInput=new HTMLElement('collapsed-input'),invisible=new HTMLElement('invisible');
invisible.offsetParent=null;
const details={querySelector:selector=>selector===':scope > summary'?summary:null};
summary.closed=details;hiddenInput.closed=details;
const editor={dataset:{propertiesOpen:'true'}};
let handler,prevented=0,selectorUsed='';
const pane={querySelectorAll(selector){selectorUsed=selector;return [first,...(selector.includes('summary')?[summary]:[]),hiddenInput,invisible];}};
const document={activeElement:first,querySelector:selector=>selector==='#uploadedPdfEditor'?editor:pane,addEventListener:(kind,callback)=>handler=callback};
const uploadedEditorMobileDrawerIsCompact=()=>true;
const closeUploadedEditorMobileDrawer=()=>{};
'''
        case = r'''
const event=(shiftKey=false)=>({key:'Tab',shiftKey,preventDefault(){prevented++;},stopPropagation(){}});
handler(event(true));
assert.equal(document.activeElement,summary,'Shift+Tab must land on the visible closed summary');
assert.match(selectorUsed,/summary/);
handler(event(false));
assert.equal(document.activeElement,first,'Tab wraps after the last visible summary');
assert.equal(prevented,2);
assert.notEqual(document.activeElement,hiddenInput);
'''
        result = subprocess.run([node, "-e", harness + listener + case], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_loaded_canvas_stage_does_not_force_portrait_minimum_dimensions(self) -> None:
        rules = re.findall(
            r'#uploadedPdfEditor\[data-has-document="true"\]\s+\.uploaded-pdf-stage\s*\{([^}]*)\}',
            self.css,
        )
        self.assertTrue(rules, "Loaded PDF stage must override the portrait empty-state minimum")
        self.assertRegex(rules[-1], r"min-width:\s*0\s*;")
        self.assertRegex(rules[-1], r"min-height:\s*0\s*;")

    def test_svg_text_and_shape_hit_targets_are_touch_sized_without_changing_pdf_geometry(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for shipping SVG hit-target tests")
        implementation = javascript_function(self.js, "appendEditorElementVisual")
        harness = r'''
const assert=require('node:assert/strict');
const uploadedSealEditorRuntime={selectedIds:new Set(),zoom:0.5};
function svgEditorNode(name,attributes={}){return {name,attributes:{...attributes},textContent:''};}
'''
        cases = r'''
for(const [kind,properties,rect] of [
  ['text',{text:'Synthetic note',fontSize:14},{left:100,top:80,width:22,height:12}],
  ['shape',{shapeType:'line',stroke:'#123456',strokeWidth:2},{left:60,top:45,width:120,height:2}],
  ['shape',{shapeType:'rectangle',fill:'transparent'},{left:30,top:20,width:160,height:80}],
]){
  const element={id:'synthetic-'+kind,kind,x:12,y:24,width:180,height:24,rotation:0,opacity:1,properties};
  const before=JSON.stringify(element),rectBefore=JSON.stringify(rect);
  const group={children:[],append(value){this.children.push(value);}};
  appendEditorElementVisual(group,element,rect);
  assert.equal(JSON.stringify(element),before,'Viewport hit targets must not change manifest geometry');
  assert.equal(JSON.stringify(rect),rectBefore);
  const hit=group.children[0];
  assert.equal(hit.name,'rect');assert.equal(hit.attributes.class,'editor-object-hit');
  assert.equal(hit.attributes.fill,'transparent');assert.equal(hit.attributes['aria-hidden'],'true');
  assert.equal(hit.attributes.width,Math.max(44,rect.width));
  assert.equal(hit.attributes.height,Math.max(44,rect.height));
  assert.equal(hit.attributes.x+hit.attributes.width/2,rect.left+rect.width/2);
  assert.equal(hit.attributes.y+hit.attributes.height/2,rect.top+rect.height/2);
  const visual=group.children[1];
  if(kind==='text'){
    assert.equal(visual.name,'text');assert.equal(visual.textContent,properties.text);
    assert.equal(visual.attributes.x,rect.left+3);
  }else if(properties.shapeType==='line'){
    assert.equal(visual.name,'line');assert.equal(visual.attributes.x1,rect.left);
    assert.equal(visual.attributes.x2,rect.left+rect.width);
    assert.equal(visual.attributes.y1,rect.top+rect.height/2);
  }else{
    assert.equal(visual.name,'rect');assert.equal(visual.attributes.width,rect.width);
    assert.equal(visual.attributes.height,rect.height);
  }
}
'''
        result = subprocess.run([node, "-e", harness + implementation + cases], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_svg_hit_target_overrides_noninteractive_visual_children(self) -> None:
        rules = list(re.finditer(r"\.editor-svg-element\s+\.editor-object-hit\s*\{([^}]*)\}", self.css))
        self.assertTrue(rules, "Transparent hit rectangles must receive pointer events")
        self.assertRegex(rules[-1].group(1), r"pointer-events:\s*all\s*;")
        blanket = re.search(r"\.editor-svg-element\s+\*\s*\{[^}]*pointer-events:\s*none", self.css)
        self.assertIsNotNone(blanket, "Decorative SVG children retain their existing event exclusion")
        self.assertGreater(rules[-1].start(), blanket.start())
