// Synthetic DOM/model only. No network, credentials, production cases or PDFs.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function implementation(name) {
  const start = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(start, name);
  const tail = source.slice(start.index + start[0].length);
  const next = /^\n(?:async )?function \w+\(/m.exec(tail);
  return source.slice(start.index, start.index + start[0].length + next.index);
}
function dom() {
  const document = { activeElement: null };
  class Node {
    constructor(tag, value = '') { this.nodeType = tag ? 1 : 3; this.tagName = tag?.toUpperCase(); this.nodeValue = tag ? null : value; this.childNodes = []; this.attrs = new Map(); this.listeners = []; this.scrollTop = 0; this.scrollLeft = 0; this.parentElement = null; }
    get attributes() { return [...this.attrs].map(([name, value]) => ({ name, value })); }
    get dataset() { const self = this; return new Proxy({}, { get: (_, key) => self.getAttribute('data-' + String(key).replace(/[A-Z]/g, c => '-' + c.toLowerCase())), set: (_, key, value) => { self.setAttribute('data-' + String(key).replace(/[A-Z]/g, c => '-' + c.toLowerCase()), value); return true; }, deleteProperty: (_, key) => { self.removeAttribute('data-' + String(key).replace(/[A-Z]/g, c => '-' + c.toLowerCase())); return true; } }); }
    get disabled() { return this.hasAttribute('disabled'); } set disabled(value) { value ? this.setAttribute('disabled', '') : this.removeAttribute('disabled'); }
    get open() { return this.hasAttribute('open'); } set open(value) { value ? this.setAttribute('open', '') : this.removeAttribute('open'); }
    get isConnected() { return this === document.root || !!this.parentElement?.isConnected; }
    get textContent() { return this.nodeType === 3 ? this.nodeValue : this.childNodes.map(n => n.textContent).join(''); }
    set textContent(value) { this.childNodes = []; this.insertBefore(new Node(null, value), null); }
    set innerHTML(html) { this.childNodes = []; const stack = [this]; for (const token of html.match(/<[^>]+>|[^<]+/g) || []) { if (token.startsWith('</')) { stack.pop(); continue; } if (token.startsWith('<')) { const node = new Node(/^<(\w+)/.exec(token)[1]); const attrs = token.slice(token.indexOf(' ') + 1, -1); if (token.includes(' ')) for (const match of attrs.matchAll(/([\w-]+)(?:="([^"]*)")?/g)) node.setAttribute(match[1], match[2] || ''); stack.at(-1).insertBefore(node, null); if (!/\/>$/.test(token) && !['INPUT','BR'].includes(node.tagName)) stack.push(node); } else stack.at(-1).insertBefore(new Node(null, token), null); } }
    get innerHTML() { return this.childNodes.map(n => n.nodeType === 3 ? n.nodeValue : `<${n.tagName.toLowerCase()}${n.attributes.map(a => ` ${a.name}="${a.value}"`).join('')}>${n.innerHTML}</${n.tagName.toLowerCase()}>`).join(''); }
    setAttribute(name, value) { this.attrs.set(name, String(value)); } getAttribute(name) { return this.attrs.get(name) ?? null; } hasAttribute(name) { return this.attrs.has(name); } removeAttribute(name) { this.attrs.delete(name); }
    contains(node) { return node === this || this.childNodes.some(child => child.contains(node)); }
    insertBefore(node, before) { if (node.parentElement) { if (node.contains(document.activeElement)) document.activeElement = null; node.parentElement.childNodes.splice(node.parentElement.childNodes.indexOf(node), 1); } const index = before ? this.childNodes.indexOf(before) : this.childNodes.length; this.childNodes.splice(index, 0, node); node.parentElement = this; }
    remove() { if (this.contains(document.activeElement)) document.activeElement = null; this.parentElement?.childNodes.splice(this.parentElement.childNodes.indexOf(this), 1); this.parentElement = null; }
    cloneNode(deep) { const copy = new Node(this.tagName, this.nodeValue); for (const a of this.attributes) copy.setAttribute(a.name, a.value); if (deep) for (const child of this.childNodes) copy.insertBefore(child.cloneNode(true), null); return copy; }
    matches(selector) { const attr = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(selector); return attr ? this.hasAttribute(attr[1]) && (attr[2] === undefined || this.getAttribute(attr[1]) === attr[2]) : selector.startsWith('#') ? this.getAttribute('id') === selector.slice(1) : this.tagName === selector.toUpperCase(); }
    querySelectorAll(selector) { return this.childNodes.flatMap(node => [...(node.nodeType === 1 && node.matches(selector) ? [node] : []), ...node.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    focus() { document.activeElement = this; }
    addEventListener(event, handler) { if (event === 'click') this.listeners.push(handler); }
    click() { if (!this.disabled) return Promise.all(this.listeners.map(handler => handler({ currentTarget: this }))); }
  }
  document.root = new Node('main');
  document.querySelector = selector => document.root.querySelector(selector);
  document.querySelectorAll = selector => document.root.querySelectorAll(selector);
  document.createElement = tag => { const node = new Node(tag); if (tag === 'template') node.content = node; return node; };
  return { document, Node };
}
function harness() {
  const { document, Node } = dom();
  document.root.innerHTML = '<section id="electronicSealWorkQueueList"></section><span id="electronicSealWorkQueueCount"></span><div id="electronicSealPagination"></div>';
  let finish, downloadCalls = 0, loadCalls = 0;
  const context = { document, officialWorkflowItems: [{ id: 'UX-A', title: 'Synthetic case', source_type: 'uploaded_pdf', current_status: 'stamped', can_download: true, stamped_file_id: 'UX-FINAL' }], officialWorkflowPage: { hasMore: true, loading: false, query: { scope: 'all' } }, ensureElectronicSealWorkQueue() {}, officialDocumentPriority: () => 0, officialDocumentHasEditorV2: () => false, escapeHtml: String, officialStatusLabel: String, officialDocumentCanConfirm: () => false, officialDocumentIsApplicant: () => false, downloadElectronicSealFinalFile: () => { downloadCalls++; return new Promise(resolve => { finish = resolve; }); }, loadOfficialWorkflow: () => { loadCalls++; } };
  vm.createContext(context);
  vm.runInContext(['renderStableWorkflowMarkup', 'bindWorkflowActionOnce', 'renderOfficialWorkflowPagination', 'electronicSealWorkflowItems', 'renderElectronicSealWorkQueue'].map(implementation).join('\n'), context);
  return { context, document, Node, finish: () => finish(true), downloadCalls: () => downloadCalls, loadCalls: () => loadCalls };
}
test('shipping queue refresh preserves unchanged action identity, focus and one listener', () => {
  const h = harness(); h.context.renderElectronicSealWorkQueue();
  const button = h.document.querySelector('[data-electronic-seal-download]'); button.focus();
  for (let i = 0; i < 5; i++) h.context.renderElectronicSealWorkQueue();
  assert.equal(h.document.querySelector('[data-electronic-seal-download]'), button);
  assert.equal(h.document.activeElement, button); assert.equal(button.listeners.length, 1);
});
test('changing a row status keeps its focused busy action and releases it exactly once', async () => {
  const h = harness(); h.context.renderElectronicSealWorkQueue();
  const button = h.document.querySelector('[data-electronic-seal-download]');button.focus();
  const pending = button.click();
  h.context.officialWorkflowItems[0].current_step_name = 'Updated'; h.context.renderElectronicSealWorkQueue();
  assert.equal(h.document.activeElement, button); assert.equal(button.disabled, true);assert.equal(button.textContent, '準備下載…');
  button.click();assert.equal(h.downloadCalls(), 1);h.finish();await pending;
  assert.equal(button.disabled, false);assert.equal(button.textContent, '下載用印後檔案');
});
test('keyed row reorder preserves focus and list scroll without retaining revoked downloads', () => {
  const h = harness();h.context.renderElectronicSealWorkQueue();
  const host=h.document.querySelector('#electronicSealWorkQueueList'),button=host.querySelector('[data-electronic-seal-download]');host.scrollTop=150;button.focus();
  h.context.officialWorkflowItems.push({id:'UX-B',source_type:'uploaded_pdf',title:'Another',updated_at:'2099-01-01'});h.context.renderElectronicSealWorkQueue();
  assert.equal(h.document.activeElement,button);assert.equal(host.scrollTop,150);
  h.context.officialWorkflowItems[0].can_download=false;h.context.renderElectronicSealWorkQueue();assert.equal(host.querySelector('[data-electronic-seal-download]'),null);
});
test('expanded evidence remains open when its non-action text changes', () => {
  const h=harness(),host=h.document.createElement('section');h.document.root.insertBefore(host,null);
  h.context.renderStableWorkflowMarkup(host,'<details><summary>Evidence</summary><p>Before</p></details>');const details=host.querySelector('details');details.open=true;
  h.context.renderStableWorkflowMarkup(host,'<details><summary>Evidence</summary><p>After</p></details>');assert.equal(host.querySelector('details'),details);assert.equal(details.open,true);
});
test('pagination loading state reuses its action and blocks duplicate loads', () => {
  const h=harness();h.context.renderOfficialWorkflowPagination();const button=h.document.querySelector('[data-official-load-more]');button.focus();
  h.context.officialWorkflowPage.loading=true;h.context.renderOfficialWorkflowPagination();assert.equal(h.document.querySelector('[data-official-load-more]'),button);assert.equal(button.disabled,true);button.click();assert.equal(h.loadCalls(),0);
  h.context.officialWorkflowPage.loading=false;h.context.renderOfficialWorkflowPagination();assert.equal(h.document.activeElement,button);assert.equal(button.listeners.length,1);button.click();assert.equal(h.loadCalls(),1);
});
