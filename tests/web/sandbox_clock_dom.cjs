// Real rendered clock attributes and API responses; no browser or server.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const clock = {dataset: {iso: input.iso}, textContent: input.initial_text};
const buttons = [10, 60].map(minutes => ({dataset: {advance: String(minutes)}}));
const jump = {}, controls = {
  dataset: {paperStart: input.snapshots.at(-1).now}, querySelectorAll: () => buttons,
};
const nodes = {'sandbox-clock': clock, 'sandbox-controls': controls, 'sandbox-jump': jump};
const requested = [];
let refreshes = 0;
const context = vm.createContext({
  document: {documentElement: {lang: input.lang}, body: {dataset: {clinicSlug: 'fictional'}},
    getElementById: id => nodes[id]},
  window: {NowaPhone() {}}, URL, location: {href: 'https://nowa.example/d'},
  history: {replaceState() {}}, t: key => input.texts[key], intent: () => 'test-key',
  bindButton: (button, action) => { button.click = action; },
  api: async (path, method, body) => {
    assert.equal(path, '/d/api/sandbox/advance'); assert.equal(method, 'POST');
    assert(Number.isFinite(body.minutes));
    requested.push(body.minutes); return input.snapshots[requested.length - 1];
  }, refresh: async () => { refreshes++; },
});
vm.runInContext(fs.readFileSync('nowa/web/static/clock.js', 'utf8'), context);
const source = fs.readFileSync('nowa/web/static/dashboard.js', 'utf8');
vm.runInContext(source.slice(source.indexOf('const sandboxControls ='), source.indexOf('function questionIcon(')), context);
const expected = input.lang === 'ar' ? 'الثلاثاء 13 أكتوبر، 22:40' : 'Tue 13 Oct, 22:40';
function assertDisplay(value, iso) {
  assert.equal(clock.textContent, value);
  assert.equal(clock.dataset.iso, iso);
  assert(!/\d{4}-\d{2}-\d{2}T/.test(clock.textContent));
  assert(!/[٠-٩۰-۹]/.test(clock.textContent));
}
(async () => {
  assertDisplay(expected, input.iso);
  await buttons[0].click();
  assertDisplay(expected.replace('22:40', '22:50'), input.snapshots[0].now);
  await buttons[1].click();
  assertDisplay(expected.replace('22:40', '23:50'), input.snapshots[1].now);
  await jump.click();
  assertDisplay(input.lang === 'ar' ? 'الأربعاء 14 أكتوبر، 03:00' : 'Wed 14 Oct, 03:00', input.snapshots[3].now);
  assert.deepEqual(requested, [10, 60, 180, 10]);
  assert.equal(refreshes, 3);
  await jump.click(); // Already at the paper start: no extra command.
  assert.equal(requested.length, 4);
  console.log('PASS: localized clock, preserved ISO, bounded jump across midnight');
})().catch(error => { console.error(error); process.exitCode = 1; });
