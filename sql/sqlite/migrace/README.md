# Úpravy struktury databáze SQLite (krok V1)

`NNN-popis.sql` = úprava na verzi struktury NNN (002, 003, …; základ `../schema.sql` je verze 1). Soubory se po vydání nikdy
nemění, jen přibývají. Aplikace je při startu provede sama: snímek DB do `<složka DB>/pred-upravou/`, všechny chybějící úpravy
v jedné transakci (`PRAGMA user_version` nastaví sama – do souboru ho nepiš), kontrola integrity; při chybě návrat ze snímku.
Nový sloupec s desetinným číslem: typ `DEC2`/`DEC3`/`DEC1` jako ve schema.sql (ukládá se jako celé číslo).
Nepoužívej `BEGIN`/`COMMIT` ani `VACUUM`.
