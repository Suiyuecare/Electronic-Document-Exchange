"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const probe = require("../tools/editor_canvas_latency_probe.js");

function frame() {
  const start = { pageId: "P-1", sha256: "synthetic-sha", sourcePageIndex: 0, epoch: 1, session: "fixture", documentAssigned: false, localSource: true };
  return { start, current: { ...start, documentAssigned: true, localSource: false }, visible: true,
    currentTask: true, currentProxy: true, currentCanvas: true, currentViewport: true, reviewMode: "edited",
    width: 600, height: 800, expectedWidth: 600, expectedHeight: 800, pixels: { nonblank: true } };
}
test("a completed current PDF frame accepts legitimate draft/asset remapping", () => {
  assert.equal(probe.frameIsCurrent(frame()), true);
});
test("previous page, source, session, epoch, and page-index frames never count", () => {
  for (const [key, value] of Object.entries({ pageId: "P-old", sha256: "different", sourcePageIndex: 1, epoch: 2, session: "other" })) {
    const sample = frame(); sample.current[key] = value;
    assert.equal(probe.frameIsCurrent(sample), false, key);
  }
});
test("cancelled/superseded render, wrong proxy, canvas, geometry, or review mode never count", () => {
  for (const [key, value] of Object.entries({ currentTask: false, currentProxy: false, currentCanvas: false, currentViewport: false,
    visible: false, width: 601, height: 801, reviewMode: "original" })) {
    assert.equal(probe.frameIsCurrent({ ...frame(), [key]: value }), false, key);
  }
});
test("transparent, all white, and all black canvases do not count as synthetic PDF paint", () => {
  const pixels = (rgba) => Uint8ClampedArray.from(Array(8).fill(rgba).flat());
  for (const rgba of [[0, 0, 0, 0], [255, 255, 255, 255], [0, 0, 0, 255]]) {
    assert.equal(probe.nonblankPixels(pixels(rgba)).nonblank, false);
  }
  const mixed = pixels([255, 255, 255, 255]); mixed.set([30, 30, 30, 255], 16);
  assert.equal(probe.nonblankPixels(mixed).nonblank, true);
});
test("observer records false paint return without changing it and requires a completed real render + RAF", async () => {
  let onSelection, installed, rendered = false, frames = 0, time = 0;
  const page = { pageId: "P-1", sourceAssetId: "LOCAL-1", sourcePageIndex: 0 };
  const scope = { scope: "fixture", epoch: 1, documentId: "" };
  const viewport = { width: 600, height: 800, scale: 1, rotation: 0, transform: [1, 0, 0, 1, 0, 0] };
  const data = new Uint8ClampedArray(32); data.set([255, 255, 255, 255]); data.set([0, 0, 0, 255], 16);
  const canvas = { width: 600, height: 800, hidden: false, getBoundingClientRect: () => ({ width: 600, height: 800 }),
    getContext: () => ({ getImageData: () => ({ data }) }) };
  let resolve; const task = { promise: new Promise((done) => { resolve = done; }) };
  const proxy = { render: () => { rendered = true; return task; } };
  const runtime = { currentViewport: viewport, reviewMode: "edited", renderTask: null, canvasPaint: { canvas, proxy } };
  let state = { sourceFiles: [{ assetId: "LOCAL-1", sha256: "synthetic-sha" }] };
  const observation = probe.install({ runtime, state: () => state, scope: () => scope, currentPage: () => page, pageRuntime: () => ({ proxy }),
    input: { addEventListener: (event, handler) => { onSelection = handler; } }, now: () => ++time,
    raf: (callback) => { frames++; callback(); }, paint: async () => {
      runtime.renderTask = proxy.render({ viewport, canvasContext: { canvas } });
      scope.documentId = "fixture-document"; page.sourceAssetId = "asset-1";
      // Product replaces the state object after upload; the observer must read
      // the live binding, not retain the pre-selection blank source array.
      state = { sourceFiles: [{ assetId: "asset-1", sha256: "synthetic-sha" }] };
      resolve(); await task.promise; return false;
    }, setPaint: (paint) => { installed = paint; }, devicePixelRatio: 1 });
  onSelection();
  assert.equal(await installed(proxy, viewport, "edited", "LOCAL-1"), false);
  await new Promise(setImmediate);
  assert.equal(rendered, true); assert.equal(frames, 1);
  assert.equal(observation.paintReturns[0].result, false);
  assert.equal(observation.firstFrame.accepted, true);
  assert.equal(observation.firstFrame.start.documentAssigned, false);
  assert.equal(observation.firstFrame.current.documentAssigned, true);
  assert.equal("session" in observation.firstFrame.start, false);
});
