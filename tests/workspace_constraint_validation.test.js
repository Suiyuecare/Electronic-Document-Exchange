const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'app.js'), 'utf8');
const html = fs.readFileSync(require('node:path').join(__dirname, '..', 'index.html'), 'utf8');
const names = ['workspaceControlConstraintMessage', 'setWorkspaceConstraintFeedback', 'workspaceFormControls',
  'renderWorkspaceConstraintSummary', 'focusWorkspaceConstraintControl', 'validateWorkspaceControl',
  'validateWorkspaceForm', 'handleWorkspaceConstraintSubmit', 'refreshWorkspaceConstraintInput', 'resetWorkspaceConstraintSession'];
function implementation(name) {
  const match = source.match(new RegExp(`^function ${name}\\([^\\n]*\\) \\{\\n[\\s\\S]*?^\\}`, 'm'));
  assert.ok(match, name); return match[0];
}
function element() {
  const attributes = new Map();
  return {tagName: 'INPUT', type: 'text', disabled: false, readOnly: false, willValidate: true,
    validity: {valid: true}, parentElement: null, focusCalls: 0,
    matches: () => true, getAttribute: key => attributes.has(key) ? attributes.get(key) : null,
    setAttribute: (key, value) => attributes.set(key, String(value)), removeAttribute: key => attributes.delete(key),
    insertAdjacentElement(position, node) { this.error = node; },
    focus() { this.focusCalls++; }, scrollIntoView() {}, remove() { this.removed = true; }};
}
function harness(fields = [element()]) {
  const form = {tagName: 'FORM', id: 'synthetic', elements: fields, summary: null,
    querySelector() { return this.summary; }, prepend(node) { this.summary = node; }};
  fields.forEach(field => { field.form = form; });
  const context = {document: {createElement: element, querySelector: () => null, querySelectorAll: selector => selector === '.workspace-form-errors' ? form.summary ? [form.summary] : [] : fields}, WeakMap, WeakSet, Set,
    scope: 'synthetic-A', workspaceConstraintSession: '',
    workspaceComposingControls: new WeakSet(), workspaceConstraintFeedback: new WeakMap(), workspaceConstraintErrorSequence: 0};
  context.frontendSessionScope = () => context.scope;
  vm.createContext(context); vm.runInContext(names.map(implementation).join('\n'), context);
  return {context, form, fields};
}
test('all product forms suppress native bubbles without removing constraint metadata', () => {
  const forms = [...html.matchAll(/<form\b[^>]*>/g)];
  assert.ok(forms.length > 40); forms.forEach(match => assert.match(match[0], /\bnovalidate\b/));
  assert.equal(/\.reportValidity\s*\(/.test(source), false);
  assert.match(source, /document\.addEventListener\("submit", handleWorkspaceConstraintSubmit, true\)/);
  assert.match(html, /id="uploadedSealTitle"[^>]*\brequired\b/);
  assert.match(html, /id="internalDispatchDueDaysInput"[^>]*min="1"[^>]*max="365"/);
});
test('required input blocks submit before downstream handlers and preserves entered fields', () => {
  const {context, form, fields} = harness(); fields[0].validity = {valid: false, valueMissing: true};
  fields[0].value = ''; let prevented = 0, stopped = 0;
  context.handleWorkspaceConstraintSubmit({target: form, preventDefault() {prevented++;}, stopImmediatePropagation() {stopped++;}});
  assert.equal(prevented, 1); assert.equal(stopped, 1); assert.equal(fields[0].value, '');
  assert.equal(fields[0].getAttribute('aria-invalid'), 'true'); assert.equal(fields[0].focusCalls, 1);
  assert.match(form.summary.textContent, /尚未送出/);
  assert.equal(fields[0].error.id, fields[0].getAttribute('aria-describedby'));
});
test('correction clears only shared error association and allows exactly one submit', () => {
  const {context, form, fields} = harness(); const field = fields[0];
  field.setAttribute('aria-describedby', 'existing-help'); field.validity = {valid: false, rangeOverflow: true}; field.max = '365';
  assert.equal(context.validateWorkspaceForm(form), false); assert.match(field.error.textContent, /365/);
  field.validity = {valid: true}; context.refreshWorkspaceConstraintInput({target: field});
  assert.equal(field.getAttribute('aria-describedby'), 'existing-help'); assert.equal(field.getAttribute('aria-invalid'), null);
  assert.equal(form.summary.hidden, true);
  let prevented = 0, stopped = 0; context.handleWorkspaceConstraintSubmit({target: form, preventDefault() {prevented++;}, stopImmediatePropagation() {stopped++;}});
  assert.equal(prevented, 1); assert.equal(stopped, 0);
});
test('IME guards submit and feedback until committed input, no partial validation', () => {
  const {context, form, fields} = harness(); const field = fields[0];
  context.workspaceComposingControls.add(field); field.value = '中文尚在組字';
  let stopped = 0; const event = {target: form, preventDefault() {}, stopImmediatePropagation() {stopped++;}};
  context.handleWorkspaceConstraintSubmit(event); assert.equal(stopped, 1); assert.match(form.summary.textContent, /完成文字輸入/);
  context.refreshWorkspaceConstraintInput({target: field, isComposing: true}); assert.equal(field.getAttribute('aria-invalid'), null);
  context.workspaceComposingControls.delete(field); context.handleWorkspaceConstraintSubmit(event); assert.equal(stopped, 1);
});
test('disabled and readonly values are barred as before, numeric and email constraints remain enforced', () => {
  const a = element(), b = element(), c = element(); a.disabled = true; a.validity = {valid: false, valueMissing: true};
  b.readOnly = true; b.validity = {valid: false, valueMissing: true}; c.type = 'email'; c.validity = {valid: false, typeMismatch: true};
  const {context, form} = harness([a, b, c]); assert.equal(context.validateWorkspaceForm(form), false);
  assert.equal(a.getAttribute('aria-invalid'), null); assert.equal(b.getAttribute('aria-invalid'), null); assert.match(c.error.textContent, /電子信箱/);
  c.type = 'number'; c.step = '0.1'; c.validity = {valid: false, stepMismatch: true};
  assert.equal(context.validateWorkspaceControl(c), false); assert.match(c.error.textContent, /0.1/);
});
test('session change resets old IME and owned errors, same-session refresh does not end composition', () => {
  const {context, form, fields} = harness(); const field = fields[0];
  context.resetWorkspaceConstraintSession(); context.workspaceComposingControls.add(field);
  context.resetWorkspaceConstraintSession(); assert.equal(context.workspaceComposingControls.has(field), true);
  context.workspaceComposingControls.delete(field); field.validity = {valid: false, valueMissing: true}; context.validateWorkspaceForm(form);
  context.workspaceComposingControls.add(field); context.scope = 'synthetic-B'; context.resetWorkspaceConstraintSession();
  assert.equal(context.workspaceComposingControls.has(field), false); assert.equal(field.getAttribute('aria-invalid'), null); assert.equal(form.summary.hidden, true);
  assert.match(source, /resetWorkspaceConstraintSession\(\{ force: true \}\)/);
});
