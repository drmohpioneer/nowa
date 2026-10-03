// Exercise the shipped refresh() with real HTTP snapshots, including undo.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function element(tag = 'div') {
  return {tag, children: [], dataset: {}, style: {}, textContent: '', hidden: false, value: '',
    classList: {toggle() {}}, append(...nodes) { this.children.push(...nodes); },
    prepend(...nodes) { this.children.unshift(...nodes); }, replaceChildren(...nodes) { this.children = nodes; },
    setAttribute(key, value) { this[key] = value; }, querySelectorAll() { return []; },
    querySelector() { return null; }, insertBefore(node) { this.children.push(node); }};
}
const nodes = new Map(), get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
const text = node => [node.textContent, ...node.children.map(text)].join(' ');
const context = vm.createContext({document: {getElementById: get, createElement: element, documentElement: {lang: 'en'}},
  Date, t: key => input.texts[key] || key, bindButton() {}, api: async () => context.data});
const source = fs.readFileSync('nowa/web/static/dashboard.js', 'utf8');
vm.runInContext(source.slice(source.indexOf('async function refresh()'), source.indexOf('async function command(')), context);
(async () => {
  for (const data of input.states) {
    context.data = data;
    await vm.runInContext('refresh()', context);
    const doctor = data.doctor, recorded = Boolean(doctor.on_way_at || doctor.arrived_at);
    assert.equal(get('on-way').hidden, recorded);
    assert.equal(get('onway-state').hidden, !recorded);
    if (recorded) {
      assert(text(get('onway-state')).includes(doctor.arrived_at ? 'Arrived ' : 'On the way since '));
      const at = new Date(doctor.arrived_at || doctor.on_way_at).toLocaleTimeString('en-GB',
        {timeZone: 'Africa/Cairo', hour: '2-digit', minute: '2-digit'});
      assert(text(get('onway-state')).includes(at));
    }
    if (data.in_room) {
      assert(text(get('in-room')).includes(data.in_room.first_name || input.texts.walk_in));
      const row = get('queue').children.find(row => row.dataset.state === 'in_room');
      assert(row);
      assert.equal(row.children[0].textContent, String(data.in_room.queue_number));
      assert(row.children.at(-1).children.some(node => node.className === 'dot live'));
      assert.equal(get('queue').children.filter(row => row.dataset.state === 'in_room').length, 1);
    } else {
      assert.equal(get('in-room').textContent, input.texts.empty);
      assert(!get('queue').children.some(row => row.dataset.state === 'in_room'));
    }
  }
  console.log('PASS: doctor button/state, room card and live row across real commands and undo');
})().catch(error => { console.error(error); process.exitCode = 1; });
