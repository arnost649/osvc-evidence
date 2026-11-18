// Nastavení → Síťový přístup: seznam adaptérů (předvybraný ten s výchozí trasou), část „domácí síť“ jen při té volbě.
(function(){
  const form=document.querySelector('[data-sit-form]'); if(!form) return;
  const domaci=form.querySelector('[data-sit-domaci]'), vyber=form.querySelector('[data-sit-ip]'), verejna=form.querySelector('[data-sit-verejna]');
  let nacteno=false, adaptery=[];
  const zobraz=()=>{const d=form.elements.rezim.value==='domaci'; domaci.hidden=!d; form.elements.potvrzeni.required=d; if(d&&!nacteno) nacti();};
  const kontrola=()=>{const a=adaptery.find(x=>x.ip===vyber.value); verejna.hidden=!(a&&a.kategorie==='Veřejná');};
  async function nacti(){
    nacteno=true; const ulozena=vyber.value;
    try{const r=await fetch(form.dataset.adaptery,{headers:{'Accept':'application/json'}}); adaptery=(await r.json()).adaptery||[];}catch(e){adaptery=[];}
    vyber.textContent='';
    if(!adaptery.length){const o=new Option('Žádný síťový adaptér s adresou IPv4 nenalezen',''); vyber.add(o); return;}
    for(const a of adaptery){vyber.add(new Option(a.nazev+' – '+a.ip+(a.brana?' (internet)':'')+(a.kategorie?' · síť: '+a.kategorie:''),a.ip));}
    vyber.value=adaptery.some(a=>a.ip===ulozena)?ulozena:(adaptery.find(a=>a.brana)||adaptery[0]).ip; kontrola();
  }
  form.addEventListener('change',e=>{if(e.target.name==='rezim') zobraz(); if(e.target===vyber) kontrola();});
  zobraz();
})();
