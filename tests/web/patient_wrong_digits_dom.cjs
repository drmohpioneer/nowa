// The Telegram form shows the specific wrong-digits message, like the cancel form.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function el(tag = 'div') {
  const attrs = {};
  return {tag, attrs, children: [], hidden: false, disabled: false, textContent: '', events: {}, className: '',
    append(...i) { this.children.push(...i); }, replaceChildren() { this.children = []; },
    setAttribute(k, v) { attrs[k] = v; }, addEventListener(k, f) { this.events[k] = f; },
    remove() {}, focus() { this.focused = true; }, querySelector() { return this.button; }};
}
(async () => {
  const form = el('form'), submit = el('button'), last4 = el('input'), label = el('label');
  form.button = submit; form.action = '/l/fictional/telegram'; form.elements = {form_token: {value: 'a'}, exp: {value: 1}, last4};
  last4.closest = () => ({append: n => label.children.push(n), querySelector: () => null});
  const texts = {telegram_error: 'ERROR', verify_failed: 'Those digits do not match', locked: 'Locked'};
  const nodes = {'patient-telegram-form': form, 'patient-telegram-card': el(), 'linking-texts': {textContent: JSON.stringify(texts)}};
  let notice = 'verify_failed';
  const context = vm.createContext({window: {}, Date, document: {getElementById: id => nodes[id], createElement: el},
    FormData: function () {}, URL, setTimeout() { return 1; }, clearTimeout() {},
    fetch: async () => ({ok: true, redirected: true, url: 'http://x/l/fictional?notice=' + notice + '&action=telegram', json: async () => ({})})});
  vm.runInContext(fs.readFileSync('nowa/web/static/patient-telegram.js', 'utf8'), context);
  const status = form.children[0];
  await form.events.submit({preventDefault() {}});
  assert.equal(status.textContent, texts.verify_failed);
  assert.equal(last4.attrs['aria-invalid'], 'true'); assert(last4.focused);
  assert.equal(label.children[0].textContent, texts.verify_failed);
  notice = 'other';
  await form.events.submit({preventDefault() {}});
  assert.equal(status.textContent, 'ERROR', 'an unknown redirect keeps the generic message');
  console.log('PASS: wrong last-4 on the Telegram form names the digits');
})().catch(e => { console.error(e); process.exitCode = 1; });
