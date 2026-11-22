/* Adresář – formulář kontaktu na místě řádku (úprava i nový kontakt).
   IČO + „Doplnit z ARES“ → všechna veřejná pole se vyplní z ARES a jsou jen pro čtení (štítek „Ověřeno v ARES …“, „Aktualizovat z ARES“).
   Změnou IČO se ověření zruší a pole jdou upravit ručně (soukromá osoba bez IČO). Role: aspoň jedna. */
(() => {
 const LOCKED=['name','dic','street','city','postal_code','country_code'];
 const today=()=>{const d=new Date(),p=n=>String(n).padStart(2,'0');return p(d.getDate())+'.'+p(d.getMonth()+1)+'.'+d.getFullYear();};
 document.querySelectorAll('[data-address-form]').forEach(form=>{
  const row=form.closest('[data-kontakt]'),station=form.classList.contains('is-station');
  const state=form.querySelector('[data-ares-state]'),ico=form.querySelector('[data-ares-ico]'),fill=form.querySelector('[data-ares-fill]');
  const status=form.querySelector('[data-ares-status]'),message=form.querySelector('[data-ares-message]');
  const roles=[...form.querySelectorAll('input[name=roles][type=checkbox]')];
  let verifiedIco=form.dataset.verifiedIco||'';
  const lockable=station?['dic']:LOCKED;
  function say(text){message.textContent=text||'';message.hidden=!text;}
  function lock(on){lockable.forEach(n=>{const el=form.elements[n];if(el){el.readOnly=on;el.classList.toggle('is-ares',on);}});}
  function showStatus(label){
   status.replaceChildren();
   if(!label)return;
   const badge=document.createElement('span');badge.className='ares-badge';badge.textContent=label;
   const again=document.createElement('button');again.type='button';again.className='link-button';again.textContent='Aktualizovat z ARES';again.addEventListener('click',load);
   status.append(badge,again);
  }
  function digits(){return (ico.value||'').replace(/\D/g,'');}
  function syncFill(){fill.disabled=digits().length!==8;}
  async function load(){
   const value=digits();
   if(value.length!==8){say('IČO má 8 číslic.');ico.focus();return;}
   fill.disabled=true;say('Načítám z ARES…');
   try{
    const r=await fetch(form.dataset.aresUrl.replace('00000000',value),{headers:{'Accept':'application/json'}});
    const body=await r.json().catch(()=>({ok:false,message:'ARES teď nejde načíst – zkuste to za chvíli.'}));
    if(!r.ok||!body.ok){say(body.message||'ARES teď nejde načíst.');return;}
    const c=body.contact;ico.value=c.ico;
    if(station){form.elements.dic.value=c.dic||'';}
    else{form.elements.name.value=c.name;form.elements.dic.value=c.dic||'';form.elements.street.value=c.street||'';form.elements.city.value=c.city||'';form.elements.postal_code.value=c.postal_code||'';form.elements.country_code.value=c.country_code||'CZ';}
    verifiedIco=c.ico;state.value='fresh';lock(true);say('');
    showStatus('Ověřeno v ARES '+today()+(station?' · provozovatel '+c.name:''));
    form.dispatchEvent(new Event('input',{bubbles:true}));
   }catch(e){say('ARES teď nejde načíst – zkuste to za chvíli.');}
   finally{syncFill();}
  }
  function rolesValidity(){if(!roles.length)return;const ok=roles.some(r=>r.checked);roles[0].setCustomValidity(ok?'':'Vyberte aspoň jednu roli.');}
  function initial(){
   verifiedIco=form.dataset.verifiedIco||'';state.value=verifiedIco?'keep':'';lock(!!verifiedIco);showStatus(form.dataset.verifiedLabel||'');
   say('');rolesValidity();syncFill();
  }
  fill.addEventListener('click',load);
  form.querySelectorAll('[data-ares-refresh]').forEach(b=>b.addEventListener('click',load));
  ico.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();load();}});
  ico.addEventListener('input',()=>{syncFill();if(verifiedIco&&digits()!==verifiedIco){verifiedIco='';state.value='';lock(false);showStatus('');say('IČO se změnilo – načtěte údaje z ARES, nebo je vyplňte ručně.');}});
  roles.forEach(r=>r.addEventListener('change',rolesValidity));
  form.querySelector('.address-edit-cancel').addEventListener('click',()=>{form.reset();initial();if(row){row.classList.remove('is-editing');}const back=row&&row.querySelector('[data-address-edit]');if(back)back.focus();});
  initial();
 });
 document.querySelectorAll('[data-address-edit]').forEach(button=>button.addEventListener('click',()=>{
  const row=button.closest('[data-kontakt]');row.classList.add('is-editing');const first=row.querySelector('[data-address-form] input:not([type=hidden]):not([readonly])');if(first)first.focus();
 }));
 document.querySelectorAll('[data-address-new]').forEach(button=>button.addEventListener('click',()=>{
  const section=button.closest('section'),row=section.querySelector('[data-address-new-row]');if(!row)return;
  row.hidden=false;row.scrollIntoView({block:'nearest'});const first=row.querySelector('input:not([type=hidden]):not([type=checkbox])');if(first)first.focus();
 }));
 // Přepínač Upravit vypnutý → otevřené úpravy se zavřou (nový kontakt zůstane).
 document.addEventListener('change',e=>{if(e.target.matches&&e.target.matches('[data-edit-toggle]')&&!e.target.checked){e.target.closest('section').querySelectorAll('[data-kontakt].is-editing').forEach(r=>{const c=r.querySelector('.address-edit-cancel');if(c)c.click();});}});
})();
