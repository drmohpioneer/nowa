// Shipped phone renderer: shared cards, body lines, labeled links and meta in both containers.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(tag = 'div') {
  return {tag, children: [], className: '', textContent: '',
    classList: {add() {}, remove() {}, contains() { return false; }},
    setAttribute(key, value) { this[key] = value; },
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; }, closest() { return null; }};
}
const labels = ['link_booking', 'link_way', 'link_rebook', 'time_am', 'time_pm', 'failed'].map(key => ({dataset: {key}, textContent: key}));
const context = vm.createContext({document: {documentElement: {lang: 'ar', dir: 'rtl'},
  querySelectorAll() { return labels; }, createElement: element}, setTimeout() {}});
context.window = context;
vm.runInContext(fs.readFileSync('nowa/web/static/phone.js', 'utf8'), context);
for (const isPatient of [false, true]) {
  const feed = element(); feed.classList.contains = name => isPatient && name === 'tg-body';
  const message = {outbox_id: 1, recipient_name: 'Fictional Patient', body: 'First line\nSecond line\n\nhttps://example.test/l/ABCDEFGHIJKLMNOPQRSTUV\n', created_at: '2026-10-09T16:00:00Z', status: 'delivered'};
  context.NowaPhoneCards(feed, [message, {...message, outbox_id: 2}]);
  assert.equal(feed.children.length, 2);
  for (const card of feed.children) {
    assert.equal(card.className, 'tg-msg');
    const [who, bubble] = card.children[1].children;
    assert.equal(who.className, 'tg-who'); assert.equal(bubble.className, 'tg-bubble');
    const [body, meta] = bubble.children;
    assert.equal(body.tag, 'p'); assert.equal(meta.className, 'tg-meta');
    assert.equal(body.children[0].textContent, 'First line\nSecond line');
    assert.equal(body.children[1].tag, 'a'); assert.equal(body.children[1].className, 'link-chip');
    assert.equal(body.children[1].href, '/l/ABCDEFGHIJKLMNOPQRSTUV');
    assert.equal(body.children.at(-1).textContent, '');
    assert.equal(bubble.dir, 'rtl');
  }
  const first = feed.children[0];
  context.NowaPhoneCards(feed, [message]);
  assert.equal(feed.children.length, 2); assert.equal(feed.children[0], first);
}
// An English or Franco message inside the Arabic phone is one left-to-right run; an Arabic one stays right to left.
for (const [lang, dir] of [['en', 'ltr'], ['franco', 'ltr'], ['ar', 'rtl']]) {
  const feed = element(), msg = {outbox_id: 9, recipient_name: 'Fictional Patient', lang, body: 'Leave now, number 3. Call +201000000001', created_at: '2026-10-09T16:00:00Z', status: 'delivered'};
  context.NowaPhoneCards(feed, [msg]);
  const bubble = feed.children[0].children[1].children[1];
  assert.equal(bubble.dir, dir, lang); assert.equal(bubble.children[0].dir, dir, lang);
}
console.log('PASS: patient and drawer use sender, bubble, meta with no blank body edges or duplicate cards');
