'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labelKind = kind => ({procedure:'Procedure',weight:'Weights',health:'Health issue',treatment:'Treatment',resolve_health:'Resolve health case',movement:'Movement',birth:'Birth',death:'Death',breeding:'Breeding',purchase:'Add cattle',sale:'Cattle sale',stock_in:'Receive stock',stock_use:'Use stock',expense:'Expense',income:'Income',lost:'Record lost cattle',found:'Record found cattle'}[kind] || kind);
const day = () => new Intl.DateTimeFormat('en-CA',{timeZone:'Africa/Harare',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const amount = n => Number(n || 0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const stamp = value => value ? new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Harare',dateStyle:'medium',timeStyle:'short'}).format(new Date(value)) : 'Not yet refreshed';
const svg = path => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${path}</svg>`;
const icons = {
  overview:svg('<path d="M3 10 12 3l9 7v11H3Z"/><path d="M9 21v-8h6v8"/>'),
  herd:svg('<path d="m6 8-3-5v6l4 3m11-4 3-5v6l-4 3M7 7q5-3 10 0l-1 11q-4 4-8 0Z"/><path d="M9 11h1m4 0h1M10 17h4"/>'),
  health:svg('<path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6Z"/>'),
  supplies:svg('<path d="m3 7 9-4 9 4v13H3Z M3 7l9 4 9-4 M12 11v9"/>'),
  money:svg('<rect x="3" y="5" width="18" height="14" rx="1"/><circle cx="12" cy="12" r="3"/><path d="M5 8h2m10 8h2"/>'),
  reports:svg('<path d="M5 3h10l4 4v14H5Z M14 3v5h5 M8 12h8m-8 4h8"/>'),
  approvals:svg('<path d="M8 4H4v17h16V4h-4 M8 3h8v4H8Z m0 11 3 3 6-7"/>'),
  administration:svg('<path d="M3 7h18M3 17h18M7 3v8m10 2v8"/><circle cx="7" cy="7" r="2"/><circle cx="17" cy="17" r="2"/>'),
  weight:svg('<path d="M4 9h16l2 12H2Z"/><path d="M8 9V6a4 4 0 0 1 8 0v3M12 4v3"/>'),
  movement:svg('<path d="M3 7h17m-5-5 5 5-5 5M21 17H4m5-5-5 5 5 5"/>'),
  birth:svg('<circle cx="12" cy="12" r="8"/><path d="M8 12h8m-4-4v8"/>'),
  death:svg('<path d="M12 3 2 21h20Z M12 9v6m0 2v1"/>'),
  procedure:svg('<path d="M5 5h14v16H5Z M9 3h6v4H9Z M8 12h8m-8 4h5"/>'),
  records:svg('<path d="M3 6h7l2 2h9v13H3Z M3 6V3h7l2 3"/>'),
  account:svg('<circle cx="12" cy="7" r="4"/><path d="M4 21v-3a8 8 0 0 1 16 0v3"/>'),
  performance:svg('<path d="M3 3v18h18 M6 16l5-6 4 3 6-9"/>'),
  notifications:svg('<path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>')
};
let user = null, csrf = '', ref = null, events = [], overview = null, page = '', editor = null, syncBusy = false, captureBusy = false;
let pendingLifecycleFilter = null, pendingHealthFilter = '', pendingReportType = '', pendingStationFilter = '', eventPage = 1, eventHasMore = false;
let localRecords = [], currentProfile = null, lastReport = null, reportQuery = '', importCSV = '';
const app = $('#app');
const emptyRef = {animals:[],stations:[],products:[],cases:[],categories:['Calf','Heifer','Cow','Bull','Steer'],procedures:['Dipping','Deworming','Vaccination','Other authorised procedure'],units:['L','mL','kg','g','dose','bag','unit'],finance_categories:['Medicine','Feed','Fuel','Veterinary','Transport','Other cattle expense','Other cattle income']};

const database = new Promise((resolve,reject) => {
  const request = indexedDB.open('simbanai-field-v1',1);
  request.onupgradeneeded = () => { request.result.createObjectStore('data'); };
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(new Error('Device storage is unavailable. Enable browser storage before offline capture.'));
});
async function storeGet(key) { const db = await database; return new Promise((resolve,reject) => {const r=db.transaction('data').objectStore('data').get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);}); }
async function storePut(key,value) {const db=await database;return new Promise((resolve,reject)=>{const tx=db.transaction('data','readwrite');tx.objectStore('data').put(value,key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});}
async function storeDelete(key) {const db=await database;return new Promise((resolve,reject)=>{const tx=db.transaction('data','readwrite');tx.objectStore('data').delete(key);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});}
async function loadLocal(){localRecords=await storeGet(`records:${user.id}`)||[];}
async function saveLocal(){await storePut(`records:${user.id}`,localRecords); updateConnection();}

async function api(path, options={}) {
  const response = await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json','X-Requested-With':'Simbanai','X-CSRF-Token':csrf,...options.headers}});
  const data = await response.json();
  if (!response.ok) {const error=new Error(data.error || 'The request could not be completed.');error.status=response.status;throw error;}
  return data;
}
function notice(message,error=false){const el=$('#notice');el.textContent=message;el.classList.toggle('error',error);el.style.display='block';clearTimeout(notice.timer);notice.timer=setTimeout(()=>el.style.display='none',error?12000:6500);}
function guard(fn){return async (...args)=>{try{return await fn(...args);}catch(e){notice(e.message,true);}};}
function badge(state){return `<span class="badge ${['Approved','Active','No concerns','Resolved'].includes(state)?'good':state==='Pending approval'||state==='Saved on this tablet'?'pending':['Rejected','Returned','Sync failed','Corrected'].includes(state)?'error':''}">${esc(state)}</span>`;}
function panel(title,body,extra=''){return `<section class="window section"><div class="titlebar"><span>${esc(title)}</span>${extra}</div><div class="window-body">${body}</div></section>`;}
function table(columns,rows,responsive=false){return rows.length?`<div class="table-wrap ${responsive?'record-table':''}"><table><thead><tr>${columns.map(c=>`<th scope="col">${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map((c,i)=>`<td data-label="${esc(columns[i])}">${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<div class="empty">No records to show.</div>';}
function recordTable(columns, rows){return table(columns, rows, true);}

function herdLifecycleChart(data){
  const statuses=['Active','Sold','Dead','Lost'];
  const counts=data.lifecycle_counts || {Active:data.active || 0,Sold:0,Dead:0,Lost:0};
  const total=data.registered_total ?? statuses.reduce((sum,status)=>sum+counts[status],0);
  let offset=0;
  const segments=statuses.map(status=>{
    const percentage=total?counts[status]/total*100:0;
    const circle=percentage?`<circle class="lifecycle-segment lifecycle-${status.toLowerCase()}" cx="120" cy="120" r="86" pathLength="100" stroke-dasharray="${percentage} ${100-percentage}" stroke-dashoffset="${-offset}" transform="rotate(-90 120 120)"/>`:'';
    offset+=percentage;
    return circle;
  }).join('');
  const summary=statuses.map(status=>`${status}: ${counts[status]}`).join(', ');
  return panel('Herd lifecycle',`<div class="lifecycle-layout"><svg class="lifecycle-chart" viewBox="0 0 240 240" role="img" aria-labelledby="lifecycle-title lifecycle-description"><title id="lifecycle-title">Herd lifecycle: ${total} registered cattle</title><desc id="lifecycle-description">${esc(summary)}. Includes historical cattle.</desc><circle class="lifecycle-track" cx="120" cy="120" r="86"/>${segments}<text class="lifecycle-total" x="120" y="115" text-anchor="middle">${total}</text><text class="lifecycle-centre-label" x="120" y="139" text-anchor="middle">All registered</text><text class="lifecycle-centre-label" x="120" y="155" text-anchor="middle">cattle</text></svg><div class="lifecycle-key"><p class="chart-explanation">${total?'Current and historical cattle. Select a status to view its records.':'No registered cattle.'}</p><ul class="lifecycle-legend" aria-label="Herd lifecycle key">${statuses.map(status=>`<li><button class="legend-entry" data-action="lifecycle-herd" data-status="${status}" aria-label="View ${status.toLowerCase()} cattle: ${counts[status]}"><span class="legend-swatch lifecycle-${status.toLowerCase()}" aria-hidden="true"></span><span class="legend-label">${status}</span><strong>${counts[status]}</strong><span class="legend-percent">${total?(counts[status]/total*100).toFixed(1):'0.0'}%</span></button></li>`).join('')}</ul></div></div>`);
}

function roleLabel(){return {manager:'Farm Manager',owner:'Owner · Read only',hand:'General Hand'}[user.role];}
function pageLabel(){return {home:'Home',overview:'Overview',herd:'Herd',health:'Health',supplies:'Supplies',money:'Money',reports:'Reports',approvals:'Approvals',administration:'Administration',performance:'Performance',records:'My Records',account:'Account',capture:editor?labelKind(editor.payload.kind):'Field record'}[page] || 'Overview';}
function toggleMobileMenu(open){const nav=$('#main-navigation'),button=$('[data-action=toggle-menu]');if(!nav||!button)return;const expanded=open ?? button.getAttribute('aria-expanded')!=='true';nav.classList.toggle('is-open',expanded);button.setAttribute('aria-expanded',String(expanded));button.textContent=expanded?'Close menu':'Menu';}
function field(label,name,value='',type='text',extra=''){return `<label class="field"><span>${esc(label)}</span><input name="${esc(name)}" type="${type}" value="${esc(value)}" ${extra}></label>`;}
function options(items,value,placeholder='Choose…'){return `<option value="">${esc(placeholder)}</option>`+items.map(item=>{const [v,l]=Array.isArray(item)?item:[item,item];return `<option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(l)}</option>`;}).join('');}
function select(label,name,items,value,extra=''){return `<label class="field"><span>${esc(label)}</span><select name="${esc(name)}" ${extra}>${options(items,value)}</select></label>`;}
function stationName(id){return ref.stations.find(s=>s.id===Number(id))?.name||'—';}
function animalName(id){return ref.animals.find(a=>a.id===Number(id))?.identifier||`Animal ${id}`;}
function animalLink(id){return `<button class="link" data-action="profile" data-id="${id}">${esc(animalName(id))}</button>`;}
function head(title,description,actions=''){return `<div class="page-head"><div><div class="eyebrow">Simbanai Brahmans / ${user.role==='hand'?'Field records':'Farm management'}</div><h1>${esc(title)}</h1>${description?`<p>${esc(description)}</p>`:''}</div><div class="actions no-print">${actions}</div></div>`;}
const actionButton=(kind,text)=>`<button data-action="capture" data-kind="${kind}">${esc(text||labelKind(kind))}</button>`;
function eventRows(list,review=false){return sortedEvents(list).map(e=>[esc(e.date),`<button class="link" data-action="event" data-id="${esc(e.id)}">${esc(e.name|| (e.kind==='procedure'?e.payload.procedure:labelKind(e.kind)))}</button>`,esc(stationName(e.station_id)),esc(e.author),esc(e.payload.purchase_rows?.length||e.payload.animal_ids?.length|| (['birth','purchase'].includes(e.kind)?1:0)),badge(e.conflicts?.length?'Pending with conflicts':e.state),`<button data-action="event" data-id="${esc(e.id)}">${review?'Review':'View'}</button>`]);}

function notificationItems(){
  if(!user)return [];
  const items=[];
  if(user.role==='hand'){
    const drafts=localRecords.filter(r=>['Draft','Saved on this tablet','Sync failed'].includes(r.state));
    if(drafts.length)items.push({action:'notification-records',title:`${drafts.length} saved record${drafts.length===1?'':'s'} need${drafts.length===1?'s':''} attention`,detail:'Open My Records to review drafts or send saved work.'});
    for(const event of events.filter(e=>['Pending approval','Returned','Rejected'].includes(e.state)))items.push({action:'notification-event',id:event.id,title:`${event.name||labelKind(event.kind)}: ${event.state}`,detail:event.reason||`${event.date} at ${stationName(event.station_id)}`});
  }else if(user.role==='manager'){
    const pending=events.filter(e=>e.state==='Pending approval');
    if(pending.length)items.push({action:'notification-approvals',title:`${pending.length} session${pending.length===1?'':'s'} waiting for approval`,detail:'Open Approvals to review field work.'});
    const shortages=(ref?.products||[]).filter(product=>product.active!==false&&product.low_stock);
    if(shortages.length)items.push({action:'notification-supplies',title:`${shortages.length} low-stock product${shortages.length===1?'':'s'}`,detail:'Open Supplies to review balances.'});
    const cases=(ref?.cases||[]).filter(item=>!item.closed_at);
    if(cases.length)items.push({action:'notification-health',title:`${cases.length} open health concern${cases.length===1?'':'s'}`,detail:'Open Health to review current cases.'});
  }else{
    if(overview?.concerns)items.push({action:'notification-herd',title:`${overview.concerns} health concern${overview.concerns===1?'':'s'}`,detail:'View cattle with recorded health concerns.'});
    if(overview?.shortages?.length)items.push({action:'notification-supplies-report',title:`${overview.shortages.length} low-stock product${overview.shortages.length===1?'':'s'}`,detail:'Open the Supplies report.'});
  }
  return items;
}
function notificationControl(){
  const items=notificationItems(),count=items.length;
  return `<div class="notification-control"><button class="notification-button secondary" data-action="toggle-notifications" aria-label="Notifications${count?`: ${count} current`:''}" aria-expanded="false" aria-controls="notification-menu">${icons.notifications}${count?`<span class="notification-count" aria-hidden="true">${count}</span>`:''}</button><section id="notification-menu" class="notification-menu" aria-label="Notifications" hidden><div class="notification-title">Notifications</div>${count?items.map(item=>`<button class="notification-item" data-action="${item.action}" ${item.id?`data-id="${esc(item.id)}"`:''}><strong>${esc(item.title)}</strong><small>${esc(item.detail)}</small></button>`).join(''):'<p class="notification-empty">No current notifications.</p>'}</section></div>`;
}
function updateNotifications(){
  const control=$('.notification-control');
  if(!control)return;
  const open=!$('#notification-menu')?.hidden;
  control.outerHTML=notificationControl();
  if(open){const menu=$('#notification-menu');const button=$('[data-action=toggle-notifications]');menu.hidden=false;button.setAttribute('aria-expanded','true');}
}
function avatarPreview(){
  const initials=user.name.split(/\s+/).filter(Boolean).slice(0,2).map(part=>part[0]).join('').toUpperCase()||'GH';
  return user.has_avatar?`<img class="station-avatar" src="/api/account/avatar?v=${encodeURIComponent(user.avatar_updated_at||'current')}" alt="${esc(user.name)} profile picture">`:`<span class="station-avatar avatar-initials" aria-label="No profile picture">${esc(initials)}</span>`;
}
async function updateAvatar(request){
  const response=await fetch('/api/account/avatar',{method:request.method,credentials:'same-origin',headers:{'X-Requested-With':'Simbanai','X-CSRF-Token':csrf},body:request.body});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'Profile picture could not be updated.');
  user=result.user;
  await storePut('current-user',user);
  await route();
}
function bindAvatarControls(){
  const input=$('#avatar-upload');
  if(!input)return;
  input.onchange=guard(async()=>{
    const file=input.files?.[0];
    if(!file)return;
    const form=new FormData();form.append('avatar',file);
    await updateAvatar({method:'POST',body:form});
    notice('Profile picture updated.');
  });
}

function loginScreen(needsSetup=false){renderAuthScreen(needsSetup);}

function navigation(){const entries=user.role==='hand'?[['home','Home','overview'],['records','My Records','records'],['account','Account','account']]:user.role==='owner'?[['overview','Overview','overview'],['herd','Herd','herd'],['performance','Performance','performance'],['money','Money','money'],['reports','Reports','reports']]:[['overview','Overview','overview'],['herd','Herd','herd'],['health','Health','health'],['supplies','Supplies','supplies'],['money','Money','money'],['reports','Reports','reports'],['approvals','Approvals','approvals'],['administration','Administration','administration']];return entries.map(([id,title,icon])=>`<a class="navitem ${page===id?'active':''}" href="#${id}" ${page===id?'aria-current="page"':''}>${icons[icon]}${title}</a>`).join('');}
function renderShell(){
  document.body.classList.toggle('tablet',user.role==='hand');
  app.innerHTML=`<header class="topbar"><div class="brand-stack"><div class="brand"><img src="/static/company-logo.png" alt="Simbanai Brahmans logo" width="1672" height="941"><div><strong>Simbanai Brahmans</strong><small>CATTLE MANAGEMENT SYSTEM</small></div></div></div><div class="userbox">${notificationControl()}<button class="secondary" data-action="account">Account</button><button class="secondary" data-action="logout">Sign out</button></div></header><div class="connection" id="connection"></div><div class="mobile-nav-bar"><div><strong>${esc(pageLabel())}</strong><small>${esc(roleLabel())}</small></div><button data-action="toggle-menu" aria-expanded="false" aria-controls="main-navigation">Menu</button></div><div class="shell"><nav class="sidebar" id="main-navigation" aria-label="Main navigation">${navigation()}</nav><main class="main" id="main" tabindex="-1"></main></div>`;
  updateConnection();
}
function updateConnection(){const el=$('#connection');if(!el||!user)return;const queued=localRecords.filter(r=>r.state==='Saved on this tablet'||r.state==='Sync failed').length;el.innerHTML=`<span><strong>${esc(user.name)}</strong> · ${esc(roleLabel())}</span><span>${navigator.onLine?'Online':'Offline'}${queued?` · ${queued} saved record${queued===1?'':'s'} waiting to send`:''} ${user.role==='hand'?`<button data-action="sync" ${syncBusy?'disabled':''}>${syncBusy?'Sending…':'Send & refresh'}</button>`:''}</span>`;updateNotifications();}
async function refresh(){
  const account=user;if(!account)return false;
  const reference=await api('/api/reference');
  const eventResult=await api('/api/events?order='+recordOrder);const officialEvents=eventResult.events;eventPage=1;eventHasMore=eventResult.has_more;
  const totals=account.role==='hand'?null:await api('/api/overview');
  if(user!==account)return false;
  ref=reference;events=officialEvents;if(account.role!=='hand')overview=totals;
  if(account.role==='hand'){await storePut(`reference:${account.id}`,reference);await storePut(`events:${account.id}`,officialEvents);}
  if(user!==account)return false;
  updateConnection();return true;
}
async function start(){const account=user;await loadLocal();try{if(!await refresh())return;}catch(error){if(user!==account)return;if(account.role!=='hand'||error.status)throw error;ref=await storeGet(`reference:${account.id}`);events=await storeGet(`events:${account.id}`)||[];if(!ref)throw new Error('Connect once to download your station’s cattle before working offline.');notice('Offline. Saved cattle lists and drafts are available.');}if(user!==account)return;renderShell();await route();if(user===account&&account.role==='hand'&&navigator.onLine)await syncQueue();}
async function route(){
  if(!user){
    renderAuthScreen();
    return;
  }let next=location.hash.slice(1)|| (user.role==='hand'?'home':'overview');
  if(AUTH_VIEWS.includes(next)){
    next=user.role==='hand'?'home':'overview';
    history.replaceState(null,'',location.pathname+location.search+'#'+next);
  }const allowed=user.role==='hand'?['home','records','account']:user.role==='owner'?['overview','herd','performance','money','reports','account']:['overview','herd','health','supplies','money','reports','approvals','administration','account'];
  if(!allowed.includes(next)){
    location.hash=allowed[0];
    return;
  }page=next;
  if(page!=='herd')pendingLifecycleFilter=null;
  editor=null;
  renderShell();
  const main=$('#main');
  main.innerHTML='<div class="loading">Loading records…</div>';
  try{
    if(page==='home')renderFieldHome();
    else if(page==='overview'||page==='performance')renderOverview();
    else if(page==='herd')renderHerd(pendingStationFilter,pendingHealthFilter,pendingLifecycleFilter || 'Active');
    else if(page==='records')renderRecords();
    else if(page==='approvals')renderApprovals();
    else if(page==='health')renderHealth();
    else if(page==='supplies')await renderSupplies();
    else if(page==='money')await renderMoney();
    else if(page==='reports')renderReports();
    else if(page==='administration')await renderAdministration();
    else renderAccount();
  }catch(e){
    main.innerHTML=head('Unable to load records','Your saved field drafts remain on this device.')+`<div class="alert error">${esc(e.message)}</div><button data-action="reload">Try again</button>`;
  }
}

function renderFieldHome(){const entries=[['procedure','Record procedure'],['weight','Record weights'],['health','Report health issue'],['movement','Record movement'],['birth','Record birth'],['death','Report death']];$('#main').innerHTML=head('Field records','')+stationChooser()+`<div class="quick-grid">${entries.map(([kind,title])=>`<button class="quick-action" data-action="capture" data-kind="${kind}">${icons[kind]||icons.health}<span><strong>${title}</strong></span></button>`).join('')}</div>`+panel('My recent records',recordTable(['Date','Record','Station','Recorded by','Cattle','Status',''],eventRows(sortedEvents(events).slice(0,5))))+`<p class="footer-note">Saved on this tablet means it has not reached the manager yet.</p>`;}
function renderOverview(){
  if(page==='performance'){
    renderPerformance();
    return;
  }if(!overview){
    $('#main').innerHTML=head('Overview','Connect to view official farm records.')+panel('No connection','<p>The manager and owner need an internet connection.</p>');
    return;
  }const o=overview;
  if(user.role==='owner'){renderOwnerOverview(o);return;}
  const performance=page==='performance';
  const stats=performance?[['Births this month',o.births,'Live calves','reports'],['Deaths this month',o.deaths,'Confirmed deaths','reports'],['Animals weighed',o.animals_weighed,'With official weight records','reports'],['Pregnancy checks',o.breeding_checks,'Recorded this month','reports']]:[['Active herd',o.active,'Official cattle records','herd'],['Health concerns',o.concerns,'Active cattle needing attention','health'],[user.role==='manager'?'Waiting for approval':'Births this month',user.role==='manager'?o.pending:o.births,user.role==='manager'?'Field sessions to review':'Live calves',user.role==='manager'?'approvals':'reports'],['Low stock',o.shortages.length,'Products at or below minimum','supplies']];
  $('#main').innerHTML=head(performance?'Performance':'Farm overview',`Official records · ${new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Harare',dateStyle:'long'}).format(new Date())}`,user.role==='manager'?actionButton('birth','Record birth')+actionButton('purchase','Add cattle'):'')+`<div class="stats">${stats.map(([title,count,desc,target])=>`<button class="stat" data-action="navigate" data-page="${user.role==='owner'&&target==='health'?'herd':user.role==='owner'&&target==='supplies'?'reports':target}" ${user.role==='owner'&&target==='health'?'data-health="concerns"':''} ${user.role==='owner'&&target==='supplies'?'data-report="Supplies"':''}><span class="stat-label">${title}</span><strong>${count}</strong><small>${desc}</small></button>`).join('')}</div>${user.role==='owner'&&!performance?herdLifecycleChart(o):''}<div class="grid2">${panel('Herd by station',`<ul class="split-list">${o.stations.map(s=>`<li><div><button class="link" data-action="station-herd" data-id="${s.id}">${esc(s.name)}</button><progress class="station-bar" value="${s.count}" max="${Math.max(o.active,1)}" aria-label="${esc(s.name)} herd share"></progress></div><strong>${s.count} cattle</strong></li>`).join('')}</ul>`)}${panel('Needs attention',o.shortages.length||o.concerns||o.due.length?`<ul class="split-list">${o.concerns?`<li><span>${o.concerns} cattle with health concerns</span><button data-action="navigate" data-page="${user.role==='manager'?'health':'herd'}" data-health="concerns">View cattle</button></li>`:''}${o.shortages.map(p=>`<li><span>${esc(p.name)}<br><small class="muted">${esc(p.balance)} ${esc(p.unit)} remaining · minimum ${esc(p.minimum)}</small></span>${user.role==='manager'?'<button data-action="capture" data-kind="stock_in">Receive stock</button>':badge('Low stock')}</li>`).join('')}${groupProcedureReminders(o.due).map(d=>`<li><span>${esc(d.procedure)} · ${esc(stationName(d.station_id))}<br><small>Due ${esc(d.date)}</small></span><button data-action="event" data-id="${d.event_id}">View</button></li>`).join('')}</ul>`:'<div class="empty">No current health or supply concerns.</div>')}</div>`+panel('Money this month',`<div class="money-grid">${['USD','ZiG'].map(currency=>`<div class="money-total"><h3>${currency}</h3><ul class="split-list"><li><span>Income</span><strong>${amount(o.money[currency].Income)}</strong></li><li><span>Expenses</span><strong>${amount(o.money[currency].Expense)}</strong></li><li class="net"><span>Net</span><strong>${amount(o.money[currency].Net)}</strong></li></ul></div>`).join('')}</div><p class="small muted">Currencies are shown separately. <button class="link" data-action="navigate" data-page="money">View transactions</button></p>`)+panel('Recent official records',recordTable(['Date','Record','Station','Recorded by','Cattle','Status',''],eventRows(o.recent)));
}

function renderHerd(station='',health='',lifecycle='Active'){
  const actions=user.role==='manager'?actionButton('purchase','Add cattle')+actionButton('movement','Record movement')+actionButton('sale','Record sale')+actionButton('breeding','Record breeding'):'';
  $('#main').innerHTML=head('Herd','Find cattle, review their history, and manage the herd.',actions)+`<section class="window"><div class="titlebar">Cattle register <span class="small">${ref.animals.length} total records</span></div><div class="window-body"><div class="toolbar"><label><span>Search tag or brand</span><input id="herd-search" type="search" placeholder="e.g. SB-0024"></label><label><span>Station</span><select id="herd-station">${options(ref.stations.map(s=>[s.id,s.name]),station,'All stations')}</select></label><label><span>Lifecycle</span><select id="herd-status">${options(['Active','Sold','Dead','Lost'],lifecycle,'All statuses')}</select></label><label><span>Health</span><select id="herd-health">${options(['concerns','No concerns','Under observation','Under treatment'],health,'All health states')}</select></label></div><div id="herd-table"></div></div></section>`;
  ['herd-search','herd-station','herd-status','herd-health'].forEach(id=>$('#'+id).addEventListener('input',filterHerd));
  filterHerd();
}
function filterHerd(){const query=$('#herd-search').value.toLowerCase(),station=$('#herd-station').value,status=$('#herd-status').value,health=$('#herd-health').value;const list=ref.animals.filter(a=>(a.identifier+' '+a.brand).toLowerCase().includes(query)&&(!station||a.station_id===Number(station))&&(!status||a.lifecycle===status)&&(!health||(health==='concerns'?a.health!=='No concerns':a.health===health)));$('#herd-table').innerHTML=recordTable(['Tag / ID','Sex','Category','Station','Lifecycle','Health'],list.map(a=>[animalLink(a.id)+(a.temporary?'<br><small>Temporary ID</small>':''),esc(a.sex),esc(a.category),esc(a.station),badge(a.lifecycle),attentionBadge(a)]));}
function renderRecords(){const drafts=localRecords.filter(r=>r.state==='Draft'||r.state==='Saved on this tablet'||r.state==='Sync failed');$('#main').innerHTML=head('My Records','Follow your saved drafts, submissions, and manager feedback.')+panel('Saved on this tablet',recordTable(['Date','Record','Status','Feedback',''],sortedEvents(drafts.map(r=>({...r,date:r.payload.date,created_at:r.updated_at}))).map(r=>[esc(r.payload.date),esc(r.payload.kind==='procedure'?(r.payload.procedure||'Procedure'):labelKind(r.payload.kind)),badge(r.state),esc(r.error||''),`<button data-action="edit-draft" data-id="${r.id}">Open</button>`])))+panel('Station cattle',`<details><summary>Find station cattle (${ref.animals.length})</summary>${recordTable(['Animal','Lifecycle','Health',''],ref.animals.map(a=>[esc(a.identifier),badge(a.lifecycle),attentionBadge(a),`<div class="actions"><button data-action="profile" data-id="${a.id}">View animal</button><button data-action="capture" data-kind="${a.lifecycle==='Lost'?'found':'lost'}" data-id="${a.id}">${a.lifecycle==='Lost'?'Record found':'Record lost'}</button></div>`]))}</details>`)+recordSortControl()+panel('Submitted records',recordTable(['Date','Record','Station','Recorded by','Cattle','Status',''],eventRows(events)))+(eventHasMore?'<button data-action="more-events">Load more records</button>':'');}
function renderApprovals(){const pending=events.filter(e=>e.state==='Pending approval');$('#main').innerHTML=head('Approvals',`${pending.length} field sessions waiting for your review. Official records update only after approval.`)+panel('Waiting for approval',recordTable(['Date','Record','Station','Recorded by','Cattle','Status',''],eventRows(pending,true)));}
function renderHealth(){const open=ref.cases.filter(c=>!c.closed_at);$('#main').innerHTML=head('Health','Observations, treatments, and procedures stay linked to each animal.',actionButton('health','Record health issue')+actionButton('procedure','Record procedure'))+panel('Open health cases',open.length?open.map(c=>`<article class="health-case"><strong class="attention">! Current health concern</strong><div class="actions">${animalLink(c.animal_id)} ${badge(c.status)}</div><p>${esc(c.observation)}</p><div class="actions"><button data-action="case-treatment" data-id="${c.id}">Record treatment</button><button data-action="case-resolve" data-id="${c.id}">Resolve case</button></div></article>`).join(''):'<div class="empty">No open health cases.</div>')+panel('Health history',recordTable(['Date','Record','Station','Recorded by','Cattle','Status',''],eventRows(events.filter(e=>['procedure','health','treatment','resolve_health'].includes(e.kind)&&['Approved','Corrected'].includes(e.state)))));}
async function renderSupplies(){const stock=(await api('/api/stock')).transactions;$('#main').innerHTML=head('Supplies','Medicine, feed, and fuel quantities. Purchases are recorded once.',actionButton('stock_in','Receive stock')+actionButton('stock_use','Record usage')+'<button data-action="add-product">Add product</button>')+panel('Current stock',recordTable(['Product','Category','Balance','Unit','Minimum','Status',''],ref.products.map(p=>[esc(p.name),esc(p.category),esc(p.balance),esc(p.unit),esc(p.minimum),p.active===false?'Archived':Number(p.balance)<=Number(p.minimum)?'<strong class="attention">! Low stock</strong>':badge('Available'),`<button data-action="minimum" data-id="${p.id}">Set minimum</button><button data-action="archive-product" data-id="${p.id}">${p.active===false?'Restore':'Archive'}</button>`])))+panel('Stock history',recordTable(['Date','Product','Quantity','Description','Source record'],stock.map(t=>[esc(t.date),esc(ref.products.find(p=>p.id===t.product_id)?.name),esc(t.quantity),esc(t.description),`<button class="link" data-action="event" data-id="${t.event_id}">${esc(t.event_id.slice(0,8))}</button>`])));}
async function renderMoney(){const transactions=(await api('/api/money')).transactions;$('#main').innerHTML=head('Money','Operational income and expenses. USD and ZiG remain separate.',user.role==='manager'?actionButton('expense','Record expense')+actionButton('income','Record income'):'')+panel('All-time totals',`<div class="money-grid">${['USD','ZiG'].map(currency=>{const list=transactions.filter(t=>t.currency===currency),income=list.filter(t=>t.type==='Income').reduce((s,t)=>s+Number(t.amount),0),expense=list.filter(t=>t.type==='Expense').reduce((s,t)=>s+Number(t.amount),0);return `<div class="money-total"><h3>${currency}</h3><ul class="split-list"><li><span>Income</span><strong>${amount(income)}</strong></li><li><span>Expenses</span><strong>${amount(expense)}</strong></li><li class="net"><span>Net</span><strong class="${income-expense<0?'attention':''}">${amount(income-expense)}</strong></li></ul></div>`;}).join('')}</div>`)+panel('Transactions',`<div class="toolbar"><label><span>Currency</span><select id="money-currency">${options(['USD','ZiG'],'','Both currencies')}</select></label><label><span>Type</span><select id="money-type">${options(['Income','Expense'],'','All types')}</select></label></div><div id="money-table"></div>`);const update=()=>$('#money-table').innerHTML=recordTable(['Date','Type','Category','Amount','Currency','Reference','Source'],transactions.filter(t=>(!$('#money-currency').value||t.currency===$('#money-currency').value)&&(!$('#money-type').value||t.type===$('#money-type').value)).map(t=>[esc(t.date),esc(t.type),esc(t.category),amount(t.amount),esc(t.currency),esc(t.reference),`<button class="link" data-action="event" data-id="${t.event_id}">${esc(labelKind(t.source))}${t.reversal_of?' · Reversal':''}</button>`]));$('#money-currency').onchange=update;$('#money-type').onchange=update;update();$('#main .page-head').insertAdjacentHTML('afterend',chartPanel('expenses'));bindChartPanel('expenses');}

function renderReports(){
  lastReport=null;
  $('#main').innerHTML=head('Reports','Generate reports from official records. No re-entry is needed.')+panel('Report filters',`<form id="report-form"><div class="form-grid">${select('Report type','type',['Herd','Health','Breeding','Growth','Movements','Births/deaths','Acquisitions/sales','Supplies','Finances'],pendingReportType||'Herd','required')}${select('Station','station',ref.stations.map(s=>[s.id,s.name]),'')}${field('From date','from','','date')}${field('To date','to','','date')}</div><p class="small muted">Herd reports show current records; date filters apply to event and transaction reports.</p><button class="primary" type="submit">Generate report</button></form>`)+`<div id="report-results"></div>`;
  $('#report-form').onsubmit=guard(async e=>{
    e.preventDefault();
    const params=new URLSearchParams(new FormData(e.target));
    reportQuery=params.toString();
    lastReport=await api('/api/reports?'+reportQuery);
    $('#report-results').innerHTML=panel(lastReport.type+' report',`<p class="report-note">${lastReport.rows.length} rows · Generated ${esc(stamp(lastReport.generated_at))} · Official records</p>`+table(lastReport.columns,lastReport.rows.map((r,index)=>r.map((value,column)=>lastReport.columns[column]==='Participating cattle'?reportAnimalTiles(lastReport.participant_groups?.[index]?.ids||[]):esc(value)))),'<div class="actions no-print"><button data-action="print">Print</button><a class="button" href="/api/reports.pdf?'+esc(reportQuery)+'">Download PDF</a></div>');
  });
}

async function renderAdministration(tab='locations'){
  const users=(await api('/api/users')).users;
  const activity=(await api('/api/activity')).activity;
  $('#main').innerHTML=head('Administration','Manage farm locations, accounts, opening records, and activity.')+`<div class="tabs">${['locations','users','opening herd','activity','settings'].map(t=>`<button data-action="admin-tab" data-tab="${t}" class="${tab===t?'active':''}">${t[0].toUpperCase()+t.slice(1)}</button>`).join('')}</div><div id="admin-content"></div>`;
  const target=$('#admin-content');
  if(tab==='locations'){
    target.innerHTML=panel('Stations',table(['Station','Active cattle'],ref.stations.map(s=>[esc(s.name),String(ref.animals.filter(a=>a.station_id===s.id&&a.lifecycle==='Active').length)])),'<button data-action="add-station">Add station</button>');
  }else if(tab==='users'){
    target.innerHTML=panel('Accounts',table(['Name','Username','Role','Station','Status',''],users.map(u=>[esc(u.name),esc(u.username),esc(u.role),esc((u.station_ids||[u.station_id]).map(stationName).join(', ')),badge(u.active?'Active':'Disabled'),u.role==='hand'?`<button data-action="edit-user" data-id="${u.id}">Manage</button>`:u.role==='owner'?'Recovery below':'Administrator recovery'])),'<button data-action="add-user">Add General Hand</button>');
    window.adminUsers=users;
    target.insertAdjacentHTML('beforeend','<div id="account-requests" class="account-request-panels"></div>');
    await renderAccountRequests();
  }else if(tab==='activity'){
    target.innerHTML=panel('Activity history',table(['When','Who','Action','Details'],activity.map(a=>[esc(stamp(a.at)),esc(a.user),esc(a.action),Object.keys(a.details||{
    }).length?`<details><summary>View change</summary><pre>${esc(formatCorrectionDetails(a.details))}</pre></details>`:'—'])));
  }else if(tab==='settings'){
    target.innerHTML=panel('Farm defaults',`<dl class="summary-list"><dt>Language</dt><dd>English</dd><dt>Weight unit</dt><dd>Kilograms</dd><dt>Time zone</dt><dd>Africa/Harare</dd><dt>Currencies</dt><dd>USD and ZiG, separate totals</dd><dt>Approval</dt><dd>Whole field session, online manager review</dd></dl><p class="small muted">Backup scheduling and restoration instructions are in the project README.</p>`);
    target.insertAdjacentHTML('beforeend',panel('Calf category review',`<form id="category-settings">${field('Review after calendar months','calf_review_months',ref.calf_review_months||6,'number','min="1" max="60" required')}<button type="submit">Save review interval</button><p>Reminders require a known birth date. Managers confirm classification; age does not determine castration or calving.</p></form>`));
    $('#category-settings').onsubmit=guard(async e=>{e.preventDefault();await api('/api/settings',{method:'POST',body:JSON.stringify({calf_review_months:Number(e.target.elements.calf_review_months.value)})});await refresh();notice('Category review interval saved.');});
  }else{
    target.innerHTML=panel('Opening herd import',`<p>Enter paper records in the CSV spreadsheet template. Dates use YYYY-MM-DD; leave unknown dates and parents blank. Create stations first.</p><a class="button" href="/api/import/template">Download template</a><form id="import-form">${field('Opening herd CSV','file','','file','accept=".csv,text/csv" required')}<button type="submit">Preview import</button></form><div id="import-preview"></div>`);
    $('#import-form').onsubmit=guard(async e=>{
      e.preventDefault();
      importCSV=await e.target.elements.file.files[0].text();
      const result=await api('/api/import/preview',{
        method:'POST',body:JSON.stringify({
          csv:importCSV
        })
      });
      $('#import-preview').innerHTML=result.errors.length?`<div class="alert error">Correct all errors before importing.</div>`+table(['CSV line','Error'],result.errors.map(r=>[esc(r.line),esc(r.error)])):`<div class="alert success">${result.count} records validated. No historical expenses will be created.</div>`+table(['Tag','Sex','Category','Station','Birth date'],result.rows.slice(0,100).map(r=>[esc(r.identifier),esc(r.sex),esc(r.category),esc(stationName(r.station_id)),esc(r.dob||'Unknown')]))+'<button class="primary" data-action="import-commit">Confirm opening herd import</button>';
    });
  }
}

function renderAccount(){ const picture=user.role==='hand'?panel('Profile picture',`<div class="avatar-tools account-avatar-tools">${avatarPreview()}<div><p class="avatar-label">Your picture is shown on your account only.</p><div class="actions"><input id="avatar-upload" type="file" accept="image/png,image/jpeg,image/webp" hidden><button type="button" class="secondary" data-action="edit-avatar">Edit picture</button><button type="button" class="secondary" data-action="remove-avatar" ${user.has_avatar?'':'disabled'}>Remove picture</button></div></div></div>`):'';$('#main').innerHTML=head('Account','Your assigned role and account details.')+panel('Account details',`<dl class="summary-list"><dt>Name</dt><dd>${esc(user.name)}</dd><dt>Username</dt><dd>${esc(user.username)}</dd><dt>Role</dt><dd>${esc(user.role)}</dd><dt>Station access</dt><dd>${esc(user.role==='hand'?(user.station_ids||[user.station_id]).map(stationName).join(', '):'Farm-wide')}</dd></dl>`)+picture+panel('Change password',`<form id="password-form">${field('Current password','current','','password','required autocomplete="current-password"')}${field('New password (12+ characters)','password','','password','required minlength="12" autocomplete="new-password"')}<button type="submit">Change password</button></form>`);bindAvatarControls();$('#password-form').onsubmit=guard(async e=>{e.preventDefault();await api('/api/account/password',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});e.target.reset();notice('Password changed.');});}

function searchableSelect(label,name,animals,value,extra=''){return `<div class="field"><label><span>${esc(label)}</span><input type="search" class="select-search" data-target="select-${esc(name)}" placeholder="Search ${esc(label.toLowerCase())}" aria-label="Search ${esc(label.toLowerCase())}"></label><select id="select-${esc(name)}" name="${esc(name)}" aria-label="${esc(label)}" ${extra}>${options(animals.map(a=>[a.id,`${a.identifier} · ${a.sex} · ${a.category}`]),value)}</select></div>`;}
function setupSearches(){ $$('.select-search').forEach(input=>input.oninput=()=>{const query=input.value.toLowerCase();$$('option',$('#'+input.dataset.target)).forEach(option=>option.hidden=!!option.value&&!option.textContent.toLowerCase().includes(query));}); }
function startCapture(kind,existing=null,mode='new'){
  if(user.role==='owner')return;
  const origin=captureOrigin();
  page='capture';
  const firstStation=(assignedStationIds().includes(activeStationId)?activeStationId:assignedStationIds()[0])||ref.stations[0]?.id;
  const payload=existing?structuredClone(existing.payload):{
    kind,date:day(),station_id:firstStation,animal_ids:[],versions:{
    },products:[],notes:''
  };
  if(kind==='birth'&&!payload.outcome)payload.outcome='Live calf';
  if(kind==='stock_in'&&!payload.receipt_type)payload.receipt_type='Purchase';
  editor={
    id:existing?.id||crypto.randomUUID(),payload,step:1,furthestStep:existing?.furthestStep||1,mode,revision:existing?.revision||1,reason:existing?.reason||'',state:existing?.state||'Draft', origin:existing?.origin||origin, originalSelection:new Set(existing?[...(payload.animal_ids||[]),...(payload.absent_ids||[]),...(payload.dam_id?[Number(payload.dam_id)]:[])]:[])
  };
  renderCapture();
}
function captureShell(body){
  editor.furthestStep=Math.max(editor.furthestStep||1,editor.step);
  $('#main').innerHTML=head(labelKind(editor.payload.kind),user.role==='hand'?'Record what happened. The manager reviews your submission.':'Review and confirm to update official records.')+`<section class="window"><div class="titlebar">${esc(labelKind(editor.payload.kind))} session <span class="small">${editor.mode==='correct'?'Controlled correction':editor.mode==='returned'?'Returned for correction':'New record'}</span></div><div class="window-body"><div class="steps capture-steps">${['Select cattle','Enter details','Review'].map((title,i)=>`<div class="step ${editor.step===i+1?'active':''} ${i+1<=editor.furthestStep?'reached':''}" data-step="${i+1}" ${editor.step===i+1?'aria-current="step"':''}><span>${i+1}.</span>${title}</div>`).join('')}</div><form id="capture-form">${body}<div id="capture-error" role="alert"></div><div class="form-footer"><button type="button" data-action="cancel-capture" class="secondary">Cancel</button><div class="actions">${user.role==='hand'?'<button type="button" data-action="save-draft">Save draft</button>':''}${editor.step>1?'<button type="button" data-action="back-step">Back</button>':''}<button type="submit" class="primary">${editor.step===3?(user.role==='hand'?'Submit record':'Confirm official record'):'Next'}</button></div></div></form></div></section>`;
  $('#capture-form').onsubmit=guard(advanceCapture);
  setupSearches();
}
function renderCapture(){
  const p=editor.payload;
  rememberCaptureMetadata([...(p.animal_ids||[]),...(p.dam_id?[Number(p.dam_id)]:[])]);
  if(editor.step===1){
    const finance=['expense','income'].includes(p.kind);
    let body=`<div class="form-grid">${finance?'':select('Station','station_id',ref.stations.filter(s=>user.role!=='hand'||assignedStationIds().includes(s.id)).map(s=>[s.id,s.name]),p.station_id,'required')}${field('Event date','date',p.date,'date','required max="'+day()+'"')}</div>`;
    if(['stock_in','stock_use','expense','income','purchase'].includes(p.kind)){
      body+='<p class="muted">Continue to enter the details.</p>';
    }else if(p.kind==='birth'){
      body+=searchableSelect('Dam','dam_id',birthDamChoices(p),p.dam_id,'required');
    }else{
      body+=`<div class="toolbar"><label><span>Find cattle</span><input id="cattle-search" type="search" placeholder="Search tag"></label><button type="button" data-action="select-all">Select all at this station</button><button type="button" data-action="select-none">Clear selection</button></div><div class="countbar"><span id="selection-count"></span><span class="small muted">Select participants; unselected cattle are excluded.</span></div><div class="cattle-list" id="cattle-list"></div>`;
    }captureShell(body+captureVersionNotice(p));
    if(['health','treatment','resolve_health','death','lost','found'].includes(p.kind)){
      $('[data-action=select-all]')?.remove();
    }if($('#cattle-list')){
      renderCattleSelection();
      $('#cattle-search').oninput=()=>renderCattleSelection();
    }$('[name=dam_id]')?.addEventListener('change',e=>{p.dam_id=Number(e.target.value)||'';rememberCaptureMetadata(p.dam_id?[p.dam_id]:[]);scheduleDraft();});$('[name=station_id]')?.addEventListener('change',()=>{
      p.station_id=Number($('[name=station_id]').value);
      p.animal_ids=[];
      p.dam_id='';
      renderCapture();
    });
  }else if(editor.step===2){
    captureShell(detailsForm(p));
    setupProducts();
    bindFarmCapture(p);
    $('[name=breeding_action]')?.addEventListener('change',e=>{
      collectBatchDetails(editor.payload,Object.fromEntries(new FormData($('#capture-form'))));
      editor.payload.breeding_action=e.target.value;
      renderCapture();
    });
    $('[name=receipt_type]')?.addEventListener('change',e=>{
      collectProducts();
      Object.assign(editor.payload,Object.fromEntries(new FormData($('#capture-form'))));
      editor.payload.receipt_type=e.target.value;
      renderCapture();
    });
  }else{
    captureShell(reviewMarkup(p)+(editor.mode==='correct'?`<label class="field"><span>Correction reason</span><textarea name="correction_reason" required>${esc(editor.reason)}</textarea></label>`:''));
  }
}
function selectableCattle(p){return ref.animals.filter(a=>a.lifecycle===(p.kind==='found'?'Lost':'Active')&&a.station_id===Number(p.station_id)&&(!['breeding'].includes(p.kind)||(a.sex==='Female'&&['Cow','Heifer'].includes(a.category))));}
function updateSelectionCount(){
  const target=$('#selection-count');if(!target||!editor)return;
  const total=selectableCattle(editor.payload).length,selected=editor.payload.animal_ids.length;
  target.textContent=`${selected} selected of ${total}; ${Math.max(0,total-selected)} excluded`;
}
function productsForm(p){
  return `<div class="wide"><h3>${p.kind==='stock_in'?'Products received':'Products used'}</h3><p class="small">Enter the actual stock quantity. Dosage describes concentration; added mixing water is not medicine consumed.</p><div id="product-rows"></div><button type="button" data-action="add-product-row">Add product</button></div>`;
}
function detailsForm(p){let fields=farmCaptureFields(p);const medicines=ref.products.filter(item=>item.category==='Medicine');const selected=ref.animals.filter(a=>p.animal_ids.includes(a.id));if(p.kind==='procedure')fields+=select('Procedure','procedure',ref.procedures,p.procedure,'required')+field('Next due date (optional)','next_due',p.next_due,'date')+productsForm(p);if(p.kind==='weight')fields+=`<div class="wide"><h3>Weights in kilograms</h3>${table(['Animal','Weight (kg)'],selected.map(a=>[esc(a.identifier),`<input type="number" name="weight_${a.id}" aria-label="Weight for ${esc(a.identifier)}" value="${esc(p.weights?.[a.id]||'')}" min="0.001" max="2999.999" step="0.001" required>`]))}</div>`;if(p.kind==='health')fields+=`<label class="field wide"><span>What did you observe?</span><textarea name="observation" required>${esc(p.observation)}</textarea></label>`;if(['treatment','resolve_health'].includes(p.kind)){fields+=select('Open health case','case_id',ref.cases.filter(c=>p.animal_ids.includes(c.animal_id)&&!c.closed_at).map(c=>[c.id,`Case ${c.id}: ${c.observation.slice(0,100)}`]),p.case_id,'required');if(p.kind==='treatment')fields+=productsForm(p);}if(p.kind==='movement')fields+=select('Destination station','destination_id',ref.stations.filter(s=>s.id!==Number(p.station_id)).map(s=>[s.id,s.name]),p.destination_id,'required')+select('Movement reason','movement_reason',['Grazing','Breeding','Treatment','Station transfer','Other'],p.movement_reason,'required')+(selected.some(a=>a.health!=='No concerns')?`<label class="field wide alert"><input type="checkbox" name="acknowledge_health" ${p.acknowledge_health?'checked':''} required> I acknowledge that some selected cattle have health concerns and have reviewed this movement.</label>`:'');if(p.kind==='purchase'&&p.purchase_rows){fields+=purchaseRowsForm(p);}if(['birth','purchase'].includes(p.kind)&&!p.purchase_rows){fields+=field(p.kind==='birth'?'Permanent tag (optional)':'Permanent tag','identifier',p.identifier,'text',p.kind==='purchase'?'required':'')+select('Sex','sex',['Female','Male'],p.sex,'required');if(p.kind==='birth')fields+=select('Calving outcome','outcome',['Live calf','Stillborn'],p.outcome,'required');else fields+=select('Category','category',ref.categories,p.category,'required')+field('Birth date (if known)','dob',p.dob,'date','max="'+p.date+'"');fields+=searchableSelect('Sire (if known)','sire_id',ref.animals.filter(a=>a.sex==='Male'),p.sire_id)+field('Breed','breed',p.breed||'Brahman');if(p.kind==='purchase')fields+=searchableSelect('Dam (if known)','dam_id',ref.animals.filter(a=>a.sex==='Female'),p.dam_id);}if(['lost','found'].includes(p.kind))fields+=field('Reason','lifecycle_reason',p.lifecycle_reason,'text','required');if(p.kind==='found')fields+=select('Found at station','found_station_id',ref.stations.filter(s=>user.role!=='hand'||assignedStationIds().includes(s.id)).map(s=>[s.id,s.name]),p.found_station_id||p.station_id,'required');if(p.kind==='death')fields+=field('Suspected cause','cause',p.cause,'text','required')+field('Carcass information','carcass',p.carcass);if(p.kind==='breeding'){p.breeding_action=p.breeding_action||'Bull exposure';fields+=breedingDetails(p);}if(['stock_in','stock_use'].includes(p.kind)){if(p.kind==='stock_in')fields+=select('Receipt type','receipt_type',['Purchase','Opening balance','External supply'],p.receipt_type,'required');fields+=productsForm(p);}if(p.kind==='stock_in'&&p.receipt_type==='External supply')fields+=field('Provider / source','reference',p.reference,'text','required');if(['sale','purchase','stock_in','expense','income'].includes(p.kind)&&p.acquisition_source!=='Gift'&&!(p.kind==='stock_in'&&['Opening balance','External supply'].includes(p.receipt_type))){fields+=(p.kind==='purchase'&&p.purchase_rows?'':field('Total amount','amount',p.amount,'number','min="0" step="0.01"'))+select('Currency','currency',['USD','ZiG'],p.currency)+field('Buyer / supplier / reference','reference',p.reference);if(['expense','income'].includes(p.kind))fields+=select('Category','finance_category',ref.finance_categories,p.finance_category,'required');}fields+=`<div class="wide"><details><summary>More details</summary>${['birth','purchase'].includes(p.kind)&&!p.purchase_rows?field('Brand / existing identifier','brand',p.brand)+field('Birth place','birth_place',p.birth_place):''}<label class="field"><span>Notes</span><textarea name="notes">${esc(p.notes)}</textarea></label></details></div>`;return `<div class="form-grid">${fields}</div>`;}
function reviewFields(kind){const global=['notes'];const byKind={procedure:['procedure','next_due'],weight:[],health:['observation'],treatment:['case_id'],resolve_health:['case_id'],movement:['destination_id','movement_reason'],birth:['dam_id','sire_id','sex','breed','dob','outcome','brand','birth_place'],purchase:['acquisition_source','dam_id','sire_id','sex','category','breed','dob','brand','birth_place','amount','currency','reference'],death:['cause','carcass'],breeding:['breeding_action','sire_id','pregnancy_result','expected_calving','estimate_basis'],lost:['lifecycle_reason'],found:['lifecycle_reason','found_station_id'],sale:['amount','currency','reference'],stock_in:['receipt_type','amount','currency','reference'],stock_use:[],expense:['amount','currency','reference','finance_category'],income:['amount','currency','reference','finance_category']};return [...global,...(byKind[kind]||[])];}
function setupProducts(){if(!$('#product-rows'))return;renderProducts();}
async function collectEditor(){
  if(!editor)return;
  const p=editor.payload;
  if(editor.step===1){
    const form=$('#capture-form');
    p.date=form.elements.date.value;
    if(form.elements.station_id)p.station_id=Number(form.elements.station_id.value);
    if(form.elements.dam_id)p.dam_id=Number(form.elements.dam_id.value);
    const noCattle=['birth','purchase','stock_in','stock_use','expense','income'].includes(p.kind);
    if(!noCattle&&!p.animal_ids.length)throw new Error('Select at least one animal.');
    if(['health','treatment','resolve_health','death','lost','found'].includes(p.kind)&&p.animal_ids.length!==1)throw new Error('Select one animal for this record.');
    if(p.kind==='procedure')p.absent_ids=ref.animals.filter(a=>a.station_id===p.station_id&&a.lifecycle==='Active'&&!p.animal_ids.includes(a.id)).map(a=>a.id);
    rememberCaptureMetadata([...p.animal_ids,...(p.absent_ids||[]),...(p.dam_id?[p.dam_id]:[])]);
  }else if(editor.step===2){
    const data=Object.fromEntries(new FormData($('#capture-form')));
    Object.assign(p,data);
    collectBatchDetails(p,data);
    ['dam_id','sire_id','case_id','destination_id'].forEach(key=>{
      if(p[key])p[key]=Number(p[key]);
    });
    p.acknowledge_health=!!$('[name=acknowledge_health]')?.checked;
    if(p.kind==='weight')p.weights=Object.fromEntries(p.animal_ids.map(id=>[String(id),data['weight_'+id]]));
    collectProducts();
    if((['sale','purchase','expense','income'].includes(p.kind)&&p.acquisition_source!=='Gift')||(p.kind==='stock_in'&&p.receipt_type==='Purchase')){
      if(!p.currency||(!p.purchase_rows&&(p.amount===''||p.amount==null)))throw new Error('Enter the total amount and choose a currency.');
    }if(['stock_in','stock_use','treatment'].includes(p.kind)||(p.kind==='procedure'&&p.procedure!=='Other authorised procedure')){
      if(!p.products.length)throw new Error('Add the products and quantities.');
    }if(p.kind==='breeding'&&p.breeding_action==='Bull exposure'&&!p.sire_id)throw new Error('Select the bull.');
    if(p.kind==='breeding'&&p.breeding_action==='Pregnancy check'&&!p.pregnancy_result&&!p.pregnancy_results)throw new Error('Select the pregnancy result.');
    if(p.expected_calving&&!p.estimate_basis)throw new Error('Explain the basis for the estimated calving date.');
  }else if(editor.mode==='correct')editor.reason=$('[name=correction_reason]').value.trim();
  if(user.role==='hand')await persistDraft();
}
function reviewMarkup(p){
  const selected=p.animal_ids.map(id=>animalName(id));
  let details=(['lost','found'].includes(p.kind)?`<p class="alert">${p.kind==='lost'?'Once confirmed, this animal leaves the active herd and remains registered as Lost.':'Once confirmed, this animal returns to the active herd at the found station.'} Identity, health and history are retained. No stock or financial entry is created.</p>`:'')+`<dl class="summary-list"><dt>Record</dt><dd>${esc(labelKind(p.kind))}</dd><dt>Date</dt><dd>${esc(p.date)}</dd><dt>Station</dt><dd>${esc(stationName(p.station_id))}</dd><dt>Cattle</dt><dd>${selected.length?`${selected.length} recorded${p.absent_ids?.length?` of ${selected.length+p.absent_ids.length} expected`:''}${animalTiles(p.animal_ids,p)}`:['birth','purchase'].includes(p.kind)?esc(p.identifier||'Temporary calf ID will be generated'):'Not applicable'}</dd>`;
  const fields={
    procedure:'Procedure',dam_id:'Dam',sire_id:'Sire',sex:'Sex',category:'Category',breed:'Breed',dob:'Birth date',outcome:'Outcome',observation:'Observation',cause:'Suspected cause',carcass:'Carcass',case_id:'Health case',destination_id:'Destination',movement_reason:'Movement reason',breeding_action:'Breeding action',pregnancy_result:'Pregnancy result',expected_calving:'Estimated calving',estimate_basis:'Estimate basis',next_due:'Next due',receipt_type:'Receipt type',amount:'Total amount',currency:'Currency',reference:'Reference',finance_category:'Category',brand:'Brand',birth_place:'Birth place',notes:'Notes',lifecycle_reason:'Reason',found_station_id:'Found station',acquisition_source:'Acquisition source'
  };
  const relevant=reviewFields(p.kind);
  for(const [key,label]of Object.entries(fields)){
    if(p[key]&&relevant.includes(key)){
      const value=['dam_id','sire_id'].includes(key)?animalName(p[key]):['destination_id','found_station_id'].includes(key)?stationName(p[key]):p[key];
      details+=`<dt>${label}</dt><dd>${esc(value)}</dd>`;
    }
  }if(p.absent_ids?.length)details+=`<dt>Absent cattle</dt><dd>${p.absent_ids.length} · ${animalTiles(p.absent_ids,p)}</dd>`;
  details+='</dl>';
  if(p.purchase_rows)details+=table(['Tag','Sex','Category','Price'],p.purchase_rows.map(r=>[esc(r.identifier),esc(r.sex),esc(r.category),p.acquisition_source==='Gift'?'Gift ? no expense':esc(r.price)+' '+esc(p.currency)]));
  if(p.pregnancy_results)details+=table(['Animal','Result','Estimated calving','Basis'],Object.entries(p.pregnancy_results).map(([id,r])=>[esc(animalName(id)),esc(r.pregnancy_result),esc(r.expected_calving||'Not estimated'),esc(r.estimate_basis)]));
  if(p.products?.length)details+='<h3>Products</h3>'+table(['Product','Entered quantity','Stock quantity','Dosage / concentration','Source'],p.products.map(item=>{
    const product=ref.products.find(x=>x.id===Number(item.product_id));
    return [esc(product?.name||item.product_id),esc(item.entered_quantity??item.quantity)+' '+esc(item.entered_unit||product?.unit),esc(displayStockQuantity(item,product))+' '+esc(product?.unit),esc(item.dosage),esc(item.source_note||'Farm stock')];
  }));
  if(p.weights)details+='<h3>Weights</h3>'+table(['Animal','kg'],Object.entries(p.weights).map(([id,w])=>[esc(animalName(id)),esc(w)]));
  return details;
}
async function persistDraft(){
  if(!editor||user.role!=='hand')return;
  const record={
    id:editor.id,payload:structuredClone(editor.payload),state:editor.state==='Saved on this tablet'?'Saved on this tablet':'Draft',mode:editor.mode,revision:editor.revision,origin:editor.origin,furthestStep:editor.furthestStep||editor.step,updated_at:new Date().toISOString()
  };
  const index=localRecords.findIndex(r=>r.id===record.id);
  if(index<0)localRecords.push(record);
  else localRecords[index]=record;
  await saveLocal();
}
function scheduleDraft(){clearTimeout(scheduleDraft.timer);scheduleDraft.timer=setTimeout(guard(snapshotDraft),500);}
async function submitEditor(){
  const p=editor.payload;
  if(user.role==='hand'){
    if(editor.mode==='correct')throw new Error('Only the manager can correct official records.');
    let record=localRecords.find(r=>r.id===editor.id);
    if(!record){
      await persistDraft();
      record=localRecords.find(r=>r.id===editor.id);
    }record.payload=structuredClone(p);
    record.state='Saved on this tablet';
    record.error='';
    record.mode=editor.mode;
    record.revision=editor.revision;
    await saveLocal();
    const origin=editor.origin;const savedId=editor.id;
    editor=null;
    await returnFromCapture(origin);
    notice('Saved on this tablet. The Manager reviews it after synchronization.');
    showRecordLink(savedId);
    await syncQueue();
    const saved=localRecords.find(r=>r.id===savedId);
    if(saved?.state==='Pending approval'){notice('Waiting for approval. Your submission has reached the Manager.');showRecordLink(savedId);}
  }else{
    if(!navigator.onLine)throw new Error('Connect before confirming official records.');
    const body={
      id:editor.id,payload:p,revision:editor.revision,reason:editor.reason
    };
    const path=editor.mode==='correct'?`/api/events/${editor.id}/correct`:'/api/events';
    const confirmed=await api(path,{
      method:'POST',body:JSON.stringify(body)
    });
    notice('Official record confirmed.');
    await refresh();
    const origin=editor.origin;
    editor=null;
    await returnFromCapture(origin);
    showRecordLink(confirmed.event.id);
  }
}
async function syncQueue(){
  if(syncBusy||!user||user.role!=='hand'||!navigator.onLine)return;
  const account=user;syncBusy=true;updateConnection();
  try{
    const sessionResult=await api('/api/session');if(user!==account)return;
    if(sessionResult.user?.id!==account.id)throw new Error('Sign in again to send saved records.');
    csrf=sessionResult.csrf;
    for(const record of localRecords.filter(r=>['Saved on this tablet','Sync failed'].includes(r.state))){
      if(user!==account)return;
      try{
        if(record.mode==='returned'){
          const remote=(await api('/api/events')).events.find(e=>e.id===record.id);if(user!==account)return;
          if(remote&&remote.state!=='Returned'&&remote.revision>record.revision){record.state=remote.state;record.error='';continue;}
        }
        const path=record.mode==='returned'?`/api/events/${record.id}/resubmit`:'/api/events';
        const result=await api(path,{method:'POST',body:JSON.stringify({id:record.id,payload:record.payload,revision:record.revision})});
        if(user!==account)return;
        record.state=result.event.state;record.error='';
      }catch(error){
        if(user!==account)return;
        record.state='Sync failed';record.error=error.status?error.message:'Connection interrupted. Saved on this tablet; retry when online.';if(!error.status)break;
      }
    }
    if(user!==account)return;await saveLocal();if(user!==account||!await refresh())return;
    if(!editor&&(page==='records'||page==='home'))await route();
  }catch(error){if(user===account)notice(error.message,true);}
  finally{syncBusy=false;updateConnection();}
}

async function openProfile(id,tab='overview'){let profile;if(navigator.onLine){profile=await api('/api/animals/'+id);if(user.role==='hand')await storePut(`profile:${user.id}:${id}`,profile);}else{profile=await storeGet(`profile:${user.id}:${id}`);if(!profile)throw new Error('This animal history has not been downloaded. Connect to view it.');}currentProfile=profile;editor=null;const a=profile.animal;const tabs=['overview','health','growth','breeding','movements'];let content='';if(tab==='overview'){content=`<dl class="summary-list"><dt>Lifecycle</dt><dd>${badge(a.lifecycle)}</dd><dt>Health</dt><dd>${badge(a.health)}</dd><dt>Tag / ID</dt><dd>${esc(a.identifier)} ${a.temporary?'· Temporary':''}</dd><dt>Sex / category</dt><dd>${esc(a.sex)} · ${esc(a.category)}</dd><dt>Breed</dt><dd>${esc(a.breed)}</dd><dt>Birth date</dt><dd>${esc(a.dob||'Unknown')}</dd><dt>Birth place</dt><dd>${esc(a.birth_place||'Unknown')}</dd><dt>Brand</dt><dd>${esc(a.brand||'—')}</dd><dt>Dam</dt><dd>${a.dam_id?animalLink(a.dam_id):'Unknown'}</dd><dt>Sire</dt><dd>${a.sire_id?animalLink(a.sire_id):'Unknown'}</dd><dt>Station</dt><dd>${esc(a.station)}</dd></dl><h3>Life history</h3>`+table(['Date','Record','Status',''],profile.events.map(e=>[esc(e.date),esc(e.name|| (e.kind==='procedure'?e.payload.procedure:labelKind(e.kind))),badge(e.state),user.role==='hand'&&e.author_id!==user.id?'Recorded by '+esc(e.author):`<button data-action="event" data-id="${e.id}">View</button>`]));}else if(tab==='growth'){const weights=profile.events.filter(e=>e.kind==='weight'&&e.state==='Approved').sort((x,y)=>x.date.localeCompare(y.date));content=table(['Date','Weight (kg)','Change (kg)','Daily gain (kg)'],weights.map((e,i)=>{const w=Number(e.payload.weights[id]);const prev=i?weights[i-1]:null;const delta=prev?w-Number(prev.payload.weights[id]):null;const days=prev?(new Date(e.date)-new Date(prev.date))/86400000:0;return[esc(e.date),esc(w),delta===null?'—':delta.toFixed(2),days>0?(delta/days).toFixed(3):'—'];}));}else if(tab==='breeding'){content='<h3>Breeding history</h3>'+table(['Date','Record','Details'],profile.events.filter(e=>['breeding','birth'].includes(e.kind)).map(e=>[esc(e.date),esc(e.name|| (e.kind==='procedure'?e.payload.procedure:labelKind(e.kind))),esc(e.payload.breeding_action||e.payload.outcome)+(e.payload.pregnancy_results?.[id]?'<br>'+esc(readableValue(e.payload.pregnancy_results[id])):'')+(e.payload.expected_calving?'<br>Estimated calving: '+esc(e.payload.expected_calving):'')]))+'<h3>Offspring</h3>'+table(['Tag','Sex','Birth date','Lifecycle'],profile.offspring.map(c=>[animalLink(c.id),esc(c.sex),esc(c.dob||'Unknown'),badge(c.lifecycle)]));}else{const kinds=tab==='health'?['health','procedure','treatment','resolve_health']:['movement','lost','found'];content=table(['Date','Record','Details',''],profile.events.filter(e=>kinds.includes(e.kind)).map(e=>[esc(e.date),esc(e.name|| (e.kind==='procedure'?e.payload.procedure:labelKind(e.kind))),esc(e.payload.observation||e.payload.procedure|| (e.kind==='movement'?stationName(e.payload.station_id)+' → '+stationName(e.payload.destination_id):e.payload.notes)),user.role==='hand'&&e.author_id!==user.id?'Recorded by '+esc(e.author):`<button data-action="event" data-id="${e.id}">View</button>`]));}$('#main').innerHTML=head(a.identifier,`${a.sex} / ${a.category} / ${a.station} / ${a.lifecycle} / ${a.health}`,user.role==='manager'?`<button data-action="identity" data-id="${a.id}">Edit identity / tag</button>`:'')+`<div class="tabs">${tabs.map(t=>`<button data-action="profile-tab" data-tab="${t}" class="${tab===t?'active':''}">${t[0].toUpperCase()+t.slice(1)}</button>`).join('')}</div>`+(user.role!=='hand'?profileActions(a):'')+panel('Recorded totals',profileSummaryHTML(profile))+panel('Animal '+tab,content)+(user.role!=='owner'&&['Active','Lost'].includes(a.lifecycle)?`<div class="actions"><button data-action="capture" data-kind="${a.lifecycle==='Lost'?'found':'lost'}">${a.lifecycle==='Lost'?'Record found':'Record lost'}</button></div>`:'');}

async function openEvent(id){let e=events.find(x=>x.id===id);if(!e&&navigator.onLine){e=(await api('/api/events/'+id)).event;events.push(e);}if(!e)throw new Error('Connect to download this event.');editor=null;const canReview=user.role==='manager'&&e.state==='Pending approval';if(canReview&&e.payload.products?.some(p=>p.source==='Outside source'))availableSupplyReceipts=(await api('/api/supply-receipts')).events;$('#main').innerHTML=head((e.name||labelKind(e.kind))+' record',`${e.date} · ${stationName(e.station_id)} · ${e.author}`,`<button data-action="reload">Back to ${page==='capture'?'overview':page}</button>`)+panel('Record details',`<div class="actions">${badge(e.state)} <span class="small">Submitted ${esc(stamp(e.created_at))}</span></div>${e.conflicts?.length?`<div class="alert error"><strong>Pending with conflicts</strong><ul>${e.conflicts.map(c=>`<li>${esc(c)}</li>`).join('')}</ul>Return for correction or reject; approval is blocked until resolved.</div>`:''}${e.reason?`<div class="alert">${esc(e.reason)}</div>`:''}${e.reviewer?`<p class="small">Reviewed by ${esc(e.reviewer)} · ${esc(stamp(e.reviewed_at))}</p>`:''}${reviewMarkup(e.payload)}${canReview?outsideReceiptControls(e):''}${canReview?`<div class="form-footer"><div class="actions"><button class="primary" data-action="review" data-id="${e.id}" data-choice="approve" ${e.conflicts?.length&&!e.payload.products?.some(item=>item.source==='Outside source')?'disabled':''}>Approve whole session</button><button data-action="review" data-id="${e.id}" data-choice="return">Return for correction</button><button data-action="review" data-id="${e.id}" data-choice="reject">Reject</button></div></div>`:''}${user.role==='hand'&&e.state==='Returned'?`<div class="form-footer"><button data-action="edit-returned" data-id="${e.id}">Correct and resubmit</button></div>`:''}${user.role==='manager'&&e.state==='Approved'?`<div class="form-footer"><button data-action="correct-event" data-id="${e.id}">Correct official record</button></div>`:''}`);}

function modal(title,body,onSubmit,submitLabel='Save'){const dialog=$('#modal');dialog.innerHTML=`<form id="modal-form"><div class="titlebar" id="modal-title">${esc(title)}</div><div class="dialog-body">${body}<div id="modal-error" role="alert"></div></div><div class="dialog-footer"><button type="button" class="secondary" data-action="close-modal">Cancel</button><button type="submit" class="primary">${esc(submitLabel)}</button></div></form>`;dialog.showModal();setupSearches();$('#modal-form').onsubmit=async e=>{e.preventDefault();const button=$('button[type=submit]',e.target);button.disabled=true;try{await onSubmit(Object.fromEntries(new FormData(e.target)));dialog.close();}catch(error){$('#modal-error').innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}finally{button.disabled=false;}};}
async function handleAction(button){
  if(captureBusy)return;
  const action=button.dataset.action,id=button.dataset.id;
  if(await handleFarmAction(action,button))return;
  if(action==='more-account-requests'){
    await renderAccountRequests(true);
  }else if(action==='review-registration'){
    reviewRegistration(button);
  }else if(action==='review-recovery'){
    reviewRecovery(button);
  }else if(action==='toggle-menu'){
    toggleMobileMenu();
  }else if(action==='toggle-notifications'){
    const menu=$('#notification-menu');
    const expanded=menu.hidden;
    menu.hidden=!expanded;
    button.setAttribute('aria-expanded',String(expanded));
  }else if(action==='notification-records'){
    location.hash='records';
    await route();
  }else if(action==='notification-event'){
    await openEvent(id);
  }else if(action==='notification-approvals'){
    location.hash='approvals';
    await route();
  }else if(action==='notification-supplies'){
    location.hash='supplies';
    await route();
  }else if(action==='notification-health'){
    location.hash='health';
    await route();
  }else if(action==='notification-herd'){
    pendingHealthFilter='concerns';
    location.hash='herd';
    await route();
  }else if(action==='notification-supplies-report'){
    pendingReportType='Supplies';
    location.hash='reports';
    await route();
  }else if(action==='lifecycle-herd'){
    pendingStationFilter='';pendingHealthFilter='';pendingLifecycleFilter=button.dataset.status;
    location.hash='herd';
    await route();
  }else if(action==='navigate'){
    pendingStationFilter='';
    pendingHealthFilter=button.dataset.health||'';
    pendingReportType=button.dataset.report||'';
    location.hash=button.dataset.page;
    await route();
  }else if(action==='account'){
    location.hash='account';
    await route();
  }else if(action==='edit-avatar'){
    $('#avatar-upload')?.click();
  }else if(action==='remove-avatar'){
    modal('Remove profile picture','<p>Remove your current profile picture? This does not change your account, records, or saved drafts.</p>',async()=>{
      await updateAvatar({method:'DELETE'});
      notice('Profile picture removed.');
    },'Remove picture');
  }else if(action==='logout'){
    if(localRecords.some(r=>['Draft','Saved on this tablet','Sync failed'].includes(r.state))){
      modal('Sign out',`<p>Unsent records remain on this tablet under your account. Sign back in with the same account to send them.</p>`,async()=>performLogout(),'Sign out');
    }else await performLogout();
  }else if(action==='more-events'){
    const result=await api('/api/events?page='+(eventPage+1)+'&order='+recordOrder);
    eventPage++;
    eventHasMore=result.has_more;
    const known=new Set(events.map(e=>e.id));
    events.push(...result.events.filter(e=>!known.has(e.id)));
    renderRecords();
  }else if(action==='capture'){
    startCapture(button.dataset.kind);
    if(editor.payload.kind==='purchase'){
      editor.payload.acquisition_source='Purchase';
      editor.payload.purchase_rows=[{
      }];
      renderCapture();
    }if(['lost','found'].includes(editor.payload.kind)&&(id||currentProfile)){
      const animal=ref.animals.find(a=>a.id===Number(id))||currentProfile.animal;
      editor.payload.animal_ids=[animal.id];
      editor.payload.station_id=animal.station_id;
      renderCapture();
    }
  }else if(action==='add-purchase-row'||action==='remove-purchase-row'){
    const data=Object.fromEntries(new FormData($('#capture-form')));
    Object.assign(editor.payload,data);
    collectBatchDetails(editor.payload,data);
    if(action==='add-purchase-row')editor.payload.purchase_rows.push({
    });
    else editor.payload.purchase_rows.splice(Number(button.dataset.index),1);
    renderCapture();
  }else if(action==='sync'){
    await syncQueue();
  }else if(action==='reload'){
    await refresh();
    if(page==='capture')page=user.role==='hand'?'home':'overview';
    location.hash=page;
    await route();
  }else if(action==='profile'){
    await openProfile(Number(id));
  }else if(action==='profile-tab'){
    await openProfile(currentProfile.animal.id,button.dataset.tab);
  }else if(action==='event'){
    await openEvent(id);
  }else if(action==='station-herd'){
    pendingStationFilter=id;
    location.hash='herd';
    await route();
  }else if(action==='select-all'||action==='select-none'){
    editor.payload.animal_ids=action==='select-none'?[]:selectableCattle(editor.payload).map(a=>a.id);
    rememberCaptureMetadata(editor.payload.animal_ids);
    renderCattleSelection();
    scheduleDraft();
  }else if(action==='add-product-row'){
    collectProducts();
    editor.payload.products.push({
      product_id:'',quantity:'',dosage:''
    });
    renderProducts();
  }else if(action==='remove-product-row'){
    collectProducts();
    editor.payload.products.splice(Number(button.dataset.index),1);
    renderProducts();
    scheduleDraft();
  }else if(action==='back-step'){
    captureBusy=true;
    try{
      await collectEditor();
      editor.step--;
      renderCapture();
    }finally{
      captureBusy=false;
    }
  }else if(action==='save-draft'){
    captureBusy=true;
    try{
      await snapshotDraft();
      notice('Draft saved on this tablet.');
    }finally{
      captureBusy=false;
    }
  }else if(action==='cancel-capture'){
    if(user.role==='hand')await snapshotDraft();
    editor=null;
    location.hash=user.role==='hand'?'records':'overview';
    await route();
  }else if(action==='edit-draft'){
    const r=localRecords.find(x=>x.id===id);
    if(r.state!=='Draft'){
      modal('Edit saved submission','<p>This submission will return to Draft and will wait for you to submit it again.</p>',async()=>{
        r.state='Draft';
        await saveLocal();
        startCapture(r.payload.kind,r,r.mode);
      },'Open draft');
    }else startCapture(r.payload.kind,r,r.mode);
  }else if(action==='reconcile-capture'){await reconcileReturnedCapture();}else if(action==='edit-returned'){
    startCapture(events.find(e=>e.id===id).kind,events.find(e=>e.id===id),'returned');
  }else if(action==='correct-event'){
    startCapture(events.find(e=>e.id===id).kind,events.find(e=>e.id===id),'correct');
  }else if(action==='review'){
    const e=events.find(x=>x.id===id),choice=button.dataset.choice;const product_receipts=receiptLinks();
    modal(choice==='approve'?'Approve whole session':choice==='return'?'Return for correction':'Reject session',choice==='approve'?'<p>Confirm this complete session. Animal histories, stock, and related official records will update together.</p>':'<label class="field"><span>Reason</span><textarea name="reason" required></textarea></label>',async data=>{
      await api(`/api/events/${id}/review`,{
        method:'POST',body:JSON.stringify({
          action:choice,reason:data.reason,revision:e.revision,product_receipts
        })
      });
      await refresh();
      renderApprovals();
      notice(choice==='approve'?'Session approved.':choice==='return'?'Session returned.':'Session rejected.');
    },choice==='approve'?'Approve session':choice==='return'?'Return session':'Reject session');
  }else if(action==='case-treatment'||action==='case-resolve'){
    const c=ref.cases.find(c=>c.id===Number(id));
    startCapture(action==='case-treatment'?'treatment':'resolve_health');
    editor.payload.animal_ids=[c.animal_id];
    editor.payload.station_id=ref.animals.find(a=>a.id===c.animal_id).station_id;
    editor.payload.case_id=c.id;
    renderCapture();
  }else if(action==='identity'){
    const a=currentProfile.animal;
    modal('Edit identity / permanent tag',field('Permanent tag','identifier',a.identifier,'text','required')+select('Category','category',ref.categories,a.category,'required')+field('Brand','brand',a.brand)+field('Reason','reason','','text','required'),async data=>{
      await api(`/api/animals/${a.id}/identity`,{
        method:'POST',body:JSON.stringify({
          ...data,version:a.version
        })
      });
      await refresh();
      await openProfile(a.id);
      notice('Identity updated; history retained.');
    });
  }else if(action==='add-station'){
    modal('Add station',field('Station name','name','','text','required'),async data=>{
      await api('/api/stations',{
        method:'POST',body:JSON.stringify(data)
      });
      await refresh();
      await renderAdministration();
    });
  }else if(action==='add-product'){
    modal('Add supply product',field('Product name','name','','text','required')+select('Category','category',['Medicine','Feed','Fuel'],'','required')+select('Unit','unit',ref.units,'','required')+field('Minimum stock','minimum','0','number','min="0" step="0.001" required'),async data=>{
      await api('/api/products',{
        method:'POST',body:JSON.stringify(data)
      });
      await refresh();
      await renderSupplies();
    });
  }else if(action==='minimum'){
    const p=ref.products.find(x=>x.id===Number(id));
    modal('Minimum stock · '+p.name,field('Minimum ('+p.unit+')','minimum',p.minimum,'number','min="0" step="0.001" required'),async data=>{
      await api('/api/products/'+id,{
        method:'POST',body:JSON.stringify(data)
      });
      await refresh();
      await renderSupplies();
    });
  }else if(action==='admin-tab'){
    await renderAdministration(button.dataset.tab);
  }else if(action==='add-user'||action==='edit-user'){
    const u=action==='edit-user'?window.adminUsers.find(x=>x.id===Number(id)):null;
    modal(u?'Manage General Hand':'Add General Hand',(u?'':field('Name','name','','text','required')+field('Username','username','','text','required'))+stationAssignmentControl(u?.station_ids||[u?.station_id].filter(Boolean))+(u?select('Status','active',[[true,'Active'],[false,'Disabled']],u.active,'required'):'')+field(u?'New password (leave blank to keep current)':'Password (12+ characters)','password','','password',u?'minlength="12" autocomplete="new-password"':'required minlength="12" autocomplete="new-password"'),async data=>{
      data.station_ids=selectedStationIds($('#modal-form'));data.station_id=data.station_ids[0];
      if(u)data.active=data.active==='true';
      await api(u?'/api/users/'+id:'/api/users',{
        method:'POST',body:JSON.stringify(data)
      });
      await renderAdministration('users');
    });
  }else if(action==='import-commit'){
    modal('Confirm opening herd import','<p>Validated animals will be registered as the opening herd. No historical purchases or expenses will be invented.</p>',async()=>{
      const result=await api('/api/import/commit',{
        method:'POST',body:JSON.stringify({
          csv:importCSV
        })
      });
      await refresh();
      await renderAdministration('opening herd');
      notice(`${result.count} cattle imported.`);
    },'Import cattle');
  }else if(action==='print'){
    window.open('/api/reports.pdf?'+reportQuery+'&inline=1','_blank','noopener');
  }else if(action==='close-modal'){
    const dialog=$('#modal');
    dialog.close();
    if(dialog.querySelector('#issued-reset-code'))dialog.innerHTML='';
  }
}
async function snapshotDraft(){if(!editor||user.role!=='hand')return;rememberCaptureMetadata([...(editor.payload.animal_ids||[]),...(editor.payload.dam_id?[Number(editor.payload.dam_id)]:[])]);clearTimeout(scheduleDraft.timer);const form=$('#capture-form');if(!form)return;const data=Object.fromEntries(new FormData(form));Object.assign(editor.payload,data);['station_id','dam_id','sire_id','case_id','destination_id'].forEach(key=>{if(editor.payload[key])editor.payload[key]=Number(editor.payload[key]);});if(editor.payload.kind==='weight'&&editor.step===2)editor.payload.weights=Object.fromEntries(editor.payload.animal_ids.map(id=>[String(id),data['weight_'+id]||'']));collectProducts();await persistDraft();}
async function performLogout(){
  await storePut('logout-pending',true);
  if(navigator.onLine){
    try{
      await completePendingLogout();
    }catch(error){
      if(error.status)throw error;
    }
  }clearTimeout(notice.timer);
  $('#notice').style.display='none';
  await storeDelete('current-user');
  user=null;
  clearFarmAccountState();
  csrf='';
  ref=null;
  events=[];
  overview=null;
  editor=null;
  localRecords=[];
  authState.username='';
  authState.message=null;
  history.replaceState(null,'',location.pathname+location.search);
  loginScreen();
}
document.addEventListener('click',guard(async e=>{const button=e.target.closest('[data-action]');if(!button||button.disabled)return;e.preventDefault();button.disabled=true;try{await handleAction(button);}finally{if(button.isConnected)button.disabled=false;}}));
document.addEventListener('click',e=>{if(e.target.closest('.notification-control'))return;const menu=$('#notification-menu'),button=$('[data-action=toggle-notifications]');if(menu&&!menu.hidden){menu.hidden=true;button?.setAttribute('aria-expanded','false');}});
document.addEventListener('input',()=>{if(editor&&user?.role==='hand')scheduleDraft();});
window.addEventListener('hashchange',guard(async()=>{if(editor&&user?.role==='hand')await snapshotDraft();await route();}));
window.addEventListener('online',guard(async()=>{updateConnection();updateAuthConnection();await syncQueue();}));
window.addEventListener('offline',()=>{updateConnection();updateAuthConnection();});
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;const menu=$('#notification-menu');if(menu&&!menu.hidden){menu.hidden=true;$('[data-action=toggle-notifications]')?.setAttribute('aria-expanded','false');$('[data-action=toggle-notifications]')?.focus();return;}if($('#main-navigation')?.classList.contains('is-open')){toggleMobileMenu(false);$('[data-action=toggle-menu]').focus();}});
window.addEventListener('beforeunload',e=>{if(editor&&user?.role==='manager'){e.preventDefault();e.returnValue='';}});
async function completePendingLogout(){
  if(!await storeGet('logout-pending'))return;
  const session=await api('/api/session');
  if(session.user){
    csrf=session.csrf;
    await api('/api/logout',{
      method:'POST',body:'{}'
    });
  }await storeDelete('logout-pending');
}
async function boot(){
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>notice('Offline page caching is unavailable. Keep this page open while capturing.',true));
  try{
    await completePendingLogout();
    const result=await api('/api/session');
    if(!result.user){
      loginScreen(result.needs_setup);
      return;
    }user=result.user;
    csrf=result.csrf;
    await storePut('current-user',user);
    await start();
  }catch(error){
    if(!error.status&&!await storeGet('logout-pending')){
      const cached=await storeGet('current-user');
      if(cached?.role==='hand'){
        user=cached;
        await start();
        return;
      }
    }loginScreen();
    notice(error.message||'Connect to sign in.',true);
  }
}
guard(boot)();

function productDosageApplicable(p) {
  return ['procedure', 'treatment'].includes(p.kind);
}
function purchaseRowsForm(p) {
  return `<div class="wide"><h3>Added cattle</h3>${p.purchase_rows.map((r,i)=>`<fieldset data-purchase-row="${i}"><legend>Animal ${i+1}</legend><div class="form-grid">${field('Permanent tag',`row_${i}_identifier`,r.identifier,'text','required')}${select('Sex',`row_${i}_sex`,['Female','Male'],r.sex,'required')}${select('Category',`row_${i}_category`,ref.categories,r.category,'required')}${(p.acquisition_source==='Gift'?'':field('Price',`row_${i}_price`,r.price,'number','required min="0.01" step="0.01"'))}${field('Birth date (if known)',`row_${i}_dob`,r.dob,'date')}${field('Breed',`row_${i}_breed`,r.breed||'Brahman')}${field('Brand',`row_${i}_brand`,r.brand)}${field('Birth place',`row_${i}_birth_place`,r.birth_place)}${searchableSelect('Dam (if known)',`row_${i}_dam_id`,ref.animals.filter(a=>a.sex==='Female').map(a=>a),r.dam_id)}${searchableSelect('Sire (if known)',`row_${i}_sire_id`,ref.animals.filter(a=>a.sex==='Male'),r.sire_id)}</div>${editor.mode==='correct'?'':`<button type="button" data-action="remove-purchase-row" data-index="${i}">Remove animal</button>`}</fieldset>`).join('')}${editor.mode==='correct'?'':'<button type="button" data-action="add-purchase-row">Add animal</button>'}</div>`;
}
function breedingDetails(p) {
  let html=select('Breeding action','breeding_action',['Bull exposure','Pregnancy check'],p.breeding_action||'Bull exposure','required');
  if((p.breeding_action||'Bull exposure')==='Bull exposure') return html+searchableSelect('Bull','sire_id',ref.animals.filter(a=>a.sex==='Male'&&a.category==='Bull'&&a.lifecycle==='Active'&&a.station_id===Number(p.station_id)),p.sire_id,'required');
  return html+`<div class="wide">${p.animal_ids.map(id=>{const r=p.pregnancy_results?.[id]||(p.animal_ids.length===1?p:{});return `<fieldset><legend>${esc(animalName(id))}</legend>${select('Pregnancy result',`preg_${id}_result`,['Pregnant','Not pregnant','Uncertain'],r.pregnancy_result,'required')}${field('Estimated calving date (optional)',`preg_${id}_date`,r.expected_calving,'date')}${field('Basis for estimate',`preg_${id}_basis`,r.estimate_basis)}</fieldset>`;}).join('')}</div>`;
}
function collectBatchDetails(p,data) {
  if(p.purchase_rows) p.purchase_rows=p.purchase_rows.map((r,i)=>({...r,...Object.fromEntries(['identifier','sex','category','price','dob','breed','brand','birth_place','dam_id','sire_id'].map(k=>[k,data[`row_${i}_${k}`]??r[k]]))}));
  if(p.purchase_rows){for(const row of p.purchase_rows){if(row.category&&row.sex&&row.category!=='Calf'&&!((row.sex==='Female'&&['Cow','Heifer'].includes(row.category))||(row.sex==='Male'&&['Bull','Steer'].includes(row.category))))throw new Error('Sex and category do not agree for '+(row.identifier||'a purchased animal'));}}
  if(p.purchase_rows)p.amount=p.acquisition_source==='Gift'?'0':(p.purchase_rows.reduce((total,row)=>total+Math.round(Number(row.price||0)*100),0)/100).toFixed(2);
  if(p.kind==='breeding'&&p.breeding_action==='Pregnancy check')p.pregnancy_results=Object.fromEntries(p.animal_ids.map(id=>[String(id),{pregnancy_result:data[`preg_${id}_result`],expected_calving:data[`preg_${id}_date`]||null,estimate_basis:data[`preg_${id}_basis`]||''}]));
  else if(p.kind==='breeding'){delete p.pregnancy_results;delete p.pregnancy_result;delete p.expected_calving;delete p.estimate_basis;}
}

function formatCorrectionDetails(details) {
  const before=details.original||{}, after=details.corrected||{};
  if(details.original||details.corrected)return Object.keys({...before,...after}).filter(k=>JSON.stringify(before[k])!==JSON.stringify(after[k])).map(k=>`${k.replaceAll('_',' ')}: ${readableValue(before[k])} ? ${readableValue(after[k])}`).join('\n')||'No field differences';
  return Object.entries(details).map(([k,v])=>`${k.replaceAll('_',' ')}: ${readableValue(v)}`).join('\n');
}
function readableValue(value) {
  if(value==null)return 'Not recorded';
  if(Array.isArray(value))return value.map(readableValue).join(', ');
  if(typeof value==='object')return Object.entries(value).map(([k,v])=>`${k.replaceAll('_',' ')}: ${readableValue(v)}`).join('; ');
  return String(value);
}
function renderPerformance() {
  if(!overview){$('#main').innerHTML=head('Performance','Connect to view official records.');return;}
  $('#main').innerHTML=head('Performance','Recorded growth and calving; no projections or invented targets.')+chartPanel('performance')+panel('Growth',`<p>${overview.animals_weighed} cattle have official weight records across all dates. Change and daily gain require two dated weights.</p>${recordTable(['Animal','Latest date','Weight (kg)','Change (kg)','Daily gain (kg)'],(overview.growth||[]).map(row=>[animalLink(row.animal_id),esc(row.date),esc(row.weight),esc(row.change??'Unavailable'),esc(row.daily_gain??'Unavailable')]))}<button data-action="navigate" data-page="reports" data-report="Growth">View growth report</button>`)+panel('Calving this month',`<p><strong>${overview.births}</strong> live calves registered this calendar month (Africa/Harare). ${overview.stillbirths||0} stillbirths recorded.</p><p>Calving rates are unavailable without a defined eligible herd and complete breeding records.</p><button data-action="navigate" data-page="reports" data-report="Births/deaths">View births and deaths</button>`);
  bindChartPanel('performance');
}

function groupProcedureReminders(reminders) {
  const groups=new Map();
  for(const reminder of reminders){const key=[reminder.station_id,reminder.procedure,reminder.date].join('|');const current=groups.get(key);if(current)current.count++;else groups.set(key,{...reminder,count:1});}
  return [...groups.values()];
}

async function advanceCapture(event) {
  event.preventDefault();
  if(captureBusy||!editor)return;
  captureBusy=true;
  const session=editor;
  $$('#capture-form button').forEach(button=>button.disabled=true);
  try {
    await collectEditor();
    if(editor!==session)return;
    if(editor.step<3){
      editor.step++;
      editor.furthestStep=Math.max(editor.furthestStep||1,editor.step);
      if(user.role==='hand')await persistDraft();
      renderCapture();
    } else {
      await submitEditor();
    }
  } catch(error) {
    const target=$('#capture-error');
    if(target)target.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;
    else notice(error.message,true);
  } finally {
    captureBusy=false;
    $$('#capture-form button').forEach(button=>button.disabled=false);
  }
}

function captureAnimalIds(p) {
  return [...new Set([...(p.animal_ids||[]),...(p.absent_ids||[]),...(p.kind==='birth'&&p.dam_id?[Number(p.dam_id)]:[])])];
}
function rememberCaptureMetadata(ids) {
  if(!editor||!ref)return;
  const p=editor.payload;
  p.versions=p.versions||{};
  p.capture_proofs=p.capture_proofs||{};
  p.capture_snapshots=p.capture_snapshots||{};
  for(const id of ids){
    if(Object.hasOwn(p.versions,String(id))||editor.originalSelection?.has(Number(id)))continue;
    const animal=ref.animals.find(a=>a.id===Number(id));
    if(!animal)continue;
    p.versions[id]=animal.version;
    if(animal.capture_proof)p.capture_proofs[id]=animal.capture_proof;
    p.capture_snapshots[id]={identifier:animal.identifier,station_id:animal.station_id,lifecycle:animal.lifecycle,health:animal.health,sex:animal.sex,category:animal.category};
  }
}
function captureVersionNotice(p) {
  const changed=captureAnimalIds(p).filter(id=>{
    const current=ref.animals.find(a=>a.id===id);
    return !current||String(p.versions?.[id])!==String(current.version);
  });
  const note=changed.length?`<p class="alert">${changed.length} selected or absent cattle have changed or are no longer in the downloaded list. Original capture versions are retained for Manager review.</p>`:'';
  return note+(user.role==='hand'&&editor.mode==='returned'?'<button type="button" data-action="reconcile-capture">Review updated cattle for this returned record</button>':'');
}
async function reconcileReturnedCapture() {
  if(user.role!=='hand'||editor?.mode!=='returned')throw new Error('Only returned field records can be reconciled here.');
  if(!navigator.onLine)throw new Error('Connect to review updated cattle.');
  await snapshotDraft();
  const session=editor, account=user;
  const latest=await api('/api/reference');
  if(editor!==session||user!==account)return;
  const ids=captureAnimalIds(session.payload);
  const unavailable=ids.some(id=>!latest.animals.some(a=>a.id===id));
  const rows=ids.map(id=>{
    const current=latest.animals.find(a=>a.id===id), before=session.payload.capture_snapshots?.[id];
    return [esc(before?.identifier||animalName(id)),esc(session.payload.versions?.[id]??'Not recorded'),esc(current?.version??'Unavailable'),esc(before?stationName(before.station_id)+' / '+before.lifecycle+' / '+before.health:'Not recorded'),esc(current?current.station+' / '+current.lifecycle+' / '+current.health:'Outside downloaded station list; Manager re-entry required')];
  });
  modal('Review updated cattle',table(['Animal','Captured version','Current version','Captured condition','Current condition'],rows)+`<p>${unavailable?'Some cattle are no longer available to your account. Original data will be retained; ask the Manager to reconcile and enter the record.':'Confirm only after reviewing these changes. This replaces capture versions and proofs; the Manager must still approve the whole session.'}</p>`,async()=>{
    if(unavailable)throw new Error('Manager reconciliation and re-entry are required. Your draft is preserved.');
    if(editor!==session||user!==account)throw new Error('Reopen the returned record before reconciling.');
    const p=session.payload;
    for(const id of ids){const animal=latest.animals.find(a=>a.id===id);p.versions[id]=animal.version;p.capture_proofs[id]=animal.capture_proof;p.capture_snapshots[id]={identifier:animal.identifier,station_id:animal.station_id,lifecycle:animal.lifecycle,health:animal.health,sex:animal.sex,category:animal.category};}
    ref=latest;
    await storePut(`reference:${account.id}`,latest);
    await persistDraft();
    renderCapture();
    notice('Capture versions updated after your review. Submit for Manager approval.');
  },unavailable?'Keep original record':'Use reviewed cattle versions');
}

function birthDamChoices(p) {
  const choices=ref.animals.filter(a=>a.sex==='Female'&&a.lifecycle==='Active'&&a.station_id===Number(p.station_id));
  if(p.dam_id&&!choices.some(a=>a.id===Number(p.dam_id))){
    const captured=p.capture_snapshots?.[p.dam_id];
    choices.push({id:Number(p.dam_id),identifier:(captured?.identifier||'Animal '+p.dam_id)+' (captured dam; Manager review required)',sex:captured?.sex||'Female',category:captured?.category||'Category not recorded'});
  }
  return choices;
}
