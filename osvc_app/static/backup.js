/* Nastavení → Záloha a obnova: vytvoření, ověření a obnova ZIP zálohy s ukazatelem průběhu a srovnávací tabulkou.
   Kroky: Nahrávám… / Kontroluji… / Obnovuji databázi… / Obnovuji doklady… / Hotovo (vytvoření: Připravuji data… / Přidávám doklady… /
   Kontroluji zálohu… / Stahuji… / Hotovo). Průběh na serveru se čte z /settings/backup/progress/<job>. */
(()=>{
const drafts=()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('osvc-draft:')).map(k=>[k,localStorage.getItem(k)]));
const message=(status,text,error=false)=>{status.hidden=!text;status.textContent=text;status.classList.toggle('is-error',error);};
const newJob=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
// Po obnově se stránka načte znovu (?obnova=…), aby byla všechna data čerstvá; adresu pak vrátíme na /settings#backup.
if(new URLSearchParams(location.search).has('obnova'))history.replaceState(null,'','/settings#backup');

function progressBox(card){
 let box=card.querySelector('[data-backup-progress]');
 const bar=box.querySelector('progress'),step=box.querySelector('[data-progress-step]'),pct=box.querySelector('[data-progress-pct]');
 let shown=0;
 return {
  set(text,value){value=Math.max(shown,Math.min(100,Math.round(value)));shown=value;box.hidden=false;bar.value=value;step.textContent=text;pct.textContent=value+' %';box.classList.toggle('is-done',value>=100);},
  reset(){shown=0;bar.value=0;box.hidden=true;box.classList.remove('is-done','is-error');},
  fail(){box.classList.add('is-error');}
 };
}
function poll(job,box,from,to){   // průběh serveru (0–100) promítnutý do části ukazatele od–do
 let stop=false;
 const tick=async()=>{if(stop)return;try{const r=await fetch('/settings/backup/progress/'+job,{cache:'no-store'});if(r.ok){const p=await r.json();if(p.popis)box.set(p.popis,from+(to-from)*p.procento/100);}}catch(e){}if(!stop)setTimeout(tick,400);};
 setTimeout(tick,250);return ()=>{stop=true;};
}
function xhr(method,url,body,{onUpload,onDownload,responseType='text',headers={}}={}){
 return new Promise((resolve,reject)=>{const x=new XMLHttpRequest();x.open(method,url);x.responseType=responseType;
  for(const [k,v] of Object.entries(headers))x.setRequestHeader(k,v);
  if(onUpload)x.upload.onprogress=e=>{if(e.lengthComputable)onUpload(e.loaded/e.total);};
  if(onDownload)x.onprogress=e=>{if(e.lengthComputable)onDownload(e.loaded/e.total);};
  x.onload=()=>resolve(x);x.onerror=()=>reject(Error('Spojení s aplikací se přerušilo. Obnovte stránku a zkuste to znovu.'));x.send(body);});
}
const fmt=(label,value)=>{if(value===null||value===undefined)return '—';if(label.endsWith('(Kč)')){const n=Number(value);return Number.isFinite(n)?n.toLocaleString('cs-CZ',{minimumFractionDigits:2,maximumFractionDigits:2})+' Kč':String(value);}return String(value);};
function comparisonTable(rows,left,right){
 const wrap=document.createElement('div');wrap.className='table-wrap';const t=document.createElement('table');t.className='responsive-table restore-comparison';
 t.innerHTML='<thead><tr><th>Položka</th><th class="numeric-column"></th><th class="numeric-column"></th><th>Stav</th></tr></thead><tbody></tbody>';
 t.querySelectorAll('th')[1].textContent=left;t.querySelectorAll('th')[2].textContent=right;
 for(const [label,a,b,state] of rows){const tr=document.createElement('tr');
  const cells=[[label.replace(' (Kč)','').replace(' (počet)',' – počet'),'Položka',''],[fmt(label,a),left,'numeric-column'],[fmt(label,b),right,'numeric-column']];
  for(const [text,l,cls] of cells){const td=document.createElement('td');td.dataset.label=l;if(cls)td.className=cls;td.textContent=text;tr.append(td);}
  const td=document.createElement('td');td.dataset.label='Stav';const chip=document.createElement('span');chip.className=state==='OK'?'status-chip':'error';chip.textContent=state;td.append(chip);tr.append(td);t.tBodies[0].append(tr);}
 wrap.append(t);return wrap;
}

document.addEventListener('change',e=>{if(!e.target.matches('[data-backup-validate] input[type=file]'))return;const card=e.target.closest('.backup-card');card.querySelector('[data-backup-result]').replaceChildren();progressBox(card).reset();message(card.querySelector('[data-backup-status]'),'Po výběru souboru klikněte na Ověřit zálohu.');});

document.addEventListener('submit',async e=>{
 const form=e.target;if(!form.matches('[data-backup-export],[data-backup-restore],[data-backup-validate]'))return;
 e.preventDefault();const card=form.closest('.backup-card'),button=form.querySelector('button'),status=card.querySelector('[data-backup-status]');
 const box=progressBox(card);box.reset();message(status,'');
 const input=form.matches('[data-backup-validate]')?form.querySelector('input[type=file]'):null;
 const body=new FormData(form);const job=newJob();body.set('job',job);
 button.disabled=true;form.setAttribute('aria-busy','true');if(input)input.disabled=true;
 let stopPoll=()=>{};
 try{
  if(form.matches('[data-backup-validate]')){
   const result=card.querySelector('[data-backup-result]');result.replaceChildren();
   box.set('Nahrávám…',0);
   const x=await xhr('POST',form.action,body,{headers:{'X-Backup-Fragment':'1'},onUpload:f=>{box.set(f<1?'Nahrávám…':'Kontroluji…',f*70);}});
   box.set('Kontroluji…',75);
   const html=x.responseText||'';
   if(x.responseURL.includes('/login')||(x.status!==200&&x.status!==400)||!html.includes('backup-'))throw Error('Zálohu se nepodařilo ověřit. Obnovte stránku a zkuste to znovu.');
   result.innerHTML=html;
   if(x.status===400){box.fail();box.set('Záloha neprošla kontrolou',100);}else box.set('Záloha je ověřená',100);
   return;
  }
  body.set('drafts',JSON.stringify(drafts()));
  if(form.matches('[data-backup-export]')){
   box.set('Připravuji data…',2);stopPoll=poll(job,box,0,85);
   const x=await xhr('POST',form.action,body,{responseType:'blob',onDownload:f=>{stopPoll();box.set(f<1?'Stahuji…':'Hotovo',85+15*f);}});
   stopPoll();
   if(x.status!==200||!(x.getResponseHeader('content-type')||'').includes('application/zip')){let msg='Zálohu se nepodařilo vytvořit. Obnovte stránku a zkuste to znovu.';try{msg=JSON.parse(await x.response.text()).error||msg;}catch(err){}throw Error(msg);}
   const blob=x.response,url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='osvc-'+new Date().toISOString().slice(0,10)+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
   box.set('Hotovo',100);
   const warnings=Number(x.getResponseHeader('X-Backup-Warnings'));
   let rows=[];try{rows=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(x.getResponseHeader('X-Backup-Comparison')||''),c=>c.charCodeAt(0))));}catch(err){}
   const ok=rows.length&&rows.every(r=>r[3]==='OK');
   message(status,warnings?`Záloha byla vytvořena, ale kontrola dokumentů zjistila ${warnings} problémů. Podrobnosti jsou v manifest.json.`:(ok?'Kompletní záloha byla vytvořena a zpětně zkontrolována – vše sedí.':'Záloha byla vytvořena.'),!!warnings||(rows.length&&!ok));
   const meta=card.querySelector('[data-backup-export-meta]');meta.replaceChildren();
   for(const [label,value] of [['Právě vytvořená záloha',new Date().toLocaleString('cs-CZ')],['Velikost ZIPu',(blob.size/1048576).toLocaleString('cs-CZ',{maximumFractionDigits:2})+' MB']]){const wrap=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;wrap.append(dt,dd);meta.append(wrap);}
   meta.hidden=false;
   const cmp=card.querySelector('[data-backup-export-comparison]');cmp.replaceChildren();
   if(rows.length){const h=document.createElement('h4');h.textContent='Srovnání: data v aplikaci a v záloze';cmp.append(h,comparisonTable(rows,'V aplikaci','V záloze'));cmp.hidden=false;}
   return;
  }
  // obnova
  box.set('Kontroluji…',2);stopPoll=poll(job,box,0,99);
  const response=await fetch(form.action,{method:'POST',body});
  stopPoll();
  const result=await response.json().catch(()=>({error:'Obnova selhala. Obnovte stránku a zkuste to znovu.'}));
  if(!response.ok||!result.ok)throw Error(result.error||'Obnova selhala.');
  box.set('Hotovo',100);
  for(const key of Object.keys(localStorage))if(key.startsWith('osvc-draft:'))localStorage.removeItem(key);
  for(const [key,value] of Object.entries(result.drafts||{}))localStorage.setItem(key,value);
  message(status,'Hotovo – načítám obnovená data a srovnávací tabulku…');
  // Vždy jiná adresa → stránka se opravdu načte znovu (dřív zůstala viset na „Probíhá zpracování…“, když už byla na /settings#backup).
  setTimeout(()=>location.assign('/settings?obnova='+Date.now()+'#backup'),600);
 }catch(error){stopPoll();box.fail();message(status,error.message,true);}
 finally{button.disabled=false;if(input)input.disabled=false;form.removeAttribute('aria-busy');}
});
})();
