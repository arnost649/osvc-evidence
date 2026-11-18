/* ARES selection uses the shared combobox, including its keyboard controls. */
(function(){
 const button=document.querySelector('[data-employer-verify]');if(!button)return;
 const box=button.closest('[data-combobox]'),input=box.querySelector('input[role=combobox]'),form=input.form;
 const ico=form.querySelector('[data-employer-ico]'),status=form.querySelector('[data-employer-status]'),token=form.elements.employer_verification;
 let generation=0;
 async function post(action,data){const body=new FormData();body.set('csrf_token',form.elements.csrf_token.value);Object.entries(data).forEach(([k,v])=>body.set(k,v));const response=await fetch('/settings/profile/employer/'+action,{method:'POST',body});const result=await response.json();if(!response.ok)throw Error(result.error||'Ověření se nezdařilo.');return result;}
 input.addEventListener('input',()=>{generation++;ico.textContent='—';token.value='';status.textContent='Neověřeno';button.removeAttribute('data-state');});
 async function run(action,data,apply){const version=generation;button.dataset.busy='yes';button.updateAvailability?.();status.textContent='Ověřuji…';try{const result=await post(action,data);if(version===generation)apply(result);}catch(e){if(version===generation)status.textContent=e.message;}finally{delete button.dataset.busy;button.updateAvailability?.();}}
 button.addEventListener('click',()=>{if(input.value.trim().length<2)return;run('search',{name:input.value},result=>{box.dispatchEvent(new CustomEvent('combobox:options',{detail:result.results}));status.textContent=result.results.length?'Vyberte odpovídající subjekt.':'Subjekt nebyl nalezen.';});});
 box.addEventListener('combobox:choose',event=>run('verify',{ico:event.detail.value},result=>{input.value=result.name;token.value=result.token;ico.textContent=result.ico;status.textContent='ARES · ověřeno';status.title='Firma ověřena v ARES '+result.at.slice(0,10)+'. Pracovní poměr zůstává potvrzen uživatelem.';input.dispatchEvent(new Event('change',{bubbles:true}));}));
})();
