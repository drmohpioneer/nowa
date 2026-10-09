// Offline DOM/transport regression check: node tests/web/chat_dom.cjs
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const nodes = new Map(), requests = [];
function element() {
    const classes = new Set();
    return {textContent: '', value: '', disabled: false, children: [],
        classList: {add: c => classes.add(c), remove: c => classes.delete(c)},
        setAttribute(key, value) { this[key] = value; }, removeAttribute(key) { delete this[key]; }, addEventListener() {},
        append(...children) { this.children.push(...children); },
        insertBefore(child, reference) {
            const index = this.children.indexOf(reference);
            assert.notEqual(index, -1, 'reference must be an actual child');
            this.children.splice(index, 0, child);
        },
        replaceChildren() { this.children = []; }, querySelectorAll() { return []; }};
}
for (const id of ['chat-config', 'chat', 'controls', 'error', 'send', 'book-chip', 'message',
    'chat-emergency', 'message-label', 'faq', 'message-form']) nodes.set(id, element());
nodes.get('chat').append(nodes.get('controls'));
const bookTexts = {ar: 'عايز أحجز', en: 'I want to book', franco: '3ayez a7gez'};
const hourLabels = {ar: 'مواعيد العيادة', en: 'Clinic hours', franco: 'Mawa3eed el 3eyada'};
const strings = Object.fromEntries(Object.entries(bookTexts).map(([lang, book_text]) =>
    [lang, {send: 'Send', message: 'Message', book_chip: 'Book', book_text, emergency: '123', error: 'Error', faq_hours: hourLabels[lang]}]));
nodes.get('chat-config').textContent = JSON.stringify({slug: 'test', strings,
    faq: [{label: hourLabels.ar, action: {payload: {faq: 'hours'}}}], areas: []});
const replies = [
    {lang: 'en', reply: 'First answer\nFirst source', source: {label: 'First source', url: 'https://example.test/first', attribution: 'NHS licence'}, buttons: []},
    {lang: 'franco', reply: 'Booking card', buttons: [{label: 'Day', action: {kind: 'confirm', payload: {}}}]},
    {lang: 'ar', reply: 'Lookup card', buttons: [{label: 'Lookup', action: {kind: 'lookup', payload: {}}}]},
    {lang: 'en', reply: 'Later answer\nLater source', source: {label: 'Later source', url: 'https://example.test/later', attribution: 'NHS licence'}, buttons: []},
];
let resolveTurn;
const context = {
    document: {getElementById: id => nodes.get(id) || null,
        createElement: element, documentElement: {}},
    URLSearchParams, location: {search: ""}, setTimeout, clearTimeout,
    crypto: {randomUUID: () => 'test-id'},
    fetch: async (url, options) => {
        const data = JSON.parse(options.body); requests.push({url, data});
        if (url.includes('/session')) return {ok: true, json: async () => ({session: 'session'})};
        assert(url.endsWith('/turn'));
        await new Promise(resolve => { resolveTurn = resolve; });
        return {ok: true, json: async () => replies.shift()};
    },
};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('nowa/web/static/chat.js', 'utf8'), context);
(async () => {
    await new Promise(setImmediate);
    const input = nodes.get('message'), chip = nodes.get('book-chip');
    assert.equal(nodes.get('faq').children[0].textContent, hourLabels.ar);
    input.value = 'Unfinished patient draft';
    const replyLanguages = ['en', 'franco', 'ar'];
    for (const [index, text] of Object.values(bookTexts).entries()) {
        const pending = chip.onclick();
        assert.equal(input.value, 'Unfinished patient draft');
        assert.equal(chip.disabled, true);
        const count = requests.length;
        await chip.onclick();
        assert.equal(requests.length, count, 'busy chip must not duplicate a turn');
        assert.equal(requests.at(-1).data.text, text);
        resolveTurn(); await pending;
        assert.equal(nodes.get('faq').children[0].textContent, hourLabels[replyLanguages[index]]);
        assert.equal(nodes.get('error').textContent, '');
        assert.equal(input.value, 'Unfinished patient draft');
        assert.equal(chip.disabled, false);
    }
    const pending = nodes.get('message-form').onsubmit({preventDefault() {}});
    assert.equal(input.value, '');
    assert.equal(requests.at(-1).data.text, 'Unfinished patient draft');
    assert.deepEqual(requests.at(-1).data.history, [
        {role: 'user', text: bookTexts.ar}, {role: 'assistant', text: 'First answer\nFirst source'},
        {role: 'user', text: bookTexts.en}, {role: 'user', text: bookTexts.franco},
    ]);
    resolveTurn(); await pending;
    const children = nodes.get('chat').children;
    assert.equal(children.at(-1), nodes.get('controls'));
    const links = children.filter(child => child.href);
    assert.equal(links.length, 2);
    for (const [index, link] of links.entries()) {
        assert.equal(link.className, 'bubble');
        assert.equal(link.dir, 'ltr');
        assert.equal(link.title, 'NHS licence');
        assert(!link.textContent.includes('https://'));
        assert.equal(children.filter(c => c.textContent === link.textContent).length, 1);
        assert.equal(link.rel, 'noopener noreferrer');
        assert.equal(link.target, '_blank');
        const bubble = children[children.indexOf(link) - 1];
        assert.equal(bubble.textContent, index === 0
            ? 'First answer'
            : 'Later answer');
        assert.equal(bubble.className, 'bubble');
        assert.equal(bubble.dir, 'ltr');
    }
    console.log('PASS: source links stay with their replies before controls across turns; localized chips preserve drafts; shared form submission and history rules');
})().catch(error => { console.error(error); process.exitCode = 1; });
