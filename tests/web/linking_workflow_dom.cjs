const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const width = Number(process.argv[2]);
function element(tag = 'div') {
  return {tag, children: [], hidden: false, textContent: '', disabled: false,
    append(...els) {this.children.push(...els);},
    setAttribute(k,v) {this[k]=v;}, removeAttribute(k) {delete this[k];},
    replaceChildren() {this.children=[];},
  };
}
async function run() {
  let state = {status:'pending', remaining_seconds:900, usable:true, qr:'data:image/svg+xml;base64,old'};
  let timer, fail = false, resolveRenew, renewCalls = 0, edited = 0;
  const requests = [], media = {matches: width >= 900, addEventListener(_,f) {this.change=f;}, removeEventListener() {}};
  const window = {matchMedia: query => {assert.equal(query, '(min-width: 900px)'); return media;}};
  const context = vm.createContext({window, document:{createElement:element}, Date,
    setTimeout:(f,ms) => {if(ms<=3000) {timer=f;return 1;} return 2;}, clearTimeout:id => {if(id===1) timer=null;},
    fetch:async (url, options) => {requests.push(JSON.parse(options.body)); assert.equal(url,'/telegram/link-status');
      if (fail) throw new Error('offline'); return {ok:true,json:async()=>({...state})};},
  });
  vm.runInContext(fs.readFileSync('nowa/web/static/telegram-link.js','utf8'),context);
  const labels = {telegram_scan:'SCAN',telegram_install:'INSTALL',telegram_renew:'RENEW',telegram_edit:'EDIT',
    telegram_mismatch:'MISMATCH',telegram_patient_linked:'LINKED',telegram_error:'ERROR',telegram_retry:'RETRY'};
  const parent = element();
  const widget = window.NowaTelegramLink(parent,'https://t.me/bot?start=p_old',labels, {
    openLabel:'OPEN', edit:()=>{edited++;}, renew:async()=>{renewCalls++;return new Promise(r=>{resolveRenew=r;});},
  });
  await new Promise(setImmediate);
  const [open, renew, note, qr, message, edit, retry] = widget.root.children;
  assert.equal(note.textContent,'INSTALL'); assert.equal(open.href,'https://t.me/bot?start=p_old');
  assert.equal(qr.hidden,width<900); assert.equal(qr.children[0].src,state.qr);
  assert.equal(qr.children[1].textContent,'SCAN'); assert.equal(renew.hidden,true);
  // Resize live, including exactly the 900 px breakpoint.
  media.matches=!media.matches;media.change();assert.equal(qr.hidden,!media.matches);
  media.matches=width>=900;media.change();
  state={...state,status:'contact_mismatch',remaining_seconds:450};await timer();
  assert.equal(message.textContent,'MISMATCH');assert.equal(edit.hidden,false);
  state={...state,status:'contact_mismatch',usable:false};await timer();
  assert.equal(open.hidden,true);assert.equal(qr.hidden,true);assert.equal(renew.hidden,true);
  state={...state,status:'expired',remaining_seconds:0};await timer();
  assert.equal(renew.hidden,false);assert.equal(open.hidden,true);assert.equal(qr.hidden,true);
  const pending=renew.onclick();await renew.onclick();assert.equal(renewCalls,1);
  state={status:'pending',remaining_seconds:900,usable:true,qr:'data:image/svg+xml;base64,new'};
  resolveRenew('https://t.me/bot?start=p_new');await pending;await new Promise(setImmediate);
  assert.equal(open.href,'https://t.me/bot?start=p_new');assert.equal(qr.children[0].src,state.qr);
  assert.equal(qr.hidden,width<900);assert.equal(renew.hidden,true);
  assert.equal(requests.at(-1).url,open.href);assert.equal(requests.at(-1).qr,true);
  fail=true;await timer();assert.equal(message.textContent,'ERROR');assert.equal(retry.hidden,false);
  fail=false;state={...state,status:'contact_mismatch'};retry.onclick();await new Promise(setImmediate);
  edit.onclick();assert.equal(edited,1);assert.equal(timer,null);
  // Used successfully is distinct from a burned claim and stops polling.
  state={...state,status:'linked',usable:false};
  const linked=window.NowaTelegramLink(element(),'https://t.me/bot?start=p_done',labels,{openLabel:'OPEN'});
  await new Promise(setImmediate);assert.equal(linked.root.children[4].textContent,'LINKED');assert.equal(timer,null);
  assert.equal(linked.root.children[3].hidden,true);
  // D remains stopped: this component never creates a private booking URL.
  assert(!JSON.stringify(parent).includes('/l/'));
  console.log('PASS linking view at width',width);
}
run().catch(error=>{console.error(error);process.exitCode=1;});
