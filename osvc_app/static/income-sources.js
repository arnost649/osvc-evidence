document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('form').forEach(form=>{
  const enabled=form.querySelector('[name=import_documents]'),mode=form.querySelector('[name=invoice_mode]');
  function update(){
   if(enabled){const group=form.querySelector('.connector-document-fields');if(group)group.hidden=!enabled.checked;}
   if(mode)form.querySelectorAll('[data-invoice-mode]').forEach(e=>e.hidden=e.dataset.invoiceMode!==mode.value);
  }
  [enabled,mode].forEach(e=>e?.addEventListener('change',update));update();
 });
 const forms=[...document.querySelectorAll('[data-source-action]')];
 const state=(button,value)=>{
  if(!button._saveOriginal){
   const label=button.getAttribute('aria-label')||button.textContent.trim()||'Provést akci';
   if(!button.title)button.title=label;
   button.setAttribute('aria-label',label);
  }
  button.dataset.saveAction='';
  window.osvcActionState(button,value);
  if(value==='saving')button.title='Probíhá synchronizace / ověření…';
  if(value==='success')button.title='Dokončeno';
  if(value!=='idle')button.setAttribute('aria-label',button.title);
 };
 const notify=(text,type='error')=>{
  const p=document.createElement('p');p.className='flash '+type;p.setAttribute('role','alert');p.textContent=text;document.querySelector('.global-notifications').append(p);
 };
 let completed,failure;
 try{completed=JSON.parse(sessionStorage.getItem('source-action-result'));sessionStorage.removeItem('source-action-result');}catch{}
 // Ověření, které nedoběhlo v prohlížeči (výpadek spojení, vypršení času), ohlásíme až po obnovení stránky.
 try{failure=JSON.parse(sessionStorage.getItem('source-test-failure'));sessionStorage.removeItem('source-test-failure');}catch{}
 if(failure&&Date.now()-failure.at<120000)notify(failure.text);
 const verify=async(form,button)=>{
  // po ověření se stránka obnoví VŽDY (i při chybě, neplatné odpovědi nebo vypršení času), aby byl vidět čerstvý výsledek.
  const info=document.createElement('p');info.className='flash info';info.setAttribute('role','status');
  info.textContent='Ověřuji připojení… (může trvat až minutu)';document.querySelector('.global-notifications').append(info);
  const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),150000);
  try{
   const response=await fetch(form.action,{method:'POST',body:new FormData(form),headers:{Accept:'application/json'},cache:'no-store',signal:abort.signal});
   if(!response.headers.get('content-type')?.includes('json'))throw Error(response.status===400?'Platnost formuláře vypršela (obnovte stránku a zkuste to znovu).':'Server vrátil neočekávanou odpověď ('+response.status+').');
  }catch(error){
   const text=error.name==='AbortError'?'Ověření trvalo déle než 2,5 minuty a bylo přerušeno. Výsledek se může objevit po obnovení stránky.':'Ověření se nepodařilo odeslat: '+(error.message||'chyba spojení');
   try{sessionStorage.setItem('source-test-failure',JSON.stringify({text,at:Date.now()}));}catch{}
  }
  clearTimeout(timer);location.reload();
 };
 forms.forEach(form=>{
  const button=form.querySelector('[data-source-button]');
  if(completed&&completed.action===form.action&&Date.now()-completed.at<120000){
   state(button,'success');setTimeout(()=>state(button,'idle'),1800);
  }
  form.addEventListener('submit',async event=>{
   event.preventDefault();
   if(form.dataset.busy==='yes')return;
   form.dataset.busy='yes';state(button,'saving');
   if(form.dataset.sourceAction==='test'){verify(form,button);return;}
   try{
    const response=await fetch(form.action,{method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});
    const data=await response.json();
    if(!response.ok||!data.ok)throw Error(data.message||'Akci se nepodařilo dokončit.');
    if(['sync','test','activation'].includes(form.dataset.sourceAction)){
     try{sessionStorage.setItem('source-action-result',JSON.stringify({action:form.action,at:Date.now()}));}catch{}
     // Updated rows and document links are rendered by the existing server table.
     location.reload();return;
    }
    state(button,'success');
   }catch(error){state(button,'error');notify(error.message||'Zdroj není dostupný.');}
   delete form.dataset.busy;setTimeout(()=>state(button,'idle'),1800);
  });
 });
 const params=new URLSearchParams(location.search);
 if(params.get('test')==='1'){
  const id=params.get('configure'),form=document.querySelector('#source-'+CSS.escape(id||'')+' [data-source-action=test]');
  params.delete('test');history.replaceState(null,'',location.pathname+'?'+params);
  form?.requestSubmit();
 }
});
