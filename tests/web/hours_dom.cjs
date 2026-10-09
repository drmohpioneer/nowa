const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function row(weekday, open) {
  const classes = new Set(), enabled = {checked: open, addEventListener(_, fn) { this.change = fn; }};
  const controls = {enabled, start: {value: '19:00'}, end: {value: '23:00'}};
  const times = {hidden: !open};
  return {dataset: {weekday: String(weekday)}, controls, times, classes,
    classList: {toggle(key, on) { if (on) classes.add(key); else classes.delete(key); }},
    querySelector(key) { return key === '.hours-times' ? times : controls[key.match(/name="(\w+)"/)[1]]; }};
}
const rows = [row(0, true), row(1, false)];
const root = {querySelectorAll() { return rows; }};
const context = vm.createContext({window: {}, document: root});
vm.runInContext(fs.readFileSync('nowa/web/static/hours.js', 'utf8'), context);
const values = () => JSON.parse(JSON.stringify(context.window.NowaHours.values(root)));
assert.deepEqual(values(), [{weekday: 0, start: '19:00', end: '23:00'}]);
rows[0].controls.start.value = '20:30';
rows[0].controls.enabled.checked = false; rows[0].controls.enabled.change();
assert(rows[0].times.hidden && rows[0].classes.has('is-closed'));
assert.equal(rows[0].controls.start.value, '20:30');
assert.deepEqual(values(), []);
rows[0].controls.enabled.checked = true; rows[0].controls.enabled.change();
assert(!rows[0].times.hidden && !rows[0].classes.has('is-closed'));
assert.deepEqual(values(), [{weekday: 0, start: '20:30', end: '23:00'}]);
console.log('PASS: shared hours switch, closed state, payload and retained times');
