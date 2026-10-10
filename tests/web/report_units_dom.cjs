// The evening report: every duration shows its unit, names use the Arabic comma, an empty section is hidden.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(tag = 'div') {
  const attrs = {};
  return {tag, children: [], textContent: '', hidden: false, className: '', dataset: {}, attrs,
    setAttribute(k, v) {attrs[k] = v;}, removeAttribute(k) {delete this[k]; delete attrs[k];},
    classList: {add() {}, remove() {}}, addEventListener() {},
    append(...nodes) {this.children.push(...nodes);}, replaceChildren(...nodes) {this.children = nodes;},
    querySelectorAll: () => [], querySelector: () => null};
}
async function check(language, answers) {
  const ar = language === 'ar';
  const labels = {error: 'x', report_booked: 'b', report_avg_visit: 'v', report_avg_wait: 'w', report_no_show: 'n',
    unit_minutes_few: ar ? 'دقايق' : 'minutes', unit_minutes_many: ar ? 'دقيقة' : 'minutes'};
  const nodes = Object.fromEntries(['message', 'report-summary', 'health-answers', 'health-section'].map(id => [id, element()]));
  nodes['health-section'].hidden = true;
  const report = {booked: 12, avg_visit: 13, avg_wait: 5, no_show_names: ['A', 'B'], failed_names: [], health_answers: answers, origins: []};
  const context = vm.createContext({document: {body: {dataset: {mode: 'report', eveningId: '1'}}, documentElement: {lang: language},
    querySelector: () => null, cookie: '', getElementById: id => nodes[id] || null, createElement: element,
    querySelectorAll: selector => selector === '#translations [data-key]' ?
      Object.entries(labels).map(([key, textContent]) => ({dataset: {key}, textContent})) : []},
    crypto: {randomUUID: () => 'k'}, FormData: function () {return [];},
    window: {NowaHours: {sync() {}, values: () => []}, matchMedia: () => ({matches: true})},
    fetch: async () => ({ok: true, json: async () => report})});
  vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('nowa/web/static/dashboard.js', 'utf8'), context);
  await new Promise(setImmediate);
  const cards = Object.fromEntries(nodes['report-summary'].children.filter(c => c.className === 'card report-metric').map(c => [c.children[0].textContent, c.children[1].textContent]));
  assert.equal(cards.v, '13 ' + labels.unit_minutes_many);
  assert.equal(cards.w, '5 ' + labels.unit_minutes_few);
  assert.equal(String(cards.b), '12');
  assert.equal(nodes['report-summary'].children.at(-1).textContent, 'n: A' + (ar ? '، ' : ', ') + 'B');
  return nodes['health-section'].hidden;
}
(async () => {
  assert.equal(await check('ar', []), true); assert.equal(await check('en', []), true);
  assert.equal(await check('ar', [{question: 'q', answer: 'a', at_display: '1', source_label: 's'}]), false);
  console.log('PASS: report durations carry units, Arabic comma, empty health section hidden');
})().catch(error => {console.error(error); process.exitCode = 1;});
