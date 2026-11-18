#!/bin/bash
# Spouštění testů OSVČ – JEN proti testovací kopii DB osvc_test (nikdy proti ostré databázi).
#   bash tests/spust.sh                    všechny tests/test_*.py
#   bash tests/spust.sh tests/test_x.py …  vybrané testy
#   bash tests/spust.sh --jen-kontrola     jen ověří izolaci testovací DB
#   bash tests/spust.sh --mysql …          testy proti MySQL osvc_test (do konce přechodu na SQLite); výchozí je SQLite
#   bash tests/spust.sh --obnov-vzor …     vzor SQLite znovu z osvc_test (MySQL) před během
#   bash tests/spust.sh --ci …             GitHub Actions (V5): bez MySQL a bez test.env – vzor = prázdná DB ze schématu,
#                                          testy ze seznamu tests/ci.txt (soubory, které si data zakládají samy)
# SQLite (S4): vzor $OSVC_TEST_DIR/osvc_test-vzor.sqlite3 (jen čtení, vzniká převodem z osvc_test); každý testovací soubor dostane
# vlastní čerstvou kopii v $OSVC_TEST_DIR/beh/ (po úspěšném testu se smaže) → testy se neovlivňují a nezanechají stopy.
# Ochrany: (1) nastavení jen z $OSVC_TEST_DIR/test.env (DB_NAME=osvc_test, uživatel osvc_test),
# (2) před spuštěním ověří, že DB účet vidí JEN databázi osvc_test, (3) neběží jako root (ten by mohl načíst ostré app.env),
# (4) osvc_app/db.py odmítne spojení s jinou DB, když je nastaveno OSVC_TEST/TESTING,
# (5) test obsahující adresu ostrého serveru (OSVC_ZAKAZANE_ADRESY, regulární výraz) se nespustí.
# OSVC_TEST_DIR a OSVC_ZAKAZANE_ADRESY: z prostředí, nebo ze souboru tests/mistni.env (mimo git).
set -uo pipefail
ENGINE=sqlite; OBNOV_VZOR=0; CI=0
while [ $# -gt 0 ]; do case "$1" in --mysql) ENGINE=mysql; shift;; --sqlite) ENGINE=sqlite; shift;; --obnov-vzor) OBNOV_VZOR=1; shift;; --ci) CI=1; shift;; *) break;; esac; done
REPO=$(cd "$(dirname "$0")/.." && pwd)
[ -r "$REPO/tests/mistni.env" ] && { set -a; . "$REPO/tests/mistni.env"; set +a; }
if [ "$CI" = 1 ]; then OSVC_TEST_DIR=${OSVC_TEST_DIR:-$(mktemp -d)}; fi
TESTDIR=${OSVC_TEST_DIR:-}
[ -n "$TESTDIR" ] || { echo "CHYBA: nastav OSVC_TEST_DIR (složka testovacího prostředí s test.env), viz tests/README.md." >&2; exit 2; }
ENVFILE=$TESTDIR/test.env
PY=${OSVC_PYTHON:-$REPO/.venv/bin/python}
[ "$(id -u)" != 0 ] || { echo "CHYBA: testy nespouštěj jako root (spusť jako běžný uživatel ze skupiny projekty)." >&2; exit 2; }
if [ "$CI" = 1 ]; then
  ENGINE=sqlite; export SECRET_KEY=ci-jen-pro-testy DB_NAME=osvc_test
else
[ -r "$ENVFILE" ] || { echo "CHYBA: chybí $ENVFILE (viz tests/README.md)." >&2; exit 2; }

set -a; . "$ENVFILE"; set +a          # hodnoty se nevypisují
[ "${DB_NAME:-}" = osvc_test ] && [ "${DB_USER:-}" = osvc_test ] || { echo "CHYBA: test.env neukazuje na osvc_test." >&2; exit 2; }
fi
# Testy se přihlašují jako osvc/osvc (jen testovací údaje, nejsou tajné; ostré přihlášení je v app.env a sem se nenačítá).
export APP_USER=osvc
APP_PASSWORD_HASH=$("$PY" -c 'from werkzeug.security import generate_password_hash as g;print(g("osvc"))'); export APP_PASSWORD_HASH
export OSVC_TEST=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export DATA_STATE_DIR=$TESTDIR/instance UPLOAD_FOLDER=$TESTDIR/uploads THEME_SETTINGS_FILE=$TESTDIR/instance/appearance.json
export PYTHONPATH=$REPO:$REPO/tests OSVC_TEST_DIR=$TESTDIR
mkdir -p "$DATA_STATE_DIR" "$UPLOAD_FOLDER"

[ "$CI" = 1 ] || "$PY" - <<'EOF' || { echo "CHYBA: kontrola izolace testovací DB neprošla – nic nespouštím." >&2; exit 2; }
import os, pymysql
c = pymysql.connect(host=os.environ.get('DB_HOST') or 'localhost', port=int(os.environ.get('DB_PORT') or 3306),
                    user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'], database=os.environ['DB_NAME'])
cur = c.cursor()
cur.execute('SELECT DATABASE()'); assert cur.fetchone()[0] == 'osvc_test', 'jiná databáze'
cur.execute('SHOW DATABASES'); visible = {r[0] for r in cur.fetchall()} - {'information_schema', 'performance_schema'}
assert visible == {'osvc_test'}, 'účet vidí i jiné databáze: %d' % len(visible)
print('Izolace OK: účet osvc_test vidí jen databázi osvc_test.')
EOF

[ "${1:-}" = --jen-kontrola ] && exit 0

VZOR=$TESTDIR/osvc_test-vzor.sqlite3
if [ "$CI" = 1 ]; then   # vždy nová prázdná databáze ze schématu (nikdy vzor s daty z osvc_test)
  VZOR=$TESTDIR/ci-prazdna-$$.sqlite3; rm -f "$VZOR"
  "$PY" -c 'import sys; from osvc_app import sqlite_db; sqlite_db.zaloz(sys.argv[1], zakladni_data=True)' "$VZOR" || exit 2
  chmod 444 "$VZOR"; echo "Vzor SQLite: prázdná databáze ze schématu (CI)"
fi
if [ "$ENGINE" = sqlite ]; then
  if [ "$OBNOV_VZOR" = 1 ] || [ ! -s "$VZOR" ]; then
    rm -f "$VZOR.novy"
    "$PY" - "$VZOR.novy" <<'EOF' || { echo "CHYBA: vzor SQLite z osvc_test nevznikl – nic nespouštím." >&2; rm -f "$VZOR.novy"; exit 2; }
import sys
from osvc_app import create_app, prevod
app = create_app({'TESTING': True, 'DB_ENGINE': 'mysql'})
with app.app_context():
    prevod.mysql_do_sqlite(sys.argv[1], vypis=lambda *_: None)
    _, ok = prevod.porovnej_databaze(sys.argv[1], vypis=lambda *_: None)
assert ok, 'vzor se liší od osvc_test'
EOF
    chmod 444 "$VZOR.novy"; mv -f "$VZOR.novy" "$VZOR"; echo "Vzor SQLite obnoven z osvc_test: $VZOR"
  fi
  BEH=$TESTDIR/beh; mkdir -p "$BEH"
  echo "Úložiště testů: SQLite (kopie vzoru pro každý soubor)"
else
  echo "Úložiště testů: MySQL osvc_test"
fi
export DB_ENGINE=$ENGINE
if [ $# -gt 0 ]; then TESTS=("$@"); elif [ "$CI" = 1 ]; then mapfile -t TESTS < <(grep -v '^\s*\(#\|$\)' "$REPO/tests/ci.txt" | sed "s#^#$REPO/tests/#"); else TESTS=("$REPO"/tests/test_*.py); fi
STAMP=$(date +%Y%m%d-%H%M%S); LOGS=$TESTDIR/vysledky/$STAMP; mkdir -p "$LOGS"
ok=0; bad=0; skip=0
cd "$REPO"
for t in "${TESTS[@]}"; do
  name=$(basename "$t")
  case "$name" in
    *.cjs) echo "PŘESKOČENO $name – prohlížečové testy se tímto skriptem nespouštějí"; skip=$((skip+1)); continue;;
    *.py) ;;
    *) echo "PŘESKOČENO $name – neznámý typ"; skip=$((skip+1)); continue;;
  esac
  if [ -n "${OSVC_ZAKAZANE_ADRESY:-}" ] && grep -qE "$OSVC_ZAKAZANE_ADRESY" "$t"; then
    echo "ODMÍTNUTO  $name – obsahuje adresu ostrého serveru"; skip=$((skip+1)); continue
  fi
  if [ "$ENGINE" = sqlite ]; then
    export DB_PATH=$BEH/$STAMP-${name%.py}.sqlite3
    install -m 600 "$VZOR" "$DB_PATH"
  fi
  if timeout 300 "$PY" - < "$t" > "$LOGS/$name.log" 2>&1; then
    echo "OK         $name"; ok=$((ok+1))
    [ "$ENGINE" = sqlite ] && rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
  else
    echo "CHYBA      $name   (log: $LOGS/$name.log)"; bad=$((bad+1))
    if [ "$CI" = 1 ]; then echo "----- konec logu $name -----"; tail -n 60 "$LOGS/$name.log"; echo "-----"; fi   # v CI se log jinak ztratí
  fi
done
echo "Výsledek: OK $ok · CHYBA $bad · přeskočeno $skip · logy $LOGS"
[ "$bad" = 0 ]
