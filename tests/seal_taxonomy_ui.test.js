const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'..','app.js'),'utf8');
function implementation(name){const start=new RegExp(`^(?:async )?function ${name}\\(`,'m').exec(source);assert.ok(start,name);const rest=source.slice(start.index+start[0].length);const end=/^\n(?:async )?function \w+\(/m.exec(rest);return source.slice(start.index,start.index+start[0].length+end.index);}
function harness(){
  const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',dataset:{},disabled:false,hidden:false,required:false,classList:{toggle(){}},setAttribute(){},textContent:''});return nodes.get(id)};
  const c={console,document:{querySelector:node},isCompanySealCustodian:()=>true,
    selectedCompanySealCompanyId:'A',companySealLibrary:[],
    companySealPolicy:null,companySealRefOptions:type=>type==='category'?['establishment_seal','official_seal','general_seal','continuous_seal','bank_seal','other'].map(code=>({code,name:code})):['large_seal','small_seal','single_seal'].map(code=>({code,name:code})),
    decodeCompanySealImageDimensions:async()=>({width:400,height:400}),friendlyBackendErrorMessage:s=>s};
  vm.createContext(c);const constants=source.slice(source.indexOf('const pdfPointsPerMm'),source.indexOf('let officialSealOptions'));
  vm.runInContext(constants+'\n'+['officialSealHasCurrentFile','companySealCategoryLabel','companySealSelectable','companySealSizeType','companySealUsesManualRectangle','validateCompanySealCalibration','calibratedCompanySealMillimeters','companySealFixedGeometry','formatCompanySealMeasurement','companySealMinimumShortEdgePixels','companySealUploadProfile','companySealCalibrationSizeField','companySealCalibrationHeightField','syncCompanySealCalibrationInputs','readCompanySealCalibrationInputs','validateCompanySealImageGeometry','companySealCreationCategories','companySealCategorySizes','companySealReadinessTasks'].map(implementation).join('\n'),c);
  return {c,node};
}
const seal=(category,size='large_seal',owner='company')=>({seal_category:category,seal_size_type:size,owner_kind:owner,is_active:true,selectable:true,current_file:{id:'IMMUTABLE',usable:true,is_current:true,render_width_mm:30,render_height_mm:30}});
test('known owner taxonomy hides foreign primary, bank, unknown and unavailable slots',()=>{
  const {c}=harness();assert.equal(c.companySealSelectable(seal('establishment_seal')),true);assert.equal(c.companySealSelectable(seal('official_seal','large_seal','institution')),true);
  for(const record of [seal('official_seal'),seal('establishment_seal','large_seal','institution'),seal('bank_seal'),seal('other'),seal('general_seal','large_seal','unclassified'),{...seal('general_seal'),selectable:false},{...seal('general_seal'),current_file:null}])assert.equal(c.companySealSelectable(record),false);
});
test('malformed selectable true cannot override an unusable or non-current file or invalid slot pair',()=>{
  const {c}=harness();for(const record of [{...seal('general_seal'),current_file:{id:'FILE',usable:false,is_current:true}},{...seal('general_seal'),current_file:{id:'FILE',usable:true,is_current:false}},{...seal('general_seal'),current_file:null,current_file_id:'LEGACY-ID'},seal('continuous_seal','large_seal'),seal('general_seal','single_seal')])assert.equal(c.companySealSelectable(record),false);
  assert.equal(c.officialSealHasCurrentFile({...seal('general_seal'),current_file:{usable:false}}),false);
  assert.equal(c.officialSealHasCurrentFile({...seal('general_seal'),current_file:{usable:true,is_current:false}}),false);
});
test('new rectangular profiles require explicit calibration and never inherit square defaults',()=>{
  const {c,node}=harness();node('#simpleSealCategorySelect').value='official_seal';c.syncCompanySealCalibrationInputs('simple','large_seal');
  assert.equal(node('#simpleSealRenderSizeMmInput').value,'');assert.equal(node('#simpleSealRenderHeightMmInput').value,'');assert.equal(node('#simpleSealRenderHeightLabel').hidden,false);
  assert.equal(c.readCompanySealCalibrationInputs('simple','large_seal').ok,false);
  node('#simpleSealRenderSizeMmInput').value='20';node('#simpleSealRenderHeightMmInput').value='55';assert.equal(c.readCompanySealCalibrationInputs('simple','large_seal').ok,true);
});
test('continuous is one single slot; taxonomy is explicitly classified before creation',()=>{
  const {c}=harness();assert.equal(c.companySealCreationCategories().length,0);
  c.companySealPolicy={company_id:'A',owner_kind:'institution',classification_required:false};
  assert.deepEqual(Array.from(c.companySealCreationCategories(),s=>s.code),['official_seal','general_seal','continuous_seal']);
  assert.deepEqual(Array.from(c.companySealCategorySizes('continuous_seal'),s=>s.code),['single_seal']);
  assert.deepEqual(Array.from(c.companySealCategorySizes('general_seal'),s=>s.code),['large_seal','small_seal']);
});
test('rectangle validates each pixel axis at 250 DPI and retains source aspect ratio',async()=>{
  const {c}=harness();const profile={seal_category:'official_seal',seal_size_type:'large_seal',dimension_policy_version:'official-seal-v1-calibrated',render_width_mm:20,render_height_mm:55};
  c.decodeCompanySealImageDimensions=async()=>({width:240,height:660});assert.equal((await c.validateCompanySealImageGeometry({},profile)).ok,true);
  c.decodeCompanySealImageDimensions=async()=>({width:190,height:660});assert.equal((await c.validateCompanySealImageGeometry({},profile)).code,'seal_image_resolution_too_low');
  c.decodeCompanySealImageDimensions=async()=>({width:600,height:600});assert.equal((await c.validateCompanySealImageGeometry({},profile)).code,'seal_image_aspect_ratio_invalid');
});
test('legacy square official file keeps physical profile while new rectangular file uses immutable axes',()=>{
  const {c}=harness();const legacy={...seal('official_seal','large_seal','institution'),current_file:{dimension_policy_version:'company-seal-v2-calibrated',render_width_mm:32,render_height_mm:32}};
  assert.equal(c.companySealFixedGeometry(legacy).widthMm,32);assert.equal(c.companySealFixedGeometry(legacy).heightMm,32);
  const rectangle={...legacy,current_file:{dimension_policy_version:'official-seal-v1-calibrated',render_width_mm:20,render_height_mm:55}};
  assert.equal(c.companySealFixedGeometry(rectangle).widthMm,20);assert.equal(c.companySealFixedGeometry(rectangle).heightMm,55);
  assert.equal(c.companySealFixedGeometry({seal_category:'continuous_seal',seal_size_type:'single_seal'}).valid,false);
});
test('same-profile rerender does not overwrite manually entered calibration',()=>{
  const {c,node}=harness();node('#simpleSealCategorySelect').value='continuous_seal';c.syncCompanySealCalibrationInputs('simple','single_seal');node('#simpleSealRenderSizeMmInput').value='52';node('#simpleSealRenderHeightMmInput').value='15';c.syncCompanySealCalibrationInputs('simple','single_seal');assert.equal(node('#simpleSealRenderSizeMmInput').value,'52');assert.equal(node('#simpleSealRenderHeightMmInput').value,'15');
});
test('five-slot report counts each size independently and unusable current is missing',()=>{
  const {c}=harness();c.companySealPolicy={company_id:'A',owner_kind:'company',classification_required:false,required_slots:[['establishment_seal','large_seal'],['establishment_seal','small_seal'],['general_seal','large_seal'],['general_seal','small_seal'],['continuous_seal','single_seal']].map(([category,size_type])=>({category,size_type,label:category+' '+size_type}))};
  c.companySealLibrary=[{...seal('general_seal'),id:'G',seal_name:'Synthetic'}];const rows=c.companySealReadinessTasks();assert.equal(rows.length,5);assert.equal(rows.filter(row=>row.ready).length,1);assert.equal(rows.find(row=>row.code==='continuous_seal').sizeType,'single_seal');
});
