"""Spouštěč samostatné instalace OSVČ (kroky I1, I4). Windows: zástupce instalátoru (pythonw, bez okna); Linux: služba.

    python -m osvc_app.spoustec init --config SOUBOR --data SLOZKA [--port 8080|auto] [--host 127.0.0.1]   nový soubor nastavení
    python -m osvc_app.spoustec spust --config SOUBOR [--data SLOZKA] [--otevrit] [--bez-planovace]
    python -m osvc_app.spoustec zastav --config SOUBOR                                                    ukončí běžící aplikaci
    python -m osvc_app.spoustec zaloha-zip --config SOUBOR --cil SLOZKA                                   ZIP záloha (odinstalace)
    python -m osvc_app.spoustec obnovit-heslo --config SOUBOR [--ano]                                     zapomenuté heslo (osvc / osvc jen na tomto počítači)

spust: když soubor nastavení chybí a je zadané --data, založí ho (první spuštění, port auto). Když už aplikace na portu běží,
jen otevře prohlížeč. Jinak připraví data a spustí server (waitress) + plánovač: synchronizace zdrojů příjmů každých 15 minut
a denní záloha databáze do DATA_DIR/zalohy (posledních 30). Záznam běhu: DATA_DIR/logy/osvc.log.
"""
import argparse
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PORTY_AUTO = range(8765, 8800)
INTERVAL_SYNC = 15 * 60
ZNACKA = 'OSVČ evidence'   # stránka přihlášení / průvodce ji obsahuje → na portu běží právě tato aplikace
log = logging.getLogger('osvc.spoustec')
_pady = None   # soubor pro faulthandler (tvrdé pády)


def hlaska(text, chyba=False):
    """Zpráva uživateli: ve Windows bez konzole (pythonw) okno se zprávou, jinak výpis."""
    if os.name == 'nt' and (sys.stdout is None or not sys.stdout.isatty()):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, ZNACKA, 0x10 if chyba else 0x40)
            return
        except Exception: pass
    if sys.stderr is not None: print(text, file=sys.stderr if chyba else sys.stdout, flush=True)


def _zkusebni_socket():
    """Socket pro zkoušku portu. Linux: SO_REUSEADDR jako server (waitress) – port po právě ukončené aplikaci (TIME_WAIT)
    je volný. Windows: bez něj (tam by SO_REUSEADDR dovolil obsadit port, který už jiný program poslouchá)."""
    s = socket.socket()
    if os.name != 'nt': s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return s


def volny_port(host='127.0.0.1', porty=PORTY_AUTO):
    for port in porty:
        with _zkusebni_socket() as s:
            try: s.bind((host, port)); return port
            except OSError: continue
    raise RuntimeError(f'žádný volný port v rozsahu {porty.start}–{porty.stop - 1}')


def adresa(hodnoty):
    host = 'localhost' if hodnoty['HOST'] in ('127.0.0.1', '0.0.0.0', '::') else hodnoty['HOST']
    return f"http://{host}:{hodnoty['PORT']}/"


def stav_portu(hodnoty):
    """'volny', 'osvc' (už tu běží tato aplikace) nebo 'cizi' (port drží jiný program)."""
    with _zkusebni_socket() as s:
        try: s.bind((hodnoty['HOST'], hodnoty['PORT'])); return 'volny'
        except OSError: pass
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{hodnoty['PORT']}/login", timeout=3) as r:
            return 'osvc' if ZNACKA in r.read(200000).decode('utf-8', 'replace') else 'cizi'
    except Exception:
        return 'cizi'


def nastav_log(slozka):
    slozka.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(slozka / 'osvc.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    koren = logging.getLogger(); koren.addHandler(h); koren.setLevel(logging.INFO)
    # nezachycené chyby (i ve vláknech) a tvrdé pády do logu – ve Windows bez konzole by jinak zmizely beze stopy
    sys.excepthook = lambda t, e, tb: log.critical('nezachycená chyba', exc_info=(t, e, tb))
    threading.excepthook = lambda a: log.critical('nezachycená chyba ve vlákně %s', a.thread.name if a.thread else '?', exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    import faulthandler
    global _pady
    _pady = open(slozka / 'pady.log', 'a', encoding='utf-8'); faulthandler.enable(_pady)
    if os.name == 'nt' and not sys.flags.utf8_mode: log.warning('Python neběží v režimu UTF-8 (chybí -X utf8 ve spouštěči)')
    return h


class Planovac(threading.Thread):
    """Synchronizace zdrojů příjmů každých 15 minut (zarovnaně na :00, :15, …) a denní záloha databáze. Chyba běhu jen do logu."""
    def __init__(self, app, zalohy):
        super().__init__(name='osvc-planovac', daemon=True)
        self.app = app; self.zalohy = Path(zalohy); self.konec = threading.Event()

    def zaloha(self):
        from . import zaloha_db
        from .backup import data_lock
        with self.app.app_context():
            if not zaloha_db.je_cas(self.zalohy): return None
            with data_lock():
                cil = zaloha_db.vytvor(self.zalohy)
            zaloha_db.uklid(self.zalohy)
            log.info('denní záloha databáze: %s', cil.name)
            return cil

    def synchronizace(self):
        from .income_sources import planovana_synchronizace
        with self.app.app_context():
            return planovana_synchronizace(lambda text, chyba=False: log.log(logging.WARNING if chyba else logging.INFO, 'synchronizace: %s', text))

    def krok(self, nazev, funkce):
        try: return funkce()
        except Exception as exc: log.warning('%s selhala: %s: %s', nazev, type(exc).__name__, exc, exc_info=True)

    def kontrola_verze(self):
        from . import aktualizace
        with self.app.app_context():
            stav = aktualizace.zkontroluj()
            if stav: log.info('kontrola nové verze: %s', stav.get('nejnovejsi') or stav.get('chyba'))

    def run(self):
        self.krok('záloha', self.zaloha)
        self.krok('kontrola verze', self.kontrola_verze)
        while not self.konec.wait(INTERVAL_SYNC - time.time() % INTERVAL_SYNC + 5):
            self.krok('synchronizace', self.synchronizace)
            self.krok('záloha', self.zaloha)
            self.krok('kontrola verze', self.kontrola_verze)   # sama hlídá „jednou denně“


def zastav_bezici(hodnoty):
    """Ukončí běžící spouštěč podle souboru instance/spoustec.pid (instalátor před aktualizací, odinstalace). True = něco ukončil."""
    from .instalace import slozky
    pid_soubor = slozky(hodnoty)['instance'] / 'spoustec.pid'
    try: pid = int(pid_soubor.read_text(encoding='utf-8').strip())
    except (OSError, ValueError): return False
    try:
        if os.name == 'nt':
            import ctypes
            k32 = ctypes.windll.kernel32; h = k32.OpenProcess(0x0001 | 0x00100000, False, pid)   # TERMINATE | SYNCHRONIZE
            if not h: pid_soubor.unlink(missing_ok=True); return False
            try: k32.TerminateProcess(h, 0); k32.WaitForSingleObject(h, 10000)
            finally: k32.CloseHandle(h)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
            for _ in range(100):
                os.kill(pid, 0); time.sleep(0.1)
    except (ProcessLookupError, PermissionError):
        pass
    pid_soubor.unlink(missing_ok=True)
    return True


def zaloha_zip(config, cil):
    """ZIP záloha všech dat (stejná jako Nastavení → Záloha) do složky cil – i při zastavené aplikaci (odinstalace, V3).
    Vrátí cestu k ZIP. Soubor se vytvoří pod dočasným jménem a přejmenuje až hotový."""
    from datetime import datetime
    from . import instalace, zamky
    hodnoty = instalace.nacti(config)
    os.environ['OSVC_CONFIG'] = os.path.abspath(config)
    instalace.priprav(hodnoty)
    from . import create_app
    from .backup import create_backup, data_lock
    app = create_app()
    cil = Path(cil); cil.mkdir(parents=True, exist_ok=True)
    soubor = cil / f'OSVC-evidence-zaloha-{datetime.now():%Y-%m-%d_%H-%M-%S}.zip'
    docasny = soubor.with_suffix('.zip.part')
    with app.app_context(), data_lock(exclusive=True):
        create_backup(docasny)
    zamky.nahrad(docasny, soubor)
    return soubor


def main(argv=None):
    p = argparse.ArgumentParser(prog='osvc-evidence', description='OSVČ evidence – samostatná instalace')
    sub = p.add_subparsers(dest='prikaz', required=True)
    i = sub.add_parser('init', help='nový soubor nastavení'); i.add_argument('--config', required=True); i.add_argument('--data', required=True)
    i.add_argument('--port', default='8080', help='číslo portu nebo auto (první volný od 8765)'); i.add_argument('--host', default='127.0.0.1')
    s = sub.add_parser('spust', help='spustit aplikaci'); s.add_argument('--config', required=True); s.add_argument('--data')
    s.add_argument('--otevrit', action='store_true'); s.add_argument('--bez-planovace', action='store_true')
    s.add_argument('--po-restartu', action='store_true', help='nejdřív počkat, až předchozí běh uvolní port (restart z aplikace)')
    z = sub.add_parser('zastav', help='ukončit běžící aplikaci'); z.add_argument('--config', required=True)
    zz = sub.add_parser('zaloha-zip', help='ZIP záloha dat do složky'); zz.add_argument('--config', required=True); zz.add_argument('--cil', required=True)
    oh = sub.add_parser('obnovit-heslo', help='zapomenuté heslo: dočasné přihlášení osvc / osvc jen na tomto počítači')
    oh.add_argument('--config', required=True); oh.add_argument('--ano', action='store_true', help='bez otázky')
    a = p.parse_args(argv)
    if a.prikaz == 'obnovit-heslo':
        from . import obnova_hesla
        return obnova_hesla.main(['--config', a.config] + (['--ano'] if a.ano else []))
    from . import instalace
    if a.prikaz == 'init':
        port = volny_port(a.host) if a.port == 'auto' else int(a.port)
        print(instalace.zapis_nastaveni(a.config, a.data, port, a.host)); return 0
    if a.prikaz == 'zaloha-zip':
        try: print(zaloha_zip(a.config, a.cil)); return 0
        except Exception as exc:
            hlaska(f'ZIP zálohu nejde vytvořit: {exc}', chyba=True); return 5
    if a.prikaz == 'zastav':
        try: hodnoty = instalace.nacti(a.config)
        except FileNotFoundError: return 0
        print('ukončeno' if zastav_bezici(hodnoty) else 'neběží'); return 0
    try:
        if not Path(a.config).exists() and a.data:   # první spuštění (Windows: zástupce po instalaci)
            instalace.zapis_nastaveni(a.config, a.data, volny_port())
        hodnoty = instalace.nacti(a.config)
    except (OSError, ValueError, RuntimeError) as exc:
        hlaska(f'Aplikaci nejde spustit: {exc}', chyba=True); return 2
    stav = stav_portu(hodnoty)
    for _ in range(40 if a.po_restartu else 0):   # restart z aplikace: předchozí běh ještě končí
        if stav == 'volny': break
        time.sleep(0.5); stav = stav_portu(hodnoty)
    if stav == 'osvc':   # už běží – jen otevřít
        if a.otevrit: webbrowser.open(adresa(hodnoty))
        else: print(f'OSVČ evidence už běží na {adresa(hodnoty)}')
        return 0
    if stav == 'cizi':
        hlaska(f"Port {hodnoty['PORT']} používá jiný program, OSVČ evidence se nemůže spustit.\n\n"
               f'Port změníte v souboru nastavení {Path(a.config).resolve()} (řádek PORT=…).', chyba=True)
        return 3
    os.environ['OSVC_CONFIG'] = os.path.abspath(a.config)
    nastav_log(instalace.slozky(hodnoty)['logy'])   # log hned od začátku – i chyba při přípravě dat se zapíše
    try:
        s = instalace.priprav(hodnoty)
        from . import create_app
        app = create_app()
    except Exception as exc:
        log.exception('aplikaci nejde spustit')
        hlaska(f"Aplikaci nejde spustit: {exc}\n\nPodrobnosti: {instalace.slozky(hodnoty)['logy'] / 'osvc.log'}", chyba=True); return 4
    from waitress import create_server
    from . import sit
    volba = sit.nacti(s['instance'])
    if hodnoty['HOST'] in ('127.0.0.1', 'localhost'):   # síťový přístup z Nastavení (sit.json); jiný HOST v souboru nastavení má přednost
        adresy, chyba_site = sit.naslouchani(volba, hodnoty['PORT'])
    else:
        adresy, chyba_site = [f"{hodnoty['HOST']}:{hodnoty['PORT']}"], None
    try:
        server = create_server(app, listen=' '.join(adresy), threads=8)
    except OSError as exc:   # zvolenou adresu nejde použít → jen tento počítač, Nastavení to oznámí
        adresy, chyba_site = [f"127.0.0.1:{hodnoty['PORT']}"], f'Adresu {volba["ip"]} nejde použít ({exc.strerror or exc}) – aplikace běží jen na tomto počítači.'
        server = create_server(app, listen=adresy[0], threads=8)
    sit.zapis_stav(s['instance'], volba, hodnoty['PORT'], adresy, chyba_site)
    if chyba_site: log.warning('síťový přístup: %s', chyba_site)
    pid_soubor = s['instance'] / 'spoustec.pid'; pid_soubor.write_text(str(os.getpid()), encoding='utf-8')

    def zastav():
        """Ukončení z aplikace (Napájení → Zastavit aplikaci): počká na rozběhnutou synchronizaci/zálohu a skončí."""
        def konec():
            time.sleep(0.5)   # odpověď prohlížeči ještě odejde
            from .backup import data_lock
            try:
                with app.app_context(), data_lock(exclusive=True): log.info('aplikace ukončena uživatelem')
            finally:
                pid_soubor.unlink(missing_ok=True); logging.shutdown(); os._exit(0)
        threading.Thread(target=konec, daemon=True).start()
    app.config['OSVC_ZASTAV'] = zastav

    def restartuj():
        """Restart po změně síťového přístupu. Služba balíčku (OSVC_SLUZBA=systemd): konec s kódem 75 (Restart=on-failure ji spustí znovu);
        jinak (Windows, ruční běh): nová kopie spouštěče, která počká na uvolnění portu, a tento běh skončí."""
        # Jen výslovné označení ze služby balíčku – INVOCATION_ID dědí i procesy spuštěné z jiných služeb (např. runner CI).
        sluzba = os.environ.get('OSVC_SLUZBA') == 'systemd'
        def konec():
            time.sleep(0.8)   # odpověď prohlížeči ještě odejde
            from .backup import data_lock
            try:
                with app.app_context(), data_lock(exclusive=True):
                    log.info('restart po změně síťového přístupu')
                    if not sluzba:
                        prikaz = [sys.executable, '-X', 'utf8', '-m', 'osvc_app.spoustec', 'spust', '--config', os.environ['OSVC_CONFIG'], '--po-restartu']
                        if a.bez_planovace: prikaz.append('--bez-planovace')
                        volby = {'creationflags': 0x00000008 | 0x00000200} if os.name == 'nt' else {'start_new_session': True}   # DETACHED | NEW_PROCESS_GROUP
                        subprocess.Popen(prikaz, cwd=str(Path(__file__).resolve().parent.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, close_fds=True, **volby)
            finally:
                pid_soubor.unlink(missing_ok=True); logging.shutdown(); os._exit(75 if sluzba else 0)
        threading.Thread(target=konec, daemon=True).start()
    app.config['OSVC_RESTART'] = restartuj
    if not a.bez_planovace: Planovac(app, s['zalohy']).start()
    v_siti = [f'http://{x}/' for x in adresy if not x.startswith('127.0.0.1:') and not x.startswith('localhost:')]
    print(f'OSVČ evidence běží na {adresa(hodnoty)}' + (f' a v síti na {", ".join(v_siti)}' if v_siti else '') + f' (data: {hodnoty["DATA_DIR"]})', flush=True)
    log.info('spuštěno na %s%s, data %s', adresa(hodnoty), (' a ' + ', '.join(v_siti)) if v_siti else '', hodnoty['DATA_DIR'])
    if a.otevrit: threading.Timer(1.5, webbrowser.open, (adresa(hodnoty),)).start()
    try: server.run()
    except KeyboardInterrupt: pass
    finally: pid_soubor.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
