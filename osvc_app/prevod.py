"""Převod dat OSVČ mezi MySQL a SQLite a srovnávací přehled (přechod na SQLite, krok S3).

- mysql_do_sqlite(cil): nový soubor SQLite ze schématu, všechny tabulky se stejnými id, čítače id (AUTO_INCREMENT) převzaté.
- sqlite_do_mysql(zdroj): cesta zpět ve zkušebním provozu – obsah MySQL nahradí daty ze SQLite v jedné transakci (i záznamy zapsané po převodu).
- porovnej(a, b): počty záznamů, otisk obsahu každé tabulky, součty desetinných sloupců po letech na haléř, výsledky Ročního přehledu.
Příkazy aplikace: flask prevod-do-sqlite / prevod-do-mysql / prevod-porovnej (viz __init__.py). Nic nemaže soubory, MySQL mění jen
sqlite_do_mysql (a to jen tabulky OSVČ v nastavené databázi).
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import pymysql
from flask import current_app
from . import sqlite_db

# sloupec s datem, podle kterého se součty dělí po letech (ostatní tabulky jen celkem)
ROK_SLOUPEC = {'payments': 'payment_date', 'trips': 'trip_date', 'fuel_purchases': 'purchase_date', 'documents': 'issue_date',
               'bank_transactions': 'booking_date', 'business_events': 'event_date'}


def _mysql(autocommit=False):
    import os
    c = current_app.config
    if (c.get('TESTING') or os.environ.get('OSVC_TEST')) and c.get('DB_NAME') != 'osvc_test':
        raise RuntimeError('Testy smí převádět jen testovací databázi osvc_test.')
    return pymysql.connect(host=c['DB_HOST'], port=c['DB_PORT'], user=c['DB_USER'], password=c['DB_PASSWORD'], database=c['DB_NAME'],
                           charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor, autocommit=autocommit)


def _tabulky_sqlite(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _sloupce_sqlite(conn, t):
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]


def _sloupce_mysql(cur, t):
    cur.execute('SELECT column_name c FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s ORDER BY ordinal_position', (t,))
    return [r['c'] for r in cur.fetchall()]


def _kontrola_struktury(cur, lite):
    """Stejné tabulky a sloupce v obou databázích, jinak ValueError (nic se nepřevede)."""
    cur.execute("SELECT table_name t FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE' ORDER BY table_name")
    tm = [r['t'] for r in cur.fetchall()]
    tl = _tabulky_sqlite(lite)
    if tm != tl: raise ValueError(f'Různé tabulky – MySQL navíc: {sorted(set(tm) - set(tl))}, SQLite navíc: {sorted(set(tl) - set(tm))}')
    for t in tm:
        a, b = _sloupce_mysql(cur, t), _sloupce_sqlite(lite, t)
        if a != b: raise ValueError(f'Tabulka {t}: různé sloupce (MySQL {a} × SQLite {b})')
    return tm


def mysql_do_sqlite(cil, vypis=print):
    """MySQL (nastavená v aplikaci) → nový soubor SQLite. Vrátí počty záznamů po tabulkách."""
    cil = Path(cil)
    sqlite_db.zaloz(cil)   # FileExistsError, když soubor už existuje – nikdy nepřepisuje
    m = _mysql()
    s = sqlite_db.Connection(cil, autocommit=True)
    pocty = {}
    try:
        with m.cursor() as cur:
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')   # jeden konzistentní stav celé DB
            tabulky = _kontrola_struktury(cur, s._conn)
            s._conn.execute('PRAGMA foreign_keys=OFF'); s.begin()
            with s.cursor() as sc:
                for t in tabulky:
                    cur.execute(f'SELECT * FROM `{t}`'); rows = cur.fetchall()
                    if rows:
                        cols = list(rows[0])
                        sql = f'INSERT INTO {t} (' + ','.join(cols) + ') VALUES (' + ','.join(['%s'] * len(cols)) + ')'
                        for r in rows: sc.execute(sql, [r[c] for c in cols])
                    pocty[t] = len(rows)
                # MySQL 8 drží AUTO_INCREMENT v information_schema v mezipaměti (až 24 h) → číst živou hodnotu
                cur.execute('SET SESSION information_schema_stats_expiry=0')
                cur.execute('SELECT table_name t, auto_increment a FROM information_schema.tables WHERE table_schema=DATABASE() AND auto_increment IS NOT NULL')
                for r in cur.fetchall():   # další id jako v MySQL (smazaná id se znovu nepoužijí); sqlite_sequence nemá jedinečný klíč → UPDATE, jinak INSERT
                    seq = int(r['a']) - 1
                    if not s._conn.execute('UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name=?', (seq, r['t'])).rowcount:
                        s._conn.execute('INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)', (r['t'], seq))
            s.commit()
            m.rollback()
        vadne = s._conn.execute('PRAGMA foreign_key_check').fetchall()
        if vadne: raise ValueError(f'porušené cizí klíče v převedených datech: {vadne[:5]}')
        stav = s._conn.execute('PRAGMA integrity_check').fetchone()[0]
        if stav != 'ok': raise ValueError(f'kontrola integrity SQLite: {stav}')
        s._conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    except BaseException:
        s.close(); m.close()
        for p in (cil, Path(str(cil) + '-wal'), Path(str(cil) + '-shm')): p.unlink(missing_ok=True)   # nedokončený soubor pryč
        raise
    s.close(); m.close()
    vypis(f'Převedeno do {cil}: {sum(pocty.values())} záznamů ve {len(pocty)} tabulkách.')
    return pocty


def sqlite_do_mysql(zdroj, vypis=print):
    """Soubor SQLite → MySQL (nastavená v aplikaci): obsah tabulek OSVČ nahradí v jedné transakci. Vrátí počty záznamů."""
    s = sqlite_db.Connection(zdroj, autocommit=True)
    m = _mysql()
    pocty = {}
    try:
        stav = s._conn.execute('PRAGMA integrity_check').fetchone()[0]
        if stav != 'ok': raise ValueError(f'kontrola integrity SQLite: {stav}')
        with m.cursor() as cur:
            tabulky = _kontrola_struktury(cur, s._conn)
            data = {}
            with s.cursor() as sc:
                for t in tabulky:
                    sc.execute(f'SELECT * FROM {t}'); data[t] = sc.fetchall()
            m.begin()
            cur.execute('SET FOREIGN_KEY_CHECKS=0')
            for t in tabulky: cur.execute(f'DELETE FROM `{t}`')
            for t in tabulky:
                rows = data[t]
                if rows:
                    cols = list(rows[0])
                    cur.executemany(f'INSERT INTO `{t}` (' + ','.join(f'`{c}`' for c in cols) + ') VALUES (' + ','.join(['%s'] * len(cols)) + ')',
                                    [[_do_mysql(r[c]) for c in cols] for r in rows])
                pocty[t] = len(rows)
            cur.execute('SET FOREIGN_KEY_CHECKS=1')
            m.commit()
            seq = dict(s._conn.execute('SELECT name, seq FROM sqlite_sequence').fetchall())
            for t, n in seq.items():   # ALTER TABLE potvrzuje transakci sám → až po commitu dat
                if t in pocty: cur.execute(f'ALTER TABLE `{t}` AUTO_INCREMENT = {int(n) + 1}')
    except BaseException:
        try: m.rollback()
        except Exception: pass
        raise
    finally:
        s.close(); m.close()
    vypis(f'Převedeno zpět do MySQL ({current_app.config["DB_NAME"]}): {sum(pocty.values())} záznamů ve {len(pocty)} tabulkách.')
    return pocty


def _do_mysql(v):
    return v


def porovnej_databaze(cesta, vypis=print, jen_rozdily=True):
    """MySQL nastavená v aplikaci × soubor SQLite: vypíše přehled, vrátí (řádky, vše sedí)."""
    from .db import query, engine
    from . import create_app
    if engine() != 'mysql': raise RuntimeError('Porovnání se spouští s aplikací nastavenou na MySQL (DB_ENGINE=mysql).')
    a = souhrn(query)
    roky = sorted({int(k.rsplit(' ', 1)[1]) for k in a['soucty'] if k.startswith('payments.amount ')})
    a['rocni'] = rocni_prehled(roky)
    nastaveni = {'DB_ENGINE': 'sqlite', 'DB_PATH': str(cesta)}
    for k in ('TESTING', 'MODULY_SETTINGS_FILE', 'THEME_SETTINGS_FILE', 'DATA_STATE_DIR'):
        if current_app.config.get(k) is not None: nastaveni[k] = current_app.config[k]
    lite = create_app(nastaveni)
    with lite.app_context():
        b = souhrn(query); b['rocni'] = rocni_prehled(roky)
    radky, ok = porovnej(a, b)
    vypis(f'Srovnání MySQL ({current_app.config["DB_NAME"]}) × SQLite ({cesta}); roky Ročního přehledu: {", ".join(map(str, roky)) or "–"}')
    vypis_prehled(radky, ok, vypis, jen_rozdily=jen_rozdily)
    return radky, ok


# --- srovnávací přehled ---------------------------------------------------------------------------------------------------
def _norm(v):
    """Hodnota v jednotném tvaru pro otisk (stejná v MySQL i SQLite)."""
    if v is None: return None
    if isinstance(v, (bytes, bytearray)): v = v.decode()
    if isinstance(v, Decimal): return format(v.normalize(), 'f') if v == v.to_integral() else format(v.normalize(), 'f')
    if isinstance(v, datetime): return v.replace(tzinfo=None, microsecond=0).isoformat(' ')
    if isinstance(v, date): return v.isoformat()
    if isinstance(v, str) and v[:1] in '{[':
        try: return json.dumps(json.loads(v), sort_keys=True, ensure_ascii=False)
        except ValueError: return v
    if isinstance(v, bool): return int(v)
    return v


def souhrn(query, roky=None):
    """Souhrn databáze přes funkci query() dané aplikace: počty, otisky tabulek, součty desetinných sloupců (celkem a po letech)."""
    from .db import engine
    if engine() == 'sqlite':
        tabulky = [r['name'] for r in query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%%' ORDER BY name")]
        desetinne = {}
        for t in tabulky:
            for c in query(f'SELECT name, type FROM pragma_table_info(%s)', (t,)):
                if (c['type'] or '').upper().startswith('DEC'): desetinne.setdefault(t, []).append(c['name'])
    else:
        tabulky = [r['t'] for r in query("SELECT table_name t FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE' ORDER BY table_name")]
        desetinne = {}
        for r in query("SELECT table_name t, column_name c FROM information_schema.columns WHERE table_schema=DATABASE() AND data_type='decimal' ORDER BY table_name, ordinal_position"):
            desetinne.setdefault(r['t'], []).append(r['c'])
    out = {'pocty': {}, 'otisky': {}, 'soucty': {}}
    for t in tabulky:
        rows = query(f'SELECT * FROM {t}')
        out['pocty'][t] = len(rows)
        radky = sorted(json.dumps([[k, _norm(v)] for k, v in r.items()], ensure_ascii=False, default=str) for r in rows)
        out['otisky'][t] = hashlib.sha256('\n'.join(radky).encode()).hexdigest()[:16]
        for c in desetinne.get(t, []):
            out['soucty'][f'{t}.{c}'] = sum((r[c] for r in rows if r[c] is not None), Decimal(0))
            if t in ROK_SLOUPEC:
                po_letech = {}
                for r in rows:
                    d = r[ROK_SLOUPEC[t]]
                    if r[c] is not None and d is not None: po_letech[d.year] = po_letech.get(d.year, Decimal(0)) + r[c]
                for y, s in po_letech.items(): out['soucty'][f'{t}.{c} {y}'] = s
    return out


def rocni_prehled(roky):
    """Hodnoty Ročního přehledu (příjmy, výdaje, výsledek, základ, pojistné) pro roky – v kontextu aktuální aplikace."""
    from .annual import year_report
    out = {}
    for y in roky:
        *_, rep = year_report(y)
        for s in rep['sections']:
            for f in s['fields']:
                if f['unit'] == 'Kč' and f['field_key'] in ('income', 'expenses', 'result', 'base', 'assessment', 'premium', 'balance'):
                    out[f'{y} {s["key"]}.{f["field_key"]}'] = f['value']
    return out


def porovnej(a, b, nazvy=('MySQL', 'SQLite')):
    """Řádky přehledu [(položka, a, b, OK/ROZDÍL)] a celkový výsledek (True = vše sedí)."""
    radky, ok = [], True
    for skupina in ('pocty', 'otisky', 'soucty', 'rocni'):
        klice = sorted(set(a.get(skupina, {})) | set(b.get(skupina, {})), key=str)
        for k in klice:
            va, vb = a.get(skupina, {}).get(k), b.get(skupina, {}).get(k)
            shoda = va == vb
            ok &= shoda
            radky.append((f'{skupina}: {k}', va, vb, 'OK' if shoda else 'ROZDÍL'))
    return radky, ok


def vypis_prehled(radky, ok, vypis=print, jen_rozdily=False, nazvy=('MySQL', 'SQLite')):
    skupiny = {}
    for polozka, va, vb, stav in radky: skupiny.setdefault(polozka.split(':')[0], []).append(stav)
    for s, stavy in skupiny.items():
        vypis(f'{s:7} {len(stavy):4} položek · {stavy.count("OK")} OK · {stavy.count("ROZDÍL")} rozdílů')
    for polozka, va, vb, stav in radky:   # počty a Roční přehled vždy, ostatní jen při rozdílu (nebo vše s jen_rozdily=False)
        if stav != 'OK' or not jen_rozdily or polozka.startswith(('pocty', 'rocni')):
            vypis(f'  {stav:6} {polozka}: {nazvy[0]} {va} · {nazvy[1]} {vb}')
    vypis('VÝSLEDEK: VŠE SEDÍ' if ok else 'VÝSLEDEK: ROZDÍLY – převod neschvalovat')
