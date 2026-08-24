window.pdfjsLibPromise = import("./vendor/pdfjs/pdf.min.mjs?v=4.2.67").then((library) => {
  window.pdfjsLib = library;
  library.GlobalWorkerOptions.workerSrc = "vendor/pdfjs/pdf.worker.min.mjs?v=4.2.67";
  return library;
});
