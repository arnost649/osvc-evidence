// Adresář → „Hledat kontakt“: shody z adresáře ukazuje sdílený combobox (ui.js), lupa hledá firmu v ARES (stejně jako PHM, fuel.js)
// a nalezenou firmu jde jedním kliknutím přidat do sekce Dodavatelé / Odběratelé / Benzinky (POST verify-name/apply s rolí).
(() => {
 const form=document.querySelector('[data-address-search]');if(!form)return;
 const box=form.querySelector('[data-combobox]'),input=box.querySelector('input[role=combobox]'),button=box.querySelector('[data-registry-search]'),result=box.querySelector('[data-registry-results]');
 const sections={supplier:['suppliers','Dodavatelé'],customer:['customers','Odběratelé'],fuel_station:['stations','Benzinky']};
 let revision=0;
 const el=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;};
 const found=n=>n===1?'Nalezen 1 subjekt v ARES':(n>=2&&n<=4?`Nalezeny ${n} subjekty v ARES`:`Nalezeno ${n} subjektů v ARES`);
 const visibleMatches=()=>[...box.querySelectorAll('[role=option]')].filter(option=>!option.hidden).length;
 const open=address=>location.assign(form.action.split('#')[0]+'?q='+encodeURIComponent(address.name)+'#'+address.section);
 // A contact chosen from the suggestions: show it in its section.
 box.addEventListener('combobox:choose',event=>{const option=[...box.querySelectorAll('[role=option]')].find(o=>o.dataset.value===event.detail.value);if(option)open({name:option.dataset.name,section:option.dataset.section});});
 function inBook(ico){return ico?[...box.querySelectorAll('[role=option]')].filter(o=>o.dataset.ico===ico).map(o=>o.dataset.role):[];}
 async function add(candidate,role,status){
  status.textContent='Přidávám…';
  try{
   const response=await fetch(form.dataset.applyUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body:new URLSearchParams({csrf_token:form.dataset.csrf,ico:candidate.ico,role})});
   if(response.redirected)throw Error('Přihlaste se znovu.');
   const body=await response.json();if(!response.ok||!body.ok)throw Error(body.message||'Firmu se nepodařilo přidat.');
   try{sessionStorage.setItem('osvc:address-added',body.message==='Ověřené údaje byly použity.'?`${body.supplier.name} je v sekci ${sections[role][1]}.`:body.message);}catch(e){}
   open({name:body.supplier.name,section:sections[role][0]});
  }catch(error){status.textContent=error.message;}
 }
 function render(results){
  result.replaceChildren();
  if(!results.length){result.textContent='V ARES se nic nenašlo.';return;}
  const details=el('details'),summary=el('summary',null,found(results.length)+' – zobrazit');details.append(summary);
  results.forEach(candidate=>{
   const card=el('div','entity-candidate entity-candidate-card');
   card.append(el('strong',null,candidate.name),el('span',null,' · IČO '+candidate.ico));
   if(candidate.address)card.append(el('small',null,candidate.address));
   const roles=inBook(candidate.ico),actions=el('div','entity-candidate-add'),status=el('small','entity-candidate-status');
   actions.append(el('span',null,'Přidat do:'));
   Object.entries(sections).forEach(([role,[,label]])=>{
    const already=role!=='fuel_station'&&(roles.includes(role)||roles.includes('both'));
    const add_button=el('button','secondary',(already?'✓ ':'+ ')+label);add_button.type='button';add_button.disabled=already;add_button.dataset.role=role;
    if(already)add_button.title='Už je v adresáři';
    add_button.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();actions.querySelectorAll('button').forEach(b=>b.disabled=true);add(candidate,role,status);});
    actions.append(add_button);
   });
   card.append(actions,status);details.append(card);
  });
  if(results.length===1)details.open=true;
  result.append(details);
 }
 async function search(){
  const name=input.value.trim();if(name.length<2)return;const checked=++revision;
  button.dataset.busy='true';button.disabled=true;result.hidden=false;result.textContent='Hledám v ARES…';
  try{
   const response=await fetch(form.dataset.lookupUrl+'?'+new URLSearchParams({name,id:''}),{credentials:'same-origin',headers:{'Accept':'application/json'}});
   if(response.redirected)throw Error('Přihlaste se znovu.');
   const body=await response.json();if(checked!==revision)return;
   render(body.results||[]);
  }catch(error){if(checked===revision)result.textContent=error.message||'ARES teď není dostupný.';}
  finally{delete button.dataset.busy;if(button.updateAvailability)button.updateAvailability();else button.disabled=input.value.trim().length<2;}
 }
 button.addEventListener('click',event=>{event.preventDefault();search();});
 // Nothing in the address book for what was typed: just say so – the internet search is the magnifier in the field (ui.js filters first, hence the timeout).
 input.addEventListener('input',()=>{revision++;result.hidden=true;setTimeout(()=>{
  const name=input.value.trim();if(name.length<3||visibleMatches())return;
  result.replaceChildren(el('span',null,'V adresáři nic.'));result.hidden=false;
 },0);});
 document.addEventListener('click',event=>{if(!box.contains(event.target))result.hidden=true;});
 document.addEventListener('keydown',event=>{if(event.key==='Escape')result.hidden=true;});
 window.addEventListener('load',()=>{let message='';try{message=sessionStorage.getItem('osvc:address-added')||'';sessionStorage.removeItem('osvc:address-added');}catch(e){}if(message&&window.osvcToast)window.osvcToast(message);});
})();
