/* Read-only QA instrumentation. Never changes a render result or product state. */
(function (root) {
  "use strict";
  function samePdfIdentity(start, current) {
    return !!start && !!current && !!start.pageId && !!start.sha256
      && start.pageId === current.pageId && start.sha256 === current.sha256
      && start.sourcePageIndex === current.sourcePageIndex
      && start.epoch === current.epoch && start.session === current.session;
  }
  function nonblankPixels(data) {
    let white = 0, content = 0;
    for (let index = 0; index < data.length; index += 16) {
      if (data[index + 3] <= 240) continue;
      if (data[index] > 240 && data[index + 1] > 240 && data[index + 2] > 240) white++;
      if (data[index] < 200 && data[index + 1] < 200 && data[index + 2] < 200) content++;
    }
    return { white, content, nonblank: white > 0 && content > 0 };
  }
  function frameIsCurrent(frame) {
    return samePdfIdentity(frame.start, frame.current) && frame.visible
      && frame.currentTask && frame.currentProxy && frame.currentCanvas
      && frame.currentViewport && frame.reviewMode === "edited"
      && frame.width === frame.expectedWidth && frame.height === frame.expectedHeight
      && frame.pixels.nonblank;
  }
  function install(options) {
    const probe = { selectedAt: null, firstFrame: null, paintReturns: [], completedFrames: [], observerErrors: [] };
    const wrapped = new WeakSet();
    const identity = () => {
      const page = options.currentPage();
      const source = options.state().sourceFiles.find((item) => item.assetId === page?.sourceAssetId);
      const scope = options.scope();
      return { pageId: page?.pageId || "", sha256: source?.sha256 || "", sourcePageIndex: page?.sourcePageIndex,
        epoch: scope.epoch, session: scope.scope, documentAssigned: !!scope.documentId, localSource: !!page?.sourceAssetId?.startsWith("LOCAL-") };
    };
    // The session is compared internally, never written to the evidence report.
    const evidenceIdentity = ({ session, ...value }) => value;
    options.input.addEventListener("change", () => { probe.selectedAt = options.now(); }, { capture: true, once: true });
    const originalPaint = options.paint;
    options.setPaint(async (...args) => {
      const proxy = args[0], before = identity();
      if (proxy && !wrapped.has(proxy)) {
        wrapped.add(proxy);
        const originalRender = proxy.render;
        proxy.render = function (renderOptions) {
          const start = identity(), viewport = renderOptions.viewport;
          const task = originalRender.call(this, renderOptions);
          Promise.resolve(task.promise).then(async () => {
            if (probe.selectedAt === null) return;
            const completedAt = options.now();
            await new Promise(options.raf);
            const current = identity(), runtime = options.runtime;
            const canvas = renderOptions.canvasContext.canvas, rect = canvas.getBoundingClientRect();
            const outputScale = Math.min(2, Math.max(1, options.devicePixelRatio || 1));
            const activeViewport = runtime.currentViewport;
            const pixels = nonblankPixels(canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data);
            const frame = { start, current, visible: !canvas.hidden && rect.width > 0 && rect.height > 0,
              currentTask: runtime.renderTask === task,
              currentProxy: options.pageRuntime(options.currentPage()?.pageId)?.proxy === proxy,
              currentCanvas: runtime.canvasPaint?.canvas === canvas && runtime.canvasPaint?.proxy === proxy,
              currentViewport: !!activeViewport && ["width", "height", "scale", "rotation"].every((key) => activeViewport[key] === viewport[key])
                && JSON.stringify(activeViewport.transform) === JSON.stringify(viewport.transform),
              reviewMode: runtime.reviewMode, width: canvas.width, height: canvas.height,
              expectedWidth: Math.floor(viewport.width * outputScale), expectedHeight: Math.floor(viewport.height * outputScale), pixels };
            const accepted = frameIsCurrent(frame);
            const record = { ...frame, start: evidenceIdentity(start), current: evidenceIdentity(current), accepted,
              completedMs: completedAt - probe.selectedAt, frameMs: options.now() - probe.selectedAt };
            probe.completedFrames.push(record);
            if (accepted && probe.firstFrame === null) probe.firstFrame = record;
          }).catch((error) => { probe.observerErrors.push(error?.name || "observer_error"); });
          return task;
        };
      }
      const result = await originalPaint(...args);
      if (probe.selectedAt !== null) probe.paintReturns.push({ result, ms: options.now() - probe.selectedAt,
        before: evidenceIdentity(before), after: evidenceIdentity(identity()) });
      return result;
    });
    return probe;
  }
  const api = { samePdfIdentity, nonblankPixels, frameIsCurrent, install };
  root.EditorCanvasLatencyProbe = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
