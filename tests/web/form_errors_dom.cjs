// A wrong field is marked, named, cleared on edit; hours labels flip; times normalise.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function node(tag, extra = {}) {
  const attrs = {}, classes = new Set(), listeners = {};
  const n = {tag, attrs, listeners, children: [], textContent: '', dataset: {}, value: '', type: 'text',
    classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)},
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute: k => attrs[k] ?? null,
    removeAttribute(k) { delete attrs[k]; }, hasAttribute: k => k in attrs,
    addEventListener(k, f) { listeners[k] = f; }, removeEventListener(k) { delete listeners[k]; },
    append(...c) { n.children.push(...c); c.forEach(x => { x.parent = n; }); },
    remove() { if (n.parent) n.parent.children = n.parent.children.filter(x => x !== n); },
    closest: () => null, focus() { n.focused = true; }, scrollIntoView(o) { n.scrolled = o; },
    minLength: -1, maxLength: -1, pattern: '', required: false, disabled: false, ...extra};
  return n;
}
function field(label, props = {}) {
  const f = node('input', props), l = node('label');
  l.cloneNode = () => ({querySelectorAll: () => [], textContent: label});
  f.closest = sel => (sel === 'label' ? l : null);
  l.append(f); return f;
}
function setup(labels) {
  const context = vm.createContext({document: {createElement: node, querySelector: () => null}, window: {}});
  vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), context);
  return context.window.NowaFeedback;
}
const labels = {required_field: 'req', invalid_field: 'inv', field_required: '{field}: required.',
  field_min: '{field}: at least {min}.', field_time: '{field}: like 19:00.', field_agree: 'Accept the agreement.'};
const feedback = setup();
function form(...fields) { return {querySelectorAll: s => (s.includes('input') ? fields : [])}; }

// 1. empty required field is marked, named, scrolled to the centre and focused
let name = field('Doctor name', {required: true});
assert.throws(() => feedback.validate(form(name), labels), e => e.message === 'Doctor name: required.' && e.marked);
assert.equal(name.attrs['aria-invalid'], 'true'); assert(name.classList.contains('is-invalid'));
assert.equal(name.scrolled.block, 'center'); assert(name.focused);
const msg = name.parent.children.at(-1);
assert.equal(msg.className, 'field-error'); assert.equal(msg.textContent, 'Doctor name: required.');
assert.equal(name.attrs['aria-describedby'], msg.id);
// 2. editing clears the mark and the message
name.listeners.input();
assert.equal(name.attrs['aria-invalid'], undefined); assert(!name.parent.children.includes(msg));
assert.equal(name.attrs['aria-describedby'], undefined);
// 3. the rule is named: minimum length
let pw = field('Password', {required: true, minLength: 8, value: 'abc'});
assert.throws(() => feedback.validate(form(pw), labels), e => e.message === 'Password: at least 8.');
// 4. a time that is not a time
let t = field('From', {value: '25:99'}); t.attrs['data-time'] = '';
assert.throws(() => feedback.validate(form(t), labels), e => e.message === 'From: like 19:00.');
// 5. missing agreement marks its own row
let agree = field('I agree', {required: true, type: 'checkbox', checked: false});
assert.throws(() => feedback.validate(form(agree), labels), e => e.message === 'Accept the agreement.');
assert.equal(agree.attrs['aria-invalid'], 'true');
// 6. a typed 1900 becomes 19:00, and junk stays as typed
assert.equal(feedback.normalTime('1900'), '19:00'); assert.equal(feedback.normalTime('900'), '09:00');
assert.equal(feedback.normalTime('19:30'), '19:30'); assert.equal(feedback.normalTime('abc'), 'abc');
assert.equal(feedback.normalTime('٢٣٠٠'), '23:00');
// 7. server 422 fields mark the matching element by name
const target = field('Password');
const ctx2 = vm.createContext({document: {createElement: node, querySelector: s => (s === '[name="new_password"]' ? target : null)}, window: {}});
vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), ctx2);
const err = ctx2.window.NowaFeedback.requestError({status: 422}, {detail: {fields: ['new_password']}}, {check_fields: 'Check: '}, 'x');
assert.equal(err.fieldEls[0], target);
// 8. hours switch label flips live
const hours = fs.readFileSync('nowa/web/static/hours.js', 'utf8');
const text = node('span'); text.dataset = {on: 'Open', off: 'Closed'}; text.textContent = 'Open';
const enabled = node('input'); enabled.checked = true; enabled.nextElementSibling = text;
const times = node('div'), row = node('fieldset');
row.classList.toggle = () => {}; row.querySelector = s => (s === '.hours-times' ? times : enabled); row.dataset = {weekday: '1'};
const hctx = vm.createContext({window: {}, document: {querySelectorAll: () => [row]}});
vm.runInContext(hours, hctx);
assert.equal(text.textContent, 'Open');
enabled.checked = false; enabled.listeners.change(); assert.equal(text.textContent, 'Closed');
enabled.checked = true; enabled.listeners.change(); assert.equal(text.textContent, 'Open');
console.log('PASS: field errors name the field, mark it, clear on edit; hours label flips; times normalise');
