// Run real signup handlers: completion must busy its submit, never the location button.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(type) {
  const events = {}, classes = new Set();
  return {type, events, hidden: false, disabled: false, textContent: '', children: [],
    append(...items) {this.children.push(...items);}, replaceChildren() {this.children=[];},
    setAttribute(k, v) {this[k] = v;}, removeAttribute(k) {delete this[k];},
    classList: {add: c => classes.add(c), remove: c => classes.delete(c)},
    addEventListener(k, fn) {events[k] = fn;}, remove() {},
    before(node) {this.beforeNode = node;},
    querySelector(selector) {return this.children.find(n => selector === 'button' || n.type === 'submit' || !n.type);}};
}
async function check(language, width) {
  const labels = language === 'ar' ? {invalid_mobile:'رقم غلط',wrong_code:'كود غلط',no_working_days:'اختار يوم',phone_complete:'جاهز', error: 'خطأ', sent: 'الكود اتبعت', sent_telegram: 'افتح تليجرام وشارك رقمك', request_code: 'استلم الكود على تليجرام'} :
    {invalid_mobile:'Invalid mobile',wrong_code:'Wrong code',no_working_days:'Choose days',phone_complete:'Ready', error: 'Error', sent: 'Code sent', sent_telegram: 'Open Telegram and share your number', request_code: 'Get the code on Telegram'};
  const ids = ['signup-message', 'verification', 'code-form', 'verify-form', 'complete-form', 'pin-kind',
    'locate', 'location-status', 'why-telegram', 'signup-success', 'chat-url', 'poster-url', 'success-mobile', 'signup-phone'];
  const nodes = Object.fromEntries(ids.map(id => [id, element()]));
  const complete = nodes['complete-form'], locate = nodes.locate, submit = element(); locate.type = 'button';
  complete.children = [locate, submit]; complete.elements = {agree: {checked: true}};
  nodes['code-form'].children = [element()]; nodes['verify-form'].children = [element()];
  let resolve, calls = 0, stopped = 0, poll;
  let linkStatus = {status:'pending',usable:true,remaining_seconds:900,qr:'data:image/svg+xml;base64,fixture'};
  const mobile = {value:'01000000005',focus() {this.focused=true;}};
  nodes['code-form'].elements = {mobile};
  const context = vm.createContext({document: {documentElement: {lang: language}, getElementById: id => nodes[id] || null,
    createElement: () => element(), querySelectorAll: selector => selector === "[data-counter]" ? [] : Object.entries(labels).map(([key, textContent]) => ({dataset: {key}, textContent}))},
    window: {NowaPhone: () => () => {stopped++;}, NowaHours: {values: () => [{weekday: 1, start: '19:00', end: '23:00'}]}, matchMedia: () => ({matches: width>=900})},
    crypto: {randomUUID: () => 'fixture-key'}, sessionStorage: {getItem() {return null;}},
    FormData: function () {return [['mobile', '01000000005'], ['pin_kind', 'area'], ['area_id', '1']];},
    setTimeout: (f,ms) => {if(ms<=3000) poll=f; return 1;}, clearTimeout() {}, Date,
    fetch: async (url) => {if(url==='/telegram/link-status') return {ok:true,json:async()=>({...linkStatus})}; calls++; return new Promise(r => {resolve = r;});},
  });
  vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('nowa/web/static/telegram-link.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('nowa/web/static/signup.js', 'utf8'), context);
  const completion = complete.events.submit({preventDefault() {}});
  assert(submit.disabled); assert(!locate.disabled); assert.equal(submit['aria-busy'], 'true');
  await complete.events.submit({preventDefault() {}}); assert.equal(calls, 1);
  resolve({ok: false, status: 400, json: async () => ({reason: 'refused'})}); await completion;
  assert(!submit.disabled); assert.equal(submit['aria-busy'], undefined); assert.equal(nodes['signup-message'].textContent, labels.error);
  for (const reason of ['invalid_mobile', 'wrong_code', 'no_working_days']) {
    const refused = complete.events.submit({preventDefault() {}});
    resolve({ok:false,status:400,json:async()=>({reason})}); await refused;
    assert.equal(nodes['signup-message'].textContent, labels[reason]);
  }
  const code = nodes['code-form'].events.submit({preventDefault() {}});
  const url = 'https://t.me/fictional_bot?start=s_fixture';
  resolve({ok: true, json: async () => ({telegram_url: url})}); await code;
  assert(nodes['code-form'].hidden); assert(!nodes['why-telegram'].hidden);
  const link = nodes['why-telegram'].beforeNode.children[0].children[0];
  assert.equal(link.href, url); assert.equal(link.target, '_blank'); assert.equal(link.rel, 'noopener');
  assert.equal(link.textContent, labels.request_code); assert.equal(nodes['signup-message'].textContent, labels.sent_telegram);
  await new Promise(setImmediate);
  const widget=nodes['why-telegram'].beforeNode.children[0];
  assert.equal(widget.children[3].hidden,width<900);
  linkStatus={...linkStatus,status:'contact_mismatch'};await poll();
  assert.equal(widget.children[5].hidden,false);
  widget.children[5].onclick();
  assert.equal(nodes['code-form'].hidden,false);assert.equal(nodes['verify-form'].hidden,true);
  assert.equal(mobile.value,'01000000005');assert(mobile.focused);

  const demoCode = nodes['code-form'].events.submit({preventDefault() {}});
  resolve({ok:true,json:async()=>({})}); await demoCode;
  const successful = complete.events.submit({preventDefault() {}});
  resolve({ok:true,json:async()=>({chat_url:'/c/fictional',poster_url:'/d/poster',mobile:'fictional'})}); await successful;
  assert.equal(stopped,1); assert.equal(nodes['signup-message'].textContent,'');
  assert(complete.hidden && !nodes['signup-success'].hidden);
  assert.equal(nodes['signup-phone'].children[0].textContent,labels.phone_complete);

}
(async () => {for(const width of [390,900,1280]) {await check('ar',width);await check('en',width);}
  console.log('PASS: signup submits disable the right control, reject duplicate requests, recover after errors and keep Telegram help beside the bot link');
})().catch(error => {console.error(error); process.exitCode = 1;});
