// Execute the shipped chat scripts against an offline DOM and transport.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(tag = 'div') {
  return {tag, children: [], textContent: '', hidden: true, disabled: false,
    setAttribute(key, value) { this[key] = value; }, removeAttribute(key) {delete this[key];}, append(...items) { this.children.push(...items); },
    insertBefore(child, ref) { const i = this.children.indexOf(ref); assert(i >= 0); this.children.splice(i, 0, child); },
    replaceChildren() { this.children = []; }, querySelectorAll() { return []; }};
}
async function check(script, width) {
  const ids = ['chat-config', 'chat', 'controls', 'error', 'send', 'book-chip', 'message', 'chat-emergency',
    'message-label', 'faq', 'message-form', 'phone', 'chat-phone'];
  const nodes = new Map(ids.map(id => [id, element()]));
  const controls = nodes.get('controls'); nodes.get('chat').append(controls);
  const config = {slug: 'fictional', fictional_names: ['Ahmed Ali', 'Mona Hassan', 'Nour Hassan'], faq: [], areas: [], strings: {ar: {}}, demo_strings: {book_as: "Book as {name}"}, open_telegram: {ar: 'Open Telegram'}};
  nodes.get('chat-config').textContent = JSON.stringify(config);
  const polls = [], calls = [];
  const context = vm.createContext({
    document: {getElementById: id => nodes.get(id) || null, createElement: element, documentElement: {dir: "rtl"}},
    URLSearchParams, location: {search: ""}, setTimeout: () => 1, clearTimeout: () => {}, Date,
    crypto: {randomUUID: () => 'fixture-id'},
    fetch: async (url) => { calls.push(url); if(url.includes('/link-status')) return {ok:true,json:async()=>({status:'pending',usable:true,remaining_seconds:900,qr:'data:image/svg+xml;base64,fixture'})}; assert(url.includes('/session')); return {ok: true, json: async () => ({session: 'session-key'})}; },
    window: {matchMedia: () => ({matches:width>=900}), NowaPhone: (...args) => polls.push(args)},
  });
  vm.runInContext(fs.readFileSync('nowa/web/static/telegram-link.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('nowa/web/static/' + script, 'utf8'), context);
  await new Promise(setImmediate);
  assert(nodes.get('chat-phone').hidden);
  const url = 'https://t.me/fictional_bot?start=p_fixture';
  const data = {reply: 'Booked', lang: 'ar', state: 'open', buttons: [], booking_confirmed: true, telegram_url: url};
  context.data = data;
  vm.runInContext('show(data)', context);
  vm.runInContext('show(data)', context);
  const cta = controls.children.find(el => el.className === 'tg-cta');
  assert(cta, 'v2 Telegram CTA wrapper');
  assert(nodes.get('chat').children.filter(el => el.className === 'bubble').every(el => el.dir === (/[A-Za-z]/.test((/[A-Za-z\u0590-\u08FF]/.exec(el.textContent) || [''])[0]) ? 'ltr' : 'rtl')));
  await new Promise(setImmediate);
  const widget = cta.children[0];
  assert.equal(widget.children[3].hidden,width<900);
  const links = widget.children.filter(el => el.tag === 'a');
  assert.equal(links.length, 1); assert.equal(links[0].href, url);
  assert.equal(links[0].className, 'btn btn-main'); assert.equal(links[0].target, '_blank');
  assert.equal(links[0].rel, 'noopener'); assert.equal(links[0].textContent, 'Open Telegram');
  assert.equal(nodes.get('chat-phone').hidden, false);
  assert.equal(polls.length, 1); assert.equal(polls[0][1], '/c/fictional/demo/phone?session=session-key');
  assert.equal(calls.filter(url => url.includes('/session')).length,1);
  assert(calls.every(url => url.includes('/session') || url.includes('/link-status')), 'rendering reads status but never mints');
}
(async () => {
  for (const width of [390,900,1280]) {await check('chat.js',width); await check('public-chat.js',width);}
  console.log('PASS: AI and public chat render one safe Telegram button; success reveals the session-scoped phone; rerenders neither mint nor poll twice');
})().catch(error => { console.error(error); process.exitCode = 1; });
