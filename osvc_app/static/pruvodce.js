// I3/A2: průvodce prvním spuštěním – části podle odpovědí (data-ukaz="pole=hodnota" / "pole!=hodnota"),
// „Doplnit z ARES“ podle IČO a hledání zaměstnavatele v ARES. Bez JavaScriptu je vidět vše a formulář funguje.
(function(){
  const form=document.querySelector('[data-pruvodce-form]'); if(!form) return;
  const hodnota=jmeno=>{const pole=form.elements[jmeno]; if(!pole) return ''; if(pole instanceof RadioNodeList) return pole.value; return pole.type==='checkbox'?(pole.checked?pole.value:''):pole.value;};
  const prepni=()=>{for(const el of form.querySelectorAll('[data-ukaz]')){const m=el.dataset.ukaz.match(/^(\w+)(!?=)(.*)$/); if(!m) continue; const v=hodnota(m[1]); el.hidden=m[2]==='='?v!==m[3]:v===m[3];}};
  form.addEventListener('change',prepni); prepni();
  // Zálohy OSVČ: se zaměstnáním a v prvním roce podnikání (IČO podle ARES vzniklo letos, nebo začátek letos po 1. 1.)
  // předvyplnit „Neplatím“ – jen dokud na otázku o zálohách uživatel sám neodpověděl.
  const rok=form.dataset.rok, zalohyNote=form.querySelector('[data-zalohy-prvni-rok]'); let aresVznik='', zalohyRucne=false, zalohyAuto=false;
  for(const el of form.querySelectorAll('[name=social_zalohy],[name=health_zalohy]')) el.addEventListener('change',e=>{if(e.isTrusted) zalohyRucne=true;});
  function zalohyPrvniRok(){
    const od=hodnota('podnikani_od'), prvniRok=aresVznik?aresVznik.slice(0,4)===rok:(od&&od>rok+'-01-01');
    const navrh=hodnota('zamestnani')==='ano'&&!!prvniRok;
    if(navrh&&!zalohyRucne&&!hodnota('social_zalohy')&&!hodnota('health_zalohy')){form.elements.social_zalohy.value='neplati'; form.elements.health_zalohy.value='neplati'; zalohyAuto=true; prepni();}
    if(!navrh&&zalohyAuto&&!zalohyRucne){form.elements.social_zalohy.value=''; form.elements.health_zalohy.value=''; for(const r of form.querySelectorAll('[name=social_zalohy],[name=health_zalohy]')) r.checked=false; zalohyAuto=false; prepni();}
    if(zalohyNote) zalohyNote.hidden=!(navrh&&zalohyAuto);
  }
  form.addEventListener('change',e=>{if(['zamestnani','podnikani_od'].includes(e.target.name)) zalohyPrvniRok();});
  const csrf=()=>form.elements.csrf_token.value;
  async function posli(url,data){const body=new FormData(); for(const [k,v] of Object.entries(data)) body.append(k,v); body.append('csrf_token',csrf());
    const r=await fetch(url,{method:'POST',body,headers:{'Accept':'application/json'}}); const d=await r.json().catch(()=>({error:'Služba teď neodpovídá.'})); if(!r.ok||d.error) throw new Error(d.error||'Služba teď neodpovídá.'); return d;}
  // Datum vzniku IČO z ARES: „Od kdy letos podnikáte“ (vznik letos = to datum, jinak 1. 1.) a otázka na první podnikání
  // jen při vzniku v posledních 2 letech (předvyplněno „Ano“); starší IČO = „Ne“ a otázka se skryje. Bez ARES se ptá bez předvyplnění.
  const prvni=form.querySelector('[data-prvni]'), prvniOtazka=form.querySelector('[data-prvni-otazka]'), prvniText=prvniOtazka?prvniOtazka.textContent:'';
  function prvniPodnikani(d){
    if(d.podnikani_od&&form.elements.podnikani_od) form.elements.podnikani_od.value=d.podnikani_od;
    aresVznik=d.vznik||''; zalohyPrvniRok();
    if(!prvni||d.ptat_prvni===null||d.ptat_prvni===undefined) return;
    const volby=form.elements.prvni_zahajeni;
    if(d.ptat_prvni){prvni.hidden=false; prvniOtazka.textContent='Podle ARES podnikáte od '+d.vznik_text+'. Je to vaše první podnikání? (Nikdy dřív jste nepodnikal(a), nebo je to déle než 20 let.)'; volby.value='ano';}
    else{volby.value='ne'; prvni.hidden=true; prvniOtazka.textContent=prvniText;}
  }
  const ares=form.querySelector('[data-pruvodce-ares]'), aresStav=form.querySelector('[data-pruvodce-ares-stav]');
  if(ares) ares.addEventListener('click',async()=>{
    const ico=form.elements.ico.value.replace(/\s/g,'');
    if(!/^\d{8}$/.test(ico)){aresStav.textContent='Nejdřív zadejte osmimístné IČO.'; form.elements.ico.focus(); return;}
    ares.disabled=true; aresStav.textContent='Hledám v ARES…';
    try{const d=await posli(ares.dataset.url,{ico}); for(const k of ['name','street','number','city','zip','country','dic']) if(form.elements[k]&&d[k]) form.elements[k].value=d[k];
      prvniPodnikani(d);
      aresStav.textContent='Údaje z ARES jsou doplněné. Zkontrolujte je, případně upravte.';}
    catch(e){aresStav.textContent=e.message+' Údaje vyplňte ručně.';} finally{ares.disabled=false;}
  });
  const zam=form.querySelector('[data-zam-tlacitko]'); if(!zam) return;
  const hledat=form.querySelector('[data-zam-hledat]'), vysledky=form.querySelector('[data-zam-vysledky]'), stav=form.querySelector('[data-zam-stav]');
  const nazev=form.querySelector('[data-zam-nazev]'), token=form.querySelector('[data-zam-token]');
  hledat.addEventListener('input',()=>{nazev.value=''; token.value=''; stav.textContent='';});   // ručně psaný název se neukládá – jen ověřený výběr
  zam.addEventListener('click',async()=>{
    zam.disabled=true; stav.textContent='Hledám v ARES…'; vysledky.textContent='';
    try{const d=await posli(zam.dataset.url,{hledat:hledat.value});
      if(!d.vysledky.length){stav.textContent='Nic nenalezeno – zkuste jiný název, nebo pole nechte prázdné.'; return;}
      stav.textContent='Vyberte svého zaměstnavatele:';
      for(const x of d.vysledky){const b=document.createElement('button'); b.type='button'; b.className='secondary'; b.textContent=x.name+' · IČO '+x.ico+(x.city?' · '+x.city:'');
        b.addEventListener('click',async()=>{try{const v=await posli(zam.dataset.url,{ico:x.ico}); nazev.value=v.name; token.value=v.token; hledat.value=v.name; vysledky.textContent=''; stav.textContent='Vybráno: '+v.name+' (IČO '+v.ico+')';}catch(e){stav.textContent=e.message;}});
        vysledky.appendChild(b);}
    }catch(e){stav.textContent=e.message;} finally{zam.disabled=false;}
  });
})();
