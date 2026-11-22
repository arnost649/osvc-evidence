// Záchranný kód (1.0.3): Vytisknout a Stáhnout jako .txt – jen v prohlížeči, kód se na server znovu neposílá.
(function(){
  const karta=document.querySelector('[data-zachranny-kod-karta]'); if(!karta) return;
  const kod=karta.querySelector('[data-zachranny-kod]').textContent.trim();
  // Pokračovat: rovnou na cílovou adresu (formulář GET by přidal prázdné „?“); bez zaškrtnutí prohlížeč ukáže, co chybí
  const hotovo=document.querySelector('[data-kod-hotovo]');
  hotovo?.addEventListener('submit',e=>{ if(hotovo.dataset.dal){ e.preventDefault(); location.assign(hotovo.dataset.dal); } });
  document.querySelector('[data-kod-tisk]')?.addEventListener('click',()=>window.print());
  document.querySelector('[data-kod-stahnout]')?.addEventListener('click',()=>{
    const d=new Date(), dnes=d.toLocaleDateString('cs-CZ');
    const text=['OSVČ evidence – záchranný kód pro obnovu hesla','',kod,'','Vytvořen: '+dnes,
      'Použití: Přihlášení → Zapomněl jsem heslo → zadejte tento kód a nastavte si nové jméno a heslo.',
      'Kód platí, dokud si nezměníte heslo nebo nevytvoříte nový kód. Uložte ho mimo počítač.',''].join('\r\n');
    const a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob(['﻿'+text],{type:'text/plain;charset=utf-8'}));
    a.download='OSVC-evidence-zachranny-kod-'+d.toISOString().slice(0,10)+'.txt';
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  });
})();
