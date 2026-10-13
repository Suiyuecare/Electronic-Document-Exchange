/* EDOC single-select presentation. Native values/options remain the business contract. */
(() => {
  'use strict';
  if (!window.TomSelect) return; // Native controls remain usable if the asset fails.
  const records = new Map();
  const nativeValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
  const nativeIndex = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'selectedIndex');
  let queued = false;

  TomSelect.define('edoc_native_contract', function () {
    this.hook('instead', 'updateOriginalInput', function (options = {}) {
      if (this.edocSynchronizing) return;
      const before = nativeValue.get.call(this.input);
      const value = this.items[0] ?? '';
      // Do not reorder native options or replace their dataset with a synthetic option.
      nativeValue.set.call(this.input, value);
      if (this.isSetup && !options.silent && before !== value) this.trigger('change', value);
    });
  });

  function snapshot(select) {
    return JSON.stringify([
      select.value, select.disabled, select.required,
      select.getAttribute('aria-invalid'), select.getAttribute('aria-describedby'),
      Array.from(select.options, option => [option.value, option.text, option.disabled,
        option.parentElement?.tagName === 'OPTGROUP' ? option.parentElement.label : '',
        option.parentElement?.tagName === 'OPTGROUP' && option.parentElement.disabled]),
    ]);
  }

  function position(instance) {
    if (!instance.isOpen) return;
    const rect = instance.control.getBoundingClientRect();
    const viewport = window.visualViewport;
    const leftBound = viewport?.offsetLeft || 0;
    const topBound = viewport?.offsetTop || 0;
    const width = viewport?.width || document.documentElement.clientWidth;
    const height = viewport?.height || window.innerHeight;
    const below = topBound + height - rect.bottom - 12;
    const above = rect.top - topBound - 12;
    const upwards = below < 180 && above > below;
    const maxHeight = Math.max(60, Math.min(300, upwards ? above : below));
    const dropdownWidth = Math.min(rect.width, width - 16);
    Object.assign(instance.dropdown.style, {
      position: 'fixed', width: `${dropdownWidth}px`,
      left: `${Math.max(leftBound + 8, Math.min(rect.left, leftBound + width - dropdownWidth - 8))}px`,
      top: upwards ? 'auto' : `${rect.bottom + 5}px`,
      bottom: upwards ? `${window.innerHeight - rect.top + 5}px` : 'auto',
    });
    instance.dropdown_content.style.maxHeight = `${maxHeight}px`;
  }

  function sync(select, record) {
    const signature = snapshot(select);
    if (signature === record.signature) return;
    const instance = record.instance;
    const value = select.value;
    const query = instance.control_input.value;
    instance.edocSynchronizing = true;
    try {
      instance.clear(true);
      instance.clearOptions(() => false);
      instance.clearOptionGroups();
      const groups = new Set();
      Array.from(select.options).forEach((option, order) => {
        const group = option.parentElement?.tagName === 'OPTGROUP' ? option.parentElement : null;
        if (group && !groups.has(group.label)) {
          groups.add(group.label);
          instance.addOptionGroup(group.label, { label: group.label });
        }
        instance.addOption({ value: option.value, text: option.text,
          disabled: option.disabled || Boolean(group?.disabled),
          optgroup: group?.label, $order: order + 1 });
      });
      instance.setValue(value, true);
      if (select.disabled) { instance.close(); instance.disable(); } else instance.enable();
      instance.isRequired = select.required;
      for (const name of ['aria-invalid', 'aria-describedby']) {
        const attribute = select.getAttribute(name);
        if (attribute !== null) instance.control_input.setAttribute(name, attribute);
        else instance.control_input.removeAttribute(name);
      }
      instance.control_input.setAttribute('aria-required', String(select.required));
      instance.refreshValidityState();
      instance.refreshState();
      if (instance.isOpen) {
        instance.setTextboxValue(query);
        instance.refreshOptions(false);
        position(instance);
      }
      record.signature = snapshot(select);
    } finally { instance.edocSynchronizing = false; }
  }

  function enhance(select) {
    if (records.has(select) || select.multiple || select.size > 1 || select.dataset.nativeSelect !== undefined
      || select.tomselect || !select.getClientRects().length) return;
    const portal = select.closest('[role="dialog"]') || document.body;
    const instance = new TomSelect(select, {
      plugins: ['edoc_native_contract'], create: false, createOnBlur: false,
      selectOnTab: false, maxItems: 1, maxOptions: null, allowEmptyOption: true,
      refreshThrottle: 0,
      closeAfterSelect: true, hideSelected: false, dropdownParent: portal,
      searchField: ['text'], sortField: [{ field: '$order', direction: 'asc' }],
      render: { no_results: () => '<div class="no-results">沒有符合的選項</div>' },
    });
    instance.wrapper.classList.add('edoc-select');
    instance.dropdown.classList.add('edoc-select-dropdown');
    instance.hook('instead', 'positionDropdown', function () { position(this); });
    const record = { instance, signature: '', ownFocus: Object.getOwnPropertyDescriptor(select, 'focus') };
    records.set(select, record);
    // Existing form handlers set values directly, without emitting change events.
    for (const [key, descriptor] of [['value', nativeValue], ['selectedIndex', nativeIndex]]) {
      Object.defineProperty(select, key, { configurable: true,
        get() { return descriptor.get.call(this); },
        set(value) { descriptor.set.call(this, value); schedule(); },
      });
    }
    Object.defineProperty(select, 'focus', { configurable: true, value: () => instance.focus() });
    let composing = false;
    instance.control_input.addEventListener('compositionstart', () => { composing = true; });
    instance.control_input.addEventListener('compositionend', () => { composing = false; });
    instance.control_input.addEventListener('keydown', event => {
      if ((composing || event.isComposing || event.keyCode === 229) && event.key === 'Enter') {
        event.stopImmediatePropagation();
      }
    }, true);
    select.addEventListener('change', schedule);
    sync(select, record);
  }

  function flush() {
    queued = false;
    for (const [select, record] of records) {
      if (!select.isConnected) {
        // Destroy the detached presentation without resurrecting outdated native options.
        record.instance.revertSettings.innerHTML = select.innerHTML;
        record.instance.destroy();
        delete select.value; delete select.selectedIndex; delete select.focus;
        if (record.ownFocus) Object.defineProperty(select, 'focus', record.ownFocus);
        records.delete(select);
      } else {
        if (!record.instance.wrapper.getClientRects().length) record.instance.close();
        sync(select, record);
      }
    }
    document.querySelectorAll('.app-shell select, [role="dialog"] select').forEach(enhance);
  }
  function schedule() {
    if (!queued) { queued = true; requestAnimationFrame(flush); }
  }
  const observer = new MutationObserver(mutations => {
    if (mutations.some(mutation => {
      const target = mutation.target;
      if (target.closest?.('.ts-wrapper, .ts-dropdown')) return false;
      return target.matches?.('select, option, optgroup, .view, .app-shell, [role="dialog"], details')
        || Array.from(mutation.addedNodes).some(node => node.nodeType === 1
          && (node.matches('select') || node.querySelector('select')));
    })) schedule();
  });
  observer.observe(document.body, { subtree: true, childList: true, attributes: true,
    attributeFilter: ['class', 'hidden', 'disabled', 'required', 'selected', 'aria-invalid', 'aria-describedby', 'open'] });
  document.addEventListener('toggle', schedule, true);
  document.addEventListener('reset', () => setTimeout(schedule, 0), true);
  window.visualViewport?.addEventListener('resize', () => records.forEach(record => position(record.instance)));
  window.addEventListener('resize', schedule);
  window.EDOCWorkspaceSelect = Object.freeze({ refresh: schedule });
  schedule();
})();
