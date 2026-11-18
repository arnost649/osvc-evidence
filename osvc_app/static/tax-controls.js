/* Shared explicit expense tax controls. */
document.querySelectorAll('[data-tax-mode]').forEach((mode,index)=>{
 const form=mode.form,input=form.querySelector('[data-tax-share]'),error=form.querySelector('[data-tax-share-error]');
 if(!input||!error)return;
 error.id='tax-share-error-'+index;input.setAttribute('aria-describedby',error.id);
 function validate(show=false){
  let message='';const raw=input.value.trim().replace(',','.');
  if(!input.disabled){
   if(!raw)message='Vyplňte vlastní podíl.';
   else if(!/^\d+(?:\.\d{1,2})?$/.test(raw)||Number(raw)>100)message='Zadejte podíl 0 až 100 %, nejvýše dvě desetinná místa.';
  }
  input.setCustomValidity(message);input.setAttribute('aria-invalid',String(!!message&&show));error.textContent=message;error.hidden=!message||!show;
 }
 function update(){input.disabled=mode.value!=='custom';input.required=!input.disabled;validate();}
 mode.addEventListener('change',update);
 input.addEventListener('input',()=>validate(true));
 input.addEventListener('invalid',()=>validate(true));update();
});
