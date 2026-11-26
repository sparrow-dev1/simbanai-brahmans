// Standalone, isolated headless Chrome checks. No in-app browser tool is available.
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
async function availablePort(){const server=net.createServer();await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
const serverPort=await availablePort(),debugPort=await availablePort();
import assert from 'node:assert/strict';

const output=path.resolve('test-output');
await mkdir(output,{recursive:true});
const testDatabase=path.join(output,`browser-${Date.now()}.sqlite`).replaceAll('\\','/');
const appEnvironment={...process.env,DATABASE_URL:`sqlite:///${testDatabase}`,HTTPS_ONLY:'0'};
await new Promise((resolve,reject)=>{
  const seed=spawn('python',['-m','flask','--app','app','demo'],{env:appEnvironment,windowsHide:true,stdio:['ignore','ignore','pipe']});
  let errors='';seed.stderr.on('data',chunk=>errors+=chunk);seed.on('error',reject);seed.on('exit',code=>code===0?resolve():reject(new Error('Test demo initialization failed: '+errors)));
});
const baseURL='http://127.0.0.1:'+serverPort;
const server=spawn('python',['-m','flask','--app','app','run','--port',String(serverPort),'--no-debugger','--no-reload'],{env:appEnvironment,windowsHide:true,stdio:'ignore'});
let serverReady=false;
for(let i=0;i<150;i++){try{const response=await fetch(baseURL+'/api/session');if(response.ok){serverReady=true;break;}}catch{}await new Promise(resolve=>setTimeout(resolve,200));}
if(!serverReady){server.kill();throw new Error('Isolated test server did not start.');}
const chromePath='C:/Program Files/Google/Chrome/Application/chrome.exe';
const chrome=spawn(chromePath,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',`--remote-debugging-port=${debugPort}`,`--user-data-dir=${path.join(output,`chrome-check-${Date.now()}`)}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let socket;
let counter=0;
const pending=new Map();
const exceptions=[];
async function connect(){
  for(let i=0;i<150;i++){
    try{
      const targets=await(await fetch('http://127.0.0.1:'+debugPort+'/json')).json();
      const target=targets.find(t=>t.type==='page');
      if(target){socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});socket.onmessage=event=>{const value=JSON.parse(event.data);if(value.id){const entry=pending.get(value.id);pending.delete(value.id);if(value.error)entry?.reject(new Error(JSON.stringify(value.error)));else entry?.resolve(value.result);}else if(value.method==='Runtime.exceptionThrown')exceptions.push(value.params.exceptionDetails.text+' '+(value.params.exceptionDetails.exception?.description||''));};return;}
    }catch{}
    await sleep(200);
  }
  throw new Error('Headless Chrome did not start.');
}
function command(method,params={}){const id=++counter;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const result=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true,userGesture:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value;}
async function until(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await sleep(100);}throw new Error('Timed out waiting for '+expression+'\n'+await evaluate('document.body.innerText'));}
async function fill(selector,value){await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)throw Error('Missing input '+${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);}
async function click(selector){
  const point=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)throw Error('Missing control '+${JSON.stringify(selector)});e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();const x=r.left+r.width/2,y=r.top+r.height/2;const hit=document.elementFromPoint(x,y);if(!hit||!(e===hit||e.contains(hit)))throw Error('Control covered: '+${JSON.stringify(selector)});return {x,y};})()`);
  await command('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
  await command('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
}
async function reloadPage(){
  const marker=String(Date.now())+Math.random();
  await evaluate(`window.qaReloadMarker=${JSON.stringify(marker)}`);
  await command('Page.reload');
  await until(`window.qaReloadMarker!==${JSON.stringify(marker)}&&document.readyState==='complete'`);
}
async function screenshot(name){const result=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(path.join(output,name),Buffer.from(result.data,'base64'));}
async function checkBatchForms(){
  await navigate('herd');await click('[data-kind=purchase]');await nextCapture(2);
  await fill('[name=row_0_identifier]','BROWSER-BATCH-A');await fill('[name=row_0_sex]','Female');await fill('[name=row_0_category]','Cow');await fill('[name=row_0_price]','123.45');
  await fill('[name=currency]','USD');await fill('[name=reference]','BROWSER-INVOICE');
  await click('[data-action=add-purchase-row]');
  assert.equal(await evaluate('document.querySelector("[name=currency]").value'),'USD');
  assert.equal(await evaluate('document.querySelector("[name=reference]").value'),'BROWSER-INVOICE');
  assert.equal(await evaluate('document.querySelector("[name=row_0_identifier]").value'),'BROWSER-BATCH-A');
  await fill('[name=row_1_identifier]','BROWSER-BATCH-B');await fill('[name=row_1_sex]','Male');await fill('[name=row_1_category]','Bull');await fill('[name=row_1_price]','234.56');await fill('[name=currency]','ZiG');
  await nextCapture(3);assert.ok((await evaluate('document.querySelector("#main").innerText')).includes('234.56 ZiG'));await click('[data-action=back-step]');await until('editor.step===2');assert.equal(await evaluate('document.querySelector("[name=row_0_price]").value'),'123.45');
  await click('[data-action=cancel-capture]');await until('!editor');
  await evaluate("startCapture('breeding')");
  const cowIds=await evaluate('selectableCattle(editor.payload).slice(0,2).map(a=>a.id)');
  for(const id of cowIds)await click(`[data-cattle][value="${id}"]`);
  await nextCapture(2);await fill('[name=breeding_action]','Pregnancy check');
  await fill(`[name=preg_${cowIds[0]}_result]`,'Pregnant');await fill(`[name=preg_${cowIds[0]}_date]`,'2027-01-01');await fill(`[name=preg_${cowIds[0]}_basis]`,'Veterinary examination');
  await fill(`[name=preg_${cowIds[1]}_result]`,'Not pregnant');
  await nextCapture(3);assert.ok((await evaluate('document.querySelector("#main").innerText')).includes('Veterinary examination'));
  await click('[data-action=back-step]');await until('editor.step===2');assert.equal(await evaluate(`document.querySelector('[name=preg_${cowIds[0]}_basis]').value`),'Veterinary examination');
  await click('[data-action=cancel-capture]');await until('!editor');
}
async function checkCaptureProofDrafts(){
  await logout();await login('hand');
  await evaluate("startCapture('birth')");
  const dam=await evaluate('ref.animals.find(a=>a.sex==="Female"&&a.lifecycle==="Active")');
  await fill('[name=dam_id]',String(dam.id));await nextCapture(2);
  const birthDraft=await evaluate('editor.id');
  await evaluate(`(()=>{window.proofReferenceAnimals=ref.animals;ref.animals=ref.animals.filter(a=>a.id!==${dam.id});editor.step=1;renderCapture();})()`);
  assert.equal(await evaluate('document.querySelector("[name=dam_id]").value'),String(dam.id));
  assert.equal(await evaluate('document.querySelector("#capture-form").checkValidity()'),true);
  await nextCapture(2);
  assert.equal(await evaluate(`editor.payload.versions[${dam.id}]`),dam.version);
  assert.equal(await evaluate(`editor.payload.capture_proofs[${dam.id}]`),dam.capture_proof);
  await evaluate(`(async()=>{ref.animals=window.proofReferenceAnimals;delete window.proofReferenceAnimals;clearTimeout(scheduleDraft.timer);editor=null;localRecords=localRecords.filter(r=>r.id!==${JSON.stringify(birthDraft)});await saveLocal();await route();})()`);
  await evaluate("startCapture('weight')");
  const animal=await evaluate('ref.animals.find(a=>a.lifecycle==="Active")');
  await click(`[data-cattle][value="${animal.id}"]`);
  assert.equal(await evaluate(`editor.payload.versions[${animal.id}]`),animal.version);
  assert.equal(await evaluate(`editor.payload.capture_proofs[${animal.id}]`),animal.capture_proof);
  await nextCapture(2);await fill(`[name=weight_${animal.id}]`,'251');await click('[data-action=save-draft]');
  const draftId=await evaluate('editor.id');
  await logout();await login('manager');
  await evaluate(`(async()=>{const current=ref.animals.find(a=>a.id===${animal.id});await api('/api/events',{method:'POST',body:JSON.stringify({id:crypto.randomUUID(),payload:{kind:'health',date:day(),station_id:current.station_id,animal_ids:[current.id],versions:{[current.id]:current.version},products:[],notes:'Isolated proof regression',observation:'Changed after field capture'}})});})()`);
  await logout();await login('hand');await navigate('records');
  await click(`[data-action=edit-draft][data-id="${draftId}"]`);await until('!!editor');
  assert.equal(await evaluate(`editor.payload.versions[${animal.id}]`),animal.version);
  await nextCapture(2);await click('[data-action=back-step]');await until('editor.step===1');
  await click('[data-action=select-none]');await click(`[data-cattle][value="${animal.id}"]`);
  assert.equal(await evaluate(`editor.payload.versions[${animal.id}]`),animal.version);
  assert.equal(await evaluate(`editor.payload.capture_proofs[${animal.id}]`),animal.capture_proof);
  await nextCapture(2);await fill(`[name=weight_${animal.id}]`,'251');await nextCapture(3);
  await command('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await reloadPage();await until('!!document.querySelector(".sidebar")');await navigate('records');
  await click(`[data-action=edit-draft][data-id="${draftId}"]`);await until('!!editor');
  assert.equal(await evaluate(`editor.payload.versions[${animal.id}]`),animal.version);
  assert.equal(await evaluate(`editor.payload.capture_proofs[${animal.id}]`),animal.capture_proof);
  await nextCapture(2);await nextCapture(3);await evaluate('document.querySelector("#capture-form").requestSubmit()');
  await until('!editor && page==="home"');
  await command('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await evaluate('syncQueue()');await until(`events.some(e=>e.id===${JSON.stringify(draftId)}&&e.state==='Pending approval')`);
  assert.equal(await evaluate(`events.find(e=>e.id===${JSON.stringify(draftId)}).payload.versions[${animal.id}]`),animal.version);
  assert.ok(await evaluate(`events.find(e=>e.id===${JSON.stringify(draftId)}).conflicts.length`));
  await logout();await login('manager');
  await evaluate(`(async()=>{const event=(await api('/api/events/'+${JSON.stringify(draftId)})).event;await api('/api/events/'+event.id+'/review',{method:'POST',body:JSON.stringify({revision:event.revision,action:'return',reason:'Review updated cattle explicitly'})});})()`);
  await logout();await login('hand');await navigate('records');
  await evaluate(`startCapture('weight',events.find(e=>e.id===${JSON.stringify(draftId)}),'returned')`);
  await click('[data-action=reconcile-capture]');await until('document.querySelector("#modal")?.open');
  assert.equal(await evaluate(`editor.payload.versions[${animal.id}]`),animal.version);
  assert.ok((await evaluate('document.querySelector("#modal").innerText')).includes('Captured version'));
  await evaluate('document.querySelector("#modal-form").requestSubmit()');await until('!document.querySelector("#modal").open');
  assert.equal(await evaluate(`editor.payload.versions[${animal.id}]`),animal.version+1);
  assert.notEqual(await evaluate(`editor.payload.capture_proofs[${animal.id}]`),animal.capture_proof);
  await nextCapture(2);await nextCapture(3);await evaluate('document.querySelector("#capture-form").requestSubmit()');
  await until(`!syncBusy && events.some(e=>e.id===${JSON.stringify(draftId)}&&e.state==='Pending approval')`);
  assert.equal(await evaluate(`events.find(e=>e.id===${JSON.stringify(draftId)}).conflicts.length`),0);
}
async function checkOfflineLogout(){
  await logout();await login('hand');
  const accountId=await evaluate('user.id');
  const before=await evaluate(`storeGet('records:'+${accountId})`);
  await command('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await logout();assert.equal(await evaluate("storeGet('logout-pending')"),true);
  await reloadPage();await until('!!document.querySelector("#login-form")');assert.equal(await evaluate('user'),null);
  await command('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await reloadPage();await until('!!document.querySelector("#login-form")');
  assert.equal(await evaluate("api('/api/session').then(s=>s.user)"),null);
  assert.deepEqual(await evaluate(`storeGet('records:'+${accountId})`),before);
  await login('hand');await logout();
}
const passwords={manager:'Simbanai-Demo-2026!',owner:'Simbanai-Demo-2026!',hand:'Simbanai-Demo-2026!'};
async function login(role){await until('!!document.querySelector("#login-form")');await fill('[name=username]',role);await fill('[name=password]',passwords[role]);await evaluate('document.querySelector("#login-form").requestSubmit()');await until('!!document.querySelector(".sidebar") && !document.querySelector(".loading") && !syncBusy');}
async function logout(){await until('!captureBusy && !syncBusy');await click('[data-action=logout]');if(await evaluate('document.querySelector("#modal")?.open'))await evaluate('document.querySelector("#modal-form").requestSubmit()');await until('!!document.querySelector("#login-form")');}
async function authView(view){await evaluate(`location.hash=${JSON.stringify(view)}`);await until(`document.querySelector('form[data-auth-view]')?.dataset.authView===${JSON.stringify(view)}`);}
async function navigate(page){await evaluate(`location.hash=${JSON.stringify(page)}`);await until(page==='account'?'!!document.querySelector("#password-form")':`document.querySelector('.navitem.active')?.getAttribute('href')==='#${page}' && !document.querySelector('.loading')`);}

async function checkFarmWorkflowRelease(){
  await navigate('herd');
  await click('[data-action=capture][data-kind=purchase]');await until('!!editor');await nextCapture(2);
  await fill('[name=acquisition_source]','Gift');await until('!!document.querySelector("[name=reference]")&&!document.querySelector("[name=row_0_price]")');
  await fill('[name=reference]','Fictional donor');await fill('[name=row_0_identifier]','GIFT-REVIEW-ONLY');await fill('[name=row_0_sex]','Female');await fill('[name=row_0_category]','Heifer');
  await nextCapture(3);assert.ok((await evaluate('document.querySelector("#main").innerText')).includes('Gift'));
  await click('[data-action=cancel-capture]');await until('!editor');
  await evaluate("startCapture('procedure')");await until('!!document.querySelector("[data-cattle]")');
  const first=await evaluate('document.querySelector("[data-cattle]").value');await click(`[data-cattle][value="${first}"]`);
  await click(`[data-action=view-capture-animal][data-id="${first}"]`);await until('document.querySelector("#modal").open');
  assert.equal(await evaluate('editor.payload.animal_ids.length'),1);await click('[data-action=close-modal]');
  const keyboard=await evaluate('document.querySelectorAll("[data-cattle]")[1].value');await evaluate(`document.querySelector('[data-cattle][value="${keyboard}"]').focus()`);
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32});await command('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
  assert.equal(await evaluate('editor.payload.animal_ids.length'),2);
  await nextCapture(2);await fill('[name=procedure]','Dipping');await click('[data-action=add-product-row]');await fill('[data-product]','1');await fill('[data-unit]','mL');await fill('[data-quantity]','0.1');
  assert.equal(await evaluate('document.querySelector("[data-unit]").value'),'mL');await nextCapture(3);assert.ok((await evaluate('document.querySelector("#main").innerText')).includes('0.1 mL'));
  await click('[data-action=cancel-capture]');await until('!editor');
  await navigate('supplies');await click('[data-action=archive-product][data-id="1"]');await until('document.querySelector("#modal").open');await evaluate('document.querySelector("#modal-form").requestSubmit()');await until('!document.querySelector("#modal").open');
  assert.equal(await evaluate('ref.products.find(p=>p.id===1).active'),false);
  await click('[data-action=archive-product][data-id="1"]');await until('document.querySelector("#modal").open');await evaluate('document.querySelector("#modal-form").requestSubmit()');await until('!document.querySelector("#modal").open');
  assert.equal(await evaluate('ref.products.find(p=>p.id===1).active'),true);
  await navigate('money');await fill('#money-currency','ZiG');await click('[data-action=capture][data-kind=expense]');await until('!!document.querySelector("#capture-form")');await nextCapture(2);
  await fill('[name=amount]','7.50');await fill('[name=currency]','ZiG');await fill('[name=finance_category]','Other cattle expense');await nextCapture(3);await evaluate('document.querySelector("#capture-form").requestSubmit()');
  await until('!editor&&!captureBusy&&!!document.querySelector("#money-currency")');assert.equal(await evaluate('document.querySelector("#money-currency").value'),'ZiG');
  const chart=await evaluate("api('/api/charts/expenses?currency=ZiG')");assert.equal(Number(chart.total),7.5);
  for(const width of [360,390,650,820,1366]){await command('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:width<=820});assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true);}
  await command('Emulation.setDeviceMetricsOverride',{width:1366,height:900,deviceScaleFactor:1,mobile:false});
  await screenshot('farm-release-money.png');
}

async function checkReleaseLayouts(){
  for(const role of ['manager','owner','hand']){
    await login(role);
    for(const width of [360,390,650,820,1366]){
      await command('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:width<=820});
      await navigate(role==='hand'?'home':'overview');
      assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true,role+' overview '+width);
      if(role==='owner'){await until('!!document.querySelector(".farm-chart")');await screenshot(`release-owner-overview-${width}.png`);assert.equal(await evaluate('!!document.querySelector("#chart-expenses")'),true);assert.equal(await evaluate('[...document.querySelectorAll(".titlebar")].some(e=>["Herd by station","Needs attention"].includes(e.innerText.trim()))'),false);}
      if(role!=='hand'){await navigate('money');await until('!!document.querySelector("#chart-expenses-result")');if(role==='owner')await until('!!document.querySelector(".farm-chart")');assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true,role+' money '+width);}
      await screenshot(`release-${role}-${width}.png`);
    }
    if(role==='manager'){
      await evaluate("api('/api/events',{method:'POST',body:JSON.stringify({id:crypto.randomUUID(),payload:{kind:'expense',date:day(),animal_ids:[],products:[],amount:'240',currency:'USD',finance_category:'Feed',reference:'Isolated chart layout fixture'}})})");
      await managerUsers();const id=await evaluate("adminUsers.find(u=>u.username==='hand').id");
      await click(`[data-action=edit-user][data-id="${id}"]`);await until('document.querySelector("#modal").open');await click('[name=station_ids][value="2"]');await evaluate('document.querySelector("#modal-form").requestSubmit()');await until('!document.querySelector("#modal").open');
    }else if(role==='owner'){
      await navigate('performance');assert.equal(await evaluate('document.querySelector("[name=metric]").value'),'');
      await fill('[name=metric]','pregnancy');await evaluate('document.querySelector("#chart-performance").requestSubmit()');await until('document.querySelector("#chart-performance-result").innerText.includes("Insufficient")');
      assert.equal(await evaluate("svgChart({metric:'pregnancy',unit:'animals',group:'months',points:[{date:'2026-01',value:3,count:3,results:{Pregnant:2,'Not pregnant':1,Uncertain:0}}]},true).includes('Not pregnant, 1 cattle')"),true);
    }else{
      assert.equal(await evaluate('user.station_ids.length'),2);assert.equal(await evaluate('[...document.querySelector("#working-station").options].filter(o=>o.value).length'),2);
      await click('[data-action=capture][data-kind=weight]');await click('[data-cattle]');await nextCapture(2);const animal=await evaluate('editor.payload.animal_ids[0]');await fill(`[name=weight_${animal}]`,'251');await nextCapture(3);
      await until('!!navigator.serviceWorker.controller');await command('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
      await evaluate('document.querySelector("#capture-form").requestSubmit()');await until('!captureBusy&&!editor&&page==="home"');await click('[data-action=saved-record]');await until('page==="records"');await fill('#record-order','oldest');assert.equal(await evaluate('recordOrder'),'oldest');
      await reloadPage();await until('document.querySelector("#main")?.innerText.includes("Saved on this tablet")');assert.equal(await evaluate('user.station_ids.length'),2);
      await command('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});await reloadPage();await until('!!document.querySelector(".sidebar")&&!syncBusy');
    }
    await logout();
  }
  assert.equal(exceptions.length,0,exceptions.join('\n'));
  console.log(JSON.stringify({passed:true,checks:['all three roles at 360/390/650/820/1366','Owner and Manager responsive expense charts','two-station assignment through Manager UI and cached field references','Performance metric prompt and labelled pregnancy segments','offline origin return and sorting','offline reload retains queued work and station set']}));
}

async function checkCaptureStep(step,reached=step){
  const expected={1:'rgb(233, 173, 173)',2:'rgb(255, 225, 103)',3:'rgb(187, 221, 177)'};
  const actual=await evaluate(`(()=>{
    const tracker=document.querySelector('.capture-steps');
    const active=tracker.querySelector('.step.active');
    return {step:Number(active.dataset.step),colour:getComputedStyle(active).backgroundColor,
      bold:getComputedStyle(active).fontWeight,text:getComputedStyle(active).color,
      current:active.getAttribute('aria-current'),activeCount:tracker.querySelectorAll('.step.active').length,
      colours:[...tracker.querySelectorAll('.step')].map(e=>getComputedStyle(e).backgroundColor),
      reachedCount:tracker.querySelectorAll('.step.reached').length,
      inactiveWeights:[...tracker.querySelectorAll('.step:not(.active)')].map(e=>getComputedStyle(e).fontWeight)};
  })()`);
  assert.equal(actual.step,step);
  assert.equal(actual.colour,expected[step]);
  assert.equal(actual.bold,'700');
  assert.equal(actual.text,'rgb(32, 32, 32)');
  assert.equal(actual.current,'step');
  assert.equal(actual.activeCount,1);
  assert.equal(actual.reachedCount,reached);
  assert.deepEqual(actual.inactiveWeights,['400','400']);
  assert.deepEqual(actual.colours,[1,2,3].map(i=>i<=reached?expected[i]:'rgba(0, 0, 0, 0)'));
}

async function nextCapture(step){
  assert.equal(await evaluate('document.querySelector("#capture-form").checkValidity()'),true,'Fixture must satisfy the actual form');
  await evaluate('(()=>{const f=document.querySelector("#capture-form");f.requestSubmit();f.requestSubmit();})()');
  await until(`editor?.step===${step} && document.querySelector('.step.active')?.dataset.step==='${step}'`);
}

async function fillNamedValues(values){
  await evaluate(`(()=>{for(const [name,value] of Object.entries(${JSON.stringify(values)})){const e=document.querySelector('#capture-form').elements.namedItem(name);if(!e)throw Error('Missing field '+name);e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}})()`);
}

async function checkAllCaptureTrackers(){
  const kinds=['procedure','weight','health','treatment','resolve_health','movement','birth','death','breeding','purchase','sale','stock_in','stock_use','expense','income','lost','found'];
  const fixture=await evaluate(`(()=>{const station=ref.stations[0].id;const cow=ref.animals.find(a=>a.station_id===station&&a.sex==='Female'&&a.lifecycle==='Active');return {cow:cow.id,product:ref.products.find(p=>p.category==='Medicine').id,destination:ref.stations.find(s=>s.id!==station).id};})()`);
  // This case exists only in browser memory to exercise the two health forms.
  // Never confirm these display-only fixtures as official events.
  await evaluate(`ref.cases.push({id:99999,animal_id:${fixture.cow},closed_at:null,observation:'Browser-only form fixture'})`);
  for(const kind of kinds){
    await evaluate(`(()=>{if(${JSON.stringify(kind)}==='found')ref.animals.find(a=>a.id===${fixture.cow}).lifecycle='Lost';startCapture(${JSON.stringify(kind)});})()`);await checkCaptureStep(1);
    if(kind==='birth'){
      assert.equal(await evaluate('document.querySelector("#capture-form").checkValidity()'),false);
      await evaluate('document.querySelector("#capture-form").requestSubmit()');await checkCaptureStep(1);
      await checkCaptureLayouts(1,'birth');await fill('[name=dam_id]',String(fixture.cow));
    }else if(!['purchase','stock_in','stock_use','expense','income'].includes(kind)){
      await click(`[data-cattle][value="${fixture.cow}"]`);
    }
    await nextCapture(2);await checkCaptureStep(2);
    if(kind==='birth')await checkCaptureLayouts(2,'birth');
    const values={
      procedure:{procedure:'Dipping'},weight:{['weight_'+fixture.cow]:'250'},
      health:{observation:'Browser-only form fixture'},treatment:{case_id:'99999'},resolve_health:{case_id:'99999'},
      movement:{destination_id:String(fixture.destination),movement_reason:'Station transfer'},
      birth:{sex:'Female'},death:{cause:'Browser-only form fixture'},lost:{lifecycle_reason:'Browser-only missing'},found:{lifecycle_reason:'Browser-only found'},
      breeding:{breeding_action:'Pregnancy check',['preg_'+fixture.cow+'_result']:'Not pregnant'},
      purchase:{identifier:'BROWSER-UI-ONLY',sex:'Female',category:'Cow',amount:'100',currency:'USD'},
      sale:{amount:'100',currency:'USD'},stock_in:{amount:'10',currency:'USD'},stock_use:{},
      expense:{amount:'10',currency:'USD',finance_category:'Other cattle expense'},
      income:{amount:'10',currency:'USD',finance_category:'Other cattle income'}
    }[kind];
    await fillNamedValues(values);
    if(['procedure','treatment','stock_in','stock_use'].includes(kind)){
      await click('[data-action=add-product-row]');await fill('[data-product]',String(fixture.product));await fill('[data-quantity]','0.25');
    }
    await nextCapture(3);await checkCaptureStep(3);
    if(kind==='birth')await checkCaptureLayouts(3,'birth');
    await click('[data-action=back-step]');await until('editor?.step===2');await checkCaptureStep(2,3);
    await click('[data-action=back-step]');await until('editor?.step===1');await checkCaptureStep(1,3);
    await click('[data-action=cancel-capture]');await until('!editor && document.body.innerText.includes("Farm overview")');
  }
  await evaluate('ref.cases=ref.cases.filter(c=>c.id!==99999);ref.animals.forEach(a=>{if(a.lifecycle==="Lost")a.lifecycle="Active";})');
  assert.equal(await evaluate('ref.animals.length'),87,'Display-only capture checks must not register cattle');
  await command('Emulation.setDeviceMetricsOverride',{width:1366,height:900,deviceScaleFactor:1,mobile:false});
}

async function checkOfflineBirthDraft(){
  await navigate('home');await click('[data-action=capture][data-kind=birth]');await checkCaptureStep(1);
  const dam=await evaluate('ref.animals.find(a=>a.station_id===user.station_id&&a.sex==="Female"&&a.lifecycle==="Active").id');
  await fill('[name=dam_id]',String(dam));await nextCapture(2);await checkCaptureStep(2);
  const id=await evaluate('editor.id');
  await until(`storeGet('records:'+user.id).then(records=>records?.find(r=>r.id===${JSON.stringify(id)})?.furthestStep===2)`);
  await reloadPage();await until('!!document.querySelector(".sidebar")');await navigate('records');
  await click(`[data-action=edit-draft][data-id="${id}"]`);await checkCaptureStep(1,2);
  await nextCapture(2);await fill('[name=sex]','Female');await nextCapture(3);await checkCaptureStep(3);
  await until(`storeGet('records:'+user.id).then(records=>records?.find(r=>r.id===${JSON.stringify(id)})?.furthestStep===3)`);
  await reloadPage();await until('!!document.querySelector(".sidebar")');await navigate('records');
  await click(`[data-action=edit-draft][data-id="${id}"]`);await checkCaptureStep(1,3);
  assert.equal(await evaluate('document.querySelector("[name=dam_id]").value'),String(dam));
  await nextCapture(2);await checkCaptureStep(2,3);
  assert.equal(await evaluate('document.querySelector("[name=sex]").value'),'Female');
  await nextCapture(3);await checkCaptureStep(3);await screenshot('birth-offline-restored.png');
  await click('[data-action=back-step]');await until('editor?.step===2');await checkCaptureStep(2,3);
  await click('[data-action=back-step]');await until('editor?.step===1');await checkCaptureStep(1,3);
  await click('[data-action=cancel-capture]');await until('!editor');
  // Restore a legacy draft lacking progress metadata; do not infer completion
  // from fields that happen to have values.
  await evaluate(`(()=>{const legacy=structuredClone(localRecords.find(r=>r.id===${JSON.stringify(id)}));delete legacy.furthestStep;startCapture('birth',legacy);})()`);
  await checkCaptureStep(1);
  // Remove this unsubmitted fixture only from the isolated browser's storage.
  await evaluate(`(async()=>{clearTimeout(scheduleDraft.timer);editor=null;localRecords=localRecords.filter(r=>r.id!==${JSON.stringify(id)});await saveLocal();await route();})()`);
  await navigate('home');assert.equal(await evaluate('ref.animals.length'),87);
}

async function checkLogo(selector){
  await until(`document.querySelector(${JSON.stringify(selector)})?.complete && document.querySelector(${JSON.stringify(selector)})?.naturalWidth>0`);
  const logo=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});const r=e.getBoundingClientRect();const style=getComputedStyle(e);return {src:e.getAttribute('src'),naturalWidth:e.naturalWidth,naturalHeight:e.naturalHeight,width:r.width-parseFloat(style.borderLeftWidth)-parseFloat(style.borderRightWidth),height:r.height-parseFloat(style.borderTopWidth)-parseFloat(style.borderBottomWidth),fit:style.objectFit,right:r.right,viewport:innerWidth,border:style.borderTopWidth,background:style.backgroundColor};})()`);
  const transparent=selector==='.login-brand img';
  assert.equal(logo.src,transparent?'/static/company-logo-green.svg':'/static/company-logo.png');
  assert.equal(logo.naturalWidth,1672);assert.equal(logo.naturalHeight,941);
  assert.equal(logo.fit,'contain');assert.ok(Math.abs(logo.width/logo.height-1672/941)<.025);
  assert.ok(logo.right<=logo.viewport,'Logo must fit the viewport');
  if(transparent){
    assert.equal(logo.border,'0px');assert.equal(logo.background,'rgba(0, 0, 0, 0)');
    const pixels=await evaluate(`(()=>{const e=document.querySelector('.login-brand img');const c=document.createElement('canvas');c.width=e.naturalWidth;c.height=e.naturalHeight;const ctx=c.getContext('2d');ctx.drawImage(e,0,0);const alpha=[[0,0],[1671,940],[840,450],[840,680]].map(([x,y])=>ctx.getImageData(x,y,1,1).data[3]);const p=ctx.getImageData(0,0,c.width,c.height).data;let opaque=0,colour=[];for(let i=0;i<p.length;i+=4){if(p[i+3]>0)opaque++;if(p[i+3]===255)colour=[...p.slice(i,i+3)];}return {alpha,opaque,colour};})()`);
    assert.deepEqual(pixels.alpha,[0,0,0,0],'Surroundings and internal gaps must be transparent');
    assert.ok(pixels.opaque>100000);assert.deepEqual(pixels.colour,[47,93,58],'Login artwork uses the shared forest green action colour');
  }
}

async function checkBrandAssets(){
  const result=await evaluate(`(async()=>{
    const svg=document.querySelector('link[rel="icon"][type="image/svg+xml"]').getAttribute('href');
    const ico=document.querySelector('link[rel="icon"][type="image/x-icon"]').getAttribute('href');
    const manifest=await fetch(document.querySelector('link[rel="manifest"]').href).then(r=>r.json());
    const urls=[svg,ico,...manifest.icons.filter(i=>i.type==='image/png').map(i=>i.src)];
    const statuses=await Promise.all(urls.map(async url=>{const response=await fetch(url);return response.status;}));
    const icoBytes=new Uint8Array(await fetch(ico).then(r=>r.arrayBuffer()));
    const dimensions=[];
    for(const entry of manifest.icons.filter(i=>i.type==='image/png')){const im=new Image();im.src=entry.src;await im.decode();dimensions.push(im.naturalWidth+'x'+im.naturalHeight);}
    const im=new Image();im.src=svg;await im.decode();
    const tiny=[];
    for(const size of [16,32]){const c=document.createElement('canvas');c.width=c.height=size;const ctx=c.getContext('2d');ctx.drawImage(im,0,0,size,size);const p=ctx.getImageData(0,0,size,size).data;let light=0;for(let i=0;i<p.length;i+=4){if(p[i]>110&&p[i+1]>135&&p[i+2]>120)light++;}tiny.push({size,light,corner:[...p.slice(0,4)]});}
    const preview=document.createElement('section');preview.id='branding-preview';preview.style.cssText='position:fixed;top:12px;right:12px;padding:20px;background:#E6E6E6;border:1px solid #808080;z-index:9999';preview.innerHTML='<h2>Favicon and PWA icons</h2><p>16px · 32px · 192px · 512px</p>'+[16,32,192,512].map(size=>'<img style="margin:10px;vertical-align:middle" src="'+(size<=32?svg:'/static/icon-'+size+'-v6.png')+'" width="'+Math.min(size,192)+'" height="'+Math.min(size,192)+'" alt="'+size+' pixel icon">').join('');document.body.append(preview);await Promise.all([...preview.querySelectorAll('img')].map(im=>im.decode()));
    return {svg,ico,statuses,signature:[...icoBytes.slice(0,6)],dimensions,tiny};
  })()`);
  assert.equal(result.svg,'/static/favicon-v6.svg');assert.equal(result.ico,'/static/favicon-v6.ico');
  assert.equal(await evaluate('[...document.scripts].find(e=>e.src.includes("/app.js?")).getAttribute("src")'),'/static/app.js?v=16');
  assert.equal(await evaluate('[...document.scripts].find(e=>e.src.includes("/auth.js?")).getAttribute("src")'),'/static/auth.js?v=16');
  assert.equal(await evaluate('document.querySelector("link[rel=stylesheet]").getAttribute("href")'),'/static/style.css?v=16');
  assert.deepEqual(result.statuses,[200,200,200,200]);assert.deepEqual(result.signature,[0,0,1,0,2,0]);
  assert.deepEqual(result.dimensions,['192x192','512x512']);
  for(const icon of result.tiny){assert.deepEqual(icon.corner,[47,93,58,255]);assert.ok(icon.light>icon.size,`Antialiased emblem should remain visible at ${icon.size}px (${icon.light} contrasting pixels)`);}
  await screenshot('favicon-and-pwa-icons.png');await evaluate('document.querySelector("#branding-preview").remove()');
}

async function checkOfflineBrandAssets(){
  await until('caches.keys().then(keys=>keys.includes("simbanai-shell-v16"))');
  const assets=['/static/company-logo-green.svg','/static/company-logo-transparent.png','/static/favicon-v6.svg','/static/favicon-v6.ico','/static/icon-192-v6.png','/static/icon-512-v6.png','/static/auth.js?v=16','/static/app.js?v=16','/static/style.css?v=16','/static/manifest.webmanifest?v=16'];
  const result=await evaluate(`(async()=>{const cache=await caches.open('simbanai-shell-v16');return Promise.all(${JSON.stringify(assets)}.map(async path=>({cached:!!await cache.match(path,{ignoreSearch:true}),status:(await fetch(path)).status})));})()`);
  assert.deepEqual(result,assets.map(()=>({cached:true,status:200})));
}

async function checkAuthLayouts(){
  for(const width of [360,390,650,820,1366]){
    await command('Emulation.setDeviceMetricsOverride',{width,height:width<=390?844:900,deviceScaleFactor:1,mobile:width<=820});
    for(const view of ['signin','register','forgot-password','reset-password']){
      await authView(view);await checkLogo('.login-brand img');
      const layout=await evaluate(`(()=>{const panel=document.querySelector('.login-panel').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>innerWidth,width:panel.width,left:panel.left,right:panel.right,touch:[...document.querySelectorAll('.login-panel input,.login-panel select,.login-panel button,.login-panel a')].every(e=>e.getBoundingClientRect().height>=44),heading:document.querySelector('h1').innerText,font:getComputedStyle(document.querySelector('.login-panel')).fontFamily};})()`);
      assert.equal(layout.overflow,false,view+' at '+width);assert.ok(layout.width<=440);assert.ok(layout.left>=16&&layout.right<=width-16);assert.equal(layout.touch,true,view+' touch controls');assert.ok(layout.font.includes('Tahoma'));
      await screenshot(`auth-${view}-${width}.png`);
    }
  }
  await command('Emulation.setDeviceMetricsOverride',{width:360,height:568,deviceScaleFactor:1,mobile:true});await authView('register');
  assert.ok(await evaluate('document.querySelector(".login-panel").getBoundingClientRect().top>=16'),'Short screens scroll from the top');
  await evaluate('document.querySelector(".auth-submit").scrollIntoView()');assert.ok(await evaluate('document.querySelector(".auth-submit").getBoundingClientRect().bottom<=innerHeight'));
  await command('Emulation.setDeviceMetricsOverride',{width:1366,height:900,deviceScaleFactor:1,mobile:false});await authView('signin');
  await fill('[name=password]','visibility-check');await click('#password-toggle');assert.equal(await evaluate('document.querySelector("[name=password]").type'),'text');await click('#password-toggle');assert.equal(await evaluate('document.querySelector("[name=password]").type'),'password');
  await evaluate('document.querySelector("[name=password]").focus()');
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  assert.equal(await evaluate('document.activeElement.id'),'password-toggle');assert.equal(await evaluate('getComputedStyle(document.activeElement).outlineStyle'),'solid');
  await until('!!navigator.serviceWorker.controller');await command('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  for(const view of ['register','forgot-password','reset-password']){await authView(view);assert.equal(await evaluate('document.querySelector(".auth-submit").disabled'),false);}
  await authView('forgot-password');await fill('[name=username]','manager');await click('.auth-submit');
  await until('document.querySelector("#login-error").textContent.includes("Cannot reach the farm server")');
  assert.equal(await evaluate('document.querySelector(".auth-submit").disabled'),false);
  await command('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});await authView('signin');
}

async function managerUsers(){await navigate('administration');await click('[data-action=admin-tab][data-tab=users]');await until('!!document.querySelector("#account-requests .window")');}

async function checkAccountWorkflows(){
  // Account fixtures live only in this test's newly created demo database.
  for(const role of ['hand','owner','manager']){
    const username='applicant-'+role;passwords[username]='Browser-approved-password!';
    await authView('register');await fill('[name=name]','Test '+role);await fill('[name=username]',username);await fill('[name=role]',role);await fill('[name=password]',passwords[username]);await fill('[name=confirmation]','different-password');
    await evaluate('document.querySelector("#register-form").requestSubmit()');assert.equal(await evaluate('document.querySelector("[name=confirmation]").validity.customError'),true);
    await fill('[name=confirmation]',passwords[username]);await click('#password-toggle');assert.equal(await evaluate('[...document.querySelectorAll("input[name=password],input[name=confirmation]")].every(e=>e.type==="text")'),true);await click('#password-toggle');
    assert.equal(await evaluate('(()=>{document.querySelector("#register-form").requestSubmit();return document.querySelector(".auth-submit").disabled;})()'),true);
    await until('!!document.querySelector("#login-form") && document.querySelector("#auth-message")?.textContent.includes("approve")');
    await fill('[name=password]',passwords[username]);await evaluate('document.querySelector("#login-form").requestSubmit()');await until('document.querySelector("#login-error")?.innerText.includes("incorrect")');
    assert.equal(await evaluate('user'),null);
  }
  await login('manager');await managerUsers();
  for(const role of ['hand','owner','manager']){
    const id=await evaluate(`accountRequests.registrations.find(r=>r.username==='applicant-${role}').id`);
    await click(`[data-action=review-registration][data-id="${id}"][data-choice=approve]`);await until('document.querySelector("#modal").open');
    if(role==='hand'){
      assert.equal(await evaluate('selectedStationIds(document.querySelector("#modal-form")).length'),0);await click('#modal-form [name=station_ids][value="1"]');
    }else{
      assert.equal(await evaluate('!!document.querySelector("#modal-form [name=station_id]")'),false);
      if(role==='manager'){assert.equal(await evaluate('document.querySelector("#modal-form").checkValidity()'),false);await click('[name=confirm_manager]');}
    }
    await evaluate('document.querySelector("#modal-form").requestSubmit()');await until('!document.querySelector("#modal").open');
    await until(`accountRequests.registrations.find(r=>r.id===${JSON.stringify(id)})?.state==='Approved'`);
  }
  await screenshot('manager-account-requests.png');await logout();
  for(const role of ['hand','owner','manager']){
    await login('applicant-'+role);assert.equal(await evaluate('user.role'),role);
    assert.equal(await evaluate('user.station_id'),role==='hand'?1:null);
    assert.equal(await evaluate('!!document.querySelector(".navitem[href=\\"#administration\\"]")'),role==='manager');await logout();
  }
  // Save an actual field draft before credential recovery and verify its identity.
  await login('hand');await until('!!document.querySelector("[data-kind=procedure]")');await click('[data-action=capture][data-kind=procedure]');
  const cattle=await evaluate('ref.animals.find(a=>a.station_id===user.station_id).id');await click(`[data-cattle][value="${cattle}"]`);await nextCapture(2);await fill('[name=procedure]','Dipping');await evaluate('snapshotDraft()');
  const saved=await evaluate('({id:editor.id,userId:user.id,payload:JSON.stringify(editor.payload)})');await logout();
  await authView('forgot-password');await fill('[name=username]','hand');await evaluate('document.querySelector("#recovery-request-form").requestSubmit()');await until('document.querySelector("#auth-message")?.innerText.includes("eligible")');
  const ack=await evaluate('document.querySelector("#auth-message").innerText');await fill('[name=username]','unknown-account');await evaluate('document.querySelector("#recovery-request-form").requestSubmit()');await until('!document.querySelector(".auth-submit").disabled');assert.equal(await evaluate('document.querySelector("#auth-message").innerText'),ack);
  await authView('signin');await login('manager');await managerUsers();
  const resetId=await evaluate('accountRequests.password_resets.find(r=>r.username==="hand").id');
  await click(`[data-action=review-recovery][data-id="${resetId}"][data-choice=issue]`);assert.equal(await evaluate('document.querySelector("#modal-form").checkValidity()'),false);await click('[name=verified_identity]');await evaluate('document.querySelector("#modal-form").requestSubmit()');await until('!!document.querySelector("#issued-reset-code")');
  const code=await evaluate('document.querySelector("#issued-reset-code").value');assert.match(code,/^\d{4} \d{4} \d{4}$/);await click('#copy-reset-code');await until('document.querySelector("#copy-reset-code").textContent==="Copied" || document.querySelector("#issued-reset-code")===document.activeElement');
  await click('[data-action=close-modal]');await until('!document.querySelector("#modal").open && !document.querySelector("#issued-reset-code")');
  assert.equal(await evaluate('JSON.stringify(accountRequests).includes("code_hash")'),false);await logout();
  await authView('reset-password');await fill('[name=username]','hand');await fill('[name=code]',code.replaceAll(' ','-'));passwords.hand='Browser-recovered-password!';await fill('[name=password]',passwords.hand);await fill('[name=confirmation]',passwords.hand);await evaluate('document.querySelector("#reset-password-form").requestSubmit()');await until('document.querySelector("#auth-message")?.textContent.includes("updated")');assert.equal(await evaluate('user'),null);
  await login('hand');assert.equal(await evaluate('user.id'),saved.userId);await navigate('records');await click(`[data-action=edit-draft][data-id="${saved.id}"]`);await checkCaptureStep(1,2);await nextCapture(2);assert.equal(await evaluate('document.querySelector("[name=procedure]").value'),'Dipping');
  const stored=await evaluate(`storeGet('records:'+user.id).then(records=>records.find(r=>r.id===${JSON.stringify(saved.id)}))`);assert.equal(stored.id,saved.id);assert.equal(stored.payload.animal_ids[0],cattle);
  const storage=await evaluate(`(async()=>{const databaseHandle=await database;return new Promise((resolve,reject)=>{const request=databaseHandle.transaction('data').objectStore('data').getAll();request.onsuccess=()=>resolve(JSON.stringify(request.result));request.onerror=reject;});})()`);
  assert.ok(!storage.includes(passwords.hand)&&!storage.includes(code),'Credentials and reset codes must never enter IndexedDB');
  // Remove this unsubmitted fixture only from isolated device storage.
  await evaluate(`(async()=>{clearTimeout(scheduleDraft.timer);editor=null;localRecords=localRecords.filter(r=>r.id!==${JSON.stringify(saved.id)});await saveLocal();await route();})()`);await logout();
}

async function checkAccountTransition(){
  await login('hand');await until('!syncBusy');
  // Hold an authenticated response while signing out; release it afterward.
  await evaluate(`(()=>{
    window.accountTestApi=api;window.accountResponseHeld=false;
    window.accountResponseGate=new Promise(resolve=>window.releaseAccountResponse=resolve);
    api=async(path,options)=>{const result=await window.accountTestApi(path,options);if(path.split('?')[0]==='/api/events'){window.accountResponseHeld=true;await window.accountResponseGate;}return result;};
    window.accountRefreshResult=refresh().then(value=>({value}),failure=>({error:failure.message}));
  })()`);
  await until('window.accountResponseHeld');await logout();
  await evaluate('window.releaseAccountResponse()');
  assert.deepEqual(await evaluate('window.accountRefreshResult'),{value:false});
  assert.equal(await evaluate('user'),null);assert.equal(await evaluate('ref'),null);assert.deepEqual(await evaluate('events'),[]);
  await evaluate('api=window.accountTestApi;delete window.accountTestApi;delete window.accountRefreshResult;delete window.accountResponseHeld;delete window.accountResponseGate;delete window.releaseAccountResponse;');
}

async function checkCaptureLayouts(step,kind="procedure"){
  for(const width of [1366,820,650,390,360]){
    await command('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:width<1000});
    await checkCaptureStep(step);
    assert.equal(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true);
    await screenshot(`${kind}-step-${step}-${width}.png`);
  }
  await command('Emulation.setDeviceMetricsOverride',{width:820,height:1180,deviceScaleFactor:1,mobile:true});
}

async function mobileChecks(role, homePage){
  if(role==='hand')await until('!syncBusy && document.querySelector("[data-action=sync]")?.textContent==="Send & refresh"');
  for(const width of [360,390,650]){
    await command('Emulation.setDeviceMetricsOverride',{width,height:920,deviceScaleFactor:1,mobile:true});
    await navigate(homePage);
    await checkLogo('.brand img');
    assert.equal(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true,`${role} overflow at ${width}`);
    assert.equal(await evaluate('getComputedStyle(document.querySelector(".sidebar")).display'),'none');
    await click('[data-action=toggle-menu]');
    assert.equal(await evaluate('document.querySelector("[data-action=toggle-menu]").getAttribute("aria-expanded")'),'true');
    assert.equal(await evaluate('getComputedStyle(document.querySelector(".sidebar")).display'),'grid');
    assert.equal(await evaluate('[...document.querySelectorAll(".navitem")].every(e=>e.getBoundingClientRect().height>=44)'),true);
    // Exercise keyboard closing and focus return.
    await evaluate('document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}))');
    assert.equal(await evaluate('document.querySelector("[data-action=toggle-menu]").getAttribute("aria-expanded")'),'false');
    assert.equal(await evaluate('document.activeElement.dataset.action'),'toggle-menu');
    if(role==='owner'){
      await until('!!document.querySelector(".lifecycle-chart")');
      assert.equal(await evaluate('document.querySelector(".lifecycle-total").textContent'),'87');
      assert.equal(await evaluate('document.querySelectorAll(".legend-entry").length'),4);
      assert.equal(await evaluate('[...document.querySelectorAll(".legend-entry strong")].reduce((s,e)=>s+Number(e.textContent),0)'),87);
      assert.equal(await evaluate('document.querySelector(".lifecycle-chart").getBoundingClientRect().right<=window.innerWidth'),true);
      await screenshot(`owner-overview-${width}.png`);
      await click('[data-action=lifecycle-herd][data-status=Sold]');
      await until('document.querySelector("#herd-status")?.value==="Sold"');
      assert.equal(await evaluate('document.querySelectorAll("#herd-table tbody tr").length'),0);
      await navigate('overview');
      await click('[data-action=lifecycle-herd][data-status=Active]');
      await until('document.querySelector("#herd-status")?.value==="Active"');
      assert.equal(await evaluate('document.querySelectorAll("#herd-table tbody tr").length'),87);
    }else if(role==='manager'){
      await navigate('herd');
      assert.equal(await evaluate('getComputedStyle(document.querySelector(".record-table tbody tr")).display'),'block');
      await screenshot(`manager-herd-${width}.png`);
      await navigate('supplies');await click('[data-action=add-product]');await until('document.querySelector("dialog").open');
      assert.equal(await evaluate('document.querySelector("dialog").getBoundingClientRect().width<=window.innerWidth'),true);
      assert.equal(await evaluate('[...document.querySelectorAll("dialog input,dialog select,dialog button")].every(e=>e.getBoundingClientRect().height>=44)'),true);
      await click('[data-action=close-modal]');
    }else{
      assert.equal(await evaluate('[...document.querySelectorAll(".quick-action")].every(e=>e.getBoundingClientRect().height>=44)'),true);
      await screenshot(`field-home-${width}.png`);
    }
  }
  await command('Emulation.setDeviceMetricsOverride',{width:1366,height:900,deviceScaleFactor:1,mobile:false});
}

try{
  await connect();await command('Page.enable');await command('Runtime.enable');await command('Network.enable');
  await command('Emulation.setDeviceMetricsOverride',{width:1366,height:900,deviceScaleFactor:1,mobile:false});
  await command('Page.navigate',{url:baseURL+'/'});
  await until('!!document.querySelector("#login-form")');
  if(process.argv.includes('--release-layouts')){await checkReleaseLayouts();}else{
  await checkLogo('.login-brand img');await screenshot('company-logo-login.png');
  await checkBrandAssets();
  await checkAuthLayouts();await checkAccountWorkflows();await checkAccountTransition();
  await command('Emulation.setDeviceMetricsOverride',{width:360,height:920,deviceScaleFactor:1,mobile:true});
  await checkLogo('.login-brand img');await screenshot('company-logo-login-mobile.png');
  await command('Emulation.setDeviceMetricsOverride',{width:1366,height:900,deviceScaleFactor:1,mobile:false});
  // A local server can remain reachable when Windows reports no internet.
  await until('!!document.querySelector("#login-form")');
  await evaluate('Object.defineProperty(navigator,"onLine",{configurable:true,get:()=>false});updateAuthConnection()');
  assert.equal(await evaluate('document.querySelector("#login-form button[type=submit]").disabled'),false);
  await fill('[name=username]','manager');await fill('[name=password]',passwords.manager);
  await click('#login-form button[type=submit]');
  await until('!!document.querySelector(".sidebar") && !document.querySelector(".loading")');
  await evaluate('delete navigator.onLine');
  await until('document.body.innerText.includes("Farm overview")');await screenshot('manager-overview.png');
  await checkLogo('.brand img');
  assert.ok(await evaluate('document.querySelector("#connection").textContent.includes("Farm Manager")'));
  await click('[data-action=toggle-notifications]');assert.equal(await evaluate('document.querySelector("#notification-menu").hidden'),false);await click('[data-action=toggle-notifications]');
  assert.equal(await evaluate('getComputedStyle(document.body).backgroundColor'),'rgb(210, 210, 210)');
  assert.equal(await evaluate('getComputedStyle(document.querySelector("[data-action=capture]")).backgroundColor'),'rgb(47, 93, 58)');
  assert.equal(await evaluate('getComputedStyle(document.querySelector("[data-action=capture]")).color'),'rgb(255, 255, 255)');
  assert.equal(await evaluate('getComputedStyle(document.querySelector("h1")).fontWeight'),'700');
  for(const page of ['herd','health','supplies','money','reports','approvals','administration','account']){
    await navigate(page);assert.equal(await evaluate('document.body.innerText.includes("Unable to load records")'),false,page+' page should load');
  }
  await checkAllCaptureTrackers();await checkBatchForms();await checkFarmWorkflowRelease();
  await mobileChecks('manager','overview');
  await navigate('reports');await evaluate('document.querySelector("#report-form").requestSubmit()');await until('!!document.querySelector("#report-results table")');assert.ok((await evaluate('document.querySelectorAll("#report-results tbody tr").length'))>=87);
  const reportTypes=['Herd','Health','Breeding','Growth','Movements','Births/deaths','Acquisitions/sales','Supplies','Finances'];
  for(const type of reportTypes){
    await fill('[name=type]',type);await evaluate('document.querySelector("#report-form").requestSubmit()');
    await until(`document.querySelector('#report-results .titlebar')?.textContent.includes(${JSON.stringify(type+' report')})`);
    const pdf=await evaluate(`fetch('/api/reports.pdf?'+new URLSearchParams({type:${JSON.stringify(type)}})).then(async r=>({status:r.status,signature:new TextDecoder().decode((await r.arrayBuffer()).slice(0,4))}))`);
    assert.deepEqual(pdf,{status:200,signature:'%PDF'},type);
  }
  await fill('[name=type]','Herd');await evaluate('document.querySelector("#report-form").requestSubmit()');await until('!!document.querySelector("#report-results table")');
  await command('Emulation.setEmulatedMedia',{media:'print'});
  assert.equal(await evaluate('getComputedStyle(document.querySelector(".sidebar")).display'),'none');
  assert.equal(await evaluate('getComputedStyle(document.querySelector("#report-results table")).display'),'table');
  await command('Emulation.setEmulatedMedia',{media:''});
  await click('[data-action=logout]');await login('hand');await until('document.body.innerText.includes("Field records")');
  assert.ok(await evaluate('document.querySelector("#connection").textContent.includes("General Hand")'));
  assert.equal(await evaluate('!!document.querySelector("#avatar-upload")'),false);
  assert.equal(await evaluate('!!document.querySelector("[data-action=edit-avatar]")'),false);
  assert.equal(await evaluate('document.querySelector("#main").innerText.includes("Downloaded cattle cover")'),false);
  assert.equal(await evaluate('document.querySelector("#main").innerText.includes("Record what happened")'),false);
  assert.equal(await evaluate('document.querySelectorAll(".quick-action small").length'),0);
  await click('[data-action=toggle-notifications]');assert.equal(await evaluate('document.querySelector("#notification-menu").hidden'),false);await click('[data-action=toggle-notifications]');
  await navigate('account');assert.equal(await evaluate('!!document.querySelector("#avatar-upload")'),true);assert.equal(await evaluate('!!document.querySelector("[data-action=edit-avatar]")'),true);
  await mobileChecks('hand','home');
  await command('Emulation.setDeviceMetricsOverride',{width:820,height:1180,deviceScaleFactor:1,mobile:true});await screenshot('field-home.png');
  await until('!!navigator.serviceWorker.controller');
  await command('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  await checkOfflineBrandAssets();await checkOfflineBirthDraft();
  await click('[data-action=capture][data-kind=procedure]');await until('!!document.querySelector("#cattle-list")');
  await checkCaptureLayouts(1);await click('[data-action=select-all]');
  const ids=await evaluate('[...document.querySelectorAll("[data-cattle]")].slice(-4).map(e=>e.value)');
  for(const id of ids)await click(`[data-cattle][value="${id}"]`);
  assert.equal(await evaluate('document.querySelectorAll("[data-cattle]:checked").length'),83);
  await evaluate('document.querySelector("#capture-form").requestSubmit()');await until('!!document.querySelector("[name=procedure]")');
  await checkCaptureLayouts(2);
  await fill('[name=procedure]','Dipping');await click('[data-action=add-product-row]');await fill('[data-product]','1');await fill('[data-quantity]','4');await fill('[data-dosage]','Recorded concentration');
  await click('[data-action=save-draft]');await until('document.querySelector("#notice").textContent.includes("Draft saved")');
  const draftId=await evaluate('editor.id');
  await reloadPage();await until('!!document.querySelector(".sidebar")');await navigate('records');
  await click(`[data-action=edit-draft][data-id="${draftId}"]`);await until('!!document.querySelector("#capture-form")');await checkCaptureStep(1,2);
  assert.equal(await evaluate('document.querySelectorAll("[data-cattle]:checked").length'),83);
  await evaluate('document.querySelector("#capture-form").requestSubmit()');await until('!!document.querySelector("[name=procedure]")');await checkCaptureStep(2);
  assert.equal(await evaluate('document.querySelector("[data-quantity]").value'),'4');
  await evaluate('document.querySelector("#capture-form").requestSubmit()');await until('document.querySelector(".step.active")?.textContent.includes("Review")');
  await checkCaptureLayouts(3);
  await until(`storeGet('records:'+user.id).then(records=>records?.find(r=>r.id===${JSON.stringify(draftId)})?.furthestStep===3)`);
  // Reopening immediately after reaching Review must retain every reached colour.
  await reloadPage();await until('!!document.querySelector(".sidebar")');await navigate('records');
  await click(`[data-action=edit-draft][data-id="${draftId}"]`);await until('!!document.querySelector("#capture-form")');await checkCaptureStep(1,3);
  await evaluate('document.querySelector("#capture-form").requestSubmit()');await until('!!document.querySelector("[name=procedure]")');await checkCaptureStep(2,3);
  await evaluate('document.querySelector("#capture-form").requestSubmit()');await until('document.querySelector(".step.active")?.textContent.includes("Review")');await checkCaptureStep(3);
  await click('[data-action=back-step]');await until('!!document.querySelector("[name=procedure]")');await checkCaptureStep(2,3);
  await click('[data-action=back-step]');await until('!!document.querySelector("#cattle-list")');await checkCaptureStep(1,3);
  await evaluate('document.querySelector("#capture-form").requestSubmit()');await until('!!document.querySelector("[name=procedure]")');await checkCaptureStep(2,3);
  await evaluate('document.querySelector("#capture-form").requestSubmit()');await until('document.querySelector(".step.active")?.textContent.includes("Review")');await checkCaptureStep(3);
  assert.ok((await evaluate('document.querySelector("#main").innerText')).includes('83 recorded of 87 expected'));
  await screenshot('field-review.png');
  await evaluate('document.querySelector("#capture-form").requestSubmit()');
  await until('!editor && localRecords.some(r=>r.state==="Saved on this tablet")');
  await until(`storeGet('records:'+user.id).then(records=>records?.find(r=>r.id===${JSON.stringify(draftId)})?.state==='Saved on this tablet')`);
  // A restored submission must display its status without a navigation workaround.
  await until('page==="home" && document.querySelector("#notice").innerText.includes("Saved on this tablet")');
  await click('[data-action=saved-record]');await until('page==="records" && document.querySelector("#main").innerText.includes("Saved on this tablet")');
  await reloadPage();await until('document.querySelector("#main")?.innerText.includes("Saved on this tablet")');
  await command('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});await click('[data-action=sync]');await until('document.querySelector("#main").innerText.includes("Pending approval")');
  const eventId=await evaluate('[...document.querySelectorAll("[data-action=event]")].find(e=>e.textContent.includes("Dipping"))?.dataset.id');assert.ok(eventId);
  await click('[data-action=logout]');await login('manager');await navigate('approvals');await click(`[data-action=event][data-id="${eventId}"]`);await until('!!document.querySelector("[data-choice=approve]")');
  await click('[data-choice=approve]');await until('document.querySelector("dialog")?.open');await evaluate('document.querySelector("#modal-form").requestSubmit()');await until('!document.querySelector("dialog").open');
  await navigate('supplies');const balances=await evaluate('[...document.querySelectorAll("#main tbody tr")].map(r=>r.innerText)');assert.ok(balances.some(r=>r.includes('Dip concentrate')&&r.includes('16.000')));
  await screenshot('stock-after-approval.png');
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await navigate('herd');assert.equal(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true);await screenshot('mobile-herd.png');
  await click('[data-action=logout]');await login('owner');await until('document.querySelector("#connection").textContent.includes("Read only")');assert.equal(await evaluate('!!document.querySelector("#chart-expenses")'),true);assert.ok(await evaluate('[...document.querySelectorAll(".attention")].some(e=>e.textContent.includes("-7.50"))'));assert.equal(await evaluate('!!document.querySelector("[data-action=capture]")'),false);
  await click('[data-action=toggle-notifications]');assert.equal(await evaluate('document.querySelector("#notification-menu").hidden'),false);await click('[data-action=toggle-notifications]');
  await mobileChecks('owner','overview');await navigate('overview');await screenshot('owner-overview-desktop.png');await navigate('money');
  const chartCases=await evaluate(`(()=>{
    const mixed=herdLifecycleChart({registered_total:4,lifecycle_counts:{Active:1,Sold:1,Dead:1,Lost:1}});
    const empty=herdLifecycleChart({registered_total:0,lifecycle_counts:{Active:0,Sold:0,Dead:0,Lost:0}});
    return {mixedSegments:(mixed.match(/class="lifecycle-segment /g)||[]).length,mixedPercentages:(mixed.match(/25\\.0%/g)||[]).length,emptySegments:(empty.match(/class="lifecycle-segment /g)||[]).length,emptyText:empty.includes('No registered cattle.'),emptyTotal:empty.includes('text-anchor="middle">0</text>')};
  })()`);
  assert.deepEqual(chartCases,{mixedSegments:4,mixedPercentages:4,emptySegments:0,emptyText:true,emptyTotal:true});
  await checkCaptureProofDrafts();
  await checkOfflineLogout();
  assert.equal(exceptions.length,0,exceptions.join('\n'));
  assert.equal(await evaluate('document.querySelector("#notice").innerText.includes("Cannot read properties")'),false,'Account changes must not leave stale background updates');
  console.log(JSON.stringify({passed:true,checks:['Sign in/Register and recovery layouts at 360/390/650/820/1366 pixels','keyboard focus and Show/Hide','pending registration blocked and all three roles approved','General Hand station and explicit Manager access confirmation','manager-issued code, Copy, redemption, preserved account ID and field draft','account connection failures shown, local sign-in works without internet, and no credentials in IndexedDB','supplied logo fits login/header at desktop and mobile widths','all 17 capture types share retained red/yellow/green colours','reached colours retained on Back','reached colours retained in restored procedure draft','all three colours visible at Review','shared tracker colours at phone/tablet/desktop widths','Birth and Procedure forward/back and offline draft restoration','all manager pages','all nine PDF reports','print layout','forest green/deeper grey palette','bold headings','360/390/650px layouts for all roles','mobile menu and keyboard focus','record cards and touch controls','owner lifecycle totals and legend filters','tablet capture','83 participants / four absences','offline reload persistence','synchronization','whole-session approval','16 L remaining','owner read-only','pointer hit testing','double-submit protection','batch purchase form and Back retention','offline logout completes before session restoration','signed capture proof and version survive refresh, reselection, Back and offline restart','returned capture metadata updates only after explicit review'],screenshots:output},null,2));
}
}catch(error){
  if(socket){
    await screenshot('browser-failure.png').catch(()=>{});
    console.error('Browser failure context:',await evaluate('JSON.stringify({url:location.href,user:user?.role,loginError:document.querySelector("#login-error")?.innerText,loginValid:document.querySelector("#login-form")?.checkValidity(),notice:document.querySelector("#notice")?.innerText})').catch(()=>''));
  }
  throw error;
}finally{
  // Chrome may close its socket before acknowledging Browser.close.
  // Always release the isolated server rather than waiting indefinitely.
  if(socket){try{await Promise.race([command('Browser.close'),sleep(1500)]);}catch{}socket.close();}chrome.kill();server.kill();
}
