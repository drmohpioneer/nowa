// Execute the shipped board and confirmation handlers over actual API snapshots.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function element(tag = 'div') {
  return {tag, children: [], dataset: {}, style: {}, textContent: '', hidden: false, value: '',
    classList: {toggle() {}}, append(...nodes) { this.children.push(...nodes); },
    prepend(...nodes) { this.children.unshift(...nodes); }, replaceChildren(...nodes) { this.children = nodes; },
    setAttribute(key, value) { this[key] = value; }, querySelectorAll() { return []; },
    querySelector() { return null; }, insertBefore(node) { this.children.push(node); }, focus() {}};
}
const nodes = new Map(), get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
const commands = [], confirms = [];
const context = vm.createContext({document: {getElementById: get, createElement: element, documentElement: {lang: 'en'}},
  Date, t: key => { assert(input.texts[key], 'missing label ' + key); return input.texts[key]; },
  bindButton(el, action) { el.action = action; }, api: async () => context.data,
  command: async (path, body) => { commands.push({path, body}); return {ok: true}; },
  closePanel: get('close-panel'), closePreview: null,
  window: {confirm: prompt => { confirms.push(prompt); return true; }}});
const source = fs.readFileSync('nowa/web/static/dashboard.js', 'utf8');
vm.runInContext(source.slice(source.indexOf('async function refresh()'), source.indexOf('async function command(')), context);
vm.runInContext(source.slice(source.indexOf('  function showClose('), source.indexOf('  bindButton(document.getElementById("close"),')), context);
vm.runInContext(source.slice(source.indexOf('  const pause = document.getElementById("pause");'), source.indexOf('  bindButton(document.getElementById("cancel"),')), context);
(async () => {
  for (const data of input.states) {
    context.data = data;
    await vm.runInContext('refresh()', context);
    assert.equal(get('cover-limit').hidden, !data.cover_cap_reached);
    assert.equal(get('wind-down-state').hidden, data.evening_state !== 'winding_down');
    assert.equal(get('wind-down').hidden, data.evening_state !== 'running');
    assert.equal(get('pause').hidden, !['running', 'winding_down'].includes(data.evening_state));
    assert.equal(get('pause-state').hidden, !data.paused_since);
    assert.equal(get('pause').textContent, input.texts[data.paused_since ? 'resume' : 'pause']);
    if (!get('pause').hidden) {
      await get('pause').action();
      assert.equal(commands.at(-1).path, data.paused_since ? 'resume' : 'pause');
    }
    for (const row of data.rows.filter(row => row.remaining)) {
      const card = get('queue').children.find(c => c.children[0].textContent === String(row.queue_number));
      const action = card.children.at(-1);
      assert.equal(action.textContent, input.texts[row.arrived_at ? 'undo_arrived' : 'mark_arrived']);
      if (row.arrived_at) assert(card.children[3].textContent.includes(input.texts.arrived));
      await action.action();
      assert.equal(commands.at(-1).path, row.arrived_at ? 'arrived/undo' : 'arrived');
      assert.equal(commands.at(-1).body.booking_id, row.booking_id);
    }
  }
  context.preview = input.preview;
  vm.runInContext('showClose(preview)', context);
  assert.equal(get('close-panel').hidden, false);
  for (const group of ['untold', 'told', 'passed', 'arrived']) {
    assert(get('close-details').textContent.includes(input.texts['close_group_' + group]));
    for (const patient of input.preview[group]) {
      assert(get('close-details').textContent.includes(patient.patient_name));
      const at = new Date(patient.expected_shown).toLocaleTimeString('en-GB', {timeZone: 'Africa/Cairo', hour: '2-digit', minute: '2-digit'});
      assert(get('close-details').textContent.includes(at));
    }
  }
  assert.equal(get('close-confirm').hidden, input.preview.arrived_count > 0);
  context.data = input.preview;
  await get('wind-down').action();
  assert.equal(confirms[0], input.texts.wind_down_confirm.replace('{count}', input.preview.untold_count));
  assert.equal(commands.at(-1).path, 'wind-down');
  assert.equal(commands.at(-1).body.expected_untold, input.preview.untold_count);
  console.log('PASS: arrival controls, cap, wind-down and named close preview');
})().catch(error => { console.error(error); process.exitCode = 1; });
