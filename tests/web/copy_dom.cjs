// Exercise the hub's actual inline copy handlers, including unavailable clipboard.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('nowa/web/static/demo.html', 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
async function check(labels, clipboardAvailable) {
  const values = {'demo-mobile': '01000000001', 'demo-password': 'fictional-password'};
  const nodes = Object.fromEntries(Object.entries(values).map(([id, textContent]) => [id, {id, textContent}]));
  const buttons = Object.keys(nodes).map(id => ({dataset: {copy: id}, textContent: labels.copy,
    disabled: false, setAttribute(k, v) {this[k] = v;}, removeAttribute(k) {delete this[k];}}));
  let resolve, calls = [], selected = null;
  const timers = new Map(); let nextTimer = 0;
  const context = vm.createContext({document: {querySelectorAll: () => buttons, getElementById: id => nodes[id],
    createRange: () => ({selectNodeContents(node) {selected = node;}})},
    window: {getSelection: () => ({removeAllRanges() {}, addRange() {}})},
    navigator: clipboardAvailable ? {clipboard: {writeText: value => {calls.push(value); return new Promise(r => {resolve = r;});}}} : {},
    setTimeout: (fn, ms) => {assert.equal(ms, 1500); timers.set(++nextTimer, fn); return nextTimer;},
    clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(source.replace(/\{\{ t\('([^']+)'\)\|tojson \}\}/g, (_, key) => JSON.stringify(labels[key])), context);
  for (const button of buttons) {
    const request = button.onclick();
    if (clipboardAvailable) {
      assert(button.disabled); assert.equal(button['aria-busy'], 'true');
      await button.onclick(); assert.equal(calls.length, buttons.indexOf(button) + 1);
      assert.equal(calls.at(-1), values[button.dataset.copy]);
      resolve(); await request; assert.equal(button.textContent, labels.copied);
    } else {
      await request; assert.equal(selected.id, button.dataset.copy);
      assert.equal(button.textContent, labels.copy_here);
    }
    assert(!button.disabled); assert.equal(button['aria-busy'], undefined);
    timers.get(button.copyTimer)(); assert.equal(button.textContent, labels.copy);
  }
}
(async () => {
  for (const labels of [{copy: 'Copy', copied: 'Copied', copy_here: 'Copy from here'},
    {copy: 'انسخ', copied: 'اتنسخ', copy_here: 'انسخ من هنا'}]) {
    await check(labels, true); await check(labels, false);
  }
  console.log('PASS: both hub credentials copy, pending double-click guard, bilingual success/reset and selection fallback');
})().catch(error => {console.error(error); process.exitCode = 1;});
