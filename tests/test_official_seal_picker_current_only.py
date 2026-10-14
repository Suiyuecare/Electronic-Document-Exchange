"""Official-document stamp choices must include only usable current files."""
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OfficialSealPickerCurrentOnlyTest(unittest.TestCase):
    def test_missing_seal_files_are_hidden_not_disabled_choices(self):
        source = (ROOT / "app.js").read_text()
        functions = []
        for name in ("companySealSelectable", "renderOfficialSealOptions", "officialSealHasCurrentFile", "selectedOfficialSealOption", "updateOfficialSealCurrentHint"):
            match = re.search(r"^(?:async )?function " + re.escape(name) + r"\([^\n]*\) \{\n.*?^\}", source, re.M | re.S)
            self.assertIsNotNone(match, name)
            functions.append(match.group())
        script = r"""
const assert=require('node:assert/strict');
const select={value:'',innerHTML:'',options:[],set innerHTML(html){this._html=html;this.options=[...html.matchAll(/<option value="([^"]*)"([^>]*)>(.*?)<\/option>/g)].map(m=>({value:m[1],disabled:m[2].includes('disabled'),textContent:m[3]}));this.value=this.options.find(o=>!o.disabled)?.value||''},get innerHTML(){return this._html}};
const hint={};const document={querySelector:s=>s==='#officialSealSelect'?select:s==='#officialSealHint'?hint:null};
const escapeDraftHtml=s=>String(s);const ready={id:'available',seal_name:'可用大章',owner_kind:'company',selectable:true,is_active:true,seal_category:'general_seal',seal_size_type:'large_seal',current_file:{id:'file-1',usable:true,is_current:true}};
let officialSealOptions=[ready,{id:'missing',seal_name:'尚未上傳的小章'},{...ready,id:'unclassified',owner_kind:'unclassified'},{...ready,id:'bank',seal_category:'bank_seal'},{...ready,id:'unusable',current_file:{id:'broken',usable:false,is_current:true}},{...ready,id:'old',current_file:{id:'old',usable:true,is_current:false}}];
const setOfficialFieldValidity=(...args)=>{hint.args=args};const lockOfficialStampPositionSizesToSelectedSeal=()=>{};
""" + "\n".join(functions) + r"""
renderOfficialSealOptions();
assert.deepEqual(select.options.map(x=>x.value),['available']);assert.equal(select.options[0].disabled,false);assert.equal(select.value,'available');
officialSealOptions=[{id:'missing',seal_name:'尚未上傳'}];renderOfficialSealOptions();
assert.deepEqual(select.options.map(x=>x.value),['']);assert.match(select.options[0].textContent,/尚未設定可用印章/);
console.log('official seal picker hides missing files');
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
