// Run the shipped question cards, adjacent feedback and phone stop handling without a browser.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
function node(tag='div') {
  const events = {};
  return {tag, events, dataset:{}, children:[], value:'', textContent:'', hidden:false, disabled:false,
    classList:{add(){},remove(){}}, setAttribute(key,value){this[key]=value;},removeAttribute(key){delete this[key];},
    addEventListener(key, callback){events[key]=callback;}, append(...items){for(const item of items){item.parentElement=this;this.children.push(item);}},
    replaceChildren(...items){this.children=[];this.append(...items);}, scrollIntoView(){this.scrolled=true;},focus(){this.focused=true;},
    querySelector(selector){return this.children.find(child=>child.className?.includes(selector.slice(1))) || null;},
    after(item){this.parentElement?.append(item);}, closest(){return this.parentElement;}};
}
const panel = node(), top = node(), context = vm.createContext({document:{getElementById:id=>id==='questions'?panel:top,
  createElement:node,createElementNS:(_,tag)=>node(tag),createTextNode:text=>Object.assign(node('text'),{textContent:text})},
  window:{matchMedia:()=>({matches:true})},intent:()=> 'fixture-key',t:key=>key, message:text=>{top.textContent=text;},
  api:async(path,method,body)=>{ if(method==='POST') {context.actionCalls.push([path,body]);context.position++;return data.results[context.position-1];} return data.states[context.position]; },
  bindButton:(button,action)=>{button.click=action;},setTimeout:()=>0});
context.position=0;context.actionCalls=[];
const source=fs.readFileSync('nowa/web/static/dashboard.js','utf8');
vm.runInContext(source.slice(source.indexOf('function questionIcon'),source.indexOf('if (document.getElementById("questions"))')),context);
const group=state=>panel.children.find(child=>child.dataset.group===state), card=state=>group(state).children.find(child=>child.tag==='form');
const button=(state,index)=>card(state).children.find(child=>child.className==='acts').children[index];
const text=element=>[element.textContent,...element.children.map(text)].join(' ');
(async()=>{
  await vm.runInContext('loadQuestions()',context);
  for (let index=0;index<4;index++) { const action=button('open',index); assert.equal(action.children[0].tag,'svg'); assert(action.children[0].children[0].href.startsWith('#i-')); assert(action.children[1].textContent); }
  let draft=card('open').children.find(child=>child.tag==='textarea');assert(draft.hidden);
  await button('open',0).click();assert(!draft.hidden&&draft.focused);assert.equal(context.actionCalls.length,0);
  draft.value='A fictional answer';await button('open',0).click();assert.equal(context.actionCalls[0][1].text,'A fictional answer');
  assert(!button('open',1).disabled);await button('open',1).click();assert(!card('open'));assert(text(panel).includes('q_saved'));
  // Next server snapshot has a separate open question; Later updates its group immediately.
  data.states[2]=data.nextQuestion;context.position=2;await vm.runInContext('loadQuestions()',context);
  await button('open',2).click();assert(!card('open'));assert(card('later'));assert(text(group('later')).includes('later_group'));
  await button('later',3).click();assert(!card('later'));assert(text(panel).includes('q_dismissed'));
  vm.runInContext(fs.readFileSync('nowa/web/static/feedback.js','utf8'),context);
  const form=node('form'), control=node('button');form.append(control);
  await context.window.NowaFeedback.pending(control,async()=>{throw new Error('translated refusal');},top,{adjacent:true});
  const status=form.querySelector('.local-feedback');assert.equal(status.textContent,'translated refusal');assert(status.scrolled);assert.equal(top.textContent,status.textContent);
  // The stop must also ignore a poll already in flight at successful completion.
  let resolve;context.fetch=()=>new Promise(done=>{resolve=done;});context.document.querySelectorAll=()=>[];
  vm.runInContext(fs.readFileSync('nowa/web/static/phone.js','utf8'),context);
  let errors=0;const phone=node();const stop=context.window.NowaPhone(phone,'/signup/phone',()=>errors++);stop();
  resolve({ok:false,status:403});await new Promise(done=>setImmediate(done));assert.equal(errors,0);assert.equal(phone.children.length,0);
  console.log('PASS: four question actions, Later group, adjacent feedback, stopped in-flight poll');
})().catch(error=>{console.error(error);process.exitCode=1;});
