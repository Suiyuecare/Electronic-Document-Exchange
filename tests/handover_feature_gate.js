"use strict";
// Execute the real controller with a small deterministic DOM, not source matches.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(id) {
    this.id = id; this.hidden = false; this.disabled = false; this.dataset = {};
    this.attributes = {}; this.events = {}; this.textContent = ""; this.innerHTML = "";
    this.value = ""; this.checked = false; this.isConnected = true;
    const values = new Set(id === "officialHandoverModal" ? ["hidden"] : []);
    this.classList = { add: (...items) => items.forEach((item) => values.add(item)),
      remove: (...items) => items.forEach((item) => values.delete(item)),
      contains: (item) => values.has(item) };
  }
  addEventListener(type, action) { (this.events[type] ||= []).push(action); }
  dispatch(type, target = this, properties = {}) {
    const event = { target, ...properties, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; } };
    for (const action of this.events[type] || []) action(event);
    return event;
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  replaceChildren() { this.innerHTML = ""; }
  querySelectorAll() { return []; }
  closest(selector) { return selector === "button" ? this : null; }
  focus() {}
  reset() {}
}

function fixture({ gate, withGate = true, role = "總務", authenticated = true } = {}) {
  const elements = new Map();
  const document = {
    getElementById(id) { if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id); },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    body: new Element("body"), activeElement: null,
  };
  const context = { document, URLSearchParams, crypto: { randomUUID: () => "isolated-operation" } };
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "official-handover-ui.js"), "utf8"), context);
  const state = { gate, role, authenticated, scope: "isolated-company-tenant", requests: [], mutations: [] };
  const deps = { document, role: () => state.role, authenticated: () => state.authenticated,
    scope: () => state.scope, isolate() {}, trap() {}, toast() {}, openLinkedDraft() {},
    async request(url, options) {
      state.requests.push(url);
      if (options?.method === "POST") state.mutations.push({ url, body: options.body });
      if (state.response) return state.response(url, options);
      return url.endsWith("/linked-application")
        ? { payload: { subject: "Synthetic case" }, expected_fingerprint: "fixture" }
        : { items: [], has_more: false };
    } };
  if (withGate) deps.enabled = () => state.gate;
  return { document, state, controller: context.EdocHandoverUI.create(deps) };
}

async function run() {
  const flush = async () => { for (let turn = 0; turn < 8; turn++) await Promise.resolve(); };
  let assertions = 0;
  for (const mode of [{ withGate: false }, { gate: false }, { gate: "1" }, { gate: 1 }]) {
    const f = fixture(mode); f.controller.sync();
    assert.equal(f.document.getElementById("officialHandoverOpenBtn").hidden, true); assertions++;
    f.document.getElementById("officialHandoverOpenBtn").dispatch("click");
    await f.controller.loadQueue();
    await f.controller.createLinked({ id: "CASE", can_create_linked_application: true });
    const forged = new Element("forged"); forged.dataset.handoverDocument = "CASE";
    f.document.getElementById("officialHandoverPanel").dispatch("click", forged);
    await Promise.resolve();
    assert.equal(f.state.requests.length, 0); assertions++;
    assert.equal(f.document.getElementById("officialHandoverPanel").hidden, true); assertions++;
  }
  const enabled = fixture({ gate: true }); enabled.controller.sync();
  assert.equal(enabled.document.getElementById("officialHandoverOpenBtn").hidden, false); assertions++;
  enabled.document.getElementById("officialHandoverOpenBtn").dispatch("click");
  await Promise.resolve(); await Promise.resolve();
  assert.equal(enabled.state.requests.length, 1); assertions++;
  const staff = fixture({ gate: true, role: "員工" }); staff.controller.sync();
  assert.equal(staff.document.getElementById("officialHandoverOpenBtn").hidden, true); assertions++;
  const forged = new Element("forged"); forged.dataset.handoverDocument = "CASE";
  staff.document.getElementById("officialHandoverPanel").dispatch("click", forged);
  await Promise.resolve();
  assert.equal(staff.state.requests.length, 0); assertions++;
  await staff.controller.createLinked({ id: "CASE", can_create_linked_application: true });
  assert.equal(staff.document.getElementById("officialHandoverModal").classList.contains("hidden"), false); assertions++;
  staff.state.gate = false; staff.controller.sync();
  assert.equal(staff.document.getElementById("officialHandoverModal").classList.contains("hidden"), true); assertions++;
  assert.equal(staff.document.getElementById("officialHandoverPanel").hidden, true); assertions++;
  const ime = fixture({ gate: true }); ime.controller.sync();
  ime.state.response = async (url) => url.includes("/handover-context") ? {
    document: { id: "CASE", subject: "Synthetic case" },
    targets: [{ kind: "pending_approver", former_user_id: "FORMER", former_name: "Synthetic former" }],
    candidates: [{ id: "SUCCESSOR", name: "Synthetic successor", role: "主管" }],
    selected_kind: "pending_approver", selected_former_user_id: "FORMER",
    expected_fingerprint: "fixture", can_propose: true, candidate_page: 1, requests: []
  } : { items: [], has_more: false };
  ime.document.getElementById("officialHandoverOpenBtn").dispatch("click");
  await flush();
  const caseButton = new Element("case"); caseButton.dataset.handoverDocument = "CASE";
  ime.document.getElementById("officialHandoverPanel").dispatch("click", caseButton);
  await flush();
  const detail = ime.document.getElementById("officialHandoverDetail");
  const proposal = ime.document.getElementById("officialHandoverProposalForm");
  ime.document.getElementById("officialHandoverSuccessor").value = "SUCCESSOR";
  ime.document.getElementById("officialHandoverReason").value = "Synthetic handover reason";
  detail.dispatch("compositionstart");
  assert.equal(detail.dispatch("submit", proposal).defaultPrevented, true); assertions++;
  assert.equal(ime.document.getElementById("officialHandoverModal").classList.contains("hidden"), true); assertions++;
  detail.dispatch("compositionend");
  detail.dispatch("submit", proposal, { isComposing: true });
  assert.equal(ime.document.getElementById("officialHandoverModal").classList.contains("hidden"), true); assertions++;
  detail.dispatch("submit", proposal);
  const modal = ime.document.getElementById("officialHandoverModal");
  assert.equal(modal.classList.contains("hidden"), false); assertions++;
  ime.document.getElementById("officialHandoverAcknowledgement").checked = true;
  const requestCount = ime.state.requests.length;
  modal.dispatch("compositionstart");
  modal.dispatch("keydown", modal, { key: "Escape", isComposing: true });
  assert.equal(modal.classList.contains("hidden"), false); assertions++;
  const modalForm = ime.document.getElementById("officialHandoverModalForm");
  modalForm.dispatch("submit"); await Promise.resolve();
  assert.equal(ime.state.requests.length, requestCount); assertions++;
  modal.dispatch("compositionend");
  modalForm.dispatch("submit", modalForm, { keyCode: 229 }); await Promise.resolve();
  assert.equal(ime.state.requests.length, requestCount); assertions++;
  ime.document.getElementById("officialHandoverModalCancel").dispatch("click");
  assert.equal(ime.state.requests.length, requestCount); assertions++;
  assert.equal(modal.classList.contains("hidden"), true); assertions++;
  assert.equal(ime.document.getElementById("officialHandoverReason").value, "Synthetic handover reason"); assertions++;
  detail.dispatch("submit", proposal);
  ime.document.getElementById("officialHandoverAcknowledgement").checked = true;
  modalForm.dispatch("submit"); modalForm.dispatch("submit"); await flush();
  assert.equal(ime.state.mutations.length, 1); assertions++;
  assert.equal(ime.state.mutations[0].url, "/official-documents/CASE/handovers"); assertions++;
  assert.equal(modal.classList.contains("hidden"), true); assertions++;
  console.log(JSON.stringify({ status: "passed", assertions, scope: "isolated_controller_execution", realBrowserVerified: false }));
}
run().catch((error) => { console.error(error); process.exitCode = 1; });
