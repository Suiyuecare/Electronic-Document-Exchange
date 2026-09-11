/* Explicit, non-destructive A4 conversion consent and visual confirmation. */
async function showEditorA4Dialog({ report = null, file = null, isCurrent = () => true } = {}) {
  if (document.querySelector('#editorA4Dialog')) return false;
  const dialog = document.createElement('dialog');
  dialog.id = 'editorA4Dialog';
  dialog.className = 'editor-a4-dialog';
  dialog.setAttribute('aria-labelledby', 'editorA4Title');
  dialog.innerHTML = `<h2 id="editorA4Title"></h2><p id="editorA4Explanation"></p><div id="editorA4Details"></div>
    <div id="editorA4Preview" hidden><div class="editor-a4-pages"><button type="button" class="secondary-button" data-a4-prev aria-label="上一頁">上一頁</button><span data-a4-page role="status"></span><button type="button" class="secondary-button" data-a4-next aria-label="下一頁">下一頁</button></div><canvas aria-label="轉換後 A4 頁面預覽"></canvas></div>
    <p data-a4-error role="alert"></p><div class="editor-a4-actions"><button type="button" class="secondary-button" data-a4-cancel>取消，保留目前內容</button><button type="button" class="primary-button" data-a4-confirm></button></div>`;
  const title = dialog.querySelector('#editorA4Title');
  const explanation = dialog.querySelector('#editorA4Explanation');
  const confirm = dialog.querySelector('[data-a4-confirm]');
  const errors = dialog.querySelector('[data-a4-error]');
  const previousFocus = document.activeElement;
  let pdf = null, loadingTask = null, renderTask = null, currentPage = 1, generation = 0, closed = false;
  let settle;
  const result = new Promise(resolve => { settle = resolve; });
  const finish = (accepted) => {
    if (closed) return;
    closed = true; generation += 1;
    renderTask?.cancel?.();
    void (pdf?.destroy?.() || loadingTask?.destroy?.());
    dialog.close(); dialog.remove();
    previousFocus?.focus?.();
    settle(accepted && isCurrent());
  };
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); finish(false); });
  dialog.querySelector('[data-a4-cancel]').addEventListener('click', () => finish(false));
  confirm.addEventListener('click', () => finish(true));
  if (report) {
    title.textContent = '這份 PDF 有非 A4 頁面';
    explanation.textContent = '可將內容等比例縮放並置中到 A4，不裁切、不拉伸。原稿另外保留，轉換後會先讓你預覽；大尺寸內容縮小後可能比較難閱讀。';
    confirm.textContent = '等比例轉成 A4';
    const list = document.createElement('ul');
    for (const page of report.invalidPages || []) {
      const item = document.createElement('li');
      item.textContent = `第 ${page.page} 頁：${(page.widthPt * 25.4 / 72).toFixed(1)} × ${(page.heightPt * 25.4 / 72).toFixed(1)} mm`;
      list.append(item);
    }
    dialog.querySelector('#editorA4Details').append(list);
  } else {
    title.textContent = '請確認 A4 轉換結果';
    explanation.textContent = '請檢查每一頁的字體大小、內容與留白。確認後才會採用這份 A4 編輯版；原始 PDF 仍完整保留。';
    confirm.textContent = '確認使用此 A4 版本';
    confirm.disabled = true;
    dialog.querySelector('#editorA4Preview').hidden = false;
  }
  document.body.append(dialog); dialog.showModal();
  dialog.querySelector('[data-a4-cancel]').focus();
  const scopeTimer = window.setInterval(() => { if (!isCurrent()) finish(false); }, 300);
  const render = async () => {
    const token = ++generation;
    confirm.disabled = true;
    try {
      renderTask?.cancel?.();
      const page = await pdf.getPage(currentPage);
      if (closed || token !== generation) return;
      const base = page.getViewport({ scale: 1 });
      const scale = Math.min(1.6, Math.max(250, dialog.clientWidth - 64) / base.width);
      const viewport = page.getViewport({ scale });
      const canvas = dialog.querySelector('canvas');
      canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
      renderTask = page.render({ canvasContext: canvas.getContext('2d'), viewport });
      await renderTask.promise;
      if (closed || token !== generation) return;
      dialog.querySelector('[data-a4-page]').textContent = `第 ${currentPage} / ${pdf.numPages} 頁`;
      dialog.querySelector('[data-a4-prev]').disabled = currentPage === 1;
      dialog.querySelector('[data-a4-next]').disabled = currentPage === pdf.numPages;
      confirm.disabled = false;
    } catch (error) {
      if (closed || error?.name === 'RenderingCancelledException' || token !== generation) return;
      errors.textContent = '轉換版預覽失敗，未採用此版本。請取消後重新開啟案件。';
    }
  };
  if (file) {
    void (async () => {
      try {
        const library = await ensurePdfJsLibrary();
        loadingTask = library.getDocument({ data: new Uint8Array(await file.arrayBuffer()), enableXfa: false, isEvalSupported: false });
        pdf = await loadingTask.promise;
        if (closed) { void pdf.destroy(); return; }
        await render();
      } catch (_error) {
        if (!closed) errors.textContent = '無法顯示轉換版，未採用此版本。請取消後重試。';
      }
    })();
    dialog.querySelector('[data-a4-prev]').addEventListener('click', () => { if (pdf && currentPage > 1) { currentPage -= 1; void render(); } });
    dialog.querySelector('[data-a4-next]').addEventListener('click', () => { if (pdf && currentPage < pdf.numPages) { currentPage += 1; void render(); } });
  }
  try { return await result; }
  finally { window.clearInterval(scopeTimer); }
}
