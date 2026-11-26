/* Shared XP controls for the approved farm workflow release. */
'use strict';
let activeStationId=null;
let recordOrder='newest';
let availableSupplyReceipts=[];
function assignedStationIds(){return user?.role==='hand'?(user.station_ids?.length?user.station_ids:[user.station_id].filter(Boolean)):(ref?.stations||[]).map(s=>s.id);}
function stationChooser(){
  if(user.role!=='hand')return '';
  if(!assignedStationIds().includes(activeStationId))activeStationId=assignedStationIds()[0];
  return `<div class="toolbar station-toolbar"><label><span>Working station</span><select id="working-station">${options(ref.stations.filter(s=>assignedStationIds().includes(s.id)).map(s=>[s.id,s.name]),activeStationId)}</select></label></div>`;
}
function captureOrigin(){
  const origin={page:page==='capture'?(user.role==='hand'?'home':'herd'):page|| (user.role==='hand'?'home':'overview'),station:activeStationId};
  if(currentProfile&&document.querySelector('[data-action=profile-tab]'))origin.profile_id=currentProfile.animal.id;
  if(document.querySelector('#herd-search'))origin.herd={query:document.querySelector('#herd-search').value,station:document.querySelector('#herd-station').value,health:document.querySelector('#herd-health').value,lifecycle:document.querySelector('#herd-status').value};
  if($('#money-currency'))origin.money={currency:$('#money-currency').value,type:$('#money-type').value};
  return origin;
}
async function returnFromCapture(origin){
  const target=origin?.page|| (user.role==='hand'?'home':'overview');
  if(origin?.station)activeStationId=origin.station;
  history.replaceState(null,'',location.pathname+location.search+'#'+target);
  await route();
  if(origin?.money&&target==='money'){$('#money-currency').value=origin.money.currency;$('#money-type').value=origin.money.type;$('#money-currency').dispatchEvent(new Event('change'));}
  if(origin?.profile_id)await openProfile(origin.profile_id);
  else if(origin?.herd&&target==='herd'){
    renderHerd(origin.herd.station,origin.herd.health,origin.herd.lifecycle);
    $('#herd-search').value=origin.herd.query;filterHerd();
  }
}
function showRecordLink(id){const el=$('#notice');if(el)el.insertAdjacentHTML('beforeend',` <button class="link" data-action="saved-record" data-id="${esc(id)}">View saved record</button>`);}
function sortedEvents(list){return [...list].sort((a,b)=>{const order=(a.date+' '+a.created_at+' '+a.id).localeCompare(b.date+' '+b.created_at+' '+b.id);return recordOrder==='oldest'?order:-order;});}
function recordSortControl(){return `<div class="toolbar"><label><span>Record order</span><select id="record-order">${options([['newest','Newest first'],['oldest','Oldest first']],recordOrder)}</select></label></div>`;}
function attentionBadge(a){return badge(a.health)+(a.attention?.length?`<span class="attention" role="note">! ${esc(a.attention.join('; '))}</span>`:'')+(a.category_review_due?'<span class="review-note">Category review due</span>':'');}
function animalTiles(ids,payload={}){return `<div class="animal-tiles" role="group" aria-label="Participating animal IDs">${ids.map(id=>{const animal=ref.animals.find(a=>a.id===Number(id)),label=animal?.identifier||payload.capture_snapshots?.[id]?.identifier||'Animal ID unavailable';return animal?`<button type="button" class="animal-id" data-action="profile" data-id="${id}">${esc(label)}</button>`:`<span class="animal-id">${esc(label)}<small>Profile outside downloaded station list</small></span>`;}).join('')}</div>`;}

function renderCattleSelection(){
  const p=editor.payload,query=$('#cattle-search')?.value.toLowerCase()||'';
  const list=selectableCattle(p).filter(a=>a.identifier.toLowerCase().includes(query));
  $('#cattle-list').classList.add('animal-tiles','capture-tiles');
  $('#cattle-list').innerHTML=list.length?list.map(a=>`<div class="animal-tile ${p.animal_ids.includes(a.id)?'selected':''} ${a.attention?.length?'attention-border':''}"><label><input type="checkbox" value="${a.id}" ${p.animal_ids.includes(a.id)?'checked':''} data-cattle><strong>${esc(a.identifier)}</strong><small>${esc(a.sex)} / ${esc(a.category)}</small>${attentionBadge(a)}</label><button type="button" class="secondary" data-action="view-capture-animal" data-id="${a.id}">View</button></div>`).join(''):'<p class="empty">No available cattle match this station and search.</p>';
  $$('[data-cattle]').forEach(input=>input.onchange=()=>{
    const id=Number(input.value);p.animal_ids=p.animal_ids.filter(i=>i!==id);
    if(input.checked){if(['health','treatment','resolve_health','death','lost','found'].includes(p.kind)){p.animal_ids=[];$$('[data-cattle]').forEach(other=>{if(other!==input)other.checked=false;});}p.animal_ids.push(id);rememberCaptureMetadata([id]);}
    $$('.animal-tile').forEach(tile=>tile.classList.toggle('selected',!!tile.querySelector('[data-cattle]')?.checked));updateSelectionCount();scheduleDraft();
  });updateSelectionCount();
}
function farmCaptureFields(p){
  if(p.kind==='purchase')return select('Acquisition source','acquisition_source',['Purchase','Gift'],p.acquisition_source||'Purchase','required')+(p.acquisition_source==='Gift'?field('Donor / source','reference',p.reference,'text','required'):'');
  return '';
}
function bindFarmCapture(p){
  $('[name=acquisition_source]')?.addEventListener('change',event=>{
    const data=Object.fromEntries(new FormData($('#capture-form')));Object.assign(p,data);collectBatchDetails(p,data);renderCapture();
  });
}
function renderProducts(){
  const p=editor.payload;
  $('#product-rows').innerHTML=p.products.map((item,i)=>{
    const product=ref.products.find(x=>x.id===Number(item.product_id));
    const choices=ref.products.filter(x=>(x.active!==false||x.id===Number(item.product_id))&&(!['procedure','treatment'].includes(p.kind)||x.category==='Medicine'));
    const usage=['procedure','treatment','stock_use'].includes(p.kind);
    const units=product?.usage_units||[product?.unit||'unit'];
    return `<fieldset class="product-row" data-index="${i}"><legend>Product ${i+1}</legend><div class="form-grid"><div class="field"><label><span>Product</span><input type="search" class="select-search" data-target="product-${i}" aria-label="Search product ${i+1}" placeholder="Search products"></label><select id="product-${i}" data-product required aria-label="Product ${i+1}">${options(choices.map(x=>[x.id,`${x.name} (${x.unit})${x.active===false?' - archived':x.low_stock?' - Low stock':''}`]),item.product_id)}</select></div><label class="field"><span>Actual medicine / stock quantity ${usage?'consumed':'received'}</span><input type="number" data-quantity value="${esc(item.entered_quantity??item.quantity)}" min="0.001" step="0.001" required aria-label="Quantity ${i+1}"></label><label class="field"><span>Entered unit</span><select data-unit required>${options(units,item.entered_unit||product?.unit)}</select><small>Stock unit: ${esc(product?.unit||'Choose product')}. Exclude added mixing water.</small>${product?.low_stock?'<strong class="attention">! Low stock ? Manager receipt may be needed</strong>':''}</label>${productDosageApplicable(p)?`<label class="field"><span>Dosage / concentration</span><input data-dosage value="${esc(item.dosage)}" aria-label="Dosage ${i+1}"></label>`:''}${usage?`<label class="field"><span>Medicine / supply source</span><select data-source>${options(['Farm stock','Outside source'],item.source||'Farm stock')}</select></label>${item.source==='Outside source'?`<label class="field"><span>Outside source (for example neighbour)</span><input data-source-note value="${esc(item.source_note)}" maxlength="180" required><small>The Manager must record and link the receipt before approval.</small></label>`:''}`:''}</div><button type="button" data-action="remove-product-row" data-index="${i}">Remove product</button></fieldset>`;
  }).join('');
  setupSearches();
  $$('[data-product],[data-source]').forEach(input=>input.addEventListener('change',()=>{collectProducts();const item=p.products[Number(input.closest('[data-index]').dataset.index)];if(input.matches('[data-product]')){delete item.entered_unit;item.quantity='';item.entered_quantity='';}renderProducts();}));
}
function collectProducts(){
  if(!$('#product-rows'))return;
  editor.payload.products=$$('.product-row').map(row=>{const previous=editor.payload.products[Number(row.dataset.index)]||{};return {...previous,product_id:Number($('[data-product]',row).value),quantity:$('[data-quantity]',row).value,entered_quantity:$('[data-quantity]',row).value,entered_unit:$('[data-unit]',row).value,dosage:$('[data-dosage]',row)?.value||'',source:$('[data-source]',row)?.value||'Farm stock',source_note:$('[data-source-note]',row)?.value||''};});
}
function stationAssignmentControl(ids=[]){return `<fieldset><legend>Assigned stations</legend><p>Choose at least one station for a General Hand.</p>${ref.stations.map(s=>`<label class="station-check"><input type="checkbox" name="station_ids" value="${s.id}" ${ids.includes(s.id)?'checked':''}>${esc(s.name)}</label>`).join('')}</fieldset>`;}
function selectedStationIds(form){return [...form.querySelectorAll('[name=station_ids]:checked')].map(input=>Number(input.value));}
function outsideReceiptControls(event){
  const receipts=availableSupplyReceipts.filter(receipt=>['Purchase','External supply'].includes(receipt.payload.receipt_type)&&receipt.date<=event.date);
  const rows=event.payload.products.map((item,i)=>item.source==='Outside source'?`<label class="field"><span>Official receipt for ${esc(ref.products.find(p=>p.id===item.product_id)?.name||'product')} ? ${esc(item.source_note)}</span><select data-receipt-index="${i}">${options(receipts.filter(e=>e.payload.products.some(p=>p.product_id===item.product_id)).map(e=>[e.id,e.date+' ? '+(e.payload.reference||e.payload.receipt_type)+' ? '+e.id.slice(0,8)]),item.receipt_id||'')}</select><small>Record a paid or free receipt in Supplies first. Only downloaded official receipts are listed. Allocation and stock are checked on approval.</small></label>`:'').join('');
  return rows?panel('Outside supplies: link receipts before approval',rows):'';
}
function receiptLinks(){return Object.fromEntries($$('[data-receipt-index]').filter(input=>input.value.trim()).map(input=>[input.dataset.receiptIndex,input.value.trim()]));}
function profileActions(a){return `<div class="actions no-print"><button data-action="profile-print" data-id="${a.id}">Print animal profile</button><a class="button" href="/api/animals/${a.id}/profile.pdf">Download profile PDF</a></div>`;}
function profileSummaryHTML(profile){const s=profile.summary||{};return `<dl class="summary-list"><dt>Dipping records</dt><dd>${s.dipping??0}</dd><dt>Vaccinations</dt><dd>${s.vaccinations??0}</dd><dt>Pregnancy checks</dt><dd>${s.pregnancy_checks??0}</dd><dt>Registered offspring</dt><dd>${s.registered_offspring??0}</dd></dl><p>${esc(s.note||'Official records only.')}</p>`;}
function chartPanel(kind,month=false){
  const date=day(),start=month?date.slice(0,7)+'-01':'';
  return panel(kind==='performance'?'Recorded farm trend':'Recorded expenses',`<form id="chart-${kind}" class="chart-controls"><div class="form-grid">${kind==='performance'?select('Metric','metric',[['daily_gain','Measured daily gain'],['births','Recorded live births'],['deaths','Recorded deaths'],['pregnancy','Pregnancy-check results']],'','required'):select('Currency','currency',['USD','ZiG'],'USD','required')}${select('Grouping','group',[['auto','Auto'],['days','Days'],['months','Months'],['years','Years']],'auto','required')}${field('From date','from',start,'date')}${field('To date','to',date,'date')}</div><button type="submit">Show trend</button></form><div id="chart-${kind}-result" class="chart-result"><p>${kind==='performance'?'Choose a metric to display the recorded trend.':'Loading recorded expenses...'}</p></div>`);
}
function svgChart(data,bar=false){
  if(!data.points.length)return '<p class="empty">'+(bar?'Insufficient recorded data for this metric.':'No recorded expenses match this period and currency.')+'</p>';
  const target=$('#chart-'+(data.metric?'performance':'expenses')+'-result');
  const width=Math.min(720,Math.max(280,target?.clientWidth||720)),height=280,left=80,top=28,plotW=width-left-20,plotH=197,points=data.points,right=width-20;
  const tick=value=>Math.abs(value)>=100000?new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(value):value.toFixed(2);
  const values=points.map(p=>Number(p.value));const min=Math.min(0,...values),max=Math.max(1,...values),range=max-min;
  const y=v=>top+(max-v)/range*plotH;
  const x=i=>left+(points.length===1?plotW/2:i*plotW/(points.length-1));
  const grid=[0,.25,.5,.75,1].map(f=>{const value=min+range*f;return `<line x1="${left}" y1="${y(value)}" x2="${right}" y2="${y(value)}" stroke="#bbb"/><text x="72" y="${y(value)+4}" text-anchor="end">${tick(value)}</text>`;}).join('');
  let marks=bar?points.map((p,i)=>`<rect x="${x(i)-Math.min(22,plotW/points.length/3)}" y="${Math.min(y(0),y(Number(p.value)))}" width="${Math.min(44,plotW/points.length*.65)}" height="${Math.max(1,Math.abs(y(Number(p.value))-y(0)))}" fill="#2F5D3A"><title>${esc(p.date)}: ${esc(p.value)} ${esc(data.unit)}; ${p.count} contributing cattle/records</title></rect>`).join(''):`<polyline fill="none" stroke="#2F5D3A" stroke-width="3" points="${points.map((p,i)=>x(i)+','+y(Number(p.value))).join(' ')}"/>${points.map((p,i)=>`<circle cx="${x(i)}" cy="${y(Number(p.value))}" r="3" fill="#2F5D3A"><title>${esc(p.date)}: ${esc(p.value)} ${esc(data.unit)}</title></circle>`).join('')}`;
  if(bar&&data.metric==='pregnancy'){
    const fills={'Pregnant':'#2F5D3A','Not pregnant':'#808080','Uncertain':'#D2D2D2'};
    marks=points.map((point,index)=>{
      let total=0;const barWidth=Math.min(44,plotW/points.length*.65);
      return Object.entries(fills).map(([state,fill])=>{const value=Number(point.results?.[state]||0),bottom=total;total+=value;return value?`<rect x="${x(index)-barWidth/2}" y="${y(total)}" width="${barWidth}" height="${Math.abs(y(bottom)-y(total))}" fill="${fill}" stroke="#202020" stroke-width="0.5"><title>${esc(point.date)}: ${state}, ${value} cattle</title></rect>`:'';}).join('');
    }).join('');
  }
  const labels=points.map((p,i)=>i===0||i===points.length-1||(width>=450&&i%Math.max(1,Math.ceil(points.length/6))===0&&points.length-1-i>=Math.max(1,Math.ceil(points.length/6)))?`<text x="${x(i)}" y="246" text-anchor="${points.length===1?'middle':i===0?'start':i===points.length-1?'end':'middle'}">${esc(p.date)}</text>`:'').join('');
  return `<svg class="farm-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Recorded trend, ${esc(data.unit)} by ${esc(data.group)}"><rect width="${width}" height="280" fill="white"/>${grid}<line x1="${left}" y1="${y(0)}" x2="${right}" y2="${y(0)}" stroke="#808080"/>${marks}${labels}<text x="${left+plotW/2}" y="272" text-anchor="middle">Date (${esc(data.group)})</text><text x="10" y="16">${esc(data.unit)}</text></svg>`+(data.metric==='pregnancy'?'<p class="chart-legend">Pregnant: forest green ? Not pregnant: grey ? Uncertain: light grey. See labelled counts below; these are recorded checks, not a fertility rate.</p>':'');
}
function bindChartPanel(kind){
  const form=$('#chart-'+kind),target=$('#chart-'+kind+'-result');if(!form||!target)return;
  let lastData=null,lastWidth=0;
  const render=data=>{
    lastData=data;lastWidth=target.clientWidth;
    target.innerHTML=svgChart(data,kind==='performance')+`<p class="report-note">Period: ${esc(data.filters.from)} to ${esc(data.filters.to)}. ${esc(data.note)}</p>`+table(['Period','Value ('+esc(data.unit)+')','Contributing records / cattle','Results'],data.points.map(p=>[esc(p.date),esc(p.value),esc(p.count),p.results?esc(readableValue(p.results)):'']));
  };
  const draw=guard(async event=>{
    event?.preventDefault();if(!form.checkValidity())return;
    const query=new URLSearchParams(new FormData(form)),data=await api('/api/charts/'+kind+'?'+query);
    if(!target.isConnected||$('#chart-'+kind)!==form)return;
    render(data);
  });
  const observer=new ResizeObserver(()=>{if(!target.isConnected){observer.disconnect();return;}if(lastData&&target.clientWidth!==lastWidth)render(lastData);});
  observer.observe(target);form.onsubmit=draw;if(kind==='expenses')draw();
}

function renderOwnerOverview(o){
  $('#main').innerHTML=head('Farm overview','Official farm records and recorded expenses.')+`<div class="stats"><button class="stat" data-action="navigate" data-page="herd"><span>Active herd</span><strong>${o.active}</strong></button><button class="stat ${o.concerns?'attention-border':''}" data-action="navigate" data-page="herd" data-health="concerns"><span>Health concerns</span><strong>${o.concerns}</strong></button><button class="stat ${o.shortages.length?'attention-border':''}" data-action="navigate" data-page="reports" data-report="Supplies"><span>Low stock</span><strong>${o.shortages.length}</strong></button><div class="stat"><span>Live births this month</span><strong>${o.births}</strong></div></div>`+ownerStockAttention(o)+herdLifecycleChart(o)+panel('Money this month',`<div class="money-grid">${['USD','ZiG'].map(c=>`<div><h3>${c}</h3><p>Income ${amount(o.money[c].Income)} / Expenses ${amount(o.money[c].Expense)}</p><strong class="${Number(o.money[c].Net)<0?'attention':''}">Recorded net ${amount(o.money[c].Net)}</strong></div>`).join('')}</div>`)+chartPanel('expenses',true)+panel('Recent official records',recordTable(['Date','Record','Station','Recorded by','Cattle','Status',''],eventRows(o.recent)));
  bindChartPanel('expenses');
}
async function handleFarmAction(action,button){
  if(action==='saved-record'){if(user.role==='hand'){history.replaceState(null,'','#records');await route();}if(events.some(e=>e.id===button.dataset.id)||navigator.onLine){await openEvent(button.dataset.id);}else document.querySelector('[data-action=edit-draft][data-id="'+button.dataset.id+'"]')?.scrollIntoView({block:'center'});return true;}
  if(action==='view-capture-animal'){
    const id=Number(button.dataset.id),animal=ref.animals.find(a=>a.id===id);let info;
    if(navigator.onLine)info=await api('/api/animals/'+id);else info=await storeGet(`profile:${user.id}:${id}`);
    modal('Animal '+animal.identifier,`<p>${esc(animal.sex)} / ${esc(animal.category)} / ${esc(animal.station)} / ${esc(animal.lifecycle)}</p>${attentionBadge(animal)}${info?profileSummaryHTML(info):'<p>Connect to download full history. Your capture selection is unchanged.</p>'}`,async()=>{},'Close');return true;
  }
  if(action==='archive-product'){
    const product=ref.products.find(p=>p.id===Number(button.dataset.id));
    modal(product.active===false?'Restore product':'Archive product',`<p>${esc(product.name)}: ${esc(product.balance)} ${esc(product.unit)} remains visible in stock and history. ${product.active===false?'Restore it for new selections.':'It will be hidden from new selections; no stock is discarded.'}</p>`,async()=>{await api('/api/products/'+product.id,{method:'POST',body:JSON.stringify({active:product.active===false})});await refresh();await renderSupplies();},product.active===false?'Restore':'Archive');return true;
  }
  if(action==='profile-print'){
    window.open('/api/animals/'+button.dataset.id+'/profile.pdf?inline=1','_blank','noopener');return true;
  }
  return false;
}
window.addEventListener('DOMContentLoaded',()=>document.addEventListener('change',guard(async event=>{
  if(event.target.id==='working-station'){activeStationId=Number(event.target.value);renderFieldHome();}
  if(event.target.id==='record-order'){recordOrder=event.target.value;if(navigator.onLine){const result=await api('/api/events?order='+recordOrder);events=result.events;eventPage=1;eventHasMore=result.has_more;}renderRecords();}
})));

function reportAnimalTiles(identifiers){return '<div class="animal-tiles">'+identifiers.map(identifier=>{const animal=ref.animals.find(a=>a.identifier===identifier);return animal?`<button type="button" class="animal-id" data-action="profile" data-id="${animal.id}">${esc(identifier)}</button>`:`<span class="animal-id">${esc(identifier)}</span>`;}).join('')+'</div>';}

function displayStockQuantity(item,product){
  const raw=String(item.entered_quantity??item.quantity??'');
  if(!/^\d+(\.\d{1,6})?$/.test(raw))return raw;
  const [whole,fraction='']=raw.split('.');
  const factors={L:1000n,mL:1n,kg:1000n,g:1n};
  const entered=item.entered_unit||product?.unit;
  const scaled=(BigInt(whole)*1000000n+BigInt(fraction.padEnd(6,'0')))*(factors[entered]||1n)/(factors[product?.unit]||1n);
  const decimals=String(scaled%1000000n).padStart(6,'0').replace(/0+$/,'');
  return String(scaled/1000000n)+(decimals?'.'+decimals:'');
}

function ownerStockAttention(overview){
  if(!overview.shortages.length)return '';
  return `<details class="compact-attention"><summary class="attention">! Low stock: ${overview.shortages.length} product(s) ? view quantities</summary><ul>${overview.shortages.map(p=>`<li><strong>${esc(p.name)}</strong>: ${esc(p.balance)} ${esc(p.unit)} remaining; minimum ${esc(p.minimum)} ${esc(p.unit)}.</li>`).join('')}</ul></details>`;
}

function clearFarmAccountState(){activeStationId=null;recordOrder='newest';availableSupplyReceipts=[];}
