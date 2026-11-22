"""Okénko s verzí a aktualizace z aplikace: kontrola si pamatuje popis a soubory vydání (jen z tohoto repozitáře),
„Zkontrolovat teď“, stažení instalátoru s průběhem a ověřením SHA256, spuštění tiché instalace (jen Windows), Linux = odkaz
na .deb a příkaz, server majitele = jen verze a „Server se aktualizuje přes osvc-nasad“. GitHub i instalátor jsou podstrčené.
Běží jen přes tests/spust.sh."""
import hashlib
import io
import json
import os
import re
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from osvc_app import aktualizace, create_app, instalace, verze

TMP = tempfile.TemporaryDirectory()
REPO = 'vlastnik/osvc'
DL = f'https://github.com/{REPO}/releases/download/v9.9.9/'
INSTALATOR = b'MZ' + b'x' * 600_000


class Odpoved(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data); self.headers = headers or {}
    def __enter__(self): return self
    def __exit__(self, *a): pass


def vydani(soucet=None, cizi=False):
    soucet = soucet or hashlib.sha256(INSTALATOR).hexdigest()
    soubory = {DL + 'osvc-evidence-windows.exe': INSTALATOR, DL + 'osvc-evidence-linux.deb': b'deb',
               DL + 'SHA256SUMS.txt': f'{soucet}  osvc-evidence-windows.exe\n{"0" * 64}  osvc-evidence-linux.deb\n'.encode()}
    api = {'tag_name': 'v9.9.9', 'html_url': f'https://github.com/{REPO}/releases/tag/v9.9.9',
           'body': '**Novinky:**\n- Rychlejší [Přehled](https://x)\n- Oprava záloh\n\n---\nKontrolní součty souborů …',
           'assets': [{'name': n, 'browser_download_url': ('https://zlo.example/' + n) if cizi and n.endswith('.exe') else DL + n}
                      for n in ('osvc-evidence-windows.exe', 'osvc-evidence-linux.deb', 'SHA256SUMS.txt')]}
    volani = []
    def otevri(req, timeout=None):
        url = req.full_url; volani.append(url)
        if url.startswith('https://api.github.com/'): return Odpoved(json.dumps(api).encode())
        return Odpoved(soubory[url], {'Content-Length': str(len(soubory[url]))})
    otevri.volani = volani
    return otevri


class Zaklad(unittest.TestCase):
    n = 0

    def setUp(self):
        Zaklad.n += 1
        konf = Path(TMP.name) / f'z{Zaklad.n}' / 'osvc.conf'; instalace.zapis_nastaveni(konf, konf.parent / 'data')
        self.slozky = instalace.priprav(instalace.nacti(konf))
        os.environ['OSVC_CONFIG'] = str(konf)
        try: self.app = create_app({'TESTING': True, 'OSVC_AKTUALIZACE_REPO': REPO, **self.navic()})
        finally: os.environ.pop('OSVC_CONFIG')
        self.k = self.app.test_client()
        t = self.token('/pruvodce')
        self.k.post('/pruvodce', data={'csrf_token': t, 'ico': '12345678', 'name': 'Test', 'number': '1', 'city': 'Brno', 'zip': '60200', 'zamestnani': 'ne',
                                       'pojistovna': '111', 'social_zalohy': 'neplati', 'health_zalohy': 'neplati', 'vydaje': 'actual', 'dane_rezim': 'standard',
                                       'prvni_zahajeni': 'ne', 'username': 'test', 'password': 'heslo-12345', 'password2': 'heslo-12345'})
        aktualizace._nastav(faze='nic')

    def navic(self): return {}

    def token(self, url='/settings'):
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.k.get(url).get_data(as_text=True)).group(1)

    def zkontroluj(self, **kw):
        with self.app.app_context(), mock.patch.object(verze, 'VERZE', '1.0.0'):
            return aktualizace.zkontroluj(**kw)


class Kontrola(Zaklad):
    def test_popis_a_soubory_jen_z_repozitare(self):
        stav = self.zkontroluj(otevri=vydani(), vynutit=True)
        self.assertEqual(stav['nejnovejsi'], '9.9.9'); self.assertEqual(set(stav['soubory']), {'windows', 'linux', 'soucty'})
        self.assertEqual(stav['popis'], 'Novinky:\n- Rychlejší Přehled\n- Oprava záloh', 'bez odkazů, značek a patičky')
        stav = self.zkontroluj(otevri=vydani(cizi=True), vynutit=True)
        self.assertNotIn('windows', stav['soubory'], 'instalátor odjinud než z vydání repozitáře se nepřevezme')

    def test_zkontrolovat_ted_i_pri_vypnute_automatice(self):
        with self.app.app_context(): aktualizace.nastav(False)
        self.assertIsNone(self.zkontroluj(otevri=vydani()), 'automatika vypnutá')
        g = vydani(); ted = datetime.now(timezone.utc)
        self.assertEqual(self.zkontroluj(otevri=g, vynutit=True, ted=ted)['nejnovejsi'], '9.9.9')
        self.zkontroluj(otevri=g, vynutit=True, ted=ted + timedelta(minutes=1)); self.assertEqual(len(g.volani), 2, 'bez čekání na interval')
        with mock.patch.object(verze, 'VERZE', '1.0.0'):
            r = self.k.post('/aktualizace/zkontrolovat', data={'csrf_token': self.token()}, headers={'Accept': 'application/json'})
        self.assertEqual(r.status_code, 200)


class Okno(Zaklad):
    def test_nejnovejsi_a_nova_verze(self):
        with self.app.app_context(), mock.patch.object(verze, 'VERZE', '9.9.9'):
            self.zkontroluj  # noqa
            aktualizace.zkontroluj(otevri=vydani(), vynutit=True); d = aktualizace.okno()
        self.assertFalse(d['nova']); self.assertEqual(d['verze'], '9.9.9')
        with self.app.app_context(), mock.patch.object(verze, 'VERZE', '1.0.0'):
            d = aktualizace.okno()
            html = self.k.get('/').get_data(as_text=True)
        self.assertTrue(d['nova']); self.assertEqual(d['nejnovejsi'], '9.9.9'); self.assertIn('Oprava záloh', d['popis'])
        self.assertFalse(d['lze_instalovat'], 'Linux: neinstaluje se z aplikace'); self.assertTrue(d['deb'].endswith('osvc-evidence-linux.deb'))
        self.assertEqual(d['prikaz'], 'sudo apt install ./osvc-evidence-linux.deb')
        self.assertIn('data-verze-otevrit', html); self.assertIn('Verze 1.0.0 · nová verze 9.9.9', html)
        self.assertEqual(self.k.post('/aktualizace/instalovat', data={'csrf_token': self.token()}).status_code, 404, 'na Linuxu instalace z aplikace není')

    def test_nastaveni_aktualizace(self):
        html = self.k.get('/settings?tab=aktualizace').get_data(as_text=True)
        for text in ('settings-panel-aktualizace', 'Automaticky kontrolovat nové verze', 'Zkontrolovat teď'): self.assertIn(text, html)
        self.assertNotIn('Server se aktualizuje přes osvc-nasad', html)


class InstalaceWindows(Zaklad):
    def navic(self): return {'OSVC_WINDOWS': True}

    def cekej(self, faze, limit=10):
        konec = time.time() + limit
        while time.time() < konec:
            if aktualizace.prubeh().get('faze') in faze: return aktualizace.prubeh()
            time.sleep(0.05)
        return aktualizace.prubeh()

    def test_stazeni_overeni_a_spusteni(self):
        g = vydani(); self.zkontroluj(otevri=g, vynutit=True); spusteno = []
        with mock.patch.object(verze, 'VERZE', '1.0.0'):
            self.assertTrue(aktualizace.aktualizuj(self.app, otevri=g, spust=spusteno.append, cekat=0))
            self.assertFalse(aktualizace.aktualizuj(self.app, otevri=g, spust=spusteno.append, cekat=0), 'podruhé během stahování ne')
            p = self.cekej({'spoustim', 'chyba'})
        self.assertEqual(p['faze'], 'spoustim'); self.assertEqual(p['text'], 'Instaluji novou verzi – aplikace se na chvíli zavře a sama znovu spustí.')
        time.sleep(0.2)
        self.assertEqual(len(spusteno), 1); self.assertEqual(spusteno[0].read_bytes(), INSTALATOR); self.assertTrue(spusteno[0].name.endswith('9.9.9.exe'))
        self.assertFalse(list(spusteno[0].parent.glob('*.part')))

    def test_nesedi_soucet_nic_nespusti(self):
        g = vydani(soucet='a' * 64); self.zkontroluj(otevri=g, vynutit=True); spusteno = []
        with mock.patch.object(verze, 'VERZE', '1.0.0'):
            aktualizace.aktualizuj(self.app, otevri=g, spust=spusteno.append, cekat=0); p = self.cekej({'chyba', 'spoustim'})
        self.assertEqual(p['faze'], 'chyba'); self.assertIn('kontrolní součet nesedí', p['text']); self.assertEqual(spusteno, [])
        self.assertFalse(list((self.slozky['instance'] / 'aktualizace').glob('*')), 'nic stažené nezůstane')

    def test_bez_nove_verze_nic(self):
        self.zkontroluj(otevri=vydani(), vynutit=True)
        with mock.patch.object(verze, 'VERZE', '9.9.9'): self.assertFalse(aktualizace.aktualizuj(self.app, otevri=vydani(), spust=lambda e: None))

    def test_adresy_a_okno(self):
        self.zkontroluj(otevri=vydani(), vynutit=True)
        with mock.patch.object(verze, 'VERZE', '1.0.0'), mock.patch.object(aktualizace, 'aktualizuj', return_value=True) as a:
            self.assertTrue(self.k.get('/aktualizace/okno').get_json()['lze_instalovat'])
            r = self.k.post('/aktualizace/instalovat', data={'csrf_token': self.token()}); self.assertEqual(r.status_code, 200); a.assert_called_once()
        self.assertIn('prubeh', self.k.get('/aktualizace/prubeh').get_json())

    def test_instalator_spousti_tichou_instalaci_a_znovu_aplikaci(self):
        with mock.patch('subprocess.Popen') as popen: aktualizace._instalator_spust(Path('C:/x/osvc.exe'))
        self.assertEqual(popen.call_args.args[0][1:], ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SPUSTIT=1'])
        iss = (Path.cwd() / 'scripts' / 'windows' / 'osvc.iss').read_text(encoding='utf-8-sig')
        self.assertIn("ExpandConstant('{param:SPUSTIT|0}') = '1'", iss); self.assertIn('Check: SpustitPoAktualizaci', iss)


class Server(unittest.TestCase):
    def test_server_jen_verze_a_osvc_nasad(self):
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH'], 'OSVC_AKTUALIZACE_REPO': REPO})
        k = app.test_client()
        with k.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1
        html = k.get('/').get_data(as_text=True)
        self.assertIn('data-verze-otevrit', html); self.assertIn('Server se aktualizuje přes osvc-nasad.', html)
        d = k.get('/aktualizace/okno').get_json(); self.assertFalse(d['samostatna']); self.assertFalse(d['nova'])
        self.assertRegex(d['verze'], r'^\d+\.\d+\.\d+ \([0-9a-f]{7}\)$', 'server: číslo vydání a zkratka commitu'); self.assertIn(f"Verze {d['verze']}", html)
        self.assertIn('Server se aktualizuje přes osvc-nasad.', k.get('/settings?tab=aktualizace').get_data(as_text=True))
        for url in ('/aktualizace/zkontrolovat', '/aktualizace/instalovat'): self.assertEqual(k.post(url).status_code, 404, url)
        self.assertEqual(k.get('/aktualizace/prubeh').status_code, 404)


if __name__ == '__main__':
    unittest.main()
