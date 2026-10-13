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

function groupedState(count = 7, edge = 'right', rotations = [0, 90, 180, 270]) {
  const value = {pages: Array.from({length: count}, (_, i) => ({pageId: `p${i}`, widthPt: 595, heightPt: 842, rotation: rotations[i % rotations.length]})), elements: []};
  seam.partitionPages(Array.from({length: count}, (_, i) => i + 1)).forEach((numbers, group) => {
    numbers.forEach((number, part) => value.elements.push({id:`grouped-${group}-${part}`, kind:'seal',pageId:`p${number - 1}`,x:0,y:0,width:84,height:84,opacity:1,rotation:0,
      properties:{seamGroupId:`grouped-${group}`,seamMode:'grouped',seamPartCount:numbers.length,seamPartIndex:part,seamEdge:edge}}));
    seam.position(value, `grouped-${group}`, 40 + group * 20);
  });
  return value;
}

test('batch groups have five contiguous pages, with exact final remainder', () => {
  for (const [count, expected] of [[7,[5,2]], [8,[5,3]], [10,[5,5]], [6,[5,1]], [1,[1]]]) {
    const value = groupedState(count);
    assert.deepEqual([...seam.groups(value).values()].map(members => members.length), expected);
    assert.equal(seam.invalidatedGroups(value).length, 0);
    assert.ok(value.elements.every(item => item.width === 84 && item.height === 84));
  }
  assert.deepEqual(seam.partitionPages([1,2,4,5,6,7,8,9]), [[1,2],[4,5,6,7,8],[9]]);
  assert.deepEqual(seam.partitionPages([1,2,2,3]), [[1,2,3]]);
  assert.deepEqual(seam.partitionPages([1,0]), []);
});

test('grouped seams retain chosen display edge for every page rotation', () => {
  for (const edge of ['left','right','top','bottom']) {
    const value = groupedState(7, edge);
    for (const item of value.elements) {
      const page = value.pages.find(entry => entry.pageId === item.pageId);
      const isSecond = item.properties.seamGroupId === 'grouped-1';
      assert.ok(Math.abs(seam.offsetPt(page,item) - (isSecond ? 60 : 40) * seam.ptPerMm) < .001);
      const actual = ['top','bottom'].includes(edge) ? seam.topPt(page,item) : seam.leftPt(page,item);
      const expected = edge === 'left' || edge === 'top' ? 0 : (edge === 'right' ? seam.displayWidth(page) : seam.displayHeight(page)) - 84;
      assert.ok(Math.abs(actual - expected) < .001, `${edge} / ${page.rotation}`);
    }
    const previous = structuredClone(value);
    value.pages[0].rotation = 90;
    seam.reconcile(value, previous);
    assert.ok(Math.abs(seam.offsetPt(value.pages[0],value.elements[0]) - 40 * seam.ptPerMm) < .001);
  }
});

test('group edits synchronize only their group, including edge changes', () => {
  const value = groupedState(7, 'right', [0]);
  const other = JSON.stringify(value.elements.slice(5));
  const before = structuredClone(value);
  value.elements[2].y -= 20;
  seam.reconcile(value, before);
  assert.equal(new Set(value.elements.slice(0,5).map(item => item.y)).size, 1);
  assert.equal(JSON.stringify(value.elements.slice(5)), other);
  const previousEdge = structuredClone(value);
  assert.equal(seam.position(value, 'grouped-0', 25, 'top'), true);
  seam.reconcile(value,previousEdge);
  assert.ok(value.elements.slice(0,5).every(item => item.properties.seamEdge === 'top'));
  assert.ok(Math.abs(seam.offsetPt(value.pages[0],value.elements[0]) - 25 * seam.ptPerMm) < .001);
  assert.equal(JSON.stringify(value.elements.slice(5)), other);
  assert.equal(seam.position(value, 'grouped-0', 25, 'invalid'), false);
});

test('grouped page mutations remove the complete affected group only', () => {
  for (const mutation of [value => value.elements.splice(2,1), value => value.pages.splice(2,1), value => [value.pages[0], value.pages[1]] = [value.pages[1], value.pages[0]]]) {
    const value = groupedState(); const previous = structuredClone(value);
    mutation(value); seam.reconcile(value, previous);
    assert.deepEqual([...seam.groups(value).keys()], ['grouped-1']);
    assert.equal(value.elements.length, 2);
  }
});

test('preview uses consecutive strips at the chosen edge without shrinking stamp image', () => {
  for (const edge of ['left','right','top','bottom']) {
    const value = groupedState(7, edge, [0]);
    for (const item of value.elements) {
      const part = item.properties.seamPartIndex, count = item.properties.seamPartCount;
      const slice = seam.previewSlice(item, 100, 100);
      assert.equal(slice.image.width,100); assert.equal(slice.image.height,100);
      const horizontal = ['top','bottom'].includes(edge), far = ['right','bottom'].includes(edge);
      const length = 100 / count, target = far ? 100 - length : 0;
      assert.ok(Math.abs((horizontal ? slice.clip.height : slice.clip.width) - length) < 1e-8);
      assert.equal(horizontal ? slice.clip.y : slice.clip.x, target);
      const matrix=slice.image.transform.match(/[-\d.]+/g).map(Number);
      assert.equal(horizontal ? matrix[5] : matrix[4], target - 100 * part / count);
    }
  }
});

test('rectangular original preview keeps native physical axes under all viewport rotations', () => {
  const originalWidth=29.845*72/25.4,originalHeight=30.099*72/25.4;
  for(const rotation of [0,90,180,270]) {
    const width=rotation%180?originalHeight:originalWidth,height=rotation%180?originalWidth:originalHeight;
    for(const edge of ['left','right','top','bottom']) {
      for(let index=0;index<5;index++) {
        const item={properties:{seamMode:'grouped',seamEdge:edge,seamPartCount:5,seamPartIndex:index}};
        const slice=seam.previewSlice(item,width,height,rotation);
        assert.equal(slice.image.width,originalWidth); assert.equal(slice.image.height,originalHeight);
        const [a,b,c,d,e,f]=slice.image.transform.match(/[-\d.]+/g).map(Number);
        assert.equal(a*d-b*c,1); assert.equal(Math.hypot(a,b),1); assert.equal(Math.hypot(c,d),1);
        const corners=[[0,0],[originalWidth,0],[0,originalHeight],[originalWidth,originalHeight]].map(([x,y])=>[a*x+c*y+e,b*x+d*y+f]);
        const actualWidth=Math.max(...corners.map(p=>p[0]))-Math.min(...corners.map(p=>p[0]));
        const actualHeight=Math.max(...corners.map(p=>p[1]))-Math.min(...corners.map(p=>p[1]));
        assert.ok(Math.abs(actualWidth-width)<1e-8); assert.ok(Math.abs(actualHeight-height)<1e-8);
        const horizontal=['top','bottom'].includes(edge);
        assert.ok(Math.abs((horizontal?slice.clip.height:slice.clip.width)-(horizontal?height:width)/5)<1e-8);
      }
    }
  }
});
