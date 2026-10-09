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
const text = node => [`${node.textContent}`, ...node.children.map(text)].join(' ');  // undefined must show, not vanish
const context = vm.createContext({document: {getElementById: get, createElement: element, documentElement: {lang: 'en'}},
  Date, t: key => input.texts[key] || key, bindButton() {}, api: async () => context.data});
const source = fs.readFileSync('nowa/web/static/dashboard.js', 'utf8');
vm.runInContext(source.slice(source.indexOf('async function refresh()'), source.indexOf('async function command(')), context);
(async () => {
  for (const data of input.states) {
    context.data = data;
    await vm.runInContext('refresh()', context);
    if (data.evening_id == null) {
      for (const id of ['onway','who','close','cancel','undo','stats','room-section','progress-section']) assert(get(id).hidden, id);
      assert.equal(get('queue').textContent, input.texts.no_evening);
      assert(get('on-way').hidden); continue;
    }
    assert.equal(get('stats').children.length, 4);
    // No element may carry the literal word undefined (an element made without text once did).
    for (const id of ['next-patient', 'next-action', 'queue', 'stats', 'in-room']) assert(!text(get(id)).includes('undefined'), id + ' prints undefined');
    assert.equal(get('stats').children[0].children[0].textContent, String(data.rows.filter(row => row.source === 'chat' && row.state !== 'cancelled').length));
    assert.equal(get('stats').children[3].children[0].textContent, String(data.rows.filter(row => row.source === 'walkin_tap').length));
    for (const stored of data.rows) {
      const card = get('queue').children.find(card => card.children[0].textContent === String(stored.queue_number));
      const expected = stored.expected_shown ? new Date(stored.expected_shown).toLocaleTimeString('en-GB',
        {timeZone: 'Africa/Cairo', hour: '2-digit', minute: '2-digit'}) : '';
      assert.equal(card.children[2].textContent, expected, 'board preserves the projected time');
    }
    if (data.standby_count !== undefined) {
      assert.equal(get('standby-count').hidden, !(data.standby_count > 0));
      assert.equal(get('standby-count').textContent, input.texts.standby_count.replace('{count}', data.standby_count));
    }
    const doctor = data.doctor, recorded = Boolean(doctor.on_way_at || doctor.arrived_at);
    assert.equal(get('on-way').hidden, recorded);
    assert.equal(get('onway-state').hidden, !recorded);
    if (recorded) {
      assert(text(get('onway-state')).includes(doctor.arrived_at ? 'Arrived ' : 'On the way since '));
      const at = new Date(doctor.arrived_at || doctor.on_way_at).toLocaleTimeString('en-GB',
        {timeZone: 'Africa/Cairo', hour: '2-digit', minute: '2-digit'});
      assert(text(get('onway-state')).includes(at));
      if (!doctor.arrived_at) {
        const arrival = new Date(Date.parse(doctor.on_way_at) + doctor.eta_min * 60000)
          .toLocaleTimeString('en-GB', {timeZone: 'Africa/Cairo', hour: '2-digit', minute: '2-digit'});
        assert(text(get('onway-state')).includes('arrives about ' + arrival));
      }
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
