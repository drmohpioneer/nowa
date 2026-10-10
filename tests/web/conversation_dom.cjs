// shipped handlers, deferred HTTP, source direction and doctor identities.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function node(tag = 'div') {
  const classes = new Set();
  return {tag, dataset: {}, children: [], textContent: '', disabled: false, scrolled: 0,
    scrollIntoView() { this.scrolled++; },
    classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x)},
    append(...xs) { this.children.push(...xs); }, replaceChildren(...xs) { this.children = xs; },
    insertBefore(x, before) { this.children.splice(this.children.indexOf(before), 0, x); },
    setAttribute(k, v) { this[k] = v; }, removeAttribute(k) { delete this[k]; },
    addEventListener() {}, querySelectorAll() { return []; }};
}
function setup(file, publicMode = false, search = "") {
  const ids = ['chat-config', 'chat', 'controls', 'error', 'send', 'book-chip', 'message',
    'chat-emergency', 'message-label', 'faq', 'message-form', 'chat-phone', 'phone'];
  const nodes = Object.fromEntries(ids.map(id => [id, node()]));
  nodes.chat.append(nodes.controls);
  const strings = {send: 'Send', message: 'Message', book_chip: 'Book', emergency: '123',
    error: 'Request failed', location_error: 'Write your area', too_many_attempts: 'Wait 15 minutes',
    reply_received: 'Reply received', book_as: 'Book as {name}'};
  nodes['chat-config'].textContent = JSON.stringify({slug: 'test', fictional_names: ['Ahmed Ali', 'Mona Hassan', 'Nour Hassan'], demo_strings: strings,
    strings: {ar: strings, en: strings}, faq: [{label: 'Price', action: {payload: {faq: 'price'}}}],
    areas: [{id: 5, lat: 30, lng: 31}, {id: 2, lat: 31, lng: 32}]});
  let resolveRequest, locate;
  const sent = [], timers = new Map(); let timerId = 0;
  const context = {document: {getElementById: id => nodes[id], createElement: node, documentElement: {dir: "rtl"}},
    navigator: {geolocation: {getCurrentPosition(ok, fail) { locate = {ok, fail}; }}},
    URLSearchParams, location: {search}, isSecureContext: true,
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
    crypto: {randomUUID: () => 'offline'}, fetch: async (url, options) => {
      const body = options.body ? JSON.parse(options.body) : {}; sent.push({url, body});
      if (url.includes('/session')) return {ok: true, json: async () => ({session: 'session'})};
      return new Promise(resolve => { resolveRequest = resolve; });
    }, NowaPhone() {}};
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('nowa/web/static/' + file, 'utf8'), context);
  return {nodes, sent, context, timers,
    tick() { const [id, fn] = timers.entries().next().value; timers.delete(id); return fn(); },
    get locate() {return locate;},
    show(data) { vm.runInContext('show(' + JSON.stringify(data) + ')', context); },
    complete(data, status = 200) { resolveRequest({ok: status === 200, status, json: async () => data}); }};
}
const answer = (reply = 'Done', buttons = []) => ({reply, lang: 'ar', buttons});
const choice = (kind, payload = {}) => ({label: kind, action: {kind, payload}});
function busy(b) { assert(b.disabled); assert.equal(b['aria-busy'], 'true'); assert(b.classList.contains('is-busy')); }
function idle(b) { assert(!b.disabled); assert.equal(b['aria-busy'], undefined); }
async function patient() {
  const h = setup('chat.js'); await new Promise(setImmediate);
  h.show(answer('Where from?', [choice('set_area', {current_location: true})]));
  const location = h.nodes.controls.children[0].children[0];
  const pending = location.onclick(); busy(location);
  const before = h.sent.length; await location.onclick(); assert.equal(h.sent.length, before);
  h.locate.ok({coords: {latitude: 30, longitude: 31}}); await new Promise(setImmediate);
  busy(location); assert.equal(h.sent.at(-1).body.action, 'set_area');
  assert.deepEqual(h.sent.at(-1).body.payload, {area_id: 5});
  assert(!JSON.stringify(h.sent).includes('latitude'));
  h.complete(answer('Name · day · Maadi', [choice('confirm', {draft: {phone: 'SECRET'}})])); await pending;
  idle(location); assert.equal(h.nodes.error.textContent, '');
  assert.equal(h.nodes.controls.children[0].children[0].className, 'btn btn-main');
  assert(h.nodes.controls.scrolled > 0);
  assert(h.nodes.chat.children.filter(n => n.className?.startsWith('bubble')).every(n => n.scrolled > 0));
  assert(h.nodes.chat.children.some(n => n.className === 'bubble me' && n.textContent === 'set_area'));
  assert(!JSON.stringify(h.nodes.chat).includes('SECRET'));
  for (const kind of ['confirm', 'set_for', 'book', 'more_days']) {
    h.show(answer('Choose', [choice(kind)]));
    const b = h.nodes.controls.children[0].children[0], p = b.onclick(); busy(b);
    const count = h.sent.length; await b.onclick(); assert.equal(h.sent.length, count);
    h.complete(answer(kind)); await p; idle(b); assert.equal(h.nodes.error.textContent, '');
  }
  const faq = h.nodes.faq.children[0], faqPending = faq.onclick(); busy(faq);
  h.complete({detail: {}}, 429); await faqPending; idle(faq);
  assert.equal(h.nodes.error.textContent, 'Wait 15 minutes');
  h.show(answer('Where?', [choice('set_area', {current_location: true})]));
  const denied = h.nodes.controls.children[0].children[0], deniedPending = denied.onclick();
  busy(denied); h.locate.fail(); await deniedPending; idle(denied);
  assert.equal(h.nodes.error.textContent, '');
  assert(h.nodes.chat.children.some(n => n.textContent === 'Write your area'));
  assert.equal(h.nodes.chat.children.at(-2).textContent, 'Where?');
  assert.equal(h.nodes.controls.children[0].children.length, 1);
  h.show(answer('Lookup', [choice('lookup')]));
  const form = h.nodes.controls.children[1], submit = form.children[2];
  const lookupPending = form.onsubmit({preventDefault() {}}); busy(submit);
  const count = h.sent.length; await form.onsubmit({preventDefault() {}}); assert.equal(h.sent.length, count);
  h.complete(answer('Booking found')); await lookupPending; idle(submit);
  assert.equal(h.nodes.error.textContent, '');
  for (const bubble of h.nodes.chat.children.filter(n => n.className === 'bubble')) assert.equal(bubble.dir, /[A-Za-z]/.test((/[A-Za-z\u0590-\u08FF]/.exec(bubble.textContent) || [''])[0]) ? 'ltr' : 'rtl');
}
async function publicChat() {
  const h = setup('public-chat.js', true); await new Promise(setImmediate);
  const who = h.nodes.controls.children[0], start = who.onclick(); busy(who);
  h.complete(answer('Pick day', [choice('book', {date: '2026-10-06'}), choice('more_days')])); await start;
  assert.equal(h.nodes.chat.children[0].textContent, 'Book as Ahmed Ali');
  assert.equal(h.nodes.chat.children[0].className, 'bubble me');
  for (const [index, reply, buttons] of [
    [1, 'More days', [choice('book', {date: '2026-10-08'})]],
    [0, 'Area', [choice('set_area', {area_id: 5})]],
    [0, 'Review', [choice('confirm', {draft: {phone: 'SECRET'}})]],
    [0, 'Booked', []],
  ]) {
    const b = h.nodes.controls.children[0].children[index], p = b.onclick(); busy(b);
    if (b.textContent === 'confirm') assert.equal(b.className, 'btn btn-main');
    const mine = h.nodes.chat.children.filter(n => n.className === 'bubble me');
    assert.equal(mine.at(-1).textContent, b.textContent);
    const count = h.sent.length; await b.onclick(); assert.equal(h.sent.length, count);
    assert.equal(h.nodes.chat.children.filter(n => n.className === 'bubble me').length, mine.length);
    h.complete({...answer(reply, buttons), booking_confirmed: reply === 'Booked'}); await p; idle(b);
    assert.equal(h.nodes.error.textContent, '');
  }
  assert.equal(h.nodes['chat-phone'].hidden, false);
  assert(!JSON.stringify(h.nodes.chat).includes('SECRET'));
  const faq = h.nodes.faq.children[0], faqPending = faq.onclick(); busy(faq);
  assert.equal(h.nodes.chat.children.at(-2).textContent, 'Price');
  assert.equal(h.nodes.chat.children.at(-2).className, 'bubble me');
  h.complete(answer('Price answer')); await faqPending;
  assert.equal(h.nodes.error.textContent, '');
  for (const bubble of h.nodes.chat.children.filter(n => n.className?.startsWith('bubble'))) assert.equal(bubble.dir, /[A-Za-z]/.test((/[A-Za-z\u0590-\u08FF]/.exec(bubble.textContent) || [''])[0]) ? 'ltr' : 'rtl');
}
async function doctor() {
  const panel = node(), fields = {question_asker: '{name} · number {number} · {day}', question_anonymous: 'Patient from chat, not booked yet'};
  const source = fs.readFileSync('nowa/web/static/dashboard.js', 'utf8');
  const fn = source.slice(source.indexOf('function questionIcon'), source.indexOf('if (document.getElementById("questions"))'));
  const context = {document: {getElementById: () => panel, createElement: node, createElementNS: (_, tag) => node(tag), createTextNode: text => Object.assign(node('text'), {textContent: text}), documentElement: {dir: 'rtl'}},
    api: async () => [{id: 1, status: 'open', text_display: 'Question', count: 5, askers: [
      {name: 'Amira Mahmoud', queue_number: 7, day: 'Thursday 8/10'}, {}, {}, {}, {}]}],
    t: k => fields[k] || k, bindButton() {}};
  vm.createContext(context); vm.runInContext(fn, context); await vm.runInContext('loadQuestions()', context);
  const lines = panel.children[0].children[0].children.map(c => c.textContent);
  assert(lines.includes('Amira Mahmoud · number 7 · Thursday 8/10'));
  assert.equal(lines.filter(t => t === fields.question_anonymous).length, 2); assert(lines.includes('+2'));
  assert(source.includes('question.textContent = answer.question'));
  assert(source.includes('reply.textContent = answer.answer'));
  assert(source.includes('time.textContent = answer.at_display'));
  assert(!source.includes('answer.model'));
  assert(!source.includes('["question", "answer", "why", "at_display", "model"]'));
}

async function emergency() {
  for (const file of ['chat.js', 'public-chat.js']) {
    const h = setup(file); await new Promise(setImmediate);
    const wrap = node(), link = node('a'); link.href = '/demo';
    const live = [h.nodes.send, h.nodes['book-chip'], h.nodes.message, h.nodes.faq.children[0]];
    h.context.document.querySelector = () => wrap;
    h.context.document.querySelectorAll = selector => selector.startsWith('button') ? live : [link];
    for (const control of live) control.closest = () => wrap['data-emergency-locked'] ? wrap : null;
    const triggering = h.nodes.faq.children[0];
    await h.context.NowaFeedback.pending(triggering, async () => {
      h.show({...answer('Emergency: call 123'), state: 'locked_emergency'});
    }, h.nodes.error);
    assert(live.every(control => control.disabled), file + ': complete lock survives pending cleanup');
    assert.equal(link.href, undefined);
    const call = h.nodes.controls.children.find(el => el.href === 'tel:123');
    assert(call && call.scrolled > 0);
    const count = h.sent.length;
    if (file === 'chat.js') await h.nodes['book-chip'].onclick();
    await triggering.onclick();
    assert.equal(h.sent.length, count, 'locked controls must not send');
  }
}


async function standby() {
  const h = setup('chat.js'); await new Promise(setImmediate);
  h.show({...answer('Link Telegram'), standby_pending: true});
  h.show({...answer('Link Telegram'), standby_pending: true});
  assert.equal(h.timers.size, 1, 'rerender keeps one pending status poll');
  const pending = h.tick(); await new Promise(setImmediate);
  assert.equal(h.sent.at(-1).body.action, 'none');
  assert.deepEqual(h.sent.at(-1).body.payload, {standby_status: true});
  h.complete({...answer('Position 1: we will message you on Telegram'), standby_pending: false});
  await pending;
  assert.equal(h.timers.size, 0, 'successful join stops polling');
  assert(h.nodes.chat.children.some(n => n.textContent.startsWith('Position 1')));
  assert.equal(h.sent.filter(r => r.body.action === 'confirm').length, 0, 'polling never confirms a booking');

  const nextDay = setup('chat.js', false, '?day=2026-10-08'); await new Promise(setImmediate);
  assert.equal(nextDay.sent.at(-1).body.action, 'book');
  assert.deepEqual(nextDay.sent.at(-1).body.payload, {date: '2026-10-08'});
  nextDay.complete(answer('Who is this booking for?')); await new Promise(setImmediate);
  assert(nextDay.nodes.chat.children.some(n => n.textContent === 'Who is this booking for?'));
}

(async () => { await standby(); await emergency(); await patient(); await publicChat(); await doctor(); console.log('PASS: all chat actions use feedback, duplicate guards, area-only geolocation, source direction, public flow, and doctor askers'); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
