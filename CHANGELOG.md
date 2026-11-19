# Změny

Popis každého vydání (`## vX.Y.Z`) se při vydání vloží do GitHub Releases. Bez popisu se vydání nevytvoří.

## v1.0.1
- **Verze na Přehledu:** malým písmem dole; po kliknutí okénko „Máte nejnovější verzi“, nebo nová verze se stručným popisem.
- **Aktualizace jedním kliknutím (Windows):** tlačítko „Aktualizovat“ stáhne instalátor z GitHubu s ukazatelem průběhu, ověří
  jeho kontrolní součet (SHA-256), aplikaci na chvíli zavře, nainstaluje novou verzi a znovu ji spustí. Data zůstanou.
  Na Linuxu okénko ukáže odkaz na balíček a příkaz pro instalaci.
- **Nastavení → Aktualizace:** zapnutí/vypnutí automatické kontroly a tlačítko „Zkontrolovat teď“.
- Instalátor má v metadatech název produktu a verzi a před instalací ukáže zásady soukromí; README s oddílem Code signing policy.
- Síťový přístup: kratší a jemnější upozornění.

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
