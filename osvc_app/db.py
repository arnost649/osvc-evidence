import os
import tempfile
from pathlib import Path
import pymysql
from flask import current_app, g, has_app_context
from . import sqlite_db

# Úložiště (přechod na SQLite, S2–S7 dočasně obojí): DB_ENGINE=mysql (výchozí) nebo sqlite (soubor DB_PATH).
OperationalError = (pymysql.OperationalError, sqlite_db.OperationalError)
IntegrityError = (pymysql.err.IntegrityError, sqlite_db.IntegrityError)


def engine():
    return (current_app.config.get('DB_ENGINE') or 'mysql').lower()


def sqlite_path():
    """Soubor SQLite; v testech jen uvnitř $OSVC_TEST_DIR nebo dočasné složky (nikdy ostrý soubor)."""
    c=current_app.config
    path=Path(c.get('DB_PATH') or '').expanduser()
    if not c.get('DB_PATH'): raise RuntimeError('DB_ENGINE=sqlite potřebuje DB_PATH (soubor databáze).')
    if c.get('TESTING') or os.environ.get('OSVC_TEST'):
        povolene=[Path(tempfile.gettempdir()).resolve()]+([Path(os.environ['OSVC_TEST_DIR']).resolve()] if os.environ.get('OSVC_TEST_DIR') else [])
        if not any(path.resolve().is_relative_to(p) for p in povolene):
            raise RuntimeError('Testy smí pracovat jen s testovací kopií SQLite (v $OSVC_TEST_DIR nebo dočasné složce).')
    return path


def connection(autocommit=False):
    c=current_app.config
    if engine()=='sqlite':
        return sqlite_db.Connection(sqlite_path(),autocommit=autocommit)
    # Testy (TESTING nebo OSVC_TEST z tests/spust.sh) smí pracovat jen s testovací kopií, nikdy s ostrou DB.
    if (c.get('TESTING') or os.environ.get('OSVC_TEST')) and c.get('DB_NAME')!='osvc_test':
        raise RuntimeError('Testy smí pracovat jen s testovací databází osvc_test (spouštět přes tests/spust.sh).')
    return pymysql.connect(host=c['DB_HOST'], port=c['DB_PORT'], user=c['DB_USER'], password=c['DB_PASSWORD'], database=c['DB_NAME'], charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor, autocommit=autocommit)

def rok(year):
    """(od, do) pro podmínku „sloupec >= %s AND sloupec < %s“ – náhrada YEAR(sloupec)=rok, platí v MySQL i SQLite a využije index.
    Neplatný rok = prázdný rozsah (jako dřív YEAR(...)='nesmysl')."""
    try:
        y = int(str(year).strip())
        if not 1 <= y <= 9998: raise ValueError
    except (TypeError, ValueError):
        return ('9999-12-31', '9999-12-31')
    return (f'{y:04d}-01-01', f'{y + 1:04d}-01-01')

# query()/execute() sdílí jedno spojení na požadavek (uložené v flask.g, zavře se na konci požadavku – close_shared()).
# Spojení je v režimu autocommit: každý dotaz je samostatná transakce a vidí poslední potvrzená data.
# Explicitní transakce přes connection() (FOR UPDATE, commit/rollback) mají dál vlastní spojení – chování beze změny.
# DB_SHARE_CONNECTION=False (výchozí v testech, které podstrkují vlastní spojení s rollbackem) = nové spojení na každý dotaz.
def _shared():
    if not has_app_context() or not current_app.config.get('DB_SHARE_CONNECTION'):
        return None
    conn=g.get('_osvc_db')
    if conn is None:
        conn=g._osvc_db=connection(autocommit=True)
    return conn

def _drop_shared(conn):
    if g.get('_osvc_db') is conn:
        g.pop('_osvc_db', None)
    try: conn.close()
    except Exception: pass

def close_shared(exc=None):
    conn=g.pop('_osvc_db', None) if has_app_context() else None
    if conn is not None:
        try: conn.close()
        except Exception: pass

def query(sql, params=(), one=False):
    conn=_shared()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params); return cur.fetchone() if one else cur.fetchall()
        except OperationalError:
            _drop_shared(conn); raise   # přerušené spojení se nepoužije znovu
    conn=connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params); result=cur.fetchone() if one else cur.fetchall()
        return result
    finally: conn.close()

def execute(sql, params=()):
    conn=_shared()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params); return cur.lastrowid
        except OperationalError:
            _drop_shared(conn); raise
    conn=connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params); ident=cur.lastrowid
        conn.commit(); return ident
    except: conn.rollback(); raise
    finally: conn.close()


def roky_zaznamu(zdroje, navic=()):
    """Roky, ve kterých jsou záznamy, sestupně – pro výběr roku v záhlaví seznamu. zdroje = [(tabulka, sloupec_data, podmínka, parametry)].
    SUBSTR(datum,1,4) funguje pro DATE v MySQL i pro text v SQLite. navic = rok vždy v nabídce (aktuální, zvolený)."""
    vysledek = set()
    for tabulka, sloupec, podminka, parametry in zdroje:
        for r in query(f'SELECT DISTINCT SUBSTR({sloupec},1,4) y FROM {tabulka} WHERE {podminka}', parametry):
            try: vysledek.add(int(r['y']))
            except (TypeError, ValueError): pass
    for y in navic:
        try:
            y = int(str(y).strip())
            if 1 <= y <= 9998: vysledek.add(y)
        except (TypeError, ValueError): pass
    return sorted(vysledek, reverse=True)
