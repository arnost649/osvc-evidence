"""Síťový přístup samostatné instalace (Windows, Linux): „Jen tento počítač“ / „Zpřístupnit v domácí síti“.

- Volba je v DATA_DIR/instance/sit.json ({'rezim': 'lokalni'|'domaci', 'ip': '198.51.100.15'}) – soubor nastavení na Linuxu
  patří správci a služba do něj nezapisuje. Spouštěč podle ní naslouchá vždy na 127.0.0.1 a v domácí síti navíc na zvolené IPv4;
  když zvolená adresa na počítači není (jiná síť), běží jen na 127.0.0.1 a stav zapíše do instance/sit-stav.json pro Nastavení.
- Firewall: Windows – pravidlo „OSVC evidence“ (jen port aplikace, profil Soukromá, jen program aplikace) přes UAC,
  odebere se při návratu na „Jen tento počítač“ a při odinstalaci. Linux – pravidla firewallu aplikace NEMĚNÍ (rozhodnutí
  majitele 2026-11-18), Nastavení jen poradí, jak port povolit ručně. Na serveru majitele se nic z toho nepoužívá.
"""
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SOUBOR, STAV = 'sit.json', 'sit-stav.json'
PRAVIDLO = 'OSVC evidence'
UPOZORNENI = 'Spojení není šifrované – používejte jen v domácí síti.'
BEZ_OKNA = 0x08000000 if os.name == 'nt' else 0   # CREATE_NO_WINDOW – z pythonw bez blikajícího okna konzole


def _cti(cesta):
    try: return json.loads(Path(cesta).read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def _zapis(cesta, data):
    from . import zamky
    cesta = Path(cesta); cesta.parent.mkdir(parents=True, exist_ok=True)
    docasny = cesta.with_suffix('.tmp'); docasny.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    zamky.nahrad(docasny, cesta)


def platna_ip(ip):
    """IPv4 adresa vhodná pro domácí síť (ne localhost, ne 0.0.0.0, ne automatická 169.254.x)."""
    try: a = ipaddress.IPv4Address((ip or '').strip())
    except ValueError: return None
    if a.is_loopback or a.is_unspecified or a.is_link_local or a.is_multicast: return None
    return str(a)


def nacti(instance):
    """Uložená volba; poškozený nebo chybějící soubor = jen tento počítač."""
    d = _cti(Path(instance) / SOUBOR)
    if d.get('rezim') == 'domaci' and platna_ip(d.get('ip')): return {'rezim': 'domaci', 'ip': platna_ip(d['ip']), 'kdy': d.get('kdy', '')}
    return {'rezim': 'lokalni', 'ip': '', 'kdy': d.get('kdy', '')}


def uloz(instance, rezim, ip=''):
    if rezim not in ('lokalni', 'domaci'): raise ValueError('Neplatná volba síťového přístupu.')
    if rezim == 'domaci' and not platna_ip(ip): raise ValueError('Vyberte síťový adaptér s platnou adresou IPv4.')
    data = {'rezim': rezim, 'ip': platna_ip(ip) if rezim == 'domaci' else '', 'kdy': datetime.now(timezone.utc).isoformat()}
    _zapis(Path(instance) / SOUBOR, data)
    return data


def vychozi_ip():
    """IPv4 adresa rozhraní s výchozí trasou (kudy jde internet). UDP „connect“ nic neposílá, jen vybere trasu."""
    for cil in ('192.0.2.1', '8.8.8.8'):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((cil, 9)); ip = s.getsockname()[0]
                if platna_ip(ip): return ip
        except OSError: continue
    return None


def _spust(prikaz, timeout=15):
    return subprocess.run(prikaz, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, creationflags=BEZ_OKNA)


def adaptery_linux(ip_addr_json, vychozi=None):
    """Výstup `ip -j -4 addr` → [{nazev, ip, brana}]."""
    vysledek = []
    for rozhrani in json.loads(ip_addr_json or '[]'):
        for a in rozhrani.get('addr_info', []):
            ip = platna_ip(a.get('local')) if a.get('family') == 'inet' else None
            if ip: vysledek.append({'nazev': rozhrani.get('ifname', '?'), 'ip': ip, 'brana': ip == vychozi, 'kategorie': ''})
    return vysledek


def adaptery_windows(adresy_json, profily_json='[]', vychozi=None):
    """Výstup Get-NetIPAddress a Get-NetConnectionProfile (ConvertTo-Json) → [{nazev, ip, brana, kategorie}]."""
    def seznam(text):
        d = json.loads(text or '[]'); return d if isinstance(d, list) else [d]
    kategorie = {p.get('InterfaceAlias'): {0: 'Veřejná', 1: 'Soukromá', 2: 'Doménová'}.get(p.get('NetworkCategory'), str(p.get('NetworkCategory') or ''))
                 for p in seznam(profily_json)}
    vysledek = []
    for a in seznam(adresy_json):
        ip = platna_ip(a.get('IPAddress'))
        if ip: vysledek.append({'nazev': a.get('InterfaceAlias', '?'), 'ip': ip, 'brana': ip == vychozi, 'kategorie': kategorie.get(a.get('InterfaceAlias'), '')})
    return vysledek


def adaptery():
    """Síťové adaptéry s IPv4 adresou; ten s výchozí trasou první a označený (brana=True)."""
    vychozi = vychozi_ip(); seznam = []
    try:
        if os.name == 'nt':
            ps = ['powershell', '-NoProfile', '-NonInteractive', '-Command']
            adresy = _spust(ps + ['Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias,IPAddress | ConvertTo-Json -Compress']).stdout
            profily = _spust(ps + ['Get-NetConnectionProfile | Select-Object InterfaceAlias,NetworkCategory | ConvertTo-Json -Compress']).stdout
            seznam = adaptery_windows(adresy, profily, vychozi)
        else:
            seznam = adaptery_linux(_spust(['ip', '-j', '-4', 'addr']).stdout, vychozi)
    except (OSError, ValueError, subprocess.SubprocessError):
        seznam = []
    if vychozi and not any(a['ip'] == vychozi for a in seznam): seznam.append({'nazev': 'výchozí připojení', 'ip': vychozi, 'brana': True, 'kategorie': ''})
    return sorted(seznam, key=lambda a: (not a['brana'], a['nazev']))


def adresy_pocitace():
    return {a['ip'] for a in adaptery()} | ({vychozi_ip()} - {None})


def naslouchani(volba, port, adresy=None):
    """(['127.0.0.1:PORT', 'IP:PORT'], chyba) – zvolená IP, jen když ji počítač opravdu má."""
    seznam = [f'127.0.0.1:{port}']
    if volba['rezim'] != 'domaci': return seznam, None
    if volba['ip'] not in (adresy if adresy is not None else adresy_pocitace()):
        return seznam, f"Adresa {volba['ip']} teď na tomto počítači není (jiná síť?) – aplikace běží jen na tomto počítači."
    return seznam + [f"{volba['ip']}:{port}"], None


def zapis_stav(instance, volba, port, seznam, chyba):
    _zapis(Path(instance) / STAV, {'rezim': volba['rezim'], 'ip': volba['ip'], 'port': port, 'naslouchani': seznam, 'chyba': chyba,
                                   'kdy': datetime.now(timezone.utc).isoformat()})


def stav(instance):
    return _cti(Path(instance) / STAV)


# ---- firewall ----
def _netsh_pravidlo(port, program):
    return (f'advfirewall firewall add rule name="{PRAVIDLO}" dir=in action=allow protocol=TCP localport={int(port)} '
            f'profile=private program="{program}" enable=yes')


def pravidlo_windows_existuje():
    return _spust(['netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={PRAVIDLO}']).returncode == 0


def _jako_spravce(argumenty):
    """netsh s oprávněním správce (UAC). Vrátí (ok, zpráva)."""
    a = argumenty.replace("'", "''")
    r = _spust(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                f"try {{ $p = Start-Process -FilePath netsh -ArgumentList '{a}' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode }} catch {{ exit 1223 }}"],
               timeout=300)
    if r.returncode == 1223: return False, 'Oprávnění správce nebylo uděleno – pravidlo ve firewallu se nezměnilo.'
    return r.returncode == 0, '' if r.returncode == 0 else f'netsh skončil chybou {r.returncode}.'


def firewall(rezim, port):
    """Windows: přidá / odebere pravidlo. Linux: pravidla nemění, jen poradí.
    Vrátí {'stav': 'ok'|'zamitnuto'|'chyba'|'bez_zasahu', 'zprava': …}."""
    if os.name != 'nt':
        return {'stav': 'bez_zasahu', 'zprava': linux_rada(port) if rezim == 'domaci' else ''}
    try:
        if pravidlo_windows_existuje():
            ok, zprava = _jako_spravce(f'advfirewall firewall delete rule name="{PRAVIDLO}"')
            if not ok: return {'stav': 'zamitnuto' if 'udělen' in zprava else 'chyba', 'zprava': zprava}
        if rezim == 'domaci':
            pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
            program = pythonw if os.path.exists(pythonw) else sys.executable   # pravidlo jen pro program aplikace
            ok, zprava = _jako_spravce(_netsh_pravidlo(port, program))
            if not ok: return {'stav': 'zamitnuto' if 'udělen' in zprava else 'chyba', 'zprava': zprava}
            return {'stav': 'ok', 'zprava': f'Firewall Windows povoluje port {int(port)} v soukromé síti.'}
        return {'stav': 'ok', 'zprava': 'Pravidlo ve firewallu Windows je odebrané.'}
    except (OSError, subprocess.SubprocessError) as exc:
        return {'stav': 'chyba', 'zprava': f'Firewall nejde nastavit ({type(exc).__name__}).'}


def linux_rada(port):
    return (f'Aplikace pravidla firewallu nemění. Máte-li zapnutý firewall (např. ufw), povolte port ručně: '
            f'sudo ufw allow {int(port)}/tcp – a po vypnutí síťového přístupu ho zase odeberte: sudo ufw delete allow {int(port)}/tcp')
