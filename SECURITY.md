# Bezpečnost

## Jak nahlásit bezpečnostní chybu
Bezpečnostní chyby (například neoprávněný přístup k datům, obejití přihlášení, únik dat do zálohy nebo do sítě)
**nehlaste veřejně v Issues**. Použijte soukromé hlášení na GitHubu:
**Security → Report a vulnerability** (soukromé hlášení zranitelnosti).

Do hlášení prosím uveďte:
- verzi aplikace (Nastavení → Účet / Přihlášení → Aktualizace) a systém (Windows / Linux),
- co přesně se stalo a jak to zopakovat,
- jaký dopad chyba může mít.

**Nikdy nepřikládejte svá skutečná data** (databázi, zálohy ZIP, doklady, hesla) – stačí popis nebo smyšlený příklad.

## Co můžete čekat
- Potvrzení přijetí do 7 dnů.
- Oprava vyjde jako nová verze v Releases; aplikace na ni upozorní (Nastavení → Aktualizace).
- Po vydání opravy můžeme chybu popsat v CHANGELOG.md (s poděkováním, pokud si to přejete).

## Podporované verze
Opravy vycházejí pro poslední vydanou verzi. Starší verze aktualizujte instalací nové verze přes starou – data zůstanou.

## Jak aplikace chrání data
- Data jsou jen na vašem počítači (Windows: `%LOCALAPPDATA%\OSVC evidence`, Linux: `/var/lib/osvc-evidence`), mimo složku programu.
- Výchozí přístup je jen z tohoto počítače (`localhost`). Zpřístupnění v domácí síti je vědomá volba v Nastavení; spojení
  není šifrované, proto jen v domácí síti.
- Heslo se ukládá jen jako otisk; ZIP záloha přihlašovací údaje neobsahuje.
- Jediné spojení ven: dotaz do veřejného rejstříku ARES (na vyžádání) a jednou denně dotaz na novou verzi na GitHubu
  (vypnutelné). Synchronizace e-shopu jen u zapnutého modulu Externí web.
