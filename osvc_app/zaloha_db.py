"""Noční záloha databáze SQLite (přechod na SQLite, krok S5b): konzistentní snímek za běhu přes zálohovací API SQLite
(ne kopírování souboru – u WAL by kopie mohla být nekonzistentní), kontrola integrity snímku a gzip.
Příkaz aplikace: flask zaloha-db SLOZKA → SLOZKA/osvc_RRRR-MM-DD_HH-MM-SS.sqlite3.gz (práva 600). Spouští skript noční zálohy.
Obnova ze snímku: služby zastavit, rozbalit (gunzip) na místo DB_PATH (s vlastníkem a právy původního souboru), služby spustit."""
import gzip
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from flask import current_app
from . import sqlite_db, zamky
from .db import engine, sqlite_path

PREFIX = 'osvc_'
PRIPONA = '.sqlite3.gz'


def vytvor(slozka, cas=None):
    """Snímek databáze do slozka/osvc_<čas>.sqlite3.gz; vrátí cestu. Nedokončený soubor nikdy nezůstane pod konečným jménem."""
    if engine() != 'sqlite': raise RuntimeError('Záloha snímku je jen pro DB_ENGINE=sqlite (MySQL zálohuje mysqldump).')
    zdroj = sqlite_path()
    if not zdroj.is_file(): raise FileNotFoundError(f'databáze {zdroj} neexistuje')
    slozka = Path(slozka); slozka.mkdir(parents=True, exist_ok=True)
    cil = slozka / f'{PREFIX}{(cas or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")}{PRIPONA}'
    if cil.exists(): raise FileExistsError(cil)
    with tempfile.TemporaryDirectory(dir=slozka, prefix='.zaloha-db-') as tmp:
        snimek = Path(tmp) / 'snimek.sqlite3'
        src = sqlite_db.otevri(zdroj)
        try:
            dst = sqlite3.connect(snimek)
            try: src.backup(dst, pages=1024)   # po částech – web a synchronizace mezitím běží dál
            finally: dst.close()
        finally: src.close()
        kontrola = sqlite_db.otevri(snimek)   # s porovnáním OSVC_CI (indexy textu)
        try:
            stav = kontrola.execute('PRAGMA integrity_check').fetchone()[0]
            verze = kontrola.execute('PRAGMA user_version').fetchone()[0]
            tabulek = kontrola.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
            kontrola.execute('PRAGMA journal_mode=DELETE')   # snímek jako samostatný soubor bez -wal
        finally: kontrola.close()
        if stav != 'ok': raise RuntimeError(f'kontrola integrity snímku: {stav}')
        if tabulek < 10: raise RuntimeError(f'snímek má jen {tabulek} tabulek')
        polotovar = Path(tmp) / (cil.name + '.part')
        fd = os.open(polotovar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as raw, gzip.GzipFile(filename='osvc.sqlite3', mode='wb', fileobj=raw, compresslevel=6) as gz, snimek.open('rb') as f:
            shutil.copyfileobj(f, gz, 1024 * 1024)
        with gzip.open(polotovar, 'rb') as test:   # dá se rozbalit celý
            while test.read(1024 * 1024): pass
        zamky.zapis_soubor(polotovar)
        zamky.nahrad(polotovar, cil)
    zamky.zapis_slozku(slozka)
    current_app.logger.info('záloha databáze: %s (schéma verze %s, %s tabulek)', cil.name, verze, tabulek)
    return cil


# Samostatná instalace (Windows, krok I4): zálohy dělá plánovač ve spouštěči do DATA_DIR/zalohy, jednou denně, posledních 30.
PONECHAT = 30
DENNE = timedelta(hours=24)


def seznam(slozka):
    """Hotové snímky (nejstarší první)."""
    slozka = Path(slozka)
    return sorted(p for p in slozka.glob(f'{PREFIX}*{PRIPONA}') if p.is_file()) if slozka.is_dir() else []


def uklid(slozka, ponechat=PONECHAT):
    """Smaže nejstarší snímky nad počet ponechat; vrátí smazané."""
    stare = seznam(slozka)[:-ponechat] if ponechat > 0 else []
    for p in stare: p.unlink(missing_ok=True)
    return stare


def je_cas(slozka, ted=None):
    """True, když poslední snímek je starší než den (nebo žádný není)."""
    s = seznam(slozka)
    return not s or (ted or datetime.now()) - datetime.fromtimestamp(s[-1].stat().st_mtime) >= DENNE


def stav_samostatne():
    """Stav automatických záloh samostatné instalace pro Nastavení → Záloha (stejný tvar jako zálohy serveru)."""
    from datetime import timezone
    s = seznam(current_app.config['OSVC_ZALOHY_DIR'])
    polozka = {'label': 'Denní záloha databáze', 'schedule': f'jednou denně, když aplikace běží; ponechá posledních {PONECHAT}',
               'state': 'unknown', 'at': None, 'next': None}
    if s:
        at = datetime.fromtimestamp(s[-1].stat().st_mtime, timezone.utc)
        polozka.update(at=at, state='old' if datetime.now(timezone.utc) - at > DENNE * 3 else 'ok')
    return [polozka]
