// After the evening is closed the board says so and hides the actions that no longer apply.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(tag = 'div') {
  return {tag, children: [], dataset: {}, style: {}, textContent: '', hidden: false, value: '',
    classList: {toggle(name, on) { this.live = name === 'live' ? on : this.live; }}, append(...nodes) { this.children.push(...nodes); },
    prepend(...nodes) { this.children.unshift(...nodes); }, replaceChildren(...nodes) { this.children = nodes; },
    setAttribute(key, value) { this[key] = value; }, querySelectorAll() { return []; },
    querySelector() { return null; }, insertBefore(node) { this.children.push(node); }};
}
const nodes = new Map(), get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
const texts = {tonight_closed: 'Clinic closed', no_evening: 'none', empty: 'empty', walk_in: 'walk-in', call_in: 'Call {name}'};
const bound = [];
const context = vm.createContext({document: {getElementById: get, createElement: element, documentElement: {lang: 'en'}},
  Date, t: key => texts[key] || key, bindButton(node) { bound.push(node); }, api: async () => context.data});
const source = fs.readFileSync('nowa/web/static/dashboard.js', 'utf8');
vm.runInContext(source.slice(source.indexOf('async function refresh()'), source.indexOf('async function command(')), context);
const row = {booking_id: 1, queue_number: 1, patient_first_name: 'Sara', state: 'booked', remaining: true, source: 'chat', no_show_count: 0};
const base = {evening_id: 7, latest_report_id: null, rows: [row], areas: [], in_room: null, can_undo: true,
  doctor: {on_way_at: null, arrived_at: null, eta_min: null}};
(async () => {
  context.data = base; await vm.runInContext('refresh()', context);
  assert.equal(get('close').hidden, false); assert.equal(get('next-hero').hidden, false); assert.equal(get('onway').hidden, false);
  const openBound = bound.length;
  context.data = {...base, latest_report_id: 7, doctor: {on_way_at: '2026-10-08T17:00:00+00:00', arrived_at: null, eta_min: 20}};
  bound.length = 0; await vm.runInContext('refresh()', context);
  for (const id of ['onway', 'onway-state', 'who', 'who-label', 'close', 'cancel', 'undo', 'next-hero', 'area-form']) assert(get(id).hidden, id + ' stays visible after close');
  assert.equal(get('evening-label').textContent, 'Clinic closed');
  assert.equal(get('progress-label').textContent, 'Clinic closed');
  assert.equal(get('evening-dot').classList.live, false);
  assert.equal(get('stats').hidden, false); assert.equal(get('queue').children.length, 1);
  assert.equal(bound.length, 0, 'queue names are not clickable after close');
  assert(openBound > 0);
  // An older closed evening does not close tonight.
  context.data = {...base, latest_report_id: 3}; await vm.runInContext('refresh()', context);
  assert.equal(get('close').hidden, false);
  console.log('PASS: closed evening shows a closed badge and hides the actions');
})().catch(error => { console.error(error); process.exitCode = 1; });
