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
const context = vm.createContext({
  document: {getElementById: get, createElement: element, createElementNS: (_, tag) => element(tag), documentElement: {lang: 'en'}},
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
show(input.on_way);
assert.equal(get('doctor-chip').dataset.doctor, 'on_way');
assert(text(get('doctor-label')).includes(String(input.on_way.doctor_travel_min)));
show(input.active);
assert.equal(get('doctor-chip').dataset.doctor, 'arrived');
assert(text(get('now-band')).includes('No one in the room yet'));
assert(!get('now-band').children.some(node => node.className.includes('pace')));
assert(!text(get('feed')).match(/https?:\/\/|\/[lwr]\/[A-Za-z0-9_-]{22}/));
assert(!all(get('feed')).some(node => node.tag === 'a' || node.tag === 'button'));
assert.equal(get('feed').children.length, input.active.phones.length);
assert(get('feed').children[0].classList.contains('is-new'));
const leaveLines = get('timeline').children.filter(line => text(line).includes('Leave now'));
assert(leaveLines.length > 0);
assert(leaveLines.every(line => line.className.includes('is-key')));
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
console.log('PASS: real initial/on-way/active/closed stage snapshots, messages, links, timeline, report and one-shot motion');
