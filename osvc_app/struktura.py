"""Verze struktury databáze SQLite a její bezpečná úprava při startu nové verze aplikace (krok V1).

- Verze struktury = PRAGMA user_version. Základ je sql/sqlite/schema.sql (verze 1); každá další úprava je soubor
  sql/sqlite/migrace/NNN-popis.sql (NNN = cílová verze, 002, 003, …). Soubory se po vydání nemění, jen přibývají.
- Při startu (web, plánovač, spouštěč): je-li databáze starší než aplikace → výhradní zámek dat → snímek databáze do
  <složka DB>/pred-upravou/ → všechny chybějící úpravy v jedné transakci → kontrola integrity a cizích klíčů.
  Při jakékoli chybě se databáze vrátí ze snímku (zálohovací API SQLite) a aplikace se nespustí s chybou UpravaSelhala.
- Databáze novější než aplikace (návrat ke starší verzi programu) = nic se nemění, aplikace se nespustí (NovejsiDatabaze).
"""
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from . import sqlite_db

MIGRACE = Path(__file__).resolve().parent.parent / 'sql' / 'sqlite' / 'migrace'
ZAKLAD = 1
PONECHAT_SNIMKU = 10
log = logging.getLogger('osvc.struktura')


class NovejsiDatabaze(RuntimeError):
    pass


class UpravaSelhala(RuntimeError):
    pass


def migrace(slozka=None):
    """[(verze, cesta)] seřazené; kontroluje souvislou řadu 002, 003, …"""
    slozka = Path(slozka or MIGRACE)
    seznam = sorted((int(m.group(1)), p) for p in slozka.glob('*.sql') if (m := re.match(r'(\d{3})-[\w-]+\.sql$', p.name))) if slozka.is_dir() else []
    for i, (verze, p) in enumerate(seznam):
        if verze != ZAKLAD + 1 + i: raise UpravaSelhala(f'úpravy struktury netvoří souvislou řadu: {p.name}')
    return seznam


def cilova(slozka=None):
    m = migrace(slozka)
    return m[-1][0] if m else ZAKLAD


def verze_db(cesta):
    conn = sqlite3.connect(str(cesta))   # volá se jen pro existující soubor
    try: return conn.execute('PRAGMA user_version').fetchone()[0]
    finally: conn.close()


def _prikazy(text):
    """SQL skript → jednotlivé příkazy (executescript by uprostřed transakce potvrzoval)."""
    prikazy, kus = [], ''
    for radek in text.splitlines(keepends=True):
        if not kus and radek.strip().startswith('--'): continue
        kus += radek
        if sqlite3.complete_statement(kus):
            if kus.strip(): prikazy.append(kus.strip())
            kus = ''
    if kus.strip(): raise UpravaSelhala('nedokončený příkaz na konci souboru úprav')
    return prikazy


def proved(conn, od, slozka=None):
    """Provede úpravy nad verzi od na otevřeném spojení (sqlite3, autocommit). Vrátí novou verzi. Bez zálohy – volá uprav()/zaloz()."""
    cil = od
    conn.execute('BEGIN IMMEDIATE')
    try:
        for verze, p in migrace(slozka):
            if verze <= od: continue
            for prikaz in _prikazy(p.read_text(encoding='utf-8')): conn.execute(prikaz)
            conn.execute(f'PRAGMA user_version = {int(verze)}'); cil = verze
        problem = conn.execute('PRAGMA foreign_key_check').fetchone()
        if problem: raise UpravaSelhala(f'po úpravě neplatný cizí klíč v tabulce {problem[0]}')
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK'); raise
    return cil


def _snimek(cesta, slozka, od, do):
    slozka.mkdir(parents=True, exist_ok=True)
    cil = slozka / f'osvc_pred-upravou_v{od}-na-v{do}_{datetime.now():%Y-%m-%d_%H-%M-%S}.sqlite3'
    src = sqlite_db.otevri(cesta); dst = sqlite3.connect(cil)
    try: src.backup(dst)
    finally: dst.close(); src.close()
    kontrola = sqlite_db.otevri(cil)   # s porovnáním OSVC_CI (indexy textu)
    try:
        if kontrola.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise UpravaSelhala('snímek před úpravou je poškozený')
        if kontrola.execute('PRAGMA user_version').fetchone()[0] != od: raise UpravaSelhala('snímek před úpravou nesedí')
    finally: kontrola.close()
    for stary in sorted(slozka.glob('osvc_pred-upravou_*.sqlite3'))[:-PONECHAT_SNIMKU]: stary.unlink(missing_ok=True)
    return cil


def _obnov(cesta, snimek):
    src = sqlite3.connect(snimek); dst = sqlite_db.otevri(cesta)
    try: src.backup(dst)
    finally: src.close(); dst.close()


def uprav(cesta, slozka_migraci=None, slozka_snimku=None, selhani=None):
    """Upraví databázi na verzi aplikace. Vrátí (od, do, snímek nebo None). Volat pod výhradním zámkem dat.
    selhani: jen pro testy – funkce volaná po úpravách (vyhodí-li chybu, musí proběhnout návrat ze snímku)."""
    cesta = Path(cesta); cil = cilova(slozka_migraci); od = verze_db(cesta)
    if od > cil:
        raise NovejsiDatabaze(f'databáze má verzi struktury {od}, tato verze aplikace zná nejvýš {cil} – spusťte novější verzi aplikace')
    if od == cil: return od, od, None
    snimek = _snimek(cesta, Path(slozka_snimku or cesta.parent / 'pred-upravou'), od, cil)
    log.warning('úprava struktury databáze z verze %s na %s (snímek %s)', od, cil, snimek.name)
    conn = sqlite_db.otevri(cesta)
    try:
        proved(conn, od, slozka_migraci)
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise UpravaSelhala('kontrola integrity po úpravě selhala')
        if selhani: selhani()
    except Exception as exc:
        conn.close()
        try: _obnov(cesta, snimek)
        except Exception as chyba_obnovy:
            raise UpravaSelhala(f'úprava selhala ({exc}) a návrat ze snímku také ({chyba_obnovy}) – databázi obnovte ručně ze {snimek}') from exc
        log.error('úprava struktury selhala (%s: %s) – databáze vrácena ze snímku %s', type(exc).__name__, exc, snimek.name)
        raise UpravaSelhala(f'úprava struktury databáze selhala ({exc}); data jsou vrácená do stavu před úpravou') from exc
    else:
        conn.close()
    with sqlite_db._zamek: sqlite_db._meritka_cache.pop(str(cesta), None)   # nové sloupce DEC → nová měřítka
    log.warning('struktura databáze upravena na verzi %s', cil)
    return od, cil, snimek


def pri_startu(app):
    """Volá create_app (mimo testy): u SQLite upraví strukturu, chyby nechá projít – aplikace se pak nespustí."""
    from .db import engine, sqlite_path
    from .backup import data_lock
    with app.app_context():
        if engine() != 'sqlite': return None
        cesta = sqlite_path()
        if not cesta.exists(): return None
        try:
            if verze_db(cesta) == cilova(app.config.get('OSVC_MIGRACE_DIR')): return None   # běžný start: jen přečíst číslo
        except sqlite3.Error:
            return None
        with data_lock(exclusive=True):   # web, plánovač a obnova ZIP mezitím čekají
            return uprav(cesta, app.config.get('OSVC_MIGRACE_DIR'))
