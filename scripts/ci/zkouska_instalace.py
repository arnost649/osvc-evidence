#!/usr/bin/env python3
"""Zkouška nainstalované aplikace přes HTTP (krok V5, GitHub Actions – Windows i Linux). Jen zkušební údaje, žádná skutečná data.

    python scripts/ci/zkouska_instalace.py cekej   --url http://localhost:8765
    python scripts/ci/zkouska_instalace.py pripravit --url … --otisk otisk.json    průvodce (když je) + jeden výdaj + jízda; otisk dat
    python scripts/ci/zkouska_instalace.py overit    --url … --otisk otisk.json    po aktualizaci: přihlášení, data stejná, průvodce se neukáže
    python scripts/ci/zkouska_instalace.py port      --config osvc.conf             vypíše adresu z nastavení
    python scripts/ci/zkouska_instalace.py sit       --url … --rezim domaci|lokalni  síťový přístup z Nastavení; počká na restart
"""
import argparse
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

JMENO, HESLO = 'zkouska', 'zkusebni-heslo-1'
VYDAJ = 'Zkušební nákup před aktualizací'


class Klient:
    def __init__(self, url):
        self.url = url.rstrip('/'); self.o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, cesta):
        with self.o.open(self.url + cesta, timeout=30) as r: return r.geturl(), r.read().decode('utf-8')

    def post(self, cesta, data, token_z=None):
        _, html = self.get(token_z or cesta)
        data = dict(data, csrf_token=re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1))
        with self.o.open(self.url + cesta, urllib.parse.urlencode(data).encode(), timeout=60) as r: return r.geturl(), r.read().decode('utf-8')

    def prihlas(self):
        adresa, html = self.post('/login', {'username': JMENO, 'password': HESLO})
        if 'Přehled' not in html: raise SystemExit(f'CHYBA: přihlášení se nepovedlo ({adresa})')


def cekej(url, limit=90):
    konec = time.time() + limit
    while time.time() < konec:
        try:
            with urllib.request.urlopen(url.rstrip('/') + '/login', timeout=5) as r:
                if 'OSVČ evidence' in r.read().decode('utf-8'): return True
        except (OSError, urllib.error.URLError): pass
        time.sleep(1)
    raise SystemExit(f'CHYBA: aplikace na {url} neodpovídá')


def otisk(k):
    """Co se po aktualizaci nesmí změnit: výdaj, profil a Přehled."""
    _, vydaje = k.get('/payments/expense')
    _, nastaveni = k.get('/settings')
    return {'vydaj': VYDAJ in vydaje, 'castka': '1 234,50' in vydaje or '1 234,50' in vydaje, 'profil_ico': '12345678' in nastaveni,
            'jmeno': 'Zkušební OSVČ' in nastaveni}


def pripravit(url, soubor):
    k = Klient(url); adresa, html = k.get('/')
    if adresa.endswith('/pruvodce'):
        rok = time.localtime().tm_year
        adresa, html = k.post('/pruvodce', {'ico': '12345678', 'name': 'Zkušební OSVČ', 'number': '1', 'city': 'Brno', 'zip': '60200', 'country': 'Česká republika',
                                            'username': JMENO, 'password': HESLO, 'password2': HESLO, 'podnikani_od': f'{rok}-01-01', 'podnikani_konec': 'ne',
                                            'prvni_zahajeni': 'ne', 'zamestnani': 'ne', 'pojistovna': '111', 'social_zalohy': 'neplati', 'health_zalohy': 'neplati',
                                            'vydaje': 'actual', 'dane_rezim': 'standard', 'potvrzeni': 'ano', 'modul_doprava': '1'})
        if adresa.endswith('/pruvodce/dalsi'): k.post('/pruvodce/dalsi', {'vozidlo_nazev': 'Zkušební auto', 'vozidlo_rezim': 'actual', 'dalsi': 'hotovo'})
    else:
        k.prihlas()
    k.post('/payments/expense', {'payment_date': time.strftime('%Y-%m-%d'), 'counterparty_name': 'Zkušební dodavatel', 'description': VYDAJ, 'amount': '1234.50', 'tax_mode': '100'})
    o = otisk(k)
    if not all(o.values()): raise SystemExit(f'CHYBA: zkušební data se nezaložila: {o}')
    json.dump(o, open(soubor, 'w', encoding='utf-8')); print('data připravena', o)


def overit(url, soubor):
    k = Klient(url); adresa, _ = k.get('/')
    if adresa.endswith('/pruvodce'): raise SystemExit('CHYBA: po aktualizaci se ukázal průvodce – data se ztratila')
    k.prihlas(); o = otisk(k); puvodni = json.load(open(soubor, encoding='utf-8'))
    if o != puvodni: raise SystemExit(f'CHYBA: data po aktualizaci nesedí: {o} × {puvodni}')
    print('data po aktualizaci sedí', o)


def sit(url, rezim):
    """Nastavení → Síťový přístup; po restartu ověří, že aplikace odpovídá na adrese počítače (domaci) / jen na localhost (lokalni)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s: s.connect(('192.0.2.1', 9)); ip = s.getsockname()[0]
    k = Klient(url); k.prihlas()
    _, html = k.post('/settings/sit', {'rezim': rezim, 'ip': ip, 'potvrzeni': 'ano'}, token_z='/settings')
    if 'Aplikace se restartuje' not in html: raise SystemExit('CHYBA: síťový přístup se neuložil')
    firewall = re.search(r'data-firewall="([^"]+)"', html); print('firewall:', firewall.group(1) if firewall else '—')
    port = url.rstrip('/').rsplit(':', 1)[1]; sitova = f'http://{ip}:{port}'
    time.sleep(3); cekej(url, 120)   # localhost funguje vždy
    try:
        with urllib.request.urlopen(sitova + '/login', timeout=5) as r: odpovida = r.status == 200
    except OSError: odpovida = False
    if odpovida != (rezim == 'domaci'): raise SystemExit(f'CHYBA: {sitova} {"neodpovídá" if rezim == "domaci" else "stále odpovídá"}')
    print(f'síťový přístup {rezim}: {sitova} {"odpovídá" if odpovida else "neodpovídá (správně)"}')


def main(argv=None):
    a = argparse.ArgumentParser(); a.add_argument('prikaz', choices=('cekej', 'pripravit', 'overit', 'port', 'sit')); a.add_argument('--rezim', choices=('domaci', 'lokalni'))
    a.add_argument('--url'); a.add_argument('--otisk', default='otisk.json'); a.add_argument('--config')
    a = a.parse_args(argv)
    if a.prikaz == 'port':
        port = re.search(r'^PORT=(\d+)', open(a.config, encoding='utf-8').read(), re.M).group(1); print(f'http://localhost:{port}'); return 0
    cekej(a.url)
    if a.prikaz == 'pripravit': pripravit(a.url, a.otisk)
    elif a.prikaz == 'overit': overit(a.url, a.otisk)
    elif a.prikaz == 'sit': sit(a.url, a.rezim)
    return 0


if __name__ == '__main__':
    sys.exit(main())
