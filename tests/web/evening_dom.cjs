// Exercise shipped stage rendering with actual server snapshots supplied by pytest.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function element(tag = 'div') {
  const classes = new Set();
  return {tag, children: [], textContent: '', dataset: {}, style: {}, hidden: false,
    classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c),
      toggle(c, on) { if (on) classes.add(c); else classes.delete(c); }},
    setAttribute(key, value) { this[key] = value; },
    append(...children) { this.children.push(...children); }, prepend(...children) { this.children.unshift(...children); },
    replaceChildren(...children) { this.children = [...children]; }, addEventListener() {}, querySelectorAll() { return []; }};
}
const nodes = new Map();
const get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
get('demo-texts').textContent = JSON.stringify(input.texts);
const scheduled = [];
const documentElement = {lang: 'en', dir: 'ltr'};
const storage = new Map(), calls = [];
const context = vm.createContext({
  document: {getElementById: get, createElement: element, createElementNS: (_, tag) => element(tag), documentElement},
  sessionStorage: {getItem: () => null, removeItem() {}, setItem() {}},
  location: {href: 'http://localhost/demo/evening?lang=en'}, URL, Date,
  setTimeout: callback => { scheduled.push(callback); return scheduled.length; }, clearTimeout() {},
});
vm.runInContext(fs.readFileSync('nowa/web/static/evening.js', 'utf8'), context);
const all = node => [node, ...node.children.flatMap(all)];
const text = node => all(node).map(n => n.textContent).join(' ');
function show(data) { context.data = data; vm.runInContext('show(data)', context); }
show(input.initial);
assert.equal(get('stage').dataset.run, 'paused');
assert.equal(get('doctor-chip').dataset.doctor, 'waiting');
assert.equal(get('queue').children.length, 18);
assert.equal(get('report-card').hidden, true);
assert.equal(get('message-count').textContent, input.initial.phones.length);
assert.equal(get('timeline').children.at(-1).children.at(-1).textContent, 'Now');
for (const dir of ['ltr', 'rtl']) {
  documentElement.dir = dir;
  show(input.initial);
  const ticks = get('rail').children.filter(n => n.className === 'tick');
  assert.equal(text(ticks[0]).trim(), '18:20');
  assert.equal(text(ticks[1]).trim(), '02:00');
  assert.equal(ticks[0].style.insetInlineStart, '0');
  assert.equal(ticks[1].style.insetInlineEnd, '0');
  assert.equal(ticks[0].dir, undefined); // Position inherits the page direction.
  assert.equal(ticks[0].children[0].dir, 'ltr'); // Only digits are isolated.
}
show(input.on_way);
assert.equal(get('doctor-chip').dataset.doctor, 'on_way');
assert(text(get('doctor-label')).includes(String(input.on_way.doctor_travel_min)));
show(input.active);
assert.equal(get('doctor-chip').dataset.doctor, 'arrived');
assert(text(get('now-band')).includes(input.active.in_room.first_name));
assert(text(get('now-band')).includes('for 1 min'));
assert.equal(get('queue').children.find(tile => tile.dataset.state === 'in_room').dataset.bookingId,
  String(input.active.in_room.booking_id));
assert(get('queue').children.every(tile => all(tile).find(n => n.className === 't-name').dir === 'auto'));
assert(!get('now-band').children.some(node => node.className.includes('pace')));
assert(!text(get('feed')).match(/https?:\/\/|\/[lwr]\/[A-Za-z0-9_-]{22}/));
assert(!all(get('feed')).some(node => node.tag === 'a' || node.tag === 'button'));
assert.equal(get('feed').children.length, input.active.phones.length);
assert(get('feed').children[0].classList.contains('is-new'));
const leaveLines = get('timeline').children.filter(line => text(line).includes('Leave now'));
assert(leaveLines.length > 0);
assert(leaveLines.every(line => line.className.includes('is-key')));
for (const event of input.closed.timeline) {
  if (!event.booking || !['who_comes_in', 'patient_on_my_way', 'patient_undo_on_my_way',
    'booking_cancelled', 'message_failure'].includes(event.kind)) continue;
  // Full replay rendering must name every recoverable patient, including walk-ins.
  show(input.closed);
  const line = get('timeline').children.find(line => line.dataset.eventId === String(event.id));
  assert(line, 'missing booked event ' + event.id);
  assert(text(line).includes(event.booking.first_name || 'Walk-in'));
}
show(input.walk);
assert.equal(input.walk.in_room.first_name, null);
const roomCell = get('now-band').children.find(node => node.className.includes(' room'));
assert(text(roomCell).includes('Walk-in'));
assert.equal(roomCell.children[1].children[0].textContent, String(input.walk.in_room.queue_number));
assert(text(roomCell).includes('for 1 min'));
show(input.active);
for (const msg of input.active.phones) assert(text(get('feed')).includes(input.texts[msg.label]));
for (const callback of scheduled.splice(0)) callback();
show(input.active);
assert(!get('queue').children.some(tile => tile.classList.contains('is-changed')));
assert(!get('feed').children.some(card => card.classList.contains('is-new')));
show(input.closed);
assert.equal(get('stage').dataset.run, 'closed');
assert.equal(get('doctor-chip').dataset.doctor, 'closed');
assert.equal(get('report-card').hidden, false);
assert.equal(get('report-stats').children.length, Object.keys(input.closed.report).length);
assert(text(get('comparison')).includes('229 min (simulated)'));
assert.equal(get('report').href, input.closed.report_url + '?lang=en');
assert(!text(get('timeline')).includes('who_comes_in'));
assert.equal(get('rail').children[0].children[0].style.width, '100%');
const numbers = get('queue').children.map(tile => tile.children.find(n => n.className === 't-n').textContent);
assert.equal(numbers[numbers.indexOf('+') - 1], '9');
assert.equal(get('report-stats').children.at(-1).dataset.stat, 'avg_wait');
// First play uses one large, real advance. Pause/resume does not jump again.
context.crypto = {randomUUID: () => 'fixture-start-intent'};
context.sessionStorage = {getItem: key => storage.get(key) || null,
  setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)};
context.fetch = async (path, options) => {
  const body = options?.body ? JSON.parse(options.body) : null;
  calls.push({path, body});
  let result = path.endsWith('/start') ? {run_id: 'fixture', token: 'fixture-token'} : input.initial;
  if (path.endsWith('/advance')) result = {...input.initial, minute: body.to_minute,
    clock: new Date(Date.parse(input.initial.clock) + body.to_minute * 60000).toISOString()};
  return {ok: true, json: async () => result};
};
(async () => {
  vm.runInContext('run = null; lastData = null; playing = false;', context);
  await vm.runInContext('play()', context);
  await new Promise(resolve => setImmediate(resolve));
  const advances = calls.filter(call => call.path.endsWith('/advance'));
  assert.equal(advances[0].body.to_minute, input.initial.evening.start_minute);
  assert.equal(advances.filter(call => call.body.to_minute === input.initial.evening.start_minute).length, 1);
  assert.equal(advances[1].body.to_minute, input.initial.evening.start_minute + 2);
  vm.runInContext('pause()', context);
  await vm.runInContext('play()', context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.filter(call => call.path.endsWith('/advance') &&
    call.body.to_minute === input.initial.evening.start_minute).length, 1);
  console.log('PASS: FIX 1 rail, room, named replay, labels, walk-in position and first-play transport');
})().catch(error => { console.error(error); process.exitCode = 1; });
console.log('PASS: real initial/on-way/active/closed stage snapshots, messages, links, timeline, report and one-shot motion');
