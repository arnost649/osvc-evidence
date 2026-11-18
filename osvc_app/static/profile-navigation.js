(()=>{
const panel=document.querySelector('#settings-panel-profile'),form=document.querySelector('[data-profile-form]');if(!panel||!form)return;
const sections={overview:'Přehled',business:'Podnikání',employment:'Zaměstnání',social:'ČSSZ',health:'Zdravotní pojištění',tax:'Daňové nastavení',vehicle:'Vozidlo a doprava',advanced:'Pokročilé'};
const subnav=document.querySelector('[data-profile-subnav]'),selector=document.querySelector('[data-profile-selector]');
for(const [key,label] of Object.entries(sections)){const o=document.createElement('option');o.value=key;o.textContent=label;selector.append(o);}
function keyFor(hash){let k=hash.replace(/^#profile-?/,'');return k==='vehicles'?'vehicle':k==='identity'?'overview':sections[k]?k:'overview';}
function show(key){
 const active=!panel.hidden;if(subnav)subnav.hidden=!active;
 for(const page of panel.querySelectorAll('[data-profile-page]')){page.hidden=page.dataset.profilePage!==key;if(page.tagName==='DETAILS'&&page.id!=='profile-identity')page.open=!page.hidden;}
 for(const link of document.querySelectorAll('[data-profile-section]')){const selected=link.dataset.profileSection===key;link.classList.toggle('is-active',selected);if(selected)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
 selector.value=key;form.elements.profile_section.value=key;
 const save=document.querySelector('[form=osvc-profile-form]');if(save)save.hidden=false;
}
function navigate(key){history.pushState({},'','#profile-'+key);window.dispatchEvent(new HashChangeEvent('hashchange'));show(key);}
window.profileSectionNavigate=navigate;
document.addEventListener('click',e=>{const link=e.target.closest('[data-profile-section]');if(link){e.preventDefault();navigate(link.dataset.profileSection);}});
selector.addEventListener('change',()=>navigate(selector.value));
for(const type of ['hashchange','popstate'])window.addEventListener(type,()=>show(keyFor(location.hash)));
document.addEventListener('settings-tab-change',()=>show(keyFor(location.hash)));
document.querySelector('[data-profile-year]').addEventListener('submit',e=>e.target.action='/settings#profile-'+selector.value);
form.addEventListener('invalid',e=>{const page=e.target.closest('[data-profile-page]');if(page){navigate(page.dataset.profilePage);if(page.tagName==='DETAILS')page.open=true;}},true);
document.querySelector('#profile-identity').addEventListener('toggle',()=>show(keyFor(location.hash)));
// Zero is accepted only after an explicit check; nonzero entry is confirmed on save.
for(const box of form.querySelectorAll('[data-paid-control]')){
 const input=form.elements[box.dataset.paidControl],check=box.querySelector('[data-paid-confirm]'),caption=box.querySelector('[data-paid-caption]');
 function update(){const n=Number(input.value.replace(/\s/g,'').replace(',','.'));const nonzero=input.value.trim()!==''&&Number.isFinite(n)&&n>0;check.disabled=nonzero;caption.textContent=nonzero?'Potvrdí se uložením':check.checked?'Potvrzeno':'Potvrzuji tuto částku';}
 input.addEventListener('input',()=>{check.checked=false;update();});check.addEventListener('change',()=>{if(check.checked&&!input.value.trim())input.value='0,00';update();});update();
}
for(const summary of panel.querySelectorAll('.profile-card[data-profile-page]:not(#profile-identity)>summary'))summary.addEventListener('click',e=>{if(!e.target.closest('button'))e.preventDefault();});
show(keyFor(location.hash||'#profile-'+panel.dataset.profileInitial));
})();
