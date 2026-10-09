// Exercise shipped login wiring and shared feedback with deferred HTTP responses.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element() {
  const classes = new Set(), events = {};
  return {textContent: '', disabled: false, offsetWidth: 10, events,
    classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)},
    setAttribute(k, v) { this[k] = v; }, removeAttribute(k) { delete this[k]; },
    addEventListener(k, fn) { events[k] = fn; }};
}
async function check(language) {
  const labels = language === 'ar' ? {
    error: 'الطلب ما تمش. جرّب تاني', login_refused: 'رقم الموبايل أو كلمة السر غلط',
    too_many_attempts: 'محاولات كتير. استنى ١٥ دقيقة وجرّب تاني', check_fields: 'راجع: ', telegram: 'تليجرام',
  } : {error: 'The request failed. Try again', login_refused: 'Wrong mobile number or password',
    too_many_attempts: 'Too many attempts. Wait 15 minutes and try again', check_fields: 'Check: ', telegram: 'Telegram'};
  const status = element(), button = element(), form = element(); form.querySelector = () => button;
  let resolve, calls = 0, reduced = false;
  const warnings = [];
  const context = vm.createContext({document: {cookie: '', body: {dataset: {mode: 'login'}},
    getElementById: id => ({login: form, message: status}[id] || null),
    querySelector: () => null,
    documentElement: {lang:language}, querySelectorAll: selector => selector === "[data-counter]" ? [] : Object.entries(labels).map(([key, textContent]) => ({dataset: {key}, textContent}))},
    FormData: function () { return []; }, location: {assign() { throw Error('failure must never navigate'); }},
    fetch: async () => { calls++; return new Promise(r => { resolve = r; }); },
    window: {matchMedia: () => ({matches: reduced})},
    console: {warn: message => warnings.push(message)},
  });
  vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('nowa/web/static/dashboard.js', 'utf8'), context);
  assert.equal(vm.runInContext('t("missing_test_label")', context), '');
  assert.equal(vm.runInContext('t("missing_test_label")', context), '');
  assert.equal(warnings.length, 1, 'warn once per missing key');
  assert(warnings[0].includes('missing_test_label'));
  assert.equal(vm.runInContext('t("another_missing_label")', context), '');
  assert.equal(warnings.length, 2);
  assert.equal(vm.runInContext('t("error")', context), labels.error);
  async function submit(code, data) {
    const request = form.events.submit({preventDefault() {}});
    assert(button.disabled); assert.equal(button['aria-busy'], 'true'); assert(button.classList.contains('is-busy'));
    const count = calls;
    await form.events.submit({preventDefault() {}}); assert.equal(calls, count);
    resolve({ok: false, status: code, json: async () => data}); await request;
    assert(!button.disabled); assert.equal(button['aria-busy'], undefined); assert(!button.classList.contains('is-busy'));
  }
  await submit(401, {ok: false, reason: 'refused'}); assert.equal(status.textContent, labels.login_refused);
  assert(!status.classList.contains('shake'));
  await submit(401, {ok: false, reason: 'refused'}); assert(status.classList.contains('shake'));
  status.events.animationend(); assert(!status.classList.contains('shake'));
  await submit(401, {ok: false, reason: 'refused'}); assert(status.classList.contains('shake'));
  status.events.animationend(); reduced = true;
  await submit(401, {ok: false, reason: 'refused'}); assert(!status.classList.contains('shake'));
  await submit(429, {ok: false, reason: 'refused'}); assert.equal(status.textContent, labels.too_many_attempts);
  await submit(422, {detail: {fields: ['telegram'], reason: 'invalid'}});
  assert.equal(status.textContent, labels.check_fields + labels.telegram);
  await submit(500, {detail: {}}); assert.equal(status.textContent, labels.error);
  await submit(409, {ok: false, reason: 'unknown_server_reason'});
  assert.equal(status.textContent, labels.error, 'unknown real failure still shows the error sentence');
  assert(warnings.at(-1).includes('unknown_server_reason'));
  context.window.resultControl = element(); context.window.status = status;
  const result = await vm.runInContext('window.NowaFeedback.pending(window.resultControl, async () => ({message:"Saved"}), window.status)', context);
  assert.equal(result.message, 'Saved'); assert.equal(status.textContent, 'Saved');
}
(async () => { await check('ar'); await check('en'); console.log('PASS: missing labels are empty and warn once, real errors remain visible, bilingual login errors, double-submit guard, pending cleanup, repeated shakes, reduced motion, FastAPI fields and success outcome'); })().catch(e => { console.error(e); process.exitCode = 1; });
