'use strict';
const AUTH_VIEWS = ['signin','register','forgot-password','reset-password'];
const ACCOUNT_ROLE_NAMES = {hand:'General Hand',owner:'Owner',manager:'Farm Manager'};
const authState = {needsSetup:false,username:'',message:null};
let accountRequestPage = 1;
let accountRequests = {registrations:[],password_resets:[]};

function authPasswordField(label,name,confirm=false){
  const autocomplete=name==='password'&&location.hash!=='#register'&&location.hash!=='#reset-password'?'current-password':'new-password';
  const minimum=autocomplete==='new-password'?'minlength="12" maxlength="200"':'';
  return `<div class="field auth-password-field"><label for="auth-${name}">${label}</label><div class="password-control"><input id="auth-${name}" name="${name}" type="password" autocomplete="${autocomplete}" ${minimum} required>${confirm?'':'<button id="password-toggle" type="button" class="secondary" aria-pressed="false" aria-label="Show password">Show</button>'}</div></div>`;
}

function renderAuthScreen(needsSetup=authState.needsSetup){
  authState.needsSetup=needsSetup;
  document.body.classList.remove('tablet');
  const hash=location.hash.slice(1),view=AUTH_VIEWS.includes(hash)?hash:'signin';
  const titles={signin:'Sign in',register:'Register','forgot-password':'Forgot password','reset-password':'Reset password'};
  let body='',submit='Sign in',id='login-form';
  const username=field('Username','username',authState.username,'text','required maxlength="80" autocomplete="username" autocapitalize="none" spellcheck="false"');
  if(view==='signin'){
    body=username+authPasswordField('Password','password')+'<a class="auth-link forgot-link" href="#forgot-password">Forgot password?</a>';
  }else if(view==='register'){
    id='register-form';submit='Submit registration';
    body=field('Name','name','','text','required maxlength="120" autocomplete="name"')+username+
      select('Requested role','role',Object.entries(ACCOUNT_ROLE_NAMES),'hand','required')+
      '<p class="auth-help" id="role-explanation">Record field work at the station your manager assigns.</p>'+
      authPasswordField('Password (12+ characters)','password')+authPasswordField('Confirm password','confirmation',true);
  }else if(view==='forgot-password'){
    id='recovery-request-form';submit='Request a reset code';
    body='<p class="auth-help">Your manager verifies your identity and shares a reset code. Farm Managers contact the server administrator.</p>'+username+
      '<a class="auth-link" href="#reset-password">I already have a reset code</a>';
  }else{
    id='reset-password-form';submit='Update password';
    body=username+field('Reset code','code','','text','required maxlength="32" inputmode="numeric" autocomplete="one-time-code" placeholder="0000 0000 0000"')+
      authPasswordField('New password (12+ characters)','password')+authPasswordField('Confirm new password','confirmation',true);
  }
  const message=authState.message;
  app.innerHTML=`<main id="main" class="login-wrap"><section class="window login-panel" aria-labelledby="auth-heading"><div class="titlebar">Simbanai Brahmans</div><div class="window-body"><div class="login-brand"><img src="/static/company-logo-green.svg" alt="Simbanai Brahmans logo" width="1672" height="941"><p>Cattle management</p></div><nav class="auth-tabs" aria-label="Account access"><a href="#signin" class="auth-tab ${view==='signin'?'selected':''}" ${view==='signin'?'aria-current="page"':''}>Sign in</a><a href="#register" class="auth-tab ${view==='register'?'selected':''}" ${view==='register'?'aria-current="page"':''}>Register</a></nav><h1 id="auth-heading" tabindex="-1">${titles[view]}</h1>${view==='register'?'<p class="auth-help">Your manager must approve your account before you can sign in.</p>':''}${needsSetup?'<p class="alert">Farm accounts are not ready yet. Contact the farm administrator.</p>':''}${message?`<p id="auth-message" class="alert ${message.success?'success':''}" role="status">${esc(message.text)}</p>`:''}<form id="${id}" data-auth-view="${view}">${body}<div id="login-error" class="auth-error" role="alert"></div><button class="primary auth-submit" type="submit">${submit}</button></form><p id="auth-connection" class="auth-help" role="status"></p>${view==='forgot-password'||view==='reset-password'?'<a class="auth-link auth-back" href="#signin">Back to sign in</a>':''}</div></section></main>`;
  const form=$('#'+id);
  $('#password-toggle')?.addEventListener('click',e=>{
    const show=e.currentTarget.getAttribute('aria-pressed')!=='true';
    $$('input[name=password],input[name=confirmation]',form).forEach(input=>input.type=show?'text':'password');
    e.currentTarget.textContent=show?'Hide':'Show';e.currentTarget.setAttribute('aria-pressed',String(show));e.currentTarget.setAttribute('aria-label',show?'Hide password':'Show password');
  });
  if(view==='register')$('[name=role]',form).addEventListener('change',e=>{
    $('#role-explanation').textContent={hand:'Record field work at the station your manager assigns.',owner:'View farm records and finances with read-only access.',manager:'Manage farm operations, official records, and account approvals.'}[e.target.value]||'';
  });
  form.addEventListener('input',()=>{
    form.elements.confirmation?.setCustomValidity('');
  });
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(form.dataset.submitting==='true')return;const button=$('button[type=submit]',form),error=$('#login-error');
    const data=Object.fromEntries(new FormData(form));
    if(form.elements.confirmation&&data.password!==data.confirmation){
      form.elements.confirmation.setCustomValidity('The passwords do not match.');form.elements.confirmation.reportValidity();return;
    }
    form.dataset.submitting='true';button.disabled=true;button.textContent='Please wait…';error.innerHTML='';
    try{
      if(view==='signin'){
        await completePendingLogout();
        const result=await api('/api/login',{method:'POST',body:JSON.stringify(data)});
        user=result.user;csrf=result.csrf;authState.message=null;authState.username='';
        await storePut('current-user',user);await start();
      }else if(view==='register'){
        const result=await api('/api/register',{method:'POST',body:JSON.stringify(data)});
        authState.username=data.username;authState.message={text:result.message};location.hash='signin';
      }else if(view==='forgot-password'){
        const result=await api('/api/password-reset/request',{method:'POST',body:JSON.stringify(data)});
        authState.username=data.username;authState.message={text:result.message};renderAuthScreen();
      }else{
        const result=await api('/api/password-reset/complete',{method:'POST',body:JSON.stringify(data)});
        authState.username=data.username;authState.message={text:result.message,success:true};location.hash='signin';
      }
    }catch(failure){if(error.isConnected)error.innerHTML=`<p class="alert error"><span aria-hidden="true">! </span>${esc(failure instanceof TypeError?'Cannot reach the farm server. Start the application server and try again.':failure.message)}</p>`;}
    finally{delete form.dataset.submitting;if(button.isConnected){button.disabled=false;button.textContent=submit;updateAuthConnection();}}
  });
  updateAuthConnection();
}

function updateAuthConnection(){
  const form=$('form[data-auth-view]');if(!form)return;
  const button=$('button[type=submit]',form);
  button.disabled=form.dataset.submitting==='true'||(authState.needsSetup&&form.dataset.authView==='register');
  $('#auth-connection').textContent=navigator.onLine?'':'Your device reports offline. You can still try connecting to the farm server. Saved field drafts remain on this device.';
}

async function renderAccountRequests(append=false){
  const target=$('#account-requests');if(!target)return;
  try{
    const result=await api('/api/account-requests?page='+(append?accountRequestPage+1:1));if(append){for(const key of ['registrations','password_resets']){const known=new Set(accountRequests[key].map(r=>r.id));accountRequests[key].push(...result[key].filter(r=>!known.has(r.id)));}accountRequests.has_more=result.has_more;accountRequestPage++;}else{accountRequests=result;accountRequestPage=1;}
  }catch(failure){target.innerHTML=`<p class="alert">${esc(failure.message)}</p>`;return;}
  const registrations=accountRequests.registrations.filter(r=>r.state==='Pending');
  const resets=accountRequests.password_resets.filter(r=>['Pending','Issued','Expired','Invalidated'].includes(r.state));
  const registrationRows=registrations.map(r=>[esc(r.name),esc(r.username),esc(ACCOUNT_ROLE_NAMES[r.requested_role]),esc(stamp(r.created_at)),badge(r.state),`<div class="actions"><button data-action="review-registration" data-id="${r.id}" data-choice="approve">Approve</button><button data-action="review-registration" data-id="${r.id}" data-choice="reject">Reject</button></div>`]);
  const resetRows=resets.map(r=>[esc(r.name),esc(r.username),esc(ACCOUNT_ROLE_NAMES[r.role]),badge(r.active?r.state:'Account disabled'),r.expires_at?esc(stamp(r.expires_at)):'—',`<div class="actions">${r.active?`<button data-action="review-recovery" data-id="${r.id}" data-choice="issue">${r.state==='Pending'?'Issue code':'Replace code'}</button>`:''}<button data-action="review-recovery" data-id="${r.id}" data-choice="reject">Reject</button></div>`]);
  const history=[...accountRequests.registrations.filter(r=>r.state!=='Pending').map(r=>[esc(r.username),'Registration',badge(r.state),esc(stamp(r.reviewed_at)),esc(r.reason||'—')]),...accountRequests.password_resets.filter(r=>!['Pending','Issued','Expired','Invalidated'].includes(r.state)).map(r=>[esc(r.username),'Recovery',badge(r.state),esc(stamp(r.reviewed_at)),esc(r.reason||'—')])];
  target.innerHTML=panel(`Registration requests · ${registrations.length} awaiting review`,recordTable(['Name','Username','Requested role','Requested','Status',''],registrationRows))+
    panel(`Password recovery · ${resets.length} open`,recordTable(['Name','Username','Role','Status','Code expires',''],resetRows))+
    `<details><summary>Reviewed account requests (${history.length})</summary>${recordTable(['Username','Request','Status','Reviewed','Reason'],history)}${accountRequests.has_more?'<button data-action="more-account-requests">Load older requests</button>':''}</details>`;
}

function reviewRegistration(button){
  const row=accountRequests.registrations.find(r=>r.id===button.dataset.id);if(!row)return;
  const approve=button.dataset.choice==='approve';
  let body=`<div class="account-review"><p><strong>${esc(row.name)}</strong> (${esc(row.username)}) requested <strong>${esc(ACCOUNT_ROLE_NAMES[row.requested_role])}</strong> access.</p>`;
  if(approve){
    if(row.requested_role==='hand')body+=stationAssignmentControl([]);
    else if(row.requested_role==='owner')body+='<p>This account can view farm records and finances. Operational records remain read-only.</p>';
    else body+='<label class="account-confirm"><input type="checkbox" name="confirm_manager" required><span>I confirm full Farm Manager access, including operations, approvals, finances, and account approval.</span></label>';
  }else body+='<label class="field"><span>Rejection reason</span><textarea name="reason" required maxlength="1000"></textarea></label>';
  modal(approve?'Approve registration':'Reject registration',body+'</div>',async data=>{
    await api(`/api/registration-requests/${row.id}/review`,{method:'POST',body:JSON.stringify({action:approve?'approve':'reject',station_ids:selectedStationIds($('#modal-form')),station_id:data.station_id?Number(data.station_id):null,confirm_manager:data.confirm_manager==='on',reason:data.reason||''})});
    await renderAdministration('users');notice(approve?'Account approved. The applicant can now sign in.':'Registration rejected.');
  },approve?`Approve ${ACCOUNT_ROLE_NAMES[row.requested_role]}`:'Reject registration');
}

function reviewRecovery(button){
  const row=accountRequests.password_resets.find(r=>r.id===button.dataset.id);if(!row)return;
  const issue=button.dataset.choice==='issue';
  const body=`<div class="account-review"><p>${esc(row.name)} (${esc(row.username)}) · ${esc(ACCOUNT_ROLE_NAMES[row.role])}</p>`+(issue?
    `<p>The code expires in 30 minutes. ${row.state==='Pending'?'Share it privately with the account holder.':'Issuing a replacement invalidates the previous code.'}</p><label class="account-confirm"><input type="checkbox" name="verified_identity" required><span>I have verified the account holder’s identity.</span></label>`:
    '<label class="field"><span>Rejection reason</span><textarea name="reason" required maxlength="1000"></textarea></label>')+'</div>';
  modal(issue?'Issue password reset code':'Reject recovery request',body,async data=>{
    const result=await api(`/api/password-reset-requests/${row.id}/review`,{method:'POST',body:JSON.stringify({action:issue?'issue':'reject',revision:row.revision,verified_identity:data.verified_identity==='on',reason:data.reason||''})});
    await renderAdministration('users');
    if(issue)$('#modal').addEventListener('close',()=>showRecoveryCode(row,result),{once:true});
    else notice('Recovery request rejected.');
  },issue?'Issue code':'Reject request');
}

function showRecoveryCode(row,result){
  const dialog=$('#modal');
  dialog.innerHTML=`<div class="titlebar" id="modal-title">Reset code issued</div><div class="dialog-body account-review"><p>Share this code privately with <strong>${esc(row.name)}</strong> (${esc(row.username)}).</p><label class="field"><span>One-time reset code</span><input id="issued-reset-code" class="issued-code" readonly value="${esc(result.code)}"></label><p>Expires: ${esc(stamp(result.expires_at))} · Africa/Harare</p><p class="small muted">This code is shown once. If it is lost, issue a replacement.</p><button id="copy-reset-code" type="button">Copy code</button></div><div class="dialog-footer"><button type="button" data-action="close-modal">Done</button></div>`;
  dialog.showModal();
  $('#copy-reset-code').onclick=async()=>{
    try{await navigator.clipboard.writeText(result.code);$('#copy-reset-code').textContent='Copied';}
    catch{const input=$('#issued-reset-code');input.focus();input.select();notice('Code selected. Copy it manually.');}
  };
  const issuedInput=$('#issued-reset-code');
  const clearCode=()=>{issuedInput.value='';if(dialog.contains(issuedInput))dialog.innerHTML='';};
  dialog.addEventListener('cancel',clearCode);
  dialog.addEventListener('close',()=>{dialog.removeEventListener('cancel',clearCode);clearCode();},{once:true});
}
