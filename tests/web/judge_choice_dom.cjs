// Run the real judge.js: a valid code offers two actions; the ready one posts once and shows the login.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(extra = {}) {
  const events = {};
  return Object.assign({events, hidden: false, disabled: false, textContent: '', children: [], dataset: {},
    append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; },
    addEventListener(k, fn) { events[k] = fn; },
    querySelector() { return this.button; }}, extra);
}
async function check(lang) {
  const labels = {error: 'E', judge_wrong_code: 'W', field_agree: 'A', judge_credentials: 'L {mobile} P {password}'};
  const ids = ['judge-form', 'signup-message', 'judge-choice', 'own-clinic', 'ready-clinic', 'ready-agree',
    'ready-success', 'ready-credentials', 'ready-chat', 'ready-poster'];
  const nodes = Object.fromEntries(ids.map(id => [id, element()]));
  nodes['judge-form'].button = element(); nodes['judge-form'].elements = {code: {value: 'fictional'}};
  nodes['judge-choice'].hidden = true; nodes['ready-success'].hidden = true;
  nodes['ready-agree'].checked = false;
  const store = {}, assigned = [], posts = [];
  let wrong = false;
  const context = vm.createContext({
    URL, console,
    location: {href: 'https://example.test/judge?lang=' + lang, assign: url => assigned.push(url)},
    sessionStorage: {setItem: (k, v) => { store[k] = v; }},
    document: {getElementById: id => nodes[id], createElement: () => element(),
      querySelectorAll: () => Object.entries(labels).map(([key, textContent]) => element({dataset: {key}, textContent}))},
    window: {NowaFeedback: {
      pending: async (_, work, statusEl) => { try { await work(); statusEl.textContent = ''; } catch (e) { statusEl.textContent = e.message; statusEl.fieldEls = e.fieldEls; } },
      requestError: (response, data, l, generic) => new Error(generic)}},
    fetch: async (path, init) => {
      posts.push([path, JSON.parse(init.body)]);
      if (path === '/judge/start') return wrong ? {ok: false, json: async () => ({reason: 'wrong_code'})} : {ok: true, json: async () => ({signup_token: 'judge|t'})};
      return {ok: true, json: async () => ({chat_url: '/c/dr-x', poster_url: '/d/poster', mobile: '+201000000900', password: 'abc234abc234'})};
    }});
  vm.runInContext(fs.readFileSync('nowa/web/static/judge.js', 'utf8'), context);
  const submit = () => nodes['judge-form'].events.submit({preventDefault() {}});
  wrong = true; await submit();
  assert.equal(nodes['signup-message'].textContent, 'W');
  assert(nodes['judge-choice'].hidden && !nodes['judge-form'].hidden);
  wrong = false; await submit();
  assert(nodes['judge-form'].hidden && !nodes['judge-choice'].hidden);
  assert(nodes['ready-clinic'].events.click && nodes['own-clinic'].events.click);
  await nodes['ready-clinic'].events.click();
  assert.equal(nodes['signup-message'].textContent, 'A');
  assert.equal(nodes['signup-message'].fieldEls[0], nodes['ready-agree']);
  assert(nodes['ready-success'].hidden && !posts.some(p => p[0] === '/judge/ready'));
  nodes['ready-agree'].checked = true;
  await nodes['ready-clinic'].events.click();
  assert.deepEqual(posts.filter(p => p[0] === '/judge/ready'), [['/judge/ready', {signup_token: 'judge|t', agree: true}]]);
  assert(!nodes['ready-success'].hidden && nodes['judge-choice'].hidden);
  assert.equal(nodes['ready-chat'].href, '/c/dr-x');
  assert.equal(nodes['ready-credentials'].children.map(c => c.textContent ?? c).join(''), 'L +201000000900 P abc234abc234');
  assert.equal(assigned.length, 0);
  // The other action keeps the existing form: it hands over the token and opens /start.
  nodes['own-clinic'].events.click();
  assert.equal(assigned[0], '/start?lang=' + lang);
  assert('nowa-judge-signup' in store);
}
(async () => { await check('ar'); await check('en'); console.log('PASS: judge two actions, ready clinic and own form'); })().catch(e => { console.error(e); process.exit(1); });
