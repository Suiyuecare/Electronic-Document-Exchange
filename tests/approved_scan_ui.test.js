const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const start = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(start, name);
  const rest = source.slice(start.index + start[0].length);
  const end = /^\n(?:async )?function \w+\(/m.exec(rest);
  return source.slice(start.index, start.index + start[0].length + end.index);
}
const digest = 'a'.repeat(64);
const entry = {seal_id:'S',company_id:'C',seal_category:'establishment_seal',seal_size_type:'large_seal',
  png_sha256:digest,pixel_width:213,pixel_height:208,render_width_mm:27.051,render_height_mm:26.416,
  calibration_dpi:200,dimension_policy_version:'original-scan-200dpi-20260914-v1',
  source_pdf_sha256:'95d90878c71f0efd874de4b0e812daebd536ec23435bb3a5ffb0dde9ed604b2e'};
function harness() {
  const context = {hashBlob:async()=>digest,decodeCompanySealImageDimensions:async()=>({width:213,height:208}),
    formatCompanySealMeasurement:n=>Number(n).toFixed(2)};
  vm.createContext(context);
  vm.runInContext(implementation('approvedOriginalSealScan'), context);
  const record = {id:'S',company_id:'C',seal_category:'establishment_seal',seal_size_type:'large_seal',is_active:true,approved_original_scans:[{...entry}]};
  return {context,record,resolve:()=>context.approvedOriginalSealScan({type:'image/png'},[record],'C','establishment_seal','large_seal')};
}
test('the exact approved raster retains its non-square original canvas and 200 DPI', async()=>{
  const {resolve}=harness();const result=await resolve();
  assert.equal(result.widthMm,27.051);assert.equal(result.heightMm,26.416);
  assert.equal(result.profile.dimension_policy_version,entry.dimension_policy_version);
});
test('unapproved bytes, source, company, slot, category, size, inactive or MIME never receive an exception', async()=>{
  for (const mutate of [h=>h.context.hashBlob=async()=>'b'.repeat(64),h=>h.record.approved_original_scans[0].source_pdf_sha256='b'.repeat(64),
    h=>h.record.company_id='OTHER',h=>h.record.approved_original_scans[0].seal_id='OTHER',h=>h.record.seal_category='general_seal',
    h=>h.record.seal_size_type='small_seal',h=>h.record.is_active=false,h=>h.record.approved_original_scans[0].calibration_dpi=199]) {
    const h=harness();mutate(h);assert.equal(await h.resolve(),null);
  }
  const h=harness();assert.equal(await h.context.approvedOriginalSealScan({type:'image/jpeg'},[h.record],'C','establishment_seal','large_seal'),null);
});
test('mismatched pixels or physical dimensions fail closed instead of modifying image scale', async()=>{
  for(const mutate of [h=>h.context.decodeCompanySealImageDimensions=async()=>({width:214,height:208}),h=>h.record.approved_original_scans[0].render_width_mm=26,
    h=>h.record.approved_original_scans[0].render_height_mm=NaN]) {
    const h=harness();mutate(h);await assert.rejects(h.resolve(),/核准尺寸/);
  }
});
