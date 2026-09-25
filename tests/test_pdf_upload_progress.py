"""Check that PDF upload feedback reflects transfer bytes and remains accessible."""
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PdfUploadProgressTest(unittest.TestCase):
    def test_progress_component_reports_transfer_only_as_determinate(self):
        source = (ROOT / "app.js").read_text()
        match = re.search(r"^function setUploadedPdfUploadProgress\([^\n]*\) \{\n.*?^\}", source, re.M | re.S)
        self.assertIsNotNone(match)
        html = (ROOT / "index.html").read_text()
        css = (ROOT / "styles.css").read_text()
        handler = re.search(r"^async function handleUploadedSealPdfChange\([^\n]*\) \{\n.*?^\}", source, re.M | re.S)
        self.assertIsNotNone(handler)
        self.assertIn('id="uploadedPdfUploadProgress"', html)
        self.assertIn('id="uploadedPdfUploadProgressBar" max="100" value="0"', html)
        self.assertIn('.pdf-editor-upload-progress progress:not([value])', css)
        self.assertIn('setUploadedPdfUploadProgress(sending ? "uploading-pending" : "uploading", percent', handler.group())
        upload_transport = re.search(r"^async function performTusUpload\([^\n]*\) \{\n.*?^\}", source, re.M | re.S)
        self.assertIsNotNone(upload_transport)
        self.assertIn('onProgress(Math.min(1, offset / Math.max(1, file.size)), "sending")', upload_transport.group())
        self.assertIn('onProgress(Math.min(1, offset / Math.max(1, file.size)), "confirmed")', upload_transport.group())

        script = r"""
const assert=require('node:assert/strict');
function node(){return {hidden:true,dataset:{},attributes:{},value:0,textContent:'',setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]}}}
const panel=node(),bar=node(),label=node();
const nodes={'#uploadedPdfUploadProgress':panel,'#uploadedPdfUploadProgressBar':bar,'#uploadedPdfUploadProgressLabel':label};
const document={querySelector:s=>nodes[s]||null};
""" + match.group() + r"""
setUploadedPdfUploadProgress('checking',null,'正在檢查 PDF…');
assert.equal(panel.hidden,false);assert.equal(panel.dataset.state,'checking');assert.equal('value' in bar.attributes,false);
setUploadedPdfUploadProgress('uploading',37,'PDF 已傳輸 37%');
assert.equal(bar.value,37);assert.equal(bar.attributes['aria-valuetext'],'37% 已傳輸');assert.equal(label.textContent,'PDF 已傳輸 37%');
setUploadedPdfUploadProgress('uploading-pending',37,'PDF 傳輸中 · 已完成 37%');
assert.equal('value' in bar.attributes,false);assert.equal(panel.dataset.state,'uploading-pending');
setUploadedPdfUploadProgress('finalizing',null,'正在載入編輯頁面…');
assert.equal('value' in bar.attributes,false);assert.equal(panel.dataset.state,'finalizing');
setUploadedPdfUploadProgress('hidden');assert.equal(panel.hidden,true);assert.equal(panel.dataset.state,'hidden');
console.log('determinate upload progress and indeterminate preparation/finalization states passed');
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
