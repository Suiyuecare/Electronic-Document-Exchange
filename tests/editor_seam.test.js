const test = require('node:test');
const assert = require('node:assert/strict');
const seam = require('../editor-seam.js');
function state(rotations = [0, 0, 0]) {
  return {pages: rotations.map((rotation, i) => ({pageId: `p${i}`, widthPt: 595, heightPt: 842, rotation})), elements: [0, 1].flatMap((group) => [0, 1].map((part) => ({id:`g${group}-${part}`, kind:'seal',pageId:`p${group+part}`,x:0,y:0,width:84,height:84,opacity:1,rotation:0,properties:{seamGroupId:`g${group}`,seamPartIndex:part}})))};
}
test('batch placement staggers deterministically without changing physical size', () => {
  const available = 758;
  for (const count of [2, 20, 299]) {
    const tops = Array.from({length: count}, (_, i) => seam.initialTopMm(available, i, count));
    assert.equal(new Set(tops).size, count);
    assert.ok(tops[0] > 0 && tops.at(-1) * seam.ptPerMm < available);
    assert.deepEqual(tops, Array.from({length: count}, (_, i) => seam.initialTopMm(available, i, count)));
  }
  assert.equal(seam.initialTopMm(available, 0, 1), available / 2 / seam.ptPerMm);
});
test('groups position independently and invalidated reorder pairs are removed', () => {
  const value = state(); seam.position(value,'g0',40); seam.position(value,'g1',80);
  const other = JSON.stringify(value.elements.slice(2));
  const before = structuredClone(value); value.elements[1].y -= 20; seam.reconcile(value,before);
  assert.equal(value.elements[0].y, value.elements[1].y);
  assert.equal(JSON.stringify(value.elements.slice(2)),other);
  value.pages.reverse(); assert.equal(seam.invalidatedGroups(value).length,2);
  seam.reconcile(value,structuredClone(value));
  assert.equal(value.elements.length,0);
});
test('all page rotations retain visible top and edge geometry', () => {
  for (const rotation of [0,90,180,270]) {
    const value=state([rotation,(rotation+90)%360,0]); seam.position(value,'g0',40);
    for (const item of value.elements.slice(0,2)) {
      const page = value.pages.find(p=>p.pageId===item.pageId);
      assert.ok(Math.abs(seam.topPt(page,item)-40*seam.ptPerMm)<.001);
    }
    const old=structuredClone(value); value.pages[0].rotation=(rotation+90)%360; seam.reconcile(value,old);
    assert.ok(Math.abs(seam.topPt(value.pages[0],value.elements[0])-40*seam.ptPerMm)<.001);
  }
});
test('deleting one half or its page removes only its group', () => {
  const value=state(); seam.position(value,'g0',40); seam.position(value,'g1',80);
  const previous=structuredClone(value); value.elements.shift(); seam.reconcile(value,previous);
  assert.equal(value.elements.length,2); assert.equal(seam.groups(value).has('g0'),false);
  value.pages=value.pages.filter(p=>p.pageId!=='p2'); seam.reconcile(value,previous);
  assert.equal(value.elements.length,0);
});
