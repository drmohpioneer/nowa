// Execute shipped handlers with offline geolocation and DOM doubles; never start a browser.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(tag = 'div') {
  return {classList: {add() {}, remove() {}}, tag, children: [], textContent: '', value: '', disabled: false,
    setAttribute(key, value) { this[key] = value; }, removeAttribute(key) { delete this[key]; },
    append(...items) { this.children.push(...items); },
    insertBefore(child, ref) { this.children.splice(this.children.indexOf(ref), 0, child); },
    replaceChildren(...items) { this.children = items; }, querySelectorAll() { return []; }};
}
async function check(code, secure = true, supported = true) {
  const ids = ['chat-config', 'chat', 'controls', 'error', 'send', 'book-chip', 'message',
    'chat-emergency', 'message-label', 'faq', 'message-form'];
  const nodes = new Map(ids.map(id => [id, element()]));
  nodes.get('chat').append(nodes.get('controls'));
  const labels = {location_denied: 'Permission denied. Type the area.', location_timeout: 'Timed out. Type the area.', location_error: 'Unavailable. Type the area.'};
  nodes.get('chat-config').textContent = JSON.stringify({slug: 'fictional', faq: [], areas: [{id: 1, lat: 30, lng: 31}], strings: {ar: labels}});
  const calls = []; let geoCalls = 0;
  const context = vm.createContext({document: {getElementById: id => nodes.get(id) || null,
    createElement: element, documentElement: {}}, URLSearchParams, location: {search: ''},
    setTimeout, clearTimeout, crypto: {randomUUID: () => 'id'}, isSecureContext: secure,
    navigator: supported ? {geolocation: {getCurrentPosition(resolve, reject) {
      geoCalls++; if (code === 0) resolve({coords: {latitude: 30.1, longitude: 31.1}}); else reject({code});
    }}} : {}, fetch: async (url, options) => { calls.push({url, data: JSON.parse(options.body)});
      return {ok: true, json: async () => url.includes('/session') ? {session: 'session'} : {reply: 'Confirmed', lang: 'ar', buttons: []}};
    }});
  context.window = context;
  vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('nowa/web/static/chat.js', 'utf8'), context);
  await new Promise(setImmediate);
  context.data = {lang: 'ar', reply: 'Choose your area', buttons: [
    {label: 'Location', action: {kind: 'set_area', payload: {current_location: true}}},
    {label: 'Another choice', action: {kind: 'none', payload: {}}},
  ]};
  vm.runInContext('show(data)', context);
  const row = nodes.get('controls').children[0];
  if (!secure || !supported) {
    assert.equal(row.children.length, 1, 'unavailable location button must be omitted');
    assert.equal(geoCalls, 0); return;
  }
  await row.children[0].onclick();
  if (code === 0) {
    assert.equal(calls.length, 2);
    assert.deepEqual(calls[1].data.payload, {area_id: 1});
    assert(!JSON.stringify(calls).includes('latitude'));
    return;
  }
  const expected = code === 1 ? labels.location_denied : code === 3 ? labels.location_timeout : labels.location_error;
  assert(nodes.get('chat').children.some(node => node.textContent === expected), 'specific cause belongs in the chat');
  assert.equal(nodes.get('chat').children.filter(node => node.textContent === 'Choose your area').length, 2, 'same step must be re-asked');
  assert.equal(nodes.get('controls').children[0].children.length, 2);
  assert.equal(calls.length, 1, 'failed location must never send a command');
  assert.equal(nodes.get('message').disabled, false);
  // A secure origin can lose the capability after rendering: explain that as denied too.
  context.isSecureContext = false;
  await nodes.get('controls').children[0].children[0].onclick();
  assert(nodes.get('chat').children.some(node => node.textContent === labels.location_denied));
  assert.equal(geoCalls, 1);
  assert.equal(nodes.get('controls').children[0].children.length, 1);
}
(async () => {
  for (const code of [1, 2, 3, 0]) await check(code);
  await check(1, false, true); await check(1, true, false);
  console.log('PASS: geolocation causes, restored steps, unavailable controls and local-only coordinates');
})().catch(error => {console.error(error); process.exitCode = 1;});
