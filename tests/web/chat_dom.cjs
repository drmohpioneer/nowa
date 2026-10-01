// Offline DOM/transport regression check: node tests/web/chat_dom.cjs
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const nodes = new Map(), requests = [];
function element() {
    return {textContent: '', value: '', disabled: false, children: [], setAttribute() {},
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
const strings = Object.fromEntries(Object.entries(bookTexts).map(([lang, book_text]) =>
    [lang, {send: 'Send', message: 'Message', book_chip: 'Book', book_text, emergency: '123', error: 'Error'}]));
nodes.get('chat-config').textContent = JSON.stringify({slug: 'test', strings, faq: [], areas: []});
const replies = [
    {lang: 'en', reply: 'First answer\nFirst source\nhttps://example.test/first', buttons: []},
    {lang: 'franco', reply: 'Booking card', buttons: [{label: 'Day', action: {kind: 'book_day', payload: {}}}]},
    {lang: 'ar', reply: 'Lookup card', buttons: [{label: 'Lookup', action: {kind: 'lookup', payload: {}}}]},
    {lang: 'en', reply: 'Later answer\nLater source\nhttps://example.test/later', buttons: []},
];
let resolveTurn;
const context = {
    document: {getElementById: id => { assert(nodes.has(id), id); return nodes.get(id); },
        createElement: element, documentElement: {}},
    crypto: {randomUUID: () => 'test-id'},
    fetch: async (url, options) => {
        const data = JSON.parse(options.body); requests.push({url, data});
        if (url.endsWith('/session')) return {ok: true, json: async () => ({session: 'session'})};
        assert(url.endsWith('/turn'));
        await new Promise(resolve => { resolveTurn = resolve; });
        return {ok: true, json: async () => replies.shift()};
    },
};
vm.runInNewContext(fs.readFileSync('nowa/web/static/chat.js', 'utf8'), context);
(async () => {
    await new Promise(setImmediate);
    const input = nodes.get('message'), chip = nodes.get('book-chip');
    input.value = 'Unfinished patient draft';
    for (const text of Object.values(bookTexts)) {
        const pending = chip.onclick();
        assert.equal(input.value, 'Unfinished patient draft');
        assert.equal(chip.disabled, true);
        const count = requests.length;
        await chip.onclick();
        assert.equal(requests.length, count, 'busy chip must not duplicate a turn');
        assert.equal(requests.at(-1).data.text, text);
        resolveTurn(); await pending;
        assert.equal(input.value, 'Unfinished patient draft');
        assert.equal(chip.disabled, false);
    }
    const pending = nodes.get('message-form').onsubmit({preventDefault() {}});
    assert.equal(input.value, '');
    assert.equal(requests.at(-1).data.text, 'Unfinished patient draft');
    assert.deepEqual(requests.at(-1).data.history, [
        {role: 'user', text: bookTexts.ar}, {role: 'assistant', text: 'First answer\nFirst source\nhttps://example.test/first'},
        {role: 'user', text: bookTexts.en}, {role: 'user', text: bookTexts.franco},
    ]);
    resolveTurn(); await pending;
    const children = nodes.get('chat').children;
    assert.equal(children.at(-1), nodes.get('controls'));
    const links = children.filter(child => child.href);
    assert.equal(links.length, 2);
    for (const [index, link] of links.entries()) {
        assert.equal(link.className, 'bubble');
        assert.equal(link.rel, 'noopener noreferrer');
        assert.equal(link.target, '_blank');
        const bubble = children[children.indexOf(link) - 1];
        assert.equal(bubble.textContent, index === 0
            ? 'First answer\nFirst source\nhttps://example.test/first'
            : 'Later answer\nLater source\nhttps://example.test/later');
        assert.equal(bubble.className, 'bubble');
    }
    console.log('PASS: source links stay with their replies before controls across turns; localized chips preserve drafts; shared form submission and history rules');
})().catch(error => { console.error(error); process.exitCode = 1; });
