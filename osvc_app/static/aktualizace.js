// Okénko s verzí na Přehledu: nejnovější verze / nová verze s popisem a „Aktualizovat“ (Windows: stažení s průběhem,
// ověření SHA256, spuštění instalace a čekání na novou verzi) / Linux: odkaz na .deb a příkaz. Server: jen text o osvc-nasad.
(function(){
  const okno=document.querySelector('[data-verze-okno]'), tlacitko=document.querySelector('[data-verze-otevrit]');
  if(!okno||!tlacitko) return;
  const obsah=okno.querySelector('[data-verze-obsah]');
  const el=(tag,text,trida)=>{const e=document.createElement(tag); if(text!==undefined) e.textContent=text; if(trida) e.className=trida; return e;};
  async function post(url){const b=new FormData(); b.append('csrf_token',okno.dataset.csrf); const r=await fetch(url,{method:'POST',body:b,headers:{'Accept':'application/json'}}); return [r.ok, await r.json().catch(()=>({}))];}
  const odstavec=(...deti)=>{const p=el('p'); p.append(...deti); return p;};
  function odkaz(text,href){const a=el('a',text); a.href=href; a.target='_blank'; a.rel='noopener noreferrer'; return a;}
  function vykresli(d){
    if(!d.samostatna) return;   // server: obsah je v šabloně
    obsah.textContent='';
    if(d.nova){
      obsah.append(el('h2','Je k dispozici verze '+d.nejnovejsi), el('p','Máte verzi '+d.verze+'.','settings-help'));
      if(d.popis){const p=el('div','','verze-popis'); for(const r of d.popis.split('\n')) p.append(el('p',r)); obsah.append(p);}
      if(d.windows&&d.lze_instalovat){
        const b=el('button','Aktualizovat'); b.type='button'; b.dataset.aktualizovat='';
        const stav=el('div','','verze-prubeh'); stav.hidden=true; const pruh=el('progress'); pruh.max=100; pruh.value=0; const popisek=el('p','','settings-help'); stav.append(pruh,popisek);
        b.addEventListener('click',async()=>{b.disabled=true; stav.hidden=false; popisek.textContent='Stahuji…';
          const [ok,v]=await post(okno.dataset.instalovat); if(!ok){popisek.textContent=v.chyba||'Aktualizaci teď nejde spustit.'; b.disabled=false; return;} sleduj(pruh,popisek,b,d.verze);});
        obsah.append(b,stav,el('p','Data zůstanou zachovaná. Instalátor se stáhne z GitHubu a před spuštěním se ověří jeho kontrolní součet.','settings-help'));
        if(d.prubeh&&['stahuji','overuji','spoustim'].includes(d.prubeh.faze)){b.disabled=true; stav.hidden=false; sleduj(pruh,popisek,b,d.verze);}
      }else if(d.windows){obsah.append(el('p','Instalátor stáhněte ze stránky vydání:'),odkaz('Otevřít stránku vydání na GitHubu',d.odkaz));}
      else{
        obsah.append(el('p','Stáhněte balíček a nainstalujte ho přes starou verzi (data zůstanou):'));
        if(d.deb) obsah.append(odstavec(odkaz('Stáhnout osvc-evidence-linux.deb',d.deb)));
        const c=el('pre',''); c.append(el('code','cd ~/Stažené\n'+d.prikaz)); obsah.append(c,el('p','Služba se po instalaci spustí sama.','settings-help'));
      }
    }else{
      obsah.append(el('h2','Máte nejnovější verzi '+d.verze));
      if(d.chyba) obsah.append(el('p','Poslední kontrola se nepovedla (GitHub neodpověděl).','settings-help'));
      else if(!d.kontrola) obsah.append(el('p','Kontrola nových verzí zatím neproběhla.','settings-help'));
      if(d.odkaz) obsah.append(odstavec(odkaz('Vydání na GitHubu',d.odkaz)));
    }
    if(okno.dataset.zkontrolovat&&d.dostupne){const z=el('button','Zkontrolovat teď','secondary'); z.type='button';
      z.addEventListener('click',async()=>{z.disabled=true; z.textContent='Kontroluji…'; const [ok,v]=await post(okno.dataset.zkontrolovat); if(ok) vykresli(v); else {z.disabled=false; z.textContent='Zkontrolovat teď';}});
      obsah.append(z);}
  }
  function sleduj(pruh,popisek,b,stara){
    const t=setInterval(async()=>{
      let v; try{v=await (await fetch(okno.dataset.prubeh,{headers:{'Accept':'application/json'}})).json();}catch(e){v=null;}
      if(!v){popisek.textContent='Spouštím instalaci, aplikace se na chvíli zavře. Stránka se po aktualizaci obnoví sama.'; return;}   // aplikace se zavřela – čekáme
      if(v.verze&&v.verze!==stara){clearInterval(t); location.reload(); return;}   // nová verze běží
      const p=v.prubeh||{}; if(p.procent!==undefined) pruh.value=p.procent; if(p.text) popisek.textContent=p.text+(p.faze==='stahuji'&&p.procent?' '+p.procent+' %':'');
      if(p.faze==='chyba'){clearInterval(t); b.disabled=false;}
    },1000);
  }
  tlacitko.addEventListener('click',async()=>{
    if(okno.dataset.zkontrolovat){try{vykresli(await (await fetch(tlacitko.dataset.okno,{headers:{'Accept':'application/json'}})).json());}catch(e){}}
    okno.showModal();
  });
})();
