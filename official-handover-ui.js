/* Company-scoped, server-authorized handover. Never a document approval. */
(function (root) {
  "use strict";
  const labels = { pending_approver: "待簽人員", followup_owner: "案件接任人" };
  const statuses = { pending: "待行政主任確認", approved: "已確認交接", rejected: "不採用" };
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const allowed = (role) => ["總務", "行政部主任", "行政部門主任"].includes(role);

  function create(deps) {
    const document = deps.document || root.document;
    const $ = (id) => document.getElementById(id);
    const state = { scope: "", view: "needs", page: 1, sequence: 0, detailSequence: 0, context: null, modal: null, busy: false, linkedLoading: false, focus: null };
    const current = (scope) => scope === deps.scope() && deps.authenticated()
      && (allowed(deps.role()) || state.modal?.action === "linked_create");
    const kindName = (kind) => labels[kind] || "交接";
    const status = (message) => { $("officialHandoverStatus").textContent = message; };

    function closeModal(force = false) {
      if (state.busy && !force) return;
      $("officialHandoverModal").classList.add("hidden");
      deps.isolate();
      if (!document.querySelector(".modal-backdrop:not(.hidden)")) document.body.classList.remove("modal-open");
      const focus = state.focus;
      state.modal = null; state.focus = null;
      if (focus?.isConnected && !focus.closest("[inert], .hidden, [hidden]")) focus.focus({ preventScroll: true });
    }

    function sync() {
      const authorized = allowed(deps.role()) && deps.authenticated();
      $("officialHandoverOpenBtn").hidden = !authorized;
      if (!authorized || (state.scope && state.scope !== deps.scope())) {
        ++state.sequence; ++state.detailSequence;
        if (!deps.authenticated() || state.scope !== deps.scope() || state.modal?.action !== "linked_create") closeModal(true);
        if (state.modal?.action !== "linked_create") state.context = null;
        $("officialHandoverPanel").hidden = true;
        $("officialHandoverList").replaceChildren();
        $("officialHandoverDetail").replaceChildren();
        $("officialHandoverDetail").hidden = true;
        $("officialHandoverOpenBtn").setAttribute("aria-expanded", "false");
      }
      state.scope = deps.scope();
    }

    async function loadQueue() {
      sync();
      if ($("officialHandoverPanel").hidden) return;
      const scope = deps.scope(), sequence = ++state.sequence;
      const view = state.view, page = state.page;
      $("officialHandoverPanel").setAttribute("aria-busy", "true");
      $("officialHandoverPreviousBtn").disabled = true; $("officialHandoverNextBtn").disabled = true;
      status("正在載入交接案件…");
      try {
        const data = await deps.request(`/official-handovers?view=${view}&page=${page}&page_size=20`);
        if (!current(scope) || sequence !== state.sequence) return;
        $("officialHandoverList").innerHTML = (data.items || []).map((item) => `<article class="address-card"><strong>${escape(item.dispatch_no || "尚未配號")}</strong><span>${escape(item.subject || "未填主旨")}</span><div class="row-actions"><button class="secondary-button" type="button" data-handover-document="${escape(item.id)}">${view === "history" ? "查看紀錄" : "處理交接"}</button></div></article>`).join("");
        status(data.items?.length ? `本頁 ${data.items.length} 件` : "目前沒有這一類交接案件。");
        $("officialHandoverPage").textContent = `第 ${page} 頁`;
        $("officialHandoverPreviousBtn").disabled = page === 1;
        $("officialHandoverNextBtn").disabled = !data.has_more;
      } catch (error) {
        if (!current(scope) || sequence !== state.sequence) return;
        status(`清單未更新：${error.message}。請按重新整理。`);
        $("officialHandoverPreviousBtn").disabled = page === 1;
      } finally {
        if (current(scope) && sequence === state.sequence) $("officialHandoverPanel").removeAttribute("aria-busy");
      }
    }

    function renderContext(data, draft = {}) {
      state.context = data;
      const detail = $("officialHandoverDetail"); detail.hidden = false;
      const requests = data.requests || [];
      const propose = data.can_propose && data.targets?.length && state.view !== "history";
      const pendingTarget = requests.some((item) => item.status === "pending" && item.kind === data.selected_kind && item.former_user_id === data.selected_former_user_id);
      detail.innerHTML = `<h4>${escape(data.document.subject || "未填主旨")}</h4><p>${escape(data.document.dispatch_no || "尚未配號")}</p>
        ${propose ? `<form id="officialHandoverProposalForm" novalidate class="official-decision-form">
          <label>離職人員／責任<select id="officialHandoverTarget">${data.targets.map((target, index) => `<option value="${index}" ${target.kind === data.selected_kind && target.former_user_id === data.selected_former_user_id ? "selected" : ""}>${escape(target.former_name)} · ${kindName(target.kind)}</option>`).join("")}</select></label>
          <label>接任人<select id="officialHandoverSuccessor" aria-describedby="officialHandoverProposalError"><option value="">請選擇接任人</option>${data.candidates.map((person) => `<option value="${escape(person.id)}">${escape(person.name)} · ${escape(person.role)}</option>`).join("")}</select></label>
          <div class="form-actions"><button class="text-button" type="button" id="officialHandoverCandidatePrevious" ${data.candidate_page <= 1 ? "disabled" : ""}>上一批人員</button><button class="text-button" type="button" id="officialHandoverCandidateNext" ${!data.has_more_candidates ? "disabled" : ""}>下一批人員</button></div>
          ${!data.candidates.length ? '<p role="status">這一批沒有可接任人員；可翻頁或在 Finance 補齊同公司的人員與職級。</p>' : ""}
          <label>交接原因<textarea id="officialHandoverReason" rows="3" maxlength="2000" aria-describedby="officialHandoverProposalError" placeholder="請填寫離職交接原因（至少 6 個字）"></textarea></label>
          <p id="officialHandoverProposalError" class="official-decision-error" role="alert" hidden></p>
          ${pendingTarget ? '<p role="status">此責任已有交接提案，等待行政主任處理。</p>' : ""}
          <div class="form-actions"><button class="primary-button" type="submit" ${!data.candidates.length || pendingTarget ? "disabled" : ""}>提出交接</button></div>
        </form>` : ""}
        ${requests.map((request) => `<article class="address-card"><strong>${escape(request.former_name)} → ${escape(request.successor_name)}</strong><span>${kindName(request.kind)} · ${statuses[request.status] || "待查核"}</span><p>提出：${escape(request.proposer_name)}${request.confirmer_name ? ` · 確認：${escape(request.confirmer_name)}` : ""}</p><p>${escape(request.reason)}</p>${request.resolution_reason ? `<p>處理原因：${escape(request.resolution_reason)}</p>` : ""}${request.can_confirm ? `<div class="row-actions"><button class="primary-button" type="button" data-handover-confirm="${escape(request.id)}">確認交接</button><button class="secondary-button" type="button" data-handover-reject="${escape(request.id)}">不採用</button></div>` : ""}</article>`).join("")}
        ${!propose && !requests.length ? '<p role="status">目前沒有可處理的交接；案件或人員可能已異動。</p>' : ""}`;
      if (propose) {
        $("officialHandoverReason").value = draft.reason || "";
        if (data.candidates.some((candidate) => candidate.id === draft.successor)) $("officialHandoverSuccessor").value = draft.successor;
      }
    }

    async function loadContext(id, query = "", draft = {}) {
      const scope = deps.scope(), sequence = ++state.detailSequence;
      state.context = null; $("officialHandoverDetail").hidden = false;
      $("officialHandoverDetail").innerHTML = '<p role="status">正在載入交接資料…</p>';
      try {
        const data = await deps.request(`/official-documents/${encodeURIComponent(id)}/handover-context${query}`);
        if (!current(scope) || sequence !== state.detailSequence) return;
        renderContext(data, draft);
      } catch (error) {
        if (!current(scope) || sequence !== state.detailSequence) return;
        $("officialHandoverDetail").innerHTML = `<p role="alert">交接資料未載入：${escape(error.message)}</p><button class="secondary-button" type="button" data-handover-document="${escape(id)}">重試</button>`;
      }
    }

    function openModal(action, request, payload = null) {
      if (state.busy || !state.context || state.scope !== deps.scope() || !deps.authenticated()
          || (action !== "linked_create" && !allowed(deps.role()))) return;
      state.focus = document.activeElement;
      state.modal = { action, request, payload, scope: deps.scope(), documentId: state.context.document.id };
      const title = action === "linked_create" ? "建立關聯新案" : action === "propose" ? "提出交接確認" : action === "reject" ? "不採用交接" : "確認交接";
      $("officialHandoverModalTitle").textContent = title;
      $("officialHandoverModalSubmit").textContent = title;
      $("officialHandoverModalForm").reset();
      $("officialHandoverRejectReason").disabled = false;
      $("officialHandoverModalSubmit").disabled = false;
      $("officialHandoverRejectLabel").hidden = action !== "reject";
      $("officialHandoverModalError").hidden = true;
      $("officialHandoverAcknowledgementText").textContent = action === "linked_create"
        ? "我確認原案保留，新案須重新選擇檔案並完整送簽。" : "我確認僅交接待辦責任，不代表文件已簽核通過。";
      $("officialHandoverModalSummary").innerHTML = action === "linked_create"
        ? `<strong>${escape(state.context.document.subject)}</strong><p>另立新草稿與字號。附件、章位及簽核結果不會沿用。</p>`
        : `<strong>${escape(state.context.document.subject)}</strong><p>${escape(request.former_name)} → ${escape(request.successor_name)} · ${kindName(request.kind)}</p><p>${escape(request.reason)}</p><p>原申請人、已完成的簽核與文件不會被改寫。</p>`;
      $("officialHandoverModal").classList.remove("hidden"); document.body.classList.add("modal-open"); deps.isolate();
      $("officialHandoverModalCancel").focus();
    }

    function fieldError(id, message, field) {
      const element = $(id); element.hidden = false; element.textContent = message;
      field?.setAttribute("aria-invalid", "true"); field?.focus();
    }

    async function submitModal(event) {
      event.preventDefault();
      const operation = state.modal;
      if (state.busy || !operation || !current(operation.scope)) return;
      const ack = $("officialHandoverAcknowledgement"), reason = $("officialHandoverRejectReason");
      [ack, reason].forEach((element) => element.removeAttribute("aria-invalid"));
      if (!ack.checked) return fieldError("officialHandoverModalError", "請勾選確認事項。", ack);
      if (operation.action === "reject" && reason.value.trim().length < 2) return fieldError("officialHandoverModalError", "請填寫不採用原因（至少 2 個字）。", reason);
      state.busy = true;
      $("officialHandoverModalError").hidden = true;
      $("officialHandoverModalForm").setAttribute("aria-busy", "true");
      $("officialHandoverModal").querySelectorAll("button,input,textarea").forEach((element) => { element.disabled = true; });
      try {
        const path = operation.action === "linked_create" ? `/official-documents/${encodeURIComponent(operation.documentId)}/linked-application`
          : operation.action === "propose" ? `/official-documents/${encodeURIComponent(operation.documentId)}/handovers` : `/official-handovers/${encodeURIComponent(operation.request.id)}/${operation.action}`;
        operation.payload ||= { reason: reason.value.trim() };
        const result = await deps.request(path, { method: "POST", body: JSON.stringify(operation.payload) });
        if (!current(operation.scope)) return;
        state.busy = false; closeModal();
        if (operation.action === "linked_create") {
          deps.toast("新草稿已建立；請重新選擇檔案與用印款式後送簽。");
          try { await deps.openLinkedDraft(result.document_id); }
          catch (error) { deps.toast(`新草稿已建立，但畫面未載入。請至草稿編輯開啟：${error.message}`); }
          return;
        }
        deps.toast(operation.action === "propose" ? "交接已提出，等待行政主任確認。" : operation.action === "confirm" ? "交接完成；文件仍須照流程簽核。" : "已記錄不採用原因。");
        await loadContext(operation.documentId); await loadQueue();
      } catch (error) {
        if (!current(operation.scope)) return;
        // Keep the same operation ID and content for an explicit uncertain retry.
        // A conflict requires closing and refreshing, never automatic replay.
        fieldError("officialHandoverModalError", error.status === 409 ? "案件已異動。請取消並重新整理，再檢查交接內容。" : `未確認完成：${error.message}。請保留此畫面，再按確認會查核同一筆交接。`);
        if (error.status === 409 || error.status === 403) operation.blocked = true;
      } finally {
        state.busy = false;
        $("officialHandoverModalForm").removeAttribute("aria-busy");
        $("officialHandoverModal").querySelectorAll("button,input,textarea").forEach((element) => { element.disabled = false; });
        if (operation.blocked) $("officialHandoverModalSubmit").disabled = true;
        if (operation.action === "reject" && operation.payload) reason.disabled = true;
      }
    }

    $("officialHandoverOpenBtn").addEventListener("click", () => {
      sync(); if ($("officialHandoverOpenBtn").hidden) return;
      $("officialHandoverPanel").hidden = false; $("officialHandoverOpenBtn").setAttribute("aria-expanded", "true"); void loadQueue();
    });
    $("officialHandoverCloseBtn").addEventListener("click", () => { ++state.sequence; ++state.detailSequence; state.context = null; $("officialHandoverPanel").hidden = true; $("officialHandoverOpenBtn").setAttribute("aria-expanded", "false"); $("officialHandoverOpenBtn").focus(); });
    document.querySelectorAll("[data-handover-view]").forEach((button) => button.addEventListener("click", () => {
      state.view = button.dataset.handoverView; state.page = 1; ++state.detailSequence; state.context = null; $("officialHandoverDetail").hidden = true;
      document.querySelectorAll("[data-handover-view]").forEach((item) => item.setAttribute("aria-pressed", String(item === button))); void loadQueue();
    }));
    $("officialHandoverRetryBtn").addEventListener("click", () => { const id = state.context?.document.id; void loadQueue(); if (id) void loadContext(id); });
    $("officialHandoverPreviousBtn").addEventListener("click", () => { if (state.page > 1) { --state.page; void loadQueue(); } });
    $("officialHandoverNextBtn").addEventListener("click", () => { ++state.page; void loadQueue(); });
    $("officialHandoverPanel").addEventListener("click", (event) => {
      const button = event.target.closest("button"); if (!button) return;
      if (button.dataset.handoverDocument) { void loadContext(button.dataset.handoverDocument); return; }
      if (button.id.startsWith("officialHandoverCandidate") && state.context) {
        const page = state.context.candidate_page + (button.id.endsWith("Next") ? 1 : -1);
        const query = new URLSearchParams({ kind: state.context.selected_kind, former_user_id: state.context.selected_former_user_id, page: String(page) });
        void loadContext(state.context.document.id, "?" + query, { reason: $("officialHandoverReason").value }); return;
      }
      const id = button.dataset.handoverConfirm || button.dataset.handoverReject;
      const request = state.context?.requests.find((item) => item.id === id && item.can_confirm);
      if (request) openModal(button.dataset.handoverConfirm ? "confirm" : "reject", request);
    });
    $("officialHandoverDetail").addEventListener("change", (event) => {
      if (event.target.id !== "officialHandoverTarget" || !state.context) return;
      const target = state.context.targets[Number(event.target.value)];
      if (target) void loadContext(state.context.document.id, "?" + new URLSearchParams({ kind: target.kind, former_user_id: target.former_user_id }));
    });
    $("officialHandoverDetail").addEventListener("submit", (event) => {
      if (event.target.id !== "officialHandoverProposalForm") return;
      event.preventDefault(); if (!state.context) return;
      const successor = $("officialHandoverSuccessor"), reason = $("officialHandoverReason");
      [successor, reason].forEach((field) => field.removeAttribute("aria-invalid"));
      const person = state.context.candidates.find((item) => item.id === successor.value);
      if (!person) return fieldError("officialHandoverProposalError", "請選擇接任人。", successor);
      if (reason.value.trim().length < 6) return fieldError("officialHandoverProposalError", "交接原因至少需 6 個字。", reason);
      const target = state.context.targets.find((item) => item.kind === state.context.selected_kind && item.former_user_id === state.context.selected_former_user_id);
      if (!target) return;
      const payload = { operation_id: root.crypto.randomUUID(), kind: target.kind, former_user_id: target.former_user_id, successor_user_id: person.id, reason: reason.value.trim(), expected_fingerprint: state.context.expected_fingerprint };
      openModal("propose", { ...payload, former_name: target.former_name, successor_name: person.name }, payload);
    });
    $("officialHandoverModalForm").addEventListener("submit", (event) => { if (state.modal?.blocked) { event.preventDefault(); return; } void submitModal(event); });
    $("officialHandoverModalCancel").addEventListener("click", () => closeModal());
    $("officialHandoverModal").addEventListener("keydown", (event) => { if (event.key === "Escape") { event.preventDefault(); closeModal(); } else deps.trap(event, $("officialHandoverModal")); });
    async function createLinked(item) {
      if (!item?.can_create_linked_application || !deps.authenticated() || state.busy || state.modal || state.linkedLoading) return;
      const scope = deps.scope();
      state.linkedLoading = true;
      try {
        const seed = await deps.request(`/official-documents/${encodeURIComponent(item.id)}/linked-application`);
        if (scope !== deps.scope() || !deps.authenticated()) return;
        state.scope = scope; state.context = { document: { id: item.id, subject: seed.payload.subject || seed.payload.title } };
        openModal("linked_create", null, { operation_id: crypto.randomUUID(), expected_fingerprint: seed.expected_fingerprint });
      } catch (error) { if (scope === deps.scope()) deps.toast(`新案未建立：${error.message}`); }
      finally { state.linkedLoading = false; }
    }
    return { sync, loadQueue, createLinked };
  }
  root.EdocHandoverUI = { create, allowed };
})(typeof window !== "undefined" ? window : globalThis);
