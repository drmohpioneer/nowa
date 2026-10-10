// Run the shipped settings wiring with a saved override before the submit button.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(tag = 'div', type) {
  const classes = new Set(), events = {};
  return {tag, type, children: [], events, textContent: '', hidden: true, disabled: false, dataset: {},
    classList: {add: c => classes.add(c), remove: c => classes.delete(c)},
    setAttribute(k, v) {this[k] = v;}, removeAttribute(k) {delete this[k];},
    addEventListener(k, fn) {events[k] = fn;}, append(...nodes) {this.children.push(...nodes);},
    replaceChildren(...nodes) {this.children = nodes;},
    querySelectorAll(selector) {
      if (selector !== 'button' && selector !== 'button[type="submit"], button:not([type])') return [];
      const children = this.children.flatMap(n => [n, ...n.querySelectorAll(selector)]);
      return children.filter(n => n.tag === 'button' && (selector === 'button' || n.type === 'submit' || !n.type));
    }, querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}};
}
async function check(language) {
  const labels = language === 'ar' ? {error: 'خطأ', saved: 'اتحفظ', telegram_fallback: 'لو ما اتفتحش، اضغط الزرار.',
    telegram_repeated: 'جرّب تاني', check_fields: 'راجع: ', telegram: 'تليجرام', delete_override: 'امسح'} :
    {error: 'Error', saved: 'Saved', telegram_fallback: 'If it did not open, press the button.',
      telegram_repeated: 'Try again', check_fields: 'Check: ', telegram: 'Telegram', delete_override: 'Remove'};
  const ids = ['hours', 'overrides', 'timing', 'info', 'lang', 'saved-overrides', 'message',
    'telegram', 'telegram-url', 'telegram-status'];
  const nodes = Object.fromEntries(ids.map(id => [id, element()]));
  for (const id of ['hours', 'overrides', 'timing', 'info', 'lang']) {
    nodes[id].append(element('button')); nodes[id].elements = {namedItem: () => ({checked: false})};
  }
  const save = nodes.overrides.children[0]; nodes.overrides.children.unshift(nodes['saved-overrides']);
  const current = {hours: [], items: [], lang: language, overrides: [{date: '2026-10-08', date_display: '8 October', closed: false}]};
  const learned = ['visit', 'gap', 'no_show'].map(key => ({dataset: {learned: key}, textContent: ''}));
  Object.assign(labels, language === 'ar' ? {
    learned_visit_value: '{value} {minutes} · {n} {visits}', learned_gap_value: '{value} {minutes} · {n} {evenings}',
    learned_no_show_value: '{value}% · {n} {evenings}', still_learning: 'لسه بيتعلم',
    unit_minutes_few: 'دقايق', unit_minutes_many: 'دقيقة', unit_evenings_few: 'ليالي', unit_evenings_many: 'ليلة',
    unit_visits_few: 'كشوفات', unit_visits_many: 'كشف'
  } : {
    learned_visit_value: '{value} {minutes} · {n} {visits}', learned_gap_value: '{value} {minutes} · {n} {evenings}',
    learned_no_show_value: '{value}% · {n} {evenings}', still_learning: 'still learning',
    unit_minutes_few: 'minutes', unit_minutes_many: 'minutes', unit_evenings_few: 'evenings', unit_evenings_many: 'evenings',
    unit_visits_few: 'visits', unit_visits_many: 'visits'
  });
  current.learned = {visit: {value: 13.3, n: 20, still_learning: false},
    gap: {value: 0, n: 0, still_learning: true}, no_show: {value: 12, n: 3, still_learning: false}};
  let resolve, requests = [], opens = [];
  const context = vm.createContext({document: {body: {dataset: {mode: 'settings'}}, documentElement: {lang: language}, querySelector: () => null, cookie: '',
    getElementById: id => nodes[id] || null, createElement: element,
    querySelectorAll: selector => selector === '#translations [data-key]' ?
      Object.entries(labels).map(([key, textContent]) => ({dataset: {key}, textContent})) :
      selector === '[data-learned]' ? learned : []},
    crypto: {randomUUID: () => 'fixture-intent'}, FormData: function () {return [['date', '2026-10-08']];},
    window: {NowaHours: {sync() {}, values: () => []}, open: (...args) => opens.push(args), matchMedia: () => ({matches: true})},
    fetch: async (path, options) => {
      requests.push({path, options});
      if (path.startsWith('/d/api/settings?')) return {ok: true, json: async () => current};
      return new Promise(r => {resolve = r;});
    },
  });
  vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('nowa/web/static/dashboard.js', 'utf8'), context);
  await new Promise(setImmediate);
  // 13.3 and 20 take the singular noun, 3 takes the plural (Arabic 3 to 10), 0 the singular.
  assert.equal(learned[0].textContent, '13 ' + labels.unit_minutes_many + ' · 20 ' + labels.unit_visits_many);
  assert.equal(learned[1].textContent, '0 ' + labels.unit_minutes_many + ' · 0 ' + labels.unit_evenings_many + ' · ' + labels.still_learning);
  assert.equal(learned[2].textContent, '12% · 3 ' + labels.unit_evenings_few);
  const edit = nodes['saved-overrides'].children[0].children[0];
  assert.equal(nodes.overrides.querySelector('button'), edit, 'auxiliary control precedes save in the real layout');
  const request = nodes.overrides.events.submit({preventDefault() {}});
  assert(save.disabled); assert(!edit.disabled); assert.equal(save['aria-busy'], 'true');
  const count = requests.length;
  await nodes.overrides.events.submit({preventDefault() {}}); assert.equal(requests.length, count);
  resolve({ok: true, json: async () => ({ok: true})}); await request;
  assert(!save.disabled); assert.equal(nodes.message.textContent, labels.saved);

  const telegram = nodes.telegram, status = nodes['telegram-status'];
  const launch = telegram.events.click(); assert(telegram.disabled); assert.equal(telegram['aria-busy'], 'true');
  await telegram.events.click(); assert.equal(requests.length, count + 2);
  const url = 'https://t.me/fictional_bot?start=d_fixture';
  resolve({ok: true, json: async () => ({url})}); await launch;
  assert.deepEqual(opens[0], [url, '_blank', 'noopener']);
  assert.equal(nodes['telegram-url'].href, url); assert.equal(nodes['telegram-url'].hidden, false);
  assert.equal(status.textContent, labels.telegram_fallback); assert(!telegram.disabled);
  const failure = telegram.events.click();
  resolve({ok: false, status: 422, json: async () => ({detail: {fields: ['telegram']}})}); await failure;
  assert.equal(status.textContent, labels.check_fields + labels.telegram); assert(!telegram.disabled);
}
(async () => {await check('ar'); await check('en');
  console.log('PASS: merged override submit pending/cleanup, duplicate guards and bilingual Telegram launch/fallback/422');
})().catch(error => {console.error(error); process.exitCode = 1;});
