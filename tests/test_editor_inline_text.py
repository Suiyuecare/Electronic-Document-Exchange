"""Direct PDF text editing is a transient, scope-bound UI transaction.

The lifecycle contracts execute the shipping JavaScript rather than replacing
its mutation/undo path. Fixtures contain no customer documents or identities.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_electronic_seal_editor_ui_contract import html_element, javascript_function


ROOT = Path(__file__).resolve().parents[1]


class InlineEditorTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")

    def run_javascript(self, case: str) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for direct PDF text editing contracts")
        functions = "\n".join(javascript_function(self.js, name) for name in (
            "normalizeEditorDegrees",
            "uploadedEditorTextLines", "fitUploadedEditorTextHeight",
            "uploadedEditorTextEditIsCurrent", "startUploadedEditorTextEdit",
            "finishUploadedEditorTextEdit", "renderUploadedEditorTextEdit",
            "handleUploadedEditorTextKeydown", "commitUploadedEditorMutation",
            "pushUploadedEditorHistory", "undoUploadedEditor", "redoUploadedEditor",
            "setUploadedSealPage",
            "setUploadedEditorPropertyValue",
        ))
        harness = r'''
const assert = require('node:assert/strict');
const counts = {renders:0, inlineRenders:0, dirty:0, sync:0, toast:0};
const PDF_EDITOR_ALLOWED_KINDS = new Set(['seal','text','replacement','image','shape','checkmark','highlight','redaction']);
const PDF_EDITOR_MAX_ELEMENTS = 1000;
const PDF_EDITOR_DEFAULT_FONT_FAMILY = 'Synthetic safe font';
let sessionScope = 'synthetic-session';
let scopeEpoch = 1;
let nextId = 1;
let textFontReady = true;
const cloneUploadedEditorValue = value => JSON.parse(JSON.stringify(value));
const canonicalEditorJson = value => JSON.stringify(value);
const roundEditorPoint = value => Math.round(Number(value) * 1000) / 1000;
let uploadedSealEditorState = {
  schemaVersion:2, revisionNo:7, manifestSha256:'retained-manifest',
  sourceFiles:[{assetId:'asset-1',kind:'source_pdf',sha256:'retained-source'}],
  pages:[
    {pageId:'p1',sourceAssetId:'asset-1',sourcePageIndex:0,widthPt:595,heightPt:842,cropBox:[0,0,595,842],rotation:0,order:1},
    {pageId:'p2',sourceAssetId:'asset-1',sourcePageIndex:1,widthPt:595,heightPt:842,cropBox:[0,0,595,842],rotation:0,order:2},
  ],
  elements:[{
    id:'existing', pageId:'p1', kind:'text', x:30,y:600,width:180,height:24,rotation:0,opacity:1,zIndex:1,
    properties:{text:'Retained synthetic text',fontSize:14,color:'#111827',fontFamily:PDF_EDITOR_DEFAULT_FONT_FAMILY},
  }],
};
const uploadedSealEditorRuntime = {
  documentId:'OD-SYNTHETIC',revisionId:'REV-7',currentPageId:'p1',currentViewport:{width:595,height:842},
  reviewMode:'edited', locked:false,uploading:false,companyChanging:false,directoryLoading:false,
  conflict:null,mode:'general',tool:'select',textEdit:null,selectedIds:new Set(),
  undoStack:[],redoStack:[],dirtyGeneration:0,savedGeneration:0,pointerAction:null,zoom:1,
};
let uploadedSealPlacementMode = 'select';
const nodes = new Map();
function node(selector){
  if(!nodes.has(selector))nodes.set(selector,{
    id:selector.slice(1),value:'',hidden:false,disabled:false,dataset:{},style:{},attributes:{},
    classList:{toggle(){},add(){},remove(){}},
    focus(){document.activeElement=this;},select(){},scrollIntoView(){},
    setAttribute(key,value){this.attributes[key]=value;},removeAttribute(key){delete this.attributes[key];},
    getBoundingClientRect(){return {left:0,top:0,width:595,height:842};},
    querySelector(){return null;},querySelectorAll(){return [];},
    contains(value){return value===this;},
  });
  return nodes.get(selector);
}
const document = {
  activeElement:null, querySelector:node, querySelectorAll:()=>[],
  createElement(tag){assert.equal(tag,'canvas');return {getContext(kind){assert.equal(kind,'2d');return {
    font:'14px Synthetic',fontKerning:'auto',measureText(text){return {width:[...text].reduce((width,character)=>width+parseFloat(this.font)*(character.codePointAt(0)>127?1:0.5),0)};},
  };}};},
};
const window = {confirm:()=>true,requestAnimationFrame:callback=>callback()};
const requestAnimationFrame = callback => callback();
node('#uploadedSealFontSize').value='14';
node('#uploadedEditorInlineFontSize').value='14';
node('#uploadedEditorInlineColor').value='#111827';
function currentUploadedEditorPage(){return uploadedSealEditorState.pages.find(p=>p.pageId===uploadedSealEditorRuntime.currentPageId);}
function editorElementById(id){return uploadedSealEditorState.elements.find(e=>e.id===id);}
function uploadedEditorViewportRect(element){return {left:element.x,top:842-element.y-element.height,width:element.width,height:element.height};}
function uploadedSealApplicationScopeSnapshot(){return {scope:sessionScope,epoch:scopeEpoch,documentId:uploadedSealEditorRuntime.documentId};}
function uploadedSealApplicationScopeIsCurrent(scope){return scope.scope===sessionScope&&scope.epoch===scopeEpoch&&scope.documentId===uploadedSealEditorRuntime.documentId;}
function editorDefaultElement(kind,page,point,properties={}){
  return {id:'new-'+nextId++,pageId:page.pageId,kind,x:Math.max(0,Math.min(page.widthPt-180,(point?.x??290)-90)),
    y:Math.max(0,Math.min(page.heightPt-24,(point?.y??421)-12)),width:180,height:24,rotation:0,opacity:1,zIndex:2,
    properties:{text:'',fontSize:14,color:'#111827',fontFamily:PDF_EDITOR_DEFAULT_FONT_FAMILY,...properties}};
}
function renderUploadedSealWorkbench(){counts.renders++;}
function renderUploadedEditorSvgLayer(){}
function renderUploadedEditorProperties(){}
function closeUploadedEditorDisclosures(){}
function closeUploadedEditorSeamPanel(){}
function closeUploadedEditorMobileDrawer(){}
function ensureUploadedEditorTextFont(){return textFontReady;}
function normalizeUploadedEditorSealGeometry(){}
function normalizeUploadedEditorElementLayers(){}
function syncLegacyUploadedEditorCollections(){counts.sync++;}
function markUploadedEditorDirty(){counts.dirty++;uploadedSealEditorRuntime.dirtyGeneration++;}
function showToast(){counts.toast++;}
function typeText(text){node('#uploadedEditorInlineText').value=text;}
'''
        result = subprocess.run(
            [node, "-e", harness + functions + "\n" + case],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_starting_text_is_transient_and_focuses_the_document_input(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
assert.equal(startUploadedEditorTextEdit({x:120,y:600}),true);
assert.ok(uploadedSealEditorRuntime.textEdit);
assert.equal(document.activeElement,node('#uploadedEditorInlineText'));
assert.equal(JSON.stringify(uploadedSealEditorState),before);
assert.equal(uploadedSealEditorRuntime.undoStack.length,0);
assert.equal(counts.dirty,0);
''')

    def test_done_creates_one_object_and_one_undo_step_then_returns_to_selection(self) -> None:
        self.run_javascript(r'''
const before=cloneUploadedEditorValue(uploadedSealEditorState);
assert.equal(startUploadedEditorTextEdit({x:120,y:600}),true);
typeText('Synthetic direct text');
assert.equal(finishUploadedEditorTextEdit(),true);
assert.equal(uploadedSealEditorRuntime.textEdit,null);
assert.equal(uploadedSealEditorState.elements.length,2);
const created=uploadedSealEditorState.elements[1];
assert.equal(created.properties.text,'Synthetic direct text');assert.equal(created.pageId,'p1');
assert.equal(uploadedSealEditorRuntime.undoStack.length,1);assert.equal(counts.dirty,1);
assert.equal(uploadedSealEditorRuntime.tool,'select');
assert.deepEqual([...uploadedSealEditorRuntime.selectedIds],[created.id]);
assert.deepEqual(uploadedSealEditorState.sourceFiles,before.sourceFiles);
assert.deepEqual(uploadedSealEditorState.pages,before.pages);
assert.equal(uploadedSealEditorState.revisionNo,7);
finishUploadedEditorTextEdit();assert.equal(counts.dirty,1);
undoUploadedEditor();assert.deepEqual(uploadedSealEditorState,before);
redoUploadedEditor();assert.equal(uploadedSealEditorState.elements[1].properties.text,'Synthetic direct text');
''')

    def test_clicked_text_origin_accounts_for_all_quarter_page_rotations(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState.elements);
for(const [rotation,x,y] of [[0,300,376],[90,300,400],[180,120,400],[270,120,376]]){
  uploadedSealEditorState.pages[0].rotation=rotation;
  assert.equal(startUploadedEditorTextEdit({x:300,y:400}),true);
  const element=uploadedSealEditorRuntime.textEdit.element;
  assert.equal(element.x,x,'x at '+rotation);assert.equal(element.y,y,'y at '+rotation);
  assert.equal(element.pageId,'p1');assert.equal(element.width,180);assert.equal(element.height,24);
  assert.equal(element.rotation,0,'Page rotation does not become object rotation');
  finishUploadedEditorTextEdit({cancel:true});
}
assert.equal(JSON.stringify(uploadedSealEditorState.elements),before);
assert.equal(counts.dirty,0);assert.equal(uploadedSealEditorRuntime.undoStack.length,0);
''')

    def test_cancel_and_empty_new_text_do_not_consume_revision_or_history(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
for(const cancel of [false,true]){
  startUploadedEditorTextEdit({x:120,y:600});typeText(cancel?'Cancelled note':'   ');
  assert.equal(finishUploadedEditorTextEdit({cancel}),true);
  assert.equal(uploadedSealEditorRuntime.textEdit,null);
  assert.equal(JSON.stringify(uploadedSealEditorState),before);
}
assert.equal(uploadedSealEditorRuntime.undoStack.length,0);assert.equal(counts.dirty,0);
''')

    def test_editing_existing_text_preserves_identity_geometry_and_original_asset(self) -> None:
        self.run_javascript(r'''
const before=cloneUploadedEditorValue(uploadedSealEditorState);
assert.equal(startUploadedEditorTextEdit(null,'existing'),true);
assert.equal(node('#uploadedEditorInlineText').value,'Retained synthetic text');
typeText('Updated synthetic text');
assert.equal(finishUploadedEditorTextEdit(),true);
assert.equal(uploadedSealEditorState.elements.length,1);
const edited=uploadedSealEditorState.elements[0];
assert.equal(edited.properties.text,'Updated synthetic text');
for(const key of ['id','pageId','kind','x','y','width','height','rotation','opacity','zIndex'])assert.equal(edited[key],before.elements[0][key],key);
assert.deepEqual(uploadedSealEditorState.sourceFiles,before.sourceFiles);
assert.equal(uploadedSealEditorRuntime.undoStack.length,1);assert.equal(counts.dirty,1);
undoUploadedEditor();assert.deepEqual(uploadedSealEditorState,before);
''')

    def test_unchanged_existing_text_is_a_noop_and_empty_existing_text_stays_editable(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
startUploadedEditorTextEdit(null,'existing');
assert.equal(finishUploadedEditorTextEdit(),true);assert.equal(counts.dirty,0);
startUploadedEditorTextEdit(null,'existing');typeText('   ');
assert.equal(finishUploadedEditorTextEdit(),false);assert.ok(uploadedSealEditorRuntime.textEdit);
assert.equal(JSON.stringify(uploadedSealEditorState),before);assert.equal(counts.dirty,0);
assert.equal(finishUploadedEditorTextEdit({cancel:true}),true);
''')

    def test_composition_cannot_partially_commit_and_escape_can_cancel_it(self) -> None:
        self.run_javascript(r'''
startUploadedEditorTextEdit({x:120,y:600});typeText('輸入法組字');
uploadedSealEditorRuntime.textEdit.composing=true;
assert.equal(finishUploadedEditorTextEdit(),false);
assert.ok(uploadedSealEditorRuntime.textEdit);assert.equal(counts.dirty,0);
assert.equal(finishUploadedEditorTextEdit({cancel:true}),true);
assert.equal(uploadedSealEditorRuntime.textEdit,null);assert.equal(counts.dirty,0);
''')

    def test_start_is_blocked_for_read_only_upload_conflict_and_company_transitions(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
for(const patch of [{locked:true},{uploading:true},{companyChanging:true},{conflict:{code:'synthetic'}},{reviewMode:'original'},{reviewMode:'prepared'},{reviewMode:'changes'}]){
  Object.assign(uploadedSealEditorRuntime,{locked:false,uploading:false,companyChanging:false,conflict:null,reviewMode:'edited'},patch);
  assert.equal(startUploadedEditorTextEdit({x:120,y:600}),false,JSON.stringify(patch));
  assert.equal(uploadedSealEditorRuntime.textEdit,null);assert.equal(JSON.stringify(uploadedSealEditorState),before);
}
assert.equal(counts.dirty,0);
''')

    def test_invalidation_never_writes_into_another_document_page_or_session(self) -> None:
        self.run_javascript(r'''
for(const invalidate of [
  ()=>uploadedSealEditorRuntime.documentId='OD-OTHER',
  ()=>uploadedSealEditorRuntime.currentPageId='p2',
  ()=>sessionScope='other-session',
  ()=>scopeEpoch++,
  ()=>uploadedSealEditorState.pages[0].sourceAssetId='other-asset',
  ()=>uploadedSealEditorState.pages[0].sourcePageIndex=8,
  ()=>uploadedSealEditorRuntime.locked=true,
  ()=>uploadedSealEditorRuntime.uploading=true,
  ()=>uploadedSealEditorRuntime.companyChanging=true,
  ()=>uploadedSealEditorRuntime.reviewMode='original',
]){
  Object.assign(uploadedSealEditorRuntime,{documentId:'OD-SYNTHETIC',currentPageId:'p1',locked:false,uploading:false,companyChanging:false,reviewMode:'edited'});
  Object.assign(uploadedSealEditorState.pages[0],{sourceAssetId:'asset-1',sourcePageIndex:0});sessionScope='synthetic-session';
  assert.equal(startUploadedEditorTextEdit({x:120,y:600}),true);typeText('Must never leak');
  invalidate();const before=JSON.stringify(uploadedSealEditorState);
  finishUploadedEditorTextEdit();
  assert.equal(uploadedSealEditorRuntime.textEdit,null);assert.equal(JSON.stringify(uploadedSealEditorState),before);
}
assert.equal(counts.dirty,0);assert.equal(uploadedSealEditorRuntime.undoStack.length,0);
''')

    def test_successful_autosave_cursor_change_does_not_discard_typing(self) -> None:
        self.run_javascript(r'''
startUploadedEditorTextEdit(null,'existing');typeText('Retained across save');
uploadedSealEditorRuntime.revisionId='REV-8';uploadedSealEditorState.revisionNo=8;
uploadedSealEditorState.manifestSha256='saved-manifest-8';
assert.equal(finishUploadedEditorTextEdit(),true);
assert.equal(uploadedSealEditorState.elements[0].properties.text,'Retained across save');
assert.equal(uploadedSealEditorState.revisionNo,8);assert.equal(uploadedSealEditorRuntime.revisionId,'REV-8');
assert.equal(uploadedSealEditorRuntime.undoStack.length,1);
''')

    def test_changed_or_removed_existing_element_is_not_silently_overwritten(self) -> None:
        self.run_javascript(r'''
const existing=cloneUploadedEditorValue(uploadedSealEditorState.elements[0]);
for(const mutate of [()=>uploadedSealEditorState.elements[0].properties.text='Newer canonical text',()=>uploadedSealEditorState.elements.splice(0,1)]){
  uploadedSealEditorState.elements=[cloneUploadedEditorValue(existing)];
  startUploadedEditorTextEdit(null,'existing');typeText('Stale input');mutate();
  const before=JSON.stringify(uploadedSealEditorState);
  finishUploadedEditorTextEdit();
  assert.equal(uploadedSealEditorRuntime.textEdit,null);assert.equal(JSON.stringify(uploadedSealEditorState),before);
}
assert.equal(counts.dirty,0);
''')

    def test_unsafe_element_kinds_and_missing_pages_cannot_open_text_editing(self) -> None:
        self.run_javascript(r'''
for(const kind of ['seal','replacement','image','shape','redaction','highlight','checkmark']){
  uploadedSealEditorState.elements[0].kind=kind;
  assert.equal(startUploadedEditorTextEdit(null,'existing'),false,kind);
  assert.equal(uploadedSealEditorRuntime.textEdit,null);
}
assert.equal(startUploadedEditorTextEdit(null,'missing'),false);
uploadedSealEditorRuntime.currentPageId='missing-page';
assert.equal(startUploadedEditorTextEdit({x:120,y:600}),false);assert.equal(counts.dirty,0);
''')

    def test_invalid_font_sizes_and_overlong_text_stay_open_without_mutating(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
for(const fontSize of ['','5','145','not-a-number','Infinity']){
  startUploadedEditorTextEdit({x:120,y:600});typeText('Synthetic valid content');
  node('#uploadedEditorInlineFontSize').value=fontSize;
  assert.equal(finishUploadedEditorTextEdit(),false,fontSize);
  assert.ok(uploadedSealEditorRuntime.textEdit);assert.equal(JSON.stringify(uploadedSealEditorState),before);
  finishUploadedEditorTextEdit({cancel:true});
}
startUploadedEditorTextEdit({x:120,y:600});typeText('x'.repeat(1001));
assert.equal(finishUploadedEditorTextEdit(),false);
assert.equal(JSON.stringify(uploadedSealEditorState),before);assert.equal(counts.dirty,0);
''')

    def test_legacy_text_and_font_bounds_remain_editable_without_shortening(self) -> None:
        self.run_javascript(r'''
for(const fontSize of [6,144]){
  const original=uploadedSealEditorState.elements[0];
  original.properties.text='原'.repeat(1000);original.properties.fontSize=fontSize;
  const before=JSON.stringify(uploadedSealEditorState);
  assert.equal(startUploadedEditorTextEdit(null,'existing'),true);
  assert.equal(node('#uploadedEditorInlineText').value.length,1000);
  assert.equal(finishUploadedEditorTextEdit(),true);
  assert.equal(JSON.stringify(uploadedSealEditorState),before);
}
assert.equal(counts.dirty,0);
''')

    def test_pasted_newlines_are_preserved_and_inline_font_color_are_saved_once(self) -> None:
        self.run_javascript(r'''
startUploadedEditorTextEdit({x:120,y:600});typeText('First synthetic line\r\nSecond synthetic line');
node('#uploadedEditorInlineFontSize').value='18';node('#uploadedEditorInlineColor').value='#123456';
assert.equal(finishUploadedEditorTextEdit(),true);
const element=uploadedSealEditorState.elements[1];
assert.equal(element.properties.text,'First synthetic line\nSecond synthetic line');
assert.equal(element.properties.fontSize,18);assert.equal(element.properties.color,'#123456');
assert.equal(counts.dirty,1);assert.equal(uploadedSealEditorRuntime.undoStack.length,1);
''')

    def test_wrapping_preserves_blank_paragraphs_and_unicode_code_points(self) -> None:
        self.run_javascript(r'''
assert.deepEqual(uploadedEditorTextLines('abcd\r\nef\r\n\r\ngh',10,10),['ab','cd','ef','','gh']);
assert.deepEqual(uploadedEditorTextLines('甲乙丙丁',20,10),['甲乙','丙丁']);
assert.deepEqual(uploadedEditorTextLines('A😀B',10,10),['A','😀','B'],'Do not split a surrogate pair');
assert.deepEqual(uploadedEditorTextLines('',100,14),['']);
assert.equal(counts.dirty,0);
''')

    def test_multiline_height_grows_without_moving_the_existing_top_edge(self) -> None:
        self.run_javascript(r'''
const original=cloneUploadedEditorValue(uploadedSealEditorState.elements[0]);
startUploadedEditorTextEdit(null,'existing');typeText('First line\nSecond line\nThird line');
assert.equal(finishUploadedEditorTextEdit(),true);
const element=uploadedSealEditorState.elements[0];
assert.equal(element.height,50.4);assert.equal(element.y,573.6);
assert.equal(element.y+element.height,original.y+original.height);
assert.equal(element.x,original.x);assert.equal(element.width,original.width);
assert.equal(element.properties.text,'First line\nSecond line\nThird line');
assert.equal(counts.dirty,1);assert.equal(uploadedSealEditorRuntime.undoStack.length,1);
undoUploadedEditor();assert.deepEqual(uploadedSealEditorState.elements[0],original);
''')

    def test_color_only_edit_preserves_existing_geometry_even_for_legacy_long_text(self) -> None:
        self.run_javascript(r'''
uploadedSealEditorState.elements[0].properties.text='原'.repeat(1000);
uploadedSealEditorState.elements[0].properties.fontSize=144;
const original=cloneUploadedEditorValue(uploadedSealEditorState.elements[0]);
startUploadedEditorTextEdit(null,'existing');node('#uploadedEditorInlineColor').value='#abcdef';
assert.equal(finishUploadedEditorTextEdit(),true);
const element=uploadedSealEditorState.elements[0];
for(const key of ['x','y','width','height'])assert.equal(element[key],original[key],key);
assert.equal(element.properties.text,original.properties.text);assert.equal(element.properties.color,'#abcdef');
assert.equal(counts.dirty,1);
''')

    def test_page_overflow_or_pending_font_never_persists_partial_text(self) -> None:
        self.run_javascript(r'''
const before=JSON.stringify(uploadedSealEditorState);
startUploadedEditorTextEdit({x:120,y:600});typeText('a\n'.repeat(99)+'a');
node('#uploadedEditorInlineFontSize').value='14';
assert.equal(finishUploadedEditorTextEdit(),false,'100 lines cannot fit on an A4 page');
assert.ok(uploadedSealEditorRuntime.textEdit);assert.equal(JSON.stringify(uploadedSealEditorState),before);
typeText('Text must wait for matching font metrics');textFontReady=false;
assert.equal(finishUploadedEditorTextEdit(),false);
assert.ok(uploadedSealEditorRuntime.textEdit);assert.equal(JSON.stringify(uploadedSealEditorState),before);
assert.equal(counts.dirty,0);assert.equal(uploadedSealEditorRuntime.undoStack.length,0);
textFontReady=true;typeText('Fits now');
assert.equal(finishUploadedEditorTextEdit(),true);assert.equal(counts.dirty,1);
''')

    def test_render_repositions_editor_without_overwriting_active_typing_or_selection(self) -> None:
        self.run_javascript(r'''
startUploadedEditorTextEdit({x:590,y:5});typeText('Draft survives repaint');
node('#uploadedEditorInlineFontSize').value='22';node('#uploadedEditorInlineColor').value='#aabbcc';
const edit=uploadedSealEditorRuntime.textEdit;
const before=JSON.stringify(uploadedSealEditorState);
renderUploadedEditorTextEdit();renderUploadedEditorTextEdit();
assert.equal(uploadedSealEditorRuntime.textEdit,edit);
assert.equal(node('#uploadedEditorInlineText').value,'Draft survives repaint');
assert.equal(node('#uploadedEditorInlineFontSize').value,'22');assert.equal(node('#uploadedEditorInlineColor').value,'#aabbcc');
assert.equal(document.activeElement,node('#uploadedEditorInlineText'));
const panel=node('#uploadedEditorTextEdit');assert.equal(panel.hidden,false);
assert.ok(parseFloat(panel.style.left)>=0);assert.ok(parseFloat(panel.style.top)>=0);
assert.ok(parseFloat(panel.style.left)+parseFloat(panel.style.width)<=595);
assert.equal(JSON.stringify(uploadedSealEditorState),before);assert.equal(counts.dirty,0);
''')

    def test_render_invalidates_scope_without_writing_stale_input(self) -> None:
        self.run_javascript(r'''
startUploadedEditorTextEdit(null,'existing');typeText('Stale display input');
scopeEpoch++;
const before=JSON.stringify(uploadedSealEditorState);
renderUploadedEditorTextEdit();
assert.equal(uploadedSealEditorRuntime.textEdit,null);assert.equal(node('#uploadedEditorTextEdit').hidden,true);
assert.equal(JSON.stringify(uploadedSealEditorState),before);assert.equal(counts.dirty,0);
''')

    def test_keyboard_enter_commits_once_escape_cancels_and_ime_does_not_submit(self) -> None:
        self.run_javascript(r'''
let prevented=0,stopped=0;
const key=(key,extra={})=>({key,preventDefault(){prevented++;},stopPropagation(){stopped++;},...extra});
startUploadedEditorTextEdit({x:120,y:600});typeText('Chinese IME synthetic text');
for(const extra of [{isComposing:true},{keyCode:229}])handleUploadedEditorTextKeydown(key('Enter',extra));
uploadedSealEditorRuntime.textEdit.composing=true;
handleUploadedEditorTextKeydown(key('Enter'));
assert.equal(counts.dirty,0);assert.equal(prevented,0);assert.equal(stopped,0);
uploadedSealEditorRuntime.textEdit.composing=false;
handleUploadedEditorTextKeydown(key('Enter'));
assert.equal(counts.dirty,1);assert.equal(prevented,1);assert.equal(stopped,1);
assert.equal(document.activeElement,node('#uploadedEditorSvgLayer'));
handleUploadedEditorTextKeydown(key('Enter'));assert.equal(counts.dirty,1);
startUploadedEditorTextEdit({x:130,y:600});typeText('Cancelled via Escape');
handleUploadedEditorTextKeydown(key('Escape'));
assert.equal(uploadedSealEditorRuntime.textEdit,null);assert.equal(counts.dirty,1);
assert.equal(uploadedSealEditorState.elements.length,2);
''')

    def test_shift_enter_keeps_multiline_editor_open_without_intercepting_the_newline(self) -> None:
        self.run_javascript(r'''
let prevented=0,stopped=0;
startUploadedEditorTextEdit({x:120,y:600});typeText('First line');
const edit=uploadedSealEditorRuntime.textEdit;
handleUploadedEditorTextKeydown({key:'Enter',shiftKey:true,preventDefault(){prevented++;},stopPropagation(){stopped++;}});
assert.equal(uploadedSealEditorRuntime.textEdit,edit);
assert.equal(prevented,0);assert.equal(stopped,0);assert.equal(counts.dirty,0);
typeText('First line\nSecond line');
assert.equal(finishUploadedEditorTextEdit(),true);
assert.equal(uploadedSealEditorState.elements[1].properties.text,'First line\nSecond line');
assert.equal(counts.dirty,1);
''')

    def test_reopening_existing_multiline_text_does_not_collapse_lines_or_consume_revision(self) -> None:
        self.run_javascript(r'''
const element=uploadedSealEditorState.elements[0];
element.properties.text='Synthetic first line\nSynthetic second line\n\nSynthetic fourth line';element.height=90;
const before=JSON.stringify(uploadedSealEditorState);
assert.equal(startUploadedEditorTextEdit(null,'existing'),true);
assert.equal(node('#uploadedEditorInlineText').value,element.properties.text);
assert.equal(finishUploadedEditorTextEdit(),true);
assert.equal(JSON.stringify(uploadedSealEditorState),before);
assert.equal(counts.dirty,0);assert.equal(uploadedSealEditorRuntime.undoStack.length,0);
''')

    def test_inline_controls_are_labelled_and_transient_fields_are_not_revision_payload(self) -> None:
        panel = html_element(self.html, "uploadedEditorTextEdit")
        self.assertRegex(panel.split(">", 1)[0], r"\bhidden(?:\s|=|$)")
        self.assertIn('role="group"', panel)
        for element_id in (
            "uploadedEditorInlineText", "uploadedEditorInlineFontSize", "uploadedEditorInlineColor",
            "uploadedEditorInlineDone", "uploadedEditorInlineCancel",
        ):
            opening = re.search(rf'<(?:input|textarea|button)\b[^>]*\bid="{element_id}"[^>]*>', panel)
            self.assertIsNotNone(opening, element_id)
            self.assertIn("aria-label=", opening.group(0), element_id)
        self.assertRegex(panel, r'<textarea\b[^>]*\bid="uploadedEditorInlineText"')
        for function_name in ("editorDraftPayload", "calculateUploadedEditorManifest"):
            source = javascript_function(self.js, function_name)
            self.assertNotIn("textEdit", source)
            self.assertNotIn("uploadedEditorInline", source)

    def test_page_switch_finishes_once_on_original_page_and_does_not_interrupt_ime(self) -> None:
        self.run_javascript(r'''
startUploadedEditorTextEdit({x:120,y:600});typeText('Belongs to original page');
uploadedSealEditorRuntime.textEdit.composing=true;
setUploadedSealPage('p2');
assert.equal(uploadedSealEditorRuntime.currentPageId,'p1');assert.equal(counts.dirty,0);
assert.ok(uploadedSealEditorRuntime.textEdit);
uploadedSealEditorRuntime.textEdit.composing=false;
setUploadedSealPage('p2');
assert.equal(uploadedSealEditorRuntime.currentPageId,'p2');assert.equal(counts.dirty,1);
assert.equal(uploadedSealEditorState.elements[1].pageId,'p1');
assert.equal(uploadedSealEditorState.elements[1].properties.text,'Belongs to original page');
assert.equal(uploadedSealEditorRuntime.textEdit,null);
''')

    def test_enter_starts_text_only_when_the_pdf_canvas_has_keyboard_focus(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for editor keyboard scope tests")
        anchor = self.js.index('const editorVisible = document.querySelector("#electronicSeal")')
        start = self.js.rfind('document.addEventListener("keydown", (event) => {', 0, anchor)
        end = self.js.index('\n});', anchor) + len('\n});')
        self.assertGreaterEqual(start, 0)
        listener = self.js[start:end]
        harness = r'''
const assert=require('node:assert/strict');
let handler,started=0,prevented=0;
const document={querySelector:()=>({classList:{contains:()=>true}}),addEventListener:(_,callback)=>handler=callback};
const uploadedSealEditorRuntime={tool:'text',locked:false,uploading:false,reviewMode:'edited',selectedIds:new Set()};
const startUploadedEditorTextEdit=()=>{started++;};
const event=(id)=>({key:'Enter',target:{id,closest:()=>null},preventDefault(){prevented++;}});
'''
        case = r'''
for(const id of ['uploadedEditorSeamToggleBtn','uploadedEditorUndoBtn','submitUploadedSealBtn','unrelated-button',''])handler(event(id));
assert.equal(started,0,'Text mode must not hijack Enter on buttons or unrelated controls');assert.equal(prevented,0);
handler(event('uploadedEditorSvgLayer'));
assert.equal(started,1);assert.equal(prevented,1);
for(const patch of [{locked:true},{uploading:true},{reviewMode:'original'},{tool:'select'}]){
  Object.assign(uploadedSealEditorRuntime,{locked:false,uploading:false,reviewMode:'edited',tool:'text'},patch);
  handler(event('uploadedEditorSvgLayer'));
}
assert.equal(started,1);
'''
        result = subprocess.run([node, "-e", harness + listener + case], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_internal_tab_and_stale_focusout_callbacks_never_submit_text(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for inline focus transaction tests")
        start = self.js.index('document.querySelector("#uploadedEditorTextEdit")?.addEventListener("focusout",')
        end = self.js.index('\n});', start) + len('\n});')
        listener = self.js[start:end]
        harness = r'''
const assert=require('node:assert/strict');
let handler,commits=0;
const queued=[];
const text={id:'text'},font={id:'font'},color={id:'color'},done={id:'done'},cancel={id:'cancel'},outside={id:'outside'};
const members=new Set([text,font,color,done,cancel]);
const panel={contains:node=>members.has(node),addEventListener:(kind,callback)=>{assert.equal(kind,'focusout');handler=callback;}};
const document={querySelector:()=>panel,activeElement:text};
const uploadedSealEditorRuntime={textEdit:{id:'first'}};
const window={setTimeout(callback,delay){assert.equal(delay,0);queued.push(callback);}};
function finishUploadedEditorTextEdit(){commits++;uploadedSealEditorRuntime.textEdit=null;}
const flush=()=>{while(queued.length)queued.shift()();};
'''
        case = r'''
for(const relatedTarget of members){
  handler({currentTarget:panel,relatedTarget});
  assert.equal(queued.length,0,'Tab between inline controls must not schedule a save');
}
assert.equal(commits,0);
handler({currentTarget:panel,relatedTarget:outside});
assert.equal(queued.length,1);assert.equal(commits,0,'Focus must settle before deciding');
document.activeElement=font;flush();
assert.equal(commits,0,'Returning focus to inline controls keeps draft open');
handler({currentTarget:panel,relatedTarget:null});
const nextEdit={id:'next'};uploadedSealEditorRuntime.textEdit=nextEdit;document.activeElement=outside;
flush();assert.equal(commits,0);assert.equal(uploadedSealEditorRuntime.textEdit,nextEdit,'A previous edit timer cannot commit the next edit');
handler({currentTarget:panel,relatedTarget:outside});flush();
assert.equal(commits,1);assert.equal(uploadedSealEditorRuntime.textEdit,null);
'''
        result = subprocess.run([node, "-e", harness + listener + case], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unfocused_property_fields_refresh_and_normalize_values_without_mutation(self) -> None:
        self.run_javascript(r'''
const input=node('#uploadedEditorPropertyFontSize');
const before=JSON.stringify(uploadedSealEditorState);
for(const [value,expected] of [[14,'14'],[0,'0'],[null,''],[undefined,''],['Synthetic text','Synthetic text']]){
  input.value='Old display';document.activeElement=null;
  setUploadedEditorPropertyValue(input,value,'same-selection');
  assert.equal(input.value,expected);assert.equal(input.dataset.editorSelectionKey,'same-selection');
}
setUploadedEditorPropertyValue(null,14,'missing-control');
assert.equal(JSON.stringify(uploadedSealEditorState),before);assert.equal(counts.dirty,0);
''')

    def test_focused_editable_property_keeps_in_progress_typing_and_caret_on_repaint(self) -> None:
        self.run_javascript(r'''
const input=node('#uploadedEditorPropertyFontSize');
setUploadedEditorPropertyValue(input,14,'same-selection');
input.value='20.';input.selectionStart=3;input.selectionEnd=3;
input.disabled=false;input.readOnly=false;document.activeElement=input;
setUploadedEditorPropertyValue(input,14,'same-selection');
assert.equal(input.value,'20.','PDF repaint must not replace an unfinished numeric entry');
assert.equal(input.selectionStart,3);assert.equal(input.selectionEnd,3);
assert.equal(input.dataset.editorSelectionKey,'same-selection');assert.equal(counts.dirty,0);
document.activeElement=null;setUploadedEditorPropertyValue(input,20,'same-selection');
assert.equal(input.value,'20','The committed canonical value refreshes after blur');
''')

    def test_selection_session_document_and_page_changes_refresh_even_focused_properties(self) -> None:
        self.run_javascript(r'''
const input=node('#uploadedEditorPropertyText');
const key=(scope,documentId,id,pageId,epoch=1)=>JSON.stringify([{scope,epoch,documentId},[[id,pageId]]]);
const originalKey=key('session-A','document-A','object-A','page-A');
for(const nextKey of [
  key('session-B','document-A','object-A','page-A'),
  key('session-A','document-B','object-A','page-A'),
  key('session-A','document-A','object-B','page-A'),
  key('session-A','document-A','object-A','page-B'),
  key('session-A','document-A','object-A','page-A',2),
]){
  input.dataset.editorSelectionKey=originalKey;input.value='Uncommitted old-scope text';
  input.disabled=false;input.readOnly=false;document.activeElement=input;
  setUploadedEditorPropertyValue(input,'New-scope canonical text',nextKey);
  assert.equal(input.value,'New-scope canonical text');assert.equal(input.dataset.editorSelectionKey,nextKey);
}
assert.equal(counts.dirty,0);
''')
        renderer = javascript_function(self.js, "renderUploadedEditorProperties")
        self.assertIn("JSON.stringify([uploadedSealApplicationScopeSnapshot(), selected.map((item) => [item.id, item.pageId])])", renderer)
        self.assertIn("setUploadedEditorPropertyValue(input, selected.length === 1 ? value : \"\", selectionKey)", renderer)

    def test_locked_or_readonly_property_never_keeps_stale_unsaved_value(self) -> None:
        self.run_javascript(r'''
const input=node('#uploadedEditorPropertyWidth');
for(const [disabled,readOnly] of [[true,false],[false,true],[true,true]]){
  input.value='Unsaved size';input.dataset.editorSelectionKey='same-selection';
  Object.assign(input,{disabled,readOnly});document.activeElement=input;
  setUploadedEditorPropertyValue(input,56.693,'same-selection');
  assert.equal(input.value,'56.693','Locking a field must restore the canonical permitted value');
  assert.equal(input.dataset.editorSelectionKey,'same-selection');
}
assert.equal(counts.dirty,0);assert.equal(uploadedSealEditorRuntime.undoStack.length,0);
''')

    def test_late_font_completion_cannot_restore_editing_overlays_in_readonly_versions(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for asynchronous font redraw isolation")
        functions = "\n".join(javascript_function(self.js, name) for name in (
            "ensureUploadedEditorTextFont", "renderUploadedEditorSvgLayer",
        ))
        harness = r'''
const assert=require('node:assert/strict');
let releaseFont,visualCalls=0,loads=0;
const svg={children:[],attributes:{},replaceChildren(){this.children=[];},append(child){this.children.push(child);},setAttribute(key,value){this.attributes[key]=value;}};
const page={pageId:'p1',widthPt:595,heightPt:842};
const document={
  querySelector:()=>svg,
  fonts:{check:()=>false,load(){loads++;return new Promise(resolve=>releaseFont=resolve);}},
};
const uploadedSealEditorRuntime={reviewMode:'edited',currentViewport:{width:595,height:842},selectedIds:new Set(),guides:[],textFontPromise:null};
const uploadedSealEditorState={pages:[page],elements:[{id:'synthetic-text',pageId:'p1',kind:'text',x:20,y:30,width:100,height:24,opacity:1,rotation:0,properties:{text:'Synthetic overlay'}}]};
const currentUploadedEditorPage=()=>page;
const renderUploadedEditorTextEdit=()=>{};
const uploadedEditorViewportRect=()=>({left:20,top:30,width:100,height:24});
const compareEditorElementsForLayer=()=>0;
const svgEditorNode=(name,attributes)=>({name,attributes});
const appendEditorElementVisual=()=>{visualCalls++;};
const showToast=message=>{throw new Error('Unexpected synthetic font callback failure: '+message);};
'''
        case = r'''
const before=JSON.stringify(uploadedSealEditorState);
for(const reviewMode of ['original','prepared','changes']){
  uploadedSealEditorRuntime.reviewMode='edited';svg.children=[{stale:true}];
  assert.equal(ensureUploadedEditorTextFont(),false);
  const pending=uploadedSealEditorRuntime.textFontPromise;
  assert.ok(pending instanceof Promise,'Font callback must have a pending asynchronous load');
  uploadedSealEditorRuntime.reviewMode=reviewMode;
  releaseFont([]);await pending;
  assert.equal(svg.children.length,0,reviewMode+' must not regain editable overlays');
  assert.equal(visualCalls,0);assert.equal(uploadedSealEditorRuntime.textFontPromise,null);
  assert.equal(JSON.stringify(uploadedSealEditorState),before);
}
assert.equal(loads,3);
uploadedSealEditorRuntime.reviewMode='edited';renderUploadedEditorSvgLayer();
assert.equal(visualCalls,1);assert.equal(svg.children.length,1,'Edited view still renders its overlays');
assert.equal(svg.children[0].attributes['data-editor-element-id'],'synthetic-text');
'''
        result = subprocess.run(
            [node, "-e", harness + functions + "\n(async()=>{\n" + case + "\n})().catch(error=>{console.error(error);process.exitCode=1;});"],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
