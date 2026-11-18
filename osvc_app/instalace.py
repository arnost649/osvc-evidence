"""Samostatná instalace OSVČ (krok I1): Windows (.exe) a Linux (.deb). Jeden soubor nastavení a jedna složka dat.

Soubor nastavení (formát KLÍČ=hodnota, cestu dává proměnná OSVC_CONFIG), např.:
    DATA_DIR=/var/lib/osvc-evidence      # složka dat (databáze, doklady, stav)
    HOST=127.0.0.1                        # na čem spouštěč poslouchá (127.0.0.1 = jen tento počítač)
    PORT=8080
Ze složky dat se odvodí: DATA_DIR/osvc.sqlite3 (DB, SQLite), DATA_DIR/uploads (doklady), DATA_DIR/instance (stav, nastavení modulů
a vzhledu). Tajný klíč aplikace vznikne při prvním spuštění v DATA_DIR/instance/secret_key (práva 600) – v souboru nastavení není.
Na serveru (bez OSVC_CONFIG) se nic z toho nepoužije.
"""
import os
import secrets
from pathlib import Path
from dotenv import dotenv_values

VYCHOZI_PORT = 8080
VYCHOZI_HOST = '127.0.0.1'


def nacti(cesta):
    """Hodnoty ze souboru nastavení (bez proměnných prostředí)."""
    cesta = Path(cesta)
    if not cesta.is_file(): raise FileNotFoundError(f'Soubor nastavení {cesta} neexistuje.')
    hodnoty = {k: (v or '').strip() for k, v in dotenv_values(cesta).items()}
    if not hodnoty.get('DATA_DIR'): raise ValueError(f'V souboru nastavení {cesta} chybí DATA_DIR (složka dat).')
    port = hodnoty.get('PORT') or str(VYCHOZI_PORT)
    if not port.isdigit() or not 1 <= int(port) <= 65535: raise ValueError(f'Neplatný port: {port}')
    hodnoty['PORT'] = int(port); hodnoty['HOST'] = hodnoty.get('HOST') or VYCHOZI_HOST
    return hodnoty


def slozky(hodnoty):
    data = Path(hodnoty['DATA_DIR']).expanduser()
    return {'data': data, 'db': Path(hodnoty.get('DB_PATH') or data / 'osvc.sqlite3'), 'uploads': data / 'uploads',
            'instance': data / 'instance', 'klic': data / 'instance' / 'secret_key', 'zalohy': data / 'zalohy', 'logy': data / 'logy'}


def tajny_klic(cesta):
    """Tajný klíč ze souboru; při prvním spuštění se vygeneruje (práva 600)."""
    cesta = Path(cesta)
    if not cesta.exists():
        cesta.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(cesta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(secrets.token_hex(32))
    klic = cesta.read_text(encoding='utf-8').strip()
    if len(klic) < 32: raise ValueError(f'Tajný klíč v {cesta} je příliš krátký.')
    return klic


def priprav(hodnoty):
    """Složky dat, tajný klíč a databáze (při prvním spuštění prázdná s výchozími daty). Vrátí cesty."""
    from .sqlite_db import zaloz
    s = slozky(hodnoty)
    program = Path(__file__).resolve().parent.parent
    if s['data'].resolve() == program or program in s['data'].resolve().parents:   # V3: odinstalace/aktualizace by data smazala
        raise ValueError(f'Složka dat {s["data"]} nesmí být ve složce programu {program}.')
    for k in ('data', 'uploads', 'instance'): s[k].mkdir(mode=0o700, parents=True, exist_ok=True)
    tajny_klic(s['klic'])
    if not s['db'].exists(): zaloz(s['db'], zakladni_data=True)
    return s


def nastaveni_aplikace(cesta):
    """Nastavení Flasku odvozené ze souboru nastavení (doplní create_app přes OSVC_CONFIG)."""
    hodnoty = nacti(cesta); s = slozky(hodnoty)
    conf = {'DB_ENGINE': 'sqlite', 'DB_PATH': str(s['db']), 'UPLOAD_FOLDER': str(s['uploads']), 'DATA_STATE_DIR': str(s['instance']),
            'THEME_SETTINGS_FILE': str(s['instance'] / 'appearance.json'), 'OSVC_HOST': hodnoty['HOST'], 'OSVC_PORT': hodnoty['PORT'],
            'OSVC_SAMOSTATNA': True, 'OSVC_ZALOHY_DIR': str(s['zalohy']),
            'SYSTEM_SHUTDOWN_ENABLED': False, 'OSVC_WINDOWS': os.name == 'nt',            # vypnout počítač z aplikace jde jen na serveru
            'INCOME_SYNC_SCHEDULER': 'spoustec-15min'}   # plánovač synchronizace a záloh běží ve spouštěči (I4)
    if s['klic'].exists(): conf['SECRET_KEY'] = tajny_klic(s['klic'])
    # přihlášení jen z účtu v aplikaci – založí ho průvodce prvním spuštěním (I3); APP_USER z prostředí se nepoužije
    conf['APP_USER'] = conf['APP_PASSWORD_HASH'] = None
    return conf


def zapis_nastaveni(cesta, data_dir, port=VYCHOZI_PORT, host=VYCHOZI_HOST):
    """Nový soubor nastavení (instalátor). Existující nepřepíše."""
    cesta = Path(cesta)
    if cesta.exists(): raise FileExistsError(cesta)
    if not 1 <= int(port) <= 65535: raise ValueError(f'Neplatný port: {port}')
    cesta.parent.mkdir(parents=True, exist_ok=True)
    cesta.write_text('# OSVČ evidence – nastavení samostatné instalace (mění instalátor; ruční úprava jen při vypnuté aplikaci)\n'
                     f'DATA_DIR={Path(data_dir)}\nHOST={host}\nPORT={int(port)}\n', encoding='utf-8')
    return cesta
