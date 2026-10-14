"""Compose stamp options follow only the selected company's current seals."""
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ComposeSealAvailabilityTest(unittest.TestCase):
    def test_large_and_small_choices_are_filtered_by_company_size_and_current_file(self):
        source = (ROOT / "app.js").read_text()
        functions = []
        for name in ("companySealSelectable", "companySealCatalogUnavailableReason", "composeSealOptionsForSelectedCompany", "composeSealOptionsAreLoadingForSelectedCompany", "composeSealTypeLabel", "renderComposeSealTypeOptions", "loadComposeSealOptions", "officialSealHasCurrentFile"):
            match = re.search(r"^(?:async )?function " + re.escape(name) + r"\([^\n]*\) \{\n.*?^\}", source, re.M | re.S)
            self.assertIsNotNone(match, name)
            functions.append(match.group())
        html = (ROOT / "index.html").read_text()
        self.assertIn('id="composeSealAvailabilityNotice"', html)
        self.assertIn('id="composeSealRetryBtn"', html)
        large_select = re.search(r'<select id="largeSealType">(.*?)</select>', html, re.S).group(1)
        small_select = re.search(r'<select id="smallSealType">(.*?)</select>', html, re.S).group(1)
        self.assertNotIn("一般章", large_select)
        self.assertNotIn("公司設立章", small_select)
        script = r"""
const assert=require('node:assert/strict');
function node(value=''){return {value,dataset:{},disabled:false,hidden:false,options:[],textContent:'',set innerHTML(html){this.options=[...html.matchAll(/<option value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(m=>({value:m[1],textContent:m[2]}));if(!this.options.some(o=>o.value===this.value))this.value=this.options[0]?.value||''},get innerHTML(){return ''}}}
const nodes={'#composeCompanySelect':node('A'),'#composeOutputMode':node('physical'),'#largeSealType':node('一般章'),'#smallSealType':node('無'),'#continuousSealType':node('無'),'#composeContinuousSealField':node(),'#composeSealAvailabilityNotice':node(),'#composeSealAvailabilityHint':node(),'#composeSealRetryBtn':node()};
const document={querySelector:s=>nodes[s]||null};
let composeSealOptionsCompanyId='A',composeSealOptionsRequestNo=0,composeSealOptionsLoading=false,composeSealOptionsError=false;
const authState={token:'synthetic-session'};
let composeSealCatalogState={scope:'test-scope',token:authState.token,status:'ready',request:null};
const ready=(row)=>({company_id:'A',owner_kind:'company',selectable:true,is_active:true,current_file:{id:'FILE-'+row.id,usable:true,is_current:true},...row});
let composeSealOptions=[ready({id:'BANK-S',seal_category:'bank_seal',seal_size_type:'small_seal'}),ready({id:'GENERAL-S',seal_category:'general_seal',seal_size_type:'small_seal'}),{id:'EMPTY-GENERAL',owner_kind:'company',selectable:false,company_id:'A',seal_category:'general_seal',seal_size_type:'large_seal',is_active:true},ready({id:'INACTIVE',seal_category:'general_seal',seal_size_type:'large_seal',is_active:false})];
const composeCompanyForOfficialApplication=name=>name==='A'?{id:'A'}:name==='B'?{id:'B'}:null;
const composeOutputMode=()=>nodes['#composeOutputMode'].value;
const escapeDraftHtml=value=>String(value);
const hasAuthenticatedBackendSession=()=>true,frontendSessionScope=()=> 'test-scope';
let sealRows=[];
const backendRequest=async path=>{assert.match(path,/^\/companies\/(A|B)\/seals\?editor=1$/);return sealRows};
"""+"\n".join(functions)+r"""
;(async()=>{
composeSealOptionsCompanyId='';
renderComposeSealTypeOptions();
assert.match(nodes['#composeSealAvailabilityHint'].textContent,/正在載入/);
assert.equal(nodes['#largeSealType'].disabled,true);
composeSealOptionsCompanyId='A';
renderComposeSealTypeOptions();
assert.deepEqual(nodes['#largeSealType'].options.map(x=>x.value),['無']);
assert.equal(nodes['#largeSealType'].disabled,true);
assert.deepEqual(nodes['#smallSealType'].options.map(x=>x.value),['無','一般章']);
assert.deepEqual(nodes['#smallSealType'].options.map(x=>x.textContent),['無','便章']);
assert.equal(nodes['#composeContinuousSealField'].hidden,true);
assert.equal(nodes['#smallSealType'].disabled,false);
assert.equal(nodes['#composeSealAvailabilityNotice'].hidden,true);
nodes['#composeCompanySelect'].value='B';
assert.deepEqual(composeSealOptionsForSelectedCompany(),[]);
composeSealOptionsCompanyId='B';composeSealOptions=[];
renderComposeSealTypeOptions();
assert.deepEqual(nodes['#smallSealType'].options.map(x=>x.value),['無']);
assert.equal(nodes['#composeSealAvailabilityNotice'].hidden,false);
assert.match(nodes['#composeSealAvailabilityHint'].textContent,/尚無已登錄並啟用的章檔/);
console.log('compose seal choices are company-scoped and current-file-only');
nodes['#composeCompanySelect'].value='A';
sealRows=[
 ready({id:'READY-LARGE',seal_category:'general_seal',seal_size_type:'large_seal'}),
 {id:'NO-FILE',seal_category:'official_seal',seal_size_type:'large_seal',is_active:true},
 {id:'INACTIVE-FILE',seal_category:'bank_seal',seal_size_type:'small_seal',current_file_id:'file-2',is_active:false}
];
await loadComposeSealOptions('A',{force:true});
assert.deepEqual(composeSealOptions.map(x=>x.id),['READY-LARGE']);
assert.deepEqual(nodes['#largeSealType'].options.map(x=>x.value),['無','一般章']);
assert.deepEqual(nodes['#smallSealType'].options.map(x=>x.value),['無']);
console.log('company stamp API results exclude missing files and inactive seals');
sealRows=[ready({id:'SINGLE',seal_category:'continuous_seal',seal_size_type:'single_seal'})];
await loadComposeSealOptions('A',{force:true});
assert.deepEqual(nodes['#continuousSealType'].options.map(x=>x.value),['無','連續章']);
assert.equal(nodes['#composeContinuousSealField'].hidden,false);
assert.equal(nodes['#continuousSealType'].value,'無');
assert.deepEqual(nodes['#largeSealType'].options.map(x=>x.value),['無']);
assert.deepEqual(nodes['#smallSealType'].options.map(x=>x.value),['無']);
nodes['#composeOutputMode'].value='electronic';renderComposeSealTypeOptions();
assert.equal(nodes['#composeContinuousSealField'].hidden,true);assert.equal(nodes['#continuousSealType'].disabled,true);
})().catch(error=>{console.error(error);process.exit(1)});
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
