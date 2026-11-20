# Změny

Popis každého vydání (`## vX.Y.Z`) se při vydání vloží do GitHub Releases. Bez popisu se vydání nevytvoří.

## v1.0.2
- **Formuláře Příjmy, Výdaje, Jízdy a PHM:** nové přehledné rozvržení v mřížce, Uložit vpravo dole. Tabulátor jde zleva
  doprava a shora dolů, Uložit naposledy. Na mobilu jsou pole pod sebou.
- **Tlačítko Uložit** je šedé, dokud nejsou vyplněné všechny povinné údaje; kliknutím se ukáže, co chybí.
- **Výdaje:** pole „Popis“ a jedno pole „Daňové uplatnění“ – předvybráno 100 %, rychlá volba 50 %, nebo vlastní procento.
- **Příjmy:** pole „Za co“ se jmenuje „Popis“.
- **Jízdy:** Náklad cesty se spočítá sám; výpočet a sazby jsou v ikonce (i).
- **PHM:** litry se spočítají samy z ceny (Cena celkem ÷ Cena za litr) a ukazují se v seznamu.
- **Seznamy:** výběr roku vedle nadpisu (jen roky se záznamy) a součet za rok přímo nad sloupcem částky. Při vypnutém
  přepínači Upravit jsou ikonky akcí šedé a neaktivní.
- **Adresář:** úprava kontaktu přímo v seznamu; po zadání IČO se název, DIČ a adresa doplní z ARES („Ověřeno v ARES“).
  Role Dodavatel / Odběratel jako přepínací štítky. Adresář drží jen veřejné údaje (bez e-mailu, telefonu a poznámky).
- **Přehled:** větší souhrnné karty; **Roční přehled** nabízí jen roky, ke kterým jsou data.
- README: návod, jak projít varováním Windows při instalaci; obrázky ve světlé i tmavé verzi.

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
