(() => {
 const form=document.querySelector('form.fuel-entry');if(!form)return;
 const liters=form.elements.liters,price=form.elements.price_per_liter,total=form.elements.total_amount;
 function calculate(){
  const priceValue=Number(price.value.trim().replace(',','.')),totalValue=Number(total.value.trim().replace(',','.'));
  const value=totalValue/priceValue;
  const scaled=value*100;
  liters.value=price.value.trim()&&total.value.trim()&&Number.isFinite(priceValue)&&priceValue>0&&Number.isFinite(totalValue)&&totalValue>=0&&Number.isFinite(scaled)?(Math.round(scaled+Number.EPSILON*Math.max(1,scaled))/100).toFixed(2):'';
 }
 [price,total].forEach(field=>{field.addEventListener('input',calculate);field.addEventListener('change',calculate);});
 calculate();
 // Drafts are restored by ui.js during DOMContentLoaded.
 window.addEventListener('load',calculate);
})();

(() => {
 const button=document.querySelector('[data-fuel-verify]');if(!button)return;
 const box=button.closest('[data-combobox]'),input=box.querySelector('input[role=combobox]'),result=box.querySelector('[data-fuel-check-results]');
 const form=button.closest('form');let revision=0;
 // Click handler stops propagation: the clicked button is replaced below, so the outside-click handlers would hide the result.
 function choose(candidate){
  // One directory station of this operator: select it; otherwise the operator's name is used (saved as the station name).
  const stations=[...box.querySelectorAll('[role=option][data-ico]')].filter(option=>option.dataset.ico===candidate.ico);
  const station=stations.length===1?stations[0]:null;
  input.value=station?station.dataset.name:candidate.name;
  input.dispatchEvent(new Event('input',{bubbles:true}));
  if(station)form.elements.counterparty_id.value=station.dataset.value;
  input.focus({preventScroll:true});   // before closing: focus opens the combobox list (ui.js)
  box.querySelector('.combobox-options').hidden=true;input.setAttribute('aria-expanded','false');
  const label='Vybráno: '+candidate.name+' · IČO '+candidate.ico;
  button.dataset.state='success';button.title=label;
  result.replaceChildren();result.textContent=label+(stations.length>1?' – v adresáři je víc stanic tohoto provozovatele, případně vyberte pobočku ze seznamu.':'');result.hidden=false;
 }
 button.addEventListener('click',async event=>{
  event.preventDefault();if(button.disabled||input.value.trim().length<2)return;const checkedRevision=revision;
  const data=new FormData();data.set('counterparty_name',input.value);data.set('counterparty_id',form.elements.counterparty_id.value);data.set('csrf_token',button.dataset.csrf);
  button.dataset.busy='true';button.disabled=true;result.hidden=true;
  try{
   const response=await fetch(button.dataset.url,{method:'POST',body:data,credentials:'same-origin'});
   if(response.redirected)throw Error('Přihlaste se znovu.');
   const body=await response.json();if(revision!==checkedRevision)return;
   button.dataset.state=body.status||'danger';button.title=body.message;result.replaceChildren();
   if(body.station_id)form.elements.counterparty_id.value=String(body.station_id);
   if(body.status==='success'){window.osvcToast(body.message);return;}
   result.hidden=false;
   if(body.candidates?.length){
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=body.message+' – zobrazit';details.append(summary);
    // Each candidate is a button: a click fills the station name (and picks the directory station with the same IČO).
    body.candidates.forEach(candidate=>{const line=document.createElement('button');line.type='button';line.className='entity-candidate';line.textContent=candidate.name+' · IČO '+candidate.ico;
     line.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();choose(candidate);});details.append(line);});result.append(details);
   }else result.textContent=body.message||'Subjekt se nepodařilo ověřit.';
  }catch(error){button.dataset.state='danger';button.title=error.message;result.hidden=false;result.textContent=error.message;}
  finally{delete button.dataset.busy;if(button.updateAvailability)button.updateAvailability();else button.disabled=input.value.trim().length<2;}
 });
 input.addEventListener('input',()=>{revision++;result.hidden=true;delete button.dataset.state;button.title='Ověřit subjekt';});
 document.addEventListener('click',event=>{if(!box.contains(event.target))result.hidden=true;});
 document.addEventListener('keydown',event=>{if(event.key==='Escape')result.hidden=true;});
})();
