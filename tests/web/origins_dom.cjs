const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function element() {
  return {children: [], dataset: {}, style: {}, textContent: '', hidden: false, value: '',
    classList: {toggle() {}}, append(...nodes) { this.children.push(...nodes); },
    prepend(...nodes) { this.children.unshift(...nodes); }, replaceChildren(...nodes) { this.children = nodes; },
    setAttribute() {}, querySelectorAll() { return []; }, querySelector() { return null; },
    insertBefore(node) { this.children.push(node); }};
}
const nodes = new Map(), get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
const text = node => [node.textContent, ...node.children.map(text)].join(' ');
const source = fs.readFileSync('nowa/web/static/dashboard.js', 'utf8');
const context = vm.createContext({document: {getElementById: get, createElement: element, documentElement: {lang: 'en'}, body: {dataset: {mode: 'report', eveningId: input.report.evening_id}}},
  Date, URL, t: key => input.texts[key] || key, bindButton() {}, message: error => { throw Error(error); }, api: async () => input.board});
vm.runInContext(source.slice(source.indexOf('async function refresh()'), source.indexOf('async function command(')), context);
(async () => {
  await vm.runInContext('refresh()', context);
  const label = input.board.rows[0].origin_display;
  assert(text(get('queue')).includes(label));
  assert.equal(get('queue').children[0].children[1].children[0].textContent, label);
  context.api = async () => input.report;
  vm.runInContext(source.slice(source.indexOf('if (document.body.dataset.mode === "report")'), source.indexOf('window.NowaFeedback.counters')), context);
  await new Promise(resolve => setImmediate(resolve));
  assert(text(get('report-summary')).includes('1 · ' + label));
  assert(get('report-summary').children.some(n => n.textContent === '1 · ' + label));
  console.log('PASS: origin labels rendered as text on board and report');
})().catch(error => { console.error(error); process.exitCode = 1; });
