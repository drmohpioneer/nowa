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
const arrivalAt = Date.parse(input.on_way.doctor.on_way_at) + input.on_way.doctor.eta_min * 60000;
const arrivalTime = new Date(arrivalAt).toLocaleTimeString('en-GB', {timeZone: 'Africa/Cairo', hour: '2-digit', minute: '2-digit'});
assert.equal(text(get('doctor-label')), `Doctor on the way · arrives about ${arrivalTime} · ${Math.ceil((arrivalAt - Date.parse(input.on_way.clock)) / 60000)} min left`);
show({...input.on_way, clock: new Date(arrivalAt + 60000).toISOString()});
assert(text(get('doctor-label')).includes('0 min left'));
show(input.active);
assert.equal(get('doctor-chip').dataset.doctor, 'arrived');
assert(text(get('now-band')).includes(input.active.in_room.first_name));
assert(text(get('now-band')).includes('for 1 min'));
assert.equal(get('queue').children.find(tile => tile.dataset.state === 'in_room').dataset.bookingId,
  String(input.active.in_room.booking_id));
assert(get('queue').children.every(tile => all(tile).find(n => n.className === 't-name').dir === documentElement.dir));
assert(get('queue').children.every(tile => { const n = all(tile).find(n => n.className === 't-name'); return n.title === n.textContent && n['aria-label'] === n.textContent; }));
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
  assert(text(line).includes(event.booking.first_name || input.texts.walkin));
}
show(input.walk);
assert.equal(input.walk.in_room.first_name, null);
const roomCell = get('now-band').children.find(node => node.className.includes(' room'));
assert(text(roomCell).includes(input.texts.walkin));
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
assert.equal(get('report-stats').children.length, 6);
assert(text(get('comparison')).includes('229 min (simulated)'));
assert.equal(get('report').href, input.closed.report_url + '?lang=en');
assert(!text(get('timeline')).includes('who_comes_in'));
assert.equal(get('rail').children[0].children[0].style.width, ((input.closed.minute - input.closed.evening.start_minute) / (input.closed.evening.last_minute - input.closed.evening.start_minute) * 100) + '%');
const numbers = get('queue').children.map(tile => all(tile).find(n => n.className === 't-n').textContent);
assert.equal(numbers[numbers.indexOf('+') - 1], '9');
assert.equal(get('report-stats').children.at(-1).dataset.stat, 'avg_wait');
assert.deepEqual(get('report-stats').children.map(n => n.dataset.stat), ['booked', 'seen_booked', 'no_show_count', 'walk_ins', 'total_seen', 'avg_wait']);
const bookedTile = get('report-stats').children[0];
assert.equal(bookedTile.children[0].textContent, '17');
assert.equal(bookedTile.children[1].textContent, 'Booked (1 cancelled)');
assert(text(get('report-stats').children[2]).includes('تامر'));
assert(text(get('report-stats').children[4]).includes('16 + 1'));
// First play uses one large, real advance. Pause/resume does not jump again.
context.crypto = {randomUUID: () => 'fixture-start-intent'};
context.sessionStorage = {getItem: key => storage.get(key) || null,
  setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)};
context.fetch = async (path, options) => {
  const body = options?.body ? JSON.parse(options.body) : null;
  calls.push({path, body});
  let result = path.split('?')[0].endsWith('/start') ? {run_id: 'fixture', token: 'fixture-token'} : input.initial;
  if (path.split('?')[0].endsWith('/advance')) result = {...input.initial, minute: body.to_minute,
    clock: new Date(Date.parse(input.initial.clock) + body.to_minute * 60000).toISOString()};
  return {ok: true, json: async () => result};
};
(async () => {
  const oldFetch = context.fetch;
  context.fetch = async (_, options) => {
    const body = JSON.parse(options.body);
    return {ok: true, json: async () => ({...input.on_way, minute: body.to_minute,
      clock: new Date(Date.parse(input.on_way.clock) + (body.to_minute - input.on_way.minute) * 60000).toISOString()})};
  };
  show(input.on_way);
  vm.runInContext("run = {run_id:'fixture', token:'token'}; playing = true;", context);
  const labels = [text(get('doctor-label'))];
  await vm.runInContext('tick()', context); labels.push(text(get('doctor-label')));
  await vm.runInContext('tick()', context); labels.push(text(get('doctor-label')));
  assert.equal(new Set(labels).size, 3, 'countdown updates on every actual tick');
  context.fetch = oldFetch;
  calls.length = 0;
  vm.runInContext('run = null; lastData = null; playing = false;', context);
  await vm.runInContext('play()', context);
  await new Promise(resolve => setImmediate(resolve));
  const advances = calls.filter(call => call.path.split('?')[0].endsWith('/advance'));
  assert.equal(advances[0].body.to_minute, input.initial.minute + 2);
  assert.equal(advances.filter(call => call.body.to_minute === input.initial.evening.start_minute).length, 0);
  assert.equal(advances.length, 1);
  vm.runInContext('pause()', context);
  await vm.runInContext('play()', context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.filter(call => call.path.split('?')[0].endsWith('/advance') &&
    call.body.to_minute === input.initial.evening.start_minute).length, 0);
  console.log('PASS: evening rail, room, named replay, labels, walk-in position and first-play transport');
})().catch(error => { console.error(error); process.exitCode = 1; });
console.log('PASS: real initial/on-way/active/closed stage snapshots, messages, links, timeline, report and one-shot motion');
