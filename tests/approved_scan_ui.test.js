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

function native120Harness() {
  const h = harness();
  h.record.approved_original_scans[0] = {...entry,pixel_width:125,pixel_height:124,
    render_width_mm:26.458,render_height_mm:26.247,calibration_dpi:120,
    dimension_policy_version:'native-scan-120dpi-20261013-v1',
    source_pdf_sha256:'4426fcf11ca7cd45ed8d2e942b137c7f5f4ac6efc585ad87078faaadf941487c'};
  h.context.decodeCompanySealImageDimensions = async()=>({width:125,height:124});
  return h;
}
test('approved native120 accepts only its three-decimal original dimensions without square squeezing', async()=>{
  const h=native120Harness(); const result=await h.resolve();
  assert.equal(result.widthMm,26.458);assert.equal(result.heightMm,26.247);
  assert.match(result.message,/120 DPI/);
  assert.equal(result.profile.dimension_policy_version,'native-scan-120dpi-20261013-v1');
  vm.runInContext(source.slice(source.indexOf('const pdfPointsPerMm'),source.indexOf('let officialSealOptions')),h.context);
  vm.runInContext(implementation('companySealSizeType'),h.context);
  vm.runInContext(implementation('companySealUsesManualRectangle'),h.context);
  assert.equal(h.context.companySealUsesManualRectangle(result.profile),true);
});
test('native120 source or policy mixing cannot borrow old200 authorization or widen rounding', async()=>{
  for(const mutate of [h=>h.record.approved_original_scans[0].source_pdf_sha256=entry.source_pdf_sha256,
    h=>h.record.approved_original_scans[0].calibration_dpi=200,
    h=>h.record.approved_original_scans[0].dimension_policy_version='native-scan-120dpi-invented',
    h=>h.record.company_id='CO-008',h=>h.record.seal_category='bank_seal',
    h=>h.context.hashBlob=async()=>'b'.repeat(64)]) {
    const h=native120Harness();mutate(h);assert.equal(await h.resolve(),null);
  }
  for(const mutate of [h=>h.record.approved_original_scans[0].render_width_mm+=.001,
    h=>h.record.approved_original_scans[0].render_height_mm=h.record.approved_original_scans[0].render_width_mm,
    h=>h.context.decodeCompanySealImageDimensions=async()=>({width:126,height:124})]) {
    const h=native120Harness();mutate(h);await assert.rejects(h.resolve(),/核准尺寸/);
  }
  const old=harness();old.record.approved_original_scans[0].render_width_mm+=.0004;
  await assert.rejects(old.resolve(),/核准尺寸/);
});
