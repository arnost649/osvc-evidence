"""Upozornění na novou verzi (krok V2) – jen samostatná instalace (Windows, Linux), nikdy server.

Plánovač ve spouštěči jednou denně zjistí poslední vydání na GitHubu (veřejné API, bez přihlášení a bez osobních údajů –
posílá jen obecný User-Agent s číslem verze). Výsledek: instance/aktualizace.json. Aplikace pak ukáže lištu s odkazem
na stránku vydání; nic sama nestahuje ani neinstaluje. Vypíná se v Nastavení → Účet / Přihlášení → Aktualizace
(instance/aktualizace-nastaveni.json). Repozitář doplní sestavení balíčku do verze.py (REPO); bez něj se nekontroluje.
"""
import json
import re
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


def zkontroluj(ted=None, otevri=urllib.request.urlopen):
    """Jedna kontrola (plánovač). Vrátí uložený stav, nebo None, když se nekontroluje (server, vypnuto, ještě není čas)."""
    if not povoleno_zde() or not zapnuto(): return None
    ted = ted or datetime.now(timezone.utc); stav = _cti(SOUBOR)
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
        novy.update(nejnovejsi=tag.lstrip('v'), odkaz=odkaz)
    except Exception as exc:
        novy.update(chyba=type(exc).__name__, nejnovejsi=stav.get('nejnovejsi'), odkaz=stav.get('odkaz'))
    from .backup import write_atomic
    write_atomic(_cesta(SOUBOR), json.dumps(novy, ensure_ascii=False).encode())
    return novy


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
