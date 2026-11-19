"""Upozornění na novou verzi (krok V2) – jen samostatná instalace (Windows, Linux), nikdy server.

Plánovač ve spouštěči jednou denně zjistí poslední vydání na GitHubu (veřejné API, bez přihlášení a bez osobních údajů –
posílá jen obecný User-Agent s číslem verze). Výsledek: instance/aktualizace.json. Aplikace pak ukáže lištu s odkazem
na stránku vydání; nic sama nestahuje ani neinstaluje. Vypíná se v Nastavení → Účet / Přihlášení → Aktualizace
(instance/aktualizace-nastaveni.json). Repozitář doplní sestavení balíčku do verze.py (REPO); bez něj se nekontroluje.
"""
import json
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from flask import current_app
from . import verze

INTERVAL = timedelta(hours=24)
SOUBOR = 'aktualizace.json'
NASTAVENI = 'aktualizace-nastaveni.json'


def repo():
    r = getattr(verze, 'REPO', None) or current_app.config.get('OSVC_AKTUALIZACE_REPO')
    return r if r and re.fullmatch(r'[\w.-]+/[\w.-]+', r) else None


def povoleno_zde():
    """Kontrola i upozornění jen v samostatné instalaci se známým repozitářem."""
    return bool(current_app.config.get('OSVC_SAMOSTATNA')) and repo() is not None


def _cesta(jmeno):
    from .backup import state_dir
    return state_dir() / jmeno


def _cti(jmeno):
    try: return json.loads(_cesta(jmeno).read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def zapnuto():
    return _cti(NASTAVENI).get('kontrolovat', True) is not False


def nastav(kontrolovat):
    from .backup import write_atomic
    write_atomic(_cesta(NASTAVENI), json.dumps({'kontrolovat': bool(kontrolovat)}).encode())


def cislo(text):
    """'v1.2.3' / '1.2.3' → (1, 2, 3); předběžné verze (-test, -rc1, vývoj) jsou nižší než stejná vydaná."""
    m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(-[\w.-]+)?', (text or '').strip())
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if m.group(4) else 1)


def _povolena_adresa(url):
    """Soubory aktualizace jen z vydání tohoto repozitáře na GitHubu."""
    return isinstance(url, str) and repo() is not None and url.startswith(f'https://github.com/{repo()}/releases/download/')


def zkontroluj(ted=None, otevri=urllib.request.urlopen, vynutit=False):
    """Jedna kontrola (plánovač; vynutit=True = „Zkontrolovat teď“ i při vypnuté automatice a bez čekání na interval).
    Vrátí uložený stav, nebo None, když se nekontroluje (server, vypnuto, ještě není čas)."""
    if not povoleno_zde() or (not vynutit and not zapnuto()): return None
    ted = ted or datetime.now(timezone.utc); stav = _cti(SOUBOR)
    if not vynutit:
        try:
            if ted - datetime.fromisoformat(stav['kontrola']) < INTERVAL: return None
        except (KeyError, TypeError, ValueError): pass
    novy = {'kontrola': ted.isoformat()}
    try:
        pozadavek = urllib.request.Request(f'https://api.github.com/repos/{repo()}/releases/latest',
                                           headers={'User-Agent': f'osvc-evidence/{verze.VERZE}', 'Accept': 'application/vnd.github+json'})
        with otevri(pozadavek, timeout=10) as r: data = json.loads(r.read(1_000_000).decode('utf-8'))
        tag = str(data.get('tag_name') or ''); odkaz = str(data.get('html_url') or '')
        if not cislo(tag) or not odkaz.startswith('https://github.com/'): raise ValueError('neplatná odpověď')
        soubory = {jmeno: a.get('browser_download_url') for a in data.get('assets') or [] for jmeno, nazev in SOUBORY.items()
                   if a.get('name') == nazev and _povolena_adresa(a.get('browser_download_url'))}
        novy.update(nejnovejsi=tag.lstrip('v'), odkaz=odkaz, popis=_strucne(data.get('body') or ''), soubory=soubory)
    except Exception as exc:
        novy.update(chyba=type(exc).__name__, **{k: stav.get(k) for k in ('nejnovejsi', 'odkaz', 'popis', 'soubory')})
    from .backup import write_atomic
    write_atomic(_cesta(SOUBOR), json.dumps(novy, ensure_ascii=False).encode())
    return novy


SOUBORY = {'windows': 'osvc-evidence-windows.exe', 'linux': 'osvc-evidence-linux.deb', 'soucty': 'SHA256SUMS.txt'}


def _strucne(text, nejvic=900):
    """Popis vydání (Markdown) → stručný čistý text pro okénko: bez odkazů a značek, bez patičky se součty."""
    text = text.split('\n---')[0]
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text); text = re.sub(r'[*`#>]', '', text)
    radky = [r.strip() for r in text.splitlines() if r.strip()]
    vysledek = '\n'.join(radky)
    return vysledek if len(vysledek) <= nejvic else vysledek[:nejvic].rsplit(' ', 1)[0] + ' …'


def nova_verze(stav=None):
    stav = stav if stav is not None else _cti(SOUBOR)
    nova, mam = cislo(stav.get('nejnovejsi')), cislo(verze.VERZE)
    return bool(nova and mam and nova > mam)


def verze_text():
    """Verze pro zobrazení. Samostatná instalace: číslo z tagu. Server majitele: číslo vydání, ze kterého kód vychází,
    a zkrácený commit z gitu, např. „1.0.1 (3011744)“."""
    if current_app.config.get('OSVC_SAMOSTATNA'): return verze.VERZE
    try:
        from pathlib import Path
        g = Path(__file__).resolve().parent.parent / '.git'
        ref = (g / 'HEAD').read_text(encoding='utf-8').strip()
        sha = (g / ref[5:]).read_text(encoding='utf-8').strip() if ref.startswith('ref: ') else ref
        return f'{verze.VERZE} ({sha[:7]})'
    except OSError:
        return verze.VERZE


def okno():
    """Údaje pro okénko s verzí na Přehledu."""
    samostatna = bool(current_app.config.get('OSVC_SAMOSTATNA')); stav = _cti(SOUBOR) if samostatna else {}
    windows = bool(current_app.config.get('OSVC_WINDOWS'))
    soubory = stav.get('soubory') or {}
    return {'verze': verze_text(), 'samostatna': samostatna, 'windows': windows, 'dostupne': povoleno_zde(),
            'nejnovejsi': stav.get('nejnovejsi'), 'nova': samostatna and nova_verze(stav), 'popis': stav.get('popis') or '',
            'odkaz': stav.get('odkaz') or (f'https://github.com/{repo()}/releases/latest' if repo() else ''),
            'kontrola': stav.get('kontrola'), 'chyba': stav.get('chyba'), 'zapnuto': zapnuto(),
            'lze_instalovat': samostatna and windows and bool(soubory.get('windows') and soubory.get('soucty')),
            'deb': soubory.get('linux') or '', 'prikaz': 'sudo apt install ./osvc-evidence-linux.deb', 'prubeh': prubeh()}


# ---- stažení a instalace nové verze (jen Windows) ----
_PRUBEH = {'faze': 'nic'}
_ZAMEK = threading.Lock()
MAX_VELIKOST = 300 * 1024 * 1024
TEXTY = {'stahuji': 'Stahuji…', 'overuji': 'Ověřuji…', 'spoustim': 'Spouštím instalaci, aplikace se na chvíli zavře.'}


def prubeh():
    with _ZAMEK: return dict(_PRUBEH)


def _nastav(**hodnoty):
    with _ZAMEK:
        _PRUBEH.clear(); _PRUBEH.update(hodnoty)
        if hodnoty.get('faze') in TEXTY: _PRUBEH['text'] = TEXTY[hodnoty['faze']]


def _instalator_spust(exe):
    """Tichá instalace přes starou verzi; instalátor aplikaci ukončí a po instalaci ji znovu spustí (/SPUSTIT=1)."""
    import subprocess
    subprocess.Popen([str(exe), '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SPUSTIT=1'], close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008 | 0x00000200 if os.name == 'nt' else 0)


def aktualizuj(app, otevri=urllib.request.urlopen, spust=_instalator_spust, cekat=1.5):
    """Spustí na pozadí: stažení instalátoru (průběh), ověření SHA256 podle SHA256SUMS.txt, spuštění instalace.
    Vrátí False, když už běží nebo nejde (není nová verze / soubory)."""
    with app.app_context():
        stav = _cti(SOUBOR); soubory = stav.get('soubory') or {}
        url, soucty = soubory.get('windows'), soubory.get('soucty')
        if not (nova_verze(stav) and _povolena_adresa(url) and _povolena_adresa(soucty)): return False
        slozka = _cesta('aktualizace')
    with _ZAMEK:
        if _PRUBEH.get('faze') in TEXTY: return False
    _nastav(faze='stahuji', procent=0, verze=stav['nejnovejsi'])

    def prace():
        import hashlib
        slozka.mkdir(parents=True, exist_ok=True)
        cast = slozka / 'osvc-evidence-windows.exe.part'; hotovy = slozka / f"osvc-evidence-windows-{stav['nejnovejsi']}.exe"
        try:
            h = hashlib.sha256(); stazeno = 0
            pozadavek = urllib.request.Request(url, headers={'User-Agent': f'osvc-evidence/{verze.VERZE}'})
            with otevri(pozadavek, timeout=60) as r, open(cast, 'wb') as f:
                celkem = int(r.headers.get('Content-Length') or 0)
                while True:
                    kus = r.read(256 * 1024)
                    if not kus: break
                    stazeno += len(kus)
                    if stazeno > MAX_VELIKOST: raise ValueError('soubor je příliš velký')
                    f.write(kus); h.update(kus)
                    _nastav(faze='stahuji', procent=int(stazeno * 100 / celkem) if celkem else 0, verze=stav['nejnovejsi'])
            _nastav(faze='overuji', procent=100, verze=stav['nejnovejsi'])
            pozadavek = urllib.request.Request(soucty, headers={'User-Agent': f'osvc-evidence/{verze.VERZE}'})
            with otevri(pozadavek, timeout=30) as r: seznam = r.read(100_000).decode('utf-8', 'replace')
            ocekavany = next((radek.split()[0].lower() for radek in seznam.splitlines()
                              if radek.strip().endswith(' ' + SOUBORY['windows']) and len(radek.split()[0]) == 64), None)
            if not ocekavany: raise ValueError('v SHA256SUMS.txt chybí instalátor')
            if h.hexdigest() != ocekavany: raise ValueError('kontrolní součet nesedí – soubor je poškozený nebo podvržený')
            from . import zamky
            zamky.nahrad(cast, hotovy)
            _nastav(faze='spoustim', procent=100, verze=stav['nejnovejsi'])
            app.logger.info('aktualizace: instalátor %s ověřen, spouštím instalaci', hotovy.name)
            time.sleep(cekat)   # stránka v prohlížeči ještě dostane stav „Spouštím instalaci“
            spust(hotovy)
        except Exception as exc:
            cast.unlink(missing_ok=True)
            app.logger.warning('aktualizace selhala: %s: %s', type(exc).__name__, exc)
            _nastav(faze='chyba', text=f'Aktualizace se nepovedla: {exc}. Zkuste to znovu, nebo stáhněte instalátor z GitHubu.')
    threading.Thread(target=prace, name='osvc-aktualizace', daemon=True).start()
    return True


def upozorneni():
    """{'verze', 'odkaz'} pro lištu v aplikaci, nebo None."""
    try:
        if not povoleno_zde() or not zapnuto(): return None
        stav = _cti(SOUBOR); nova, mam = cislo(stav.get('nejnovejsi')), cislo(verze.VERZE)
        if nova and mam and nova > mam and str(stav.get('odkaz', '')).startswith('https://github.com/'):
            return {'verze': stav['nejnovejsi'], 'odkaz': stav['odkaz']}
    except Exception:
        current_app.logger.warning('upozornění na novou verzi nejde zjistit')
    return None


def prehled():
    """Pro Nastavení: verze, zda se kontroluje, poslední kontrola."""
    stav = _cti(SOUBOR)
    return {'verze': verze.VERZE, 'zapnuto': zapnuto(), 'kontrola': stav.get('kontrola'), 'chyba': stav.get('chyba'),
            'nejnovejsi': stav.get('nejnovejsi'), 'dostupne': povoleno_zde()}
