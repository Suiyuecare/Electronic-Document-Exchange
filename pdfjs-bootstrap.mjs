if (!window.pdfjsLib?.getDocument && !window.pdfjsLibPromise) {
  const attempts = Number(window.pdfjsLibLoadAttempts || 0);
  if (attempts < 3) {
    window.pdfjsLibLoadAttempts = attempts + 1;
    const retrySuffix = attempts ? `&retry=${attempts}` : "";
    const promise = import(`./vendor/pdfjs/pdf.min.mjs?v=4.2.67${retrySuffix}`).then((library) => {
      library.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.mjs?v=4.2.67";
      window.pdfjsLib = library;
      return library;
    });
    window.pdfjsLibPromise = promise;
    // Preloading has no awaited caller yet. Consume failure and release it so
    // the editor can retry a fresh module URL within the shared attempt budget.
    void promise.catch(() => {
      if (window.pdfjsLibPromise === promise) window.pdfjsLibPromise = null;
    });
  }
}
