# Testy OSVČ

**Testy se spouštějí jen přes `bash tests/spust.sh` a pracují jen s testovací databází `osvc_test`.**
Nikdy s ostrou databází: účet `osvc_test` na ni nemá mít práva, `spust.sh` to před během ověří a `osvc_app/db.py`
odmítne jinou databázi, když je nastaveno `TESTING` nebo `OSVC_TEST`.

Příprava:
- složka testovacího prostředí `OSVC_TEST_DIR` se souborem `test.env` (`DB_HOST`, `DB_PORT`, `DB_NAME=osvc_test`,
  `DB_USER=osvc_test`, `DB_PASSWORD`); stav a doklady testů jsou v `$OSVC_TEST_DIR/{instance,uploads}`, logy v `$OSVC_TEST_DIR/vysledky/`;
- `OSVC_TEST_DIR` (a volitelně `OSVC_ZAKAZANE_ADRESY` – regulární výraz adres ostrých serverů; test, který je obsahuje,
  se odmítne) lze nastavit v prostředí nebo v souboru `tests/mistni.env` (mimo git);
- databáze `osvc_test` má stejnou strukturu jako ostrá (např. kopie ze zálohy), Python z `.venv` v kořeni repozitáře.

Použití: `bash tests/spust.sh` (všechny `tests/test_*.py`), `bash tests/spust.sh tests/test_x.py …`, `bash tests/spust.sh --jen-kontrola`.

Úložiště (přechod na SQLite): **výchozí je SQLite** – vzor `$OSVC_TEST_DIR/osvc_test-vzor.sqlite3` (jen pro čtení) vznikne převodem
z `osvc_test` (MySQL) a každý testovací soubor dostane vlastní čerstvou kopii v `$OSVC_TEST_DIR/beh/` (po úspěšném testu se smaže;
cesta je v `DB_PATH`, `osvc_app/db.py` v testech jiný soubor než v `$OSVC_TEST_DIR` nebo dočasné složce odmítne).
`--obnov-vzor` vytvoří vzor znovu, `--mysql` spustí testy proti MySQL `osvc_test` (do konce přechodu). Testy S1–S4 porovnávají
obě úložiště; `test_s3_prevod` a `test_s4_zapisy` mění `osvc_test` jen dočasně a vrátí ho (záloha mysqldump v `$OSVC_TEST_DIR/zalohy/`).
