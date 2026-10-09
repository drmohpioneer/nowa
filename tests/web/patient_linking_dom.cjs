const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
async function check(width) {
  function el(tag='div') {return {tag,children:[],hidden:false,disabled:false,textContent:'',events:{},
    append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},
    setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];},
    addEventListener(k,f){this.events[k]=f;},querySelector(){return this.button;}};}
  const form=el('form'), card=el(), submit=el('button');form.button=submit;form.action='/l/fictional/telegram';
  form.elements={form_token:{value:'signed-one'},exp:{value:123},last4:{value:'0000'}};
  const labels={open_label:'OPEN',telegram_install:'INSTALL',telegram_scan:'SCAN',telegram_renew:'RENEW',telegram_error:'ERROR'};
  const nodes={'patient-telegram-form':form,'patient-telegram-card':card,'linking-texts':{textContent:JSON.stringify(labels)}};
  let mint=0,poll,state={status:'pending',usable:true,remaining_seconds:900,qr:'data:image/svg+xml;base64,one'};
  const requests=[];
  const window={matchMedia:()=>({matches:width>=900})};
  const context=vm.createContext({window,Date,
    document:{getElementById:id=>nodes[id],createElement:el},
    setTimeout:(f,ms)=>{if(ms<=3000) poll=f;return 1;},clearTimeout(){},
    FormData:function(f){Object.assign(this,Object.fromEntries(Object.entries(f.elements).map(([k,v])=>[k,v.value])));},
    fetch:async(url,options)=>{
      if(url==='/telegram/link-status') return {ok:true,json:async()=>({...state})};
      requests.push(options);assert.equal(url,form.action);assert.equal(options.headers.Accept,'application/json');
      mint++;return {ok:true,json:async()=>({telegram_url:'https://t.me/bot?start=p_'+mint,form_token:'signed-'+mint,exp:123+mint})};
    },
  });
  for(const script of ['telegram-link.js','patient-telegram.js']) vm.runInContext(fs.readFileSync('nowa/web/static/'+script,'utf8'),context);
  await form.events.submit({preventDefault(){}});await new Promise(setImmediate);
  assert.equal(form.hidden,true);assert.equal(requests[0].body.form_token,'signed-one');assert.equal(requests[0].body.last4,'0000');
  const widget=card.children[0];assert.equal(widget.children[3].hidden,width<900);assert.equal(widget.children[2].textContent,'INSTALL');
  state={...state,status:'expired',remaining_seconds:0,usable:false};await poll();
  assert.equal(widget.children[1].hidden,false);
  state={status:'pending',remaining_seconds:900,usable:true,qr:'data:image/svg+xml;base64,two'};
  await widget.children[1].onclick();await new Promise(setImmediate);
  assert.equal(requests[1].body.form_token,'signed-1');assert.equal(requests[1].body.last4,'0000');
  assert.equal(widget.children[0].href,'https://t.me/bot?start=p_2');assert.equal(widget.children[3].children[0].src,state.qr);
  assert.equal(widget.children[3].hidden,width<900);assert.equal(form.elements.form_token.value,'signed-2');
}
(async()=>{for(const width of [390,900,1280]) await check(width);console.log('PASS private-link form and renewal at both widths');})().catch(error=>{console.error(error);process.exitCode=1;});
