// Use labels and questions supplied by real doctor page/API responses.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function node() {
  return {dataset: {}, children: [], textContent: '', append(...xs) {this.children.push(...xs);},
    replaceChildren() {this.children = [];}, setAttribute() {}, addEventListener() {}};
}
const panel = node(), source = fs.readFileSync('nowa/web/static/dashboard.js', 'utf8');
const context = vm.createContext({document: {
  querySelectorAll: () => Object.entries(input.labels).map(([key, textContent]) => ({dataset: {key}, textContent})),
  getElementById: () => panel, createElement: node, createElementNS: node, createTextNode: text => Object.assign(node(), {textContent:text}),
}, console, api: async () => input.questions, bindButton() {}});
vm.runInContext(source.slice(0, source.indexOf('const message =')), context);
vm.runInContext(source.slice(source.indexOf('function questionIcon'),
  source.indexOf('if (document.getElementById("questions"))')), context);
(async () => {
  await vm.runInContext('loadQuestions()', context);
  const lines = panel.children[0].children[0].children.map(n => n.textContent);
  for (const expected of input.expected) assert(lines.includes(expected), `Missing asker line: ${expected}; got ${lines}`);
  assert(!lines.includes(input.labels.error));
  console.log('PASS: real doctor page labels render identified and anonymous question askers');
})().catch(error => {console.error(error); process.exitCode = 1;});
