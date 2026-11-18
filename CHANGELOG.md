# Změny

Popis každého vydání (`## vX.Y.Z`) se při vydání vloží do GitHub Releases. Bez popisu se vydání nevytvoří.

## v1.0.0
První veřejné vydání pro Windows a Linux.
- **Instalace:** instalátor pro Windows 10/11 (bez práv správce) a balíček `.deb` pro Ubuntu 24.04+ / Debian 13+. Data jsou
  vždy mimo složku programu, aktualizace instalací nové verze přes starou je zachová.
- **Průvodce prvním spuštěním** na dvě strany (IČO s doplněním z ARES, přihlášení, podnikání, zaměstnání, pojištění, zálohy,
  daně, moduly; vozidlo a zdroj příjmů): po vyplnění je Profil OSVČ i Roční přehled hotový.
- **Evidence:** příjmy a výdaje s doklady, jízdy a PHM, adresář s ověřením v ARES, Roční přehled (podklady pro daň z příjmů
  § 7, ČSSZ a zdravotní pojišťovnu) a Profil OSVČ; moduly Doprava a Externí web (e-shop WooCommerce) jde vypnout.
- **Zálohy:** denní automatická záloha databáze, ZIP záloha všech dat a obnova se srovnávací tabulkou; před úpravou struktury
  databáze novou verzí automatický snímek a při chybě návrat.
- **Síťový přístup:** jen tento počítač (výchozí), nebo zpřístupnění v domácí síti (Windows přidá pravidlo firewallu jen pro
  port aplikace a soukromou síť).
- **Upozornění na novou verzi** jednou denně (vypnutelné v Nastavení).
- **Odinstalace:** data se ponechají, nebo se smažou až po záloze (Windows: ZIP na Plochu; Linux `apt purge`: /var/backups/osvc-evidence).
