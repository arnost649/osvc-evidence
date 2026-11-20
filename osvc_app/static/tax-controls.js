/* Daňové uplatnění výdaje: výběr 100 % / 50 % / Vlastní…; u „Vlastní…“ je na stejném místě pole s % a vpravo šipka ▾
   (zmenšený tentýž select), přes kterou jde kdykoli přepnout zpět. Hláška o chybějícím podílu až při pokusu o uložení. */
document.querySelectorAll('[data-tax-mode]').forEach((mode,index)=>{
 const form=mode.form,input=form.querySelector('[data-tax-share]'),error=form.querySelector('[data-tax-share-error]');
 if(!input||!error)return;
 const field=form.querySelector('[data-tax-field]'),box=form.querySelector('[data-tax-custom]');
 let tried=false;   // uživatel zkusil uložit
 error.id='tax-share-error-'+index;input.setAttribute('aria-describedby',error.id);
 function validate(show=false){
  let message='';const raw=input.value.trim().replace(',','.');
  if(!input.disabled){
   if(!raw)message='Vyplňte podíl v procentech.';
   else if(!/^\d+(?:\.\d{1,2})?$/.test(raw)||Number(raw)>100)message='Zadejte podíl 0 až 100 %, nejvýše dvě desetinná místa.';
  }
  show=show&&tried;
  input.setCustomValidity(message);input.setAttribute('aria-invalid',String(!!message&&show));error.textContent=message;error.hidden=!message||!show;
 }
 function update(focus=false){
  const custom=mode.value==='custom';
  input.disabled=!custom;input.required=custom;
  if(field)field.classList.toggle('is-custom',custom);if(box)box.hidden=!custom;
  validate(!error.hidden);if(focus&&custom)input.focus();
 }
 form.addEventListener('click',e=>{if(e.target.closest('button[type=submit],input[type=submit]'))tried=true;},true);
 document.addEventListener('click',e=>{const b=e.target.closest('[type=submit][form]');if(b&&b.getAttribute('form')===form.id)tried=true;},true);
 form.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('input'))tried=true;},true);
 mode.addEventListener('change',()=>{form.querySelectorAll('[data-tax-server-error]').forEach(e=>e.remove());update(true);});
 input.addEventListener('input',()=>validate(!error.hidden));
 input.addEventListener('invalid',e=>{if(tried){e.preventDefault();validate(true);input.focus();}else validate();});update();
});
