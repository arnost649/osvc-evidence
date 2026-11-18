"""Síťový přístup samostatné instalace: volba v instance/sit.json, adaptéry (Linux ip -j, Windows PowerShell), naslouchání
(vždy localhost, v domácí síti i zvolená IP; zmizelá IP = jen localhost a hláška), Nastavení (potvrzení rizik, jen adresy
počítače, restart), firewall Windows (UAC, jen port, profil Soukromá, program aplikace), Linux bez zásahu do firewallu,
server majitele beze změny. Běží jen přes tests/spust.sh (i v CI)."""
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock
from osvc_app import create_app, instalace, sit

TMP = tempfile.TemporaryDirectory()
KOREN = Path.cwd()
IP_A = json.dumps([{'ifname': 'lo', 'addr_info': [{'family': 'inet', 'local': '127.0.0.1'}]},
                   {'ifname': 'wlan0', 'addr_info': [{'family': 'inet', 'local': '198.51.100.20'}, {'family': 'inet6', 'local': 'fe80::1'}]},
                   {'ifname': 'eth0', 'addr_info': [{'family': 'inet', 'local': '169.254.3.3'}, {'family': 'inet', 'local': '203.0.113.5'}]}])
WIN_A = json.dumps([{'InterfaceAlias': 'Wi-Fi', 'IPAddress': '198.51.100.20'}, {'InterfaceAlias': 'Loopback Pseudo-Interface 1', 'IPAddress': '127.0.0.1'},
                    {'InterfaceAlias': 'Ethernet', 'IPAddress': '203.0.113.5'}])
WIN_P = json.dumps([{'InterfaceAlias': 'Wi-Fi', 'NetworkCategory': 1}, {'InterfaceAlias': 'Ethernet', 'NetworkCategory': 0}])


def cekej(podminka, limit=30):
    konec = time.time() + limit
    while time.time() < konec:
        try:
            v = podminka()
            if v: return v
        except OSError: pass
        time.sleep(0.3)
    return None


class Zaklad(unittest.TestCase):
    def test_platna_ip(self):
        self.assertEqual(sit.platna_ip(' 198.51.100.15 '), '198.51.100.15')
        for spatna in ('127.0.0.1', '0.0.0.0', '169.254.1.1', '224.0.0.1', '::1', 'abc', '', None): self.assertIsNone(sit.platna_ip(spatna), spatna)

    def test_uloz_a_nacti(self):
        inst = Path(TMP.name) / 'z'
        self.assertEqual(sit.nacti(inst)['rezim'], 'lokalni', 'bez souboru = jen tento počítač')
        sit.uloz(inst, 'domaci', '198.51.100.20'); self.assertEqual((sit.nacti(inst)['rezim'], sit.nacti(inst)['ip']), ('domaci', '198.51.100.20'))
        self.assertRaises(ValueError, sit.uloz, inst, 'domaci', '127.0.0.1'); self.assertRaises(ValueError, sit.uloz, inst, 'vsude')
        (inst / sit.SOUBOR).write_text('{poškozený', encoding='utf-8'); self.assertEqual(sit.nacti(inst)['rezim'], 'lokalni')
        (inst / sit.SOUBOR).write_text(json.dumps({'rezim': 'domaci', 'ip': '0.0.0.0'}), encoding='utf-8'); self.assertEqual(sit.nacti(inst)['rezim'], 'lokalni')

    def test_adaptery_linux_a_windows(self):
        a = sit.adaptery_linux(IP_A, vychozi='198.51.100.20')
        self.assertEqual([(x['nazev'], x['ip'], x['brana']) for x in a], [('wlan0', '198.51.100.20', True), ('eth0', '203.0.113.5', False)])
        w = sit.adaptery_windows(WIN_A, WIN_P, vychozi='203.0.113.5')
        self.assertEqual([(x['nazev'], x['ip'], x['brana'], x['kategorie']) for x in w], [('Wi-Fi', '198.51.100.20', False, 'Soukromá'), ('Ethernet', '203.0.113.5', True, 'Veřejná')])
        self.assertEqual(sit.adaptery_windows(json.dumps({'InterfaceAlias': 'Wi-Fi', 'IPAddress': '198.51.100.20'}))[0]['ip'], '198.51.100.20', 'jeden adaptér = objekt, ne seznam')

    def test_adaptery_na_tomto_pocitaci(self):
        seznam = sit.adaptery()
        self.assertTrue(all(sit.platna_ip(a['ip']) for a in seznam))
        if seznam and sit.vychozi_ip(): self.assertTrue(seznam[0]['brana'], 'adaptér s výchozí trasou je první')

    def test_naslouchani(self):
        self.assertEqual(sit.naslouchani({'rezim': 'lokalni', 'ip': ''}, 8765, set()), (['127.0.0.1:8765'], None))
        self.assertEqual(sit.naslouchani({'rezim': 'domaci', 'ip': '198.51.100.20'}, 8765, {'198.51.100.20'}), (['127.0.0.1:8765', '198.51.100.20:8765'], None))
        seznam, chyba = sit.naslouchani({'rezim': 'domaci', 'ip': '198.51.100.99'}, 8765, {'198.51.100.20'})
        self.assertEqual(seznam, ['127.0.0.1:8765']); self.assertIn('198.51.100.99 teď na tomto počítači není', chyba)


class FirewallWindows(unittest.TestCase):
    def test_pravidlo_jen_port_soukroma_sit_a_program(self):
        volani = []
        def spust(prikaz, timeout=15):
            volani.append(prikaz); return subprocess.CompletedProcess(prikaz, 1 if prikaz[:2] == ['netsh', 'advfirewall'] else 0, '', '')
        with mock.patch.object(sit.os, 'name', 'nt'), mock.patch.object(sit, '_spust', side_effect=spust):
            v = sit.firewall('domaci', 8765)
        self.assertEqual(v['stav'], 'ok')
        ps = ' '.join(volani[-1])
        for cast in ('-Verb RunAs', 'add rule name="OSVC evidence"', 'dir=in', 'protocol=TCP', 'localport=8765', 'profile=private', 'program='):
            self.assertIn(cast, ps)

    def test_uac_zamitnuto_a_odebrani(self):
        def spust(prikaz, timeout=15):
            if prikaz[:2] == ['netsh', 'advfirewall']: return subprocess.CompletedProcess(prikaz, 0, '', '')   # pravidlo existuje
            return subprocess.CompletedProcess(prikaz, 1223 if 'add rule' in ' '.join(prikaz) else 0, '', '')
        with mock.patch.object(sit.os, 'name', 'nt'), mock.patch.object(sit, '_spust', side_effect=spust) as m:
            self.assertEqual(sit.firewall('domaci', 8765)['stav'], 'zamitnuto')
            self.assertEqual(sit.firewall('lokalni', 8765)['stav'], 'ok')
            self.assertIn('delete rule name="OSVC evidence"', ' '.join(m.call_args_list[-1].args[0]))

    def test_linux_bez_zasahu(self):
        with mock.patch.object(sit.os, 'name', 'posix'), mock.patch.object(sit, '_spust', side_effect=AssertionError('na Linuxu se nic nespouští')):
            v = sit.firewall('domaci', 8765)
        self.assertEqual(v['stav'], 'bez_zasahu'); self.assertIn('sudo ufw allow 8765/tcp', v['zprava'])
        zdroj = (KOREN / 'osvc_app' / 'sit.py').read_text(encoding='utf-8')
        self.assertNotRegex(zdroj, r"\['(ufw|iptables|nft|firewall-cmd)'", 'Linux: žádný zásah do firewallu')


class Nastaveni(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        konf = Path(TMP.name) / 'n' / 'osvc.conf'; instalace.zapis_nastaveni(konf, konf.parent / 'data', 8771)
        cls.slozky = instalace.priprav(instalace.nacti(konf))
        os.environ['OSVC_CONFIG'] = str(konf)
        try: cls.app = create_app({'TESTING': True})
        finally: os.environ.pop('OSVC_CONFIG')
        cls.k = cls.app.test_client()
        t = cls.token(cls, '/pruvodce')
        cls.k.post('/pruvodce', data={'csrf_token': t, 'ico': '12345678', 'name': 'Test', 'number': '1', 'city': 'Brno', 'zip': '60200', 'zamestnani': 'ne',
                                      'pojistovna': '111', 'social_zalohy': 'neplati', 'health_zalohy': 'neplati', 'vydaje': 'actual', 'dane_rezim': 'standard',
                                      'prvni_zahajeni': 'ne', 'username': 'test', 'password': 'heslo-12345', 'password2': 'heslo-12345'})

    def token(self, url='/settings'):
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.k.get(url).get_data(as_text=True)).group(1)

    def test_zalozka_a_vychozi_stav(self):
        html = self.k.get('/settings').get_data(as_text=True)
        self.assertIn('Síťový přístup', html); self.assertIn('jen na tomto počítači', html); self.assertIn(sit.UPOZORNENI, html)
        self.assertRegex(html, r'name="rezim" value="lokalni" checked')
        r = self.k.get('/settings/sit/adaptery'); self.assertEqual(r.status_code, 200); self.assertIn('adaptery', r.get_json())

    def test_bez_potvrzeni_a_cizi_adresa_nic_neulozi(self):
        with mock.patch.object(sit, 'adresy_pocitace', return_value={'198.51.100.20'}), mock.patch.object(sit, 'firewall', side_effect=AssertionError('nesmí')):
            self.k.post('/settings/sit', data={'csrf_token': self.token(), 'rezim': 'domaci', 'ip': '198.51.100.20'})
            self.assertIn('potvrďte', self.k.get('/settings').get_data(as_text=True))
            self.k.post('/settings/sit', data={'csrf_token': self.token(), 'rezim': 'domaci', 'ip': '198.51.100.99', 'potvrzeni': 'ano'})
            self.assertIn('Zvolená adresa na tomto počítači není', self.k.get('/settings').get_data(as_text=True))
        self.assertEqual(sit.nacti(self.slozky['instance'])['rezim'], 'lokalni')

    def test_zapnuti_restart_a_vypnuti(self):
        restart = mock.Mock(); self.app.config['OSVC_RESTART'] = restart
        try:
            with mock.patch.object(sit, 'adresy_pocitace', return_value={'198.51.100.20'}), \
                 mock.patch.object(sit, 'firewall', return_value={'stav': 'bez_zasahu', 'zprava': sit.linux_rada(8771)}) as fw:
                r = self.k.post('/settings/sit', data={'csrf_token': self.token(), 'rezim': 'domaci', 'ip': '198.51.100.20', 'potvrzeni': 'ano'})
                html = r.get_data(as_text=True)
                self.assertIn('http://198.51.100.20:8771/', html); self.assertIn('sudo ufw allow 8771/tcp', html); restart.assert_called_once()
                fw.assert_called_with('domaci', 8771)
                self.assertEqual(sit.nacti(self.slozky['instance'])['ip'], '198.51.100.20')
                self.k.post('/settings/sit', data={'csrf_token': self.token(), 'rezim': 'lokalni'})
                fw.assert_called_with('lokalni', 8771); self.assertEqual(sit.nacti(self.slozky['instance'])['rezim'], 'lokalni')
        finally: self.app.config.pop('OSVC_RESTART')

    def test_hlaska_zmizela_ip(self):
        sit.zapis_stav(self.slozky['instance'], {'rezim': 'domaci', 'ip': '198.51.100.99'}, 8771, ['127.0.0.1:8771'], 'Adresa 198.51.100.99 teď na tomto počítači není (jiná síť?) – aplikace běží jen na tomto počítači.')
        try: self.assertIn('198.51.100.99 teď na tomto počítači není', self.k.get('/settings').get_data(as_text=True))
        finally: (self.slozky['instance'] / sit.STAV).unlink()


class Server(unittest.TestCase):
    def test_server_beze_zmeny(self):
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH']})
        k = app.test_client()
        with k.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1
        self.assertNotIn('Síťový přístup', k.get('/settings').get_data(as_text=True))
        self.assertEqual(k.post('/settings/sit', data={'rezim': 'domaci'}).status_code, 404); self.assertEqual(k.get('/settings/sit/adaptery').status_code, 404)


class Spoustec(unittest.TestCase):
    """Skutečný běh: v domácí síti odpovídá i na adrese počítače; zmizelá adresa = jen localhost; restart z Nastavení."""
    def setUp(self):
        self.ip = sit.vychozi_ip()
        if not self.ip: self.skipTest('počítač nemá síťovou adresu IPv4')
        self.koren = Path(TMP.name) / f's{time.time_ns()}'; self.konf = self.koren / 'osvc.conf'
        r = subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'init', '--config', str(self.konf), '--data', str(self.koren / 'data'), '--port', 'auto'], capture_output=True, text=True, cwd=KOREN)
        self.assertEqual(r.returncode, 0, r.stderr); self.port = instalace.nacti(self.konf)['PORT']; self.inst = self.koren / 'data' / 'instance'

    def tearDown(self):
        if hasattr(self, 'konf'): subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'zastav', '--config', str(self.konf)], capture_output=True, timeout=30, cwd=KOREN)

    def spust(self):
        return subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'osvc_app.spoustec', 'spust', '--config', str(self.konf), '--bez-planovace'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=KOREN)

    def odpovida(self, host):
        try:
            with urllib.request.urlopen(f'http://{host}:{self.port}/login', timeout=2) as r: return r.status == 200
        except OSError: return False

    def test_domaci_sit_a_zmizela_adresa(self):
        sit.uloz(self.inst, 'domaci', self.ip); p = self.spust()
        try:
            self.assertTrue(cekej(lambda: self.odpovida('127.0.0.1'))); self.assertTrue(self.odpovida(self.ip), 'odpovídá i na adrese počítače')
            self.assertEqual(sit.stav(self.inst)['naslouchani'], [f'127.0.0.1:{self.port}', f'{self.ip}:{self.port}'])
        finally: self.tearDown(); p.wait(timeout=15)
        sit.uloz(self.inst, 'domaci', '192.0.2.77'); p = self.spust()   # adresa z dokumentačního rozsahu – na počítači není
        try:
            self.assertTrue(cekej(lambda: self.odpovida('127.0.0.1'))); self.assertFalse(self.odpovida(self.ip))
            self.assertIn('192.0.2.77 teď na tomto počítači není', sit.stav(self.inst)['chyba'])
        finally: self.tearDown(); p.wait(timeout=15)

    def test_restart_z_nastaveni(self):
        p = self.spust(); u = f'http://127.0.0.1:{self.port}'
        o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def post(cesta, data, token_z):
            t = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', o.open(u + token_z, timeout=10).read().decode()).group(1)
            return o.open(u + cesta, urllib.parse.urlencode({**data, 'csrf_token': t}).encode(), timeout=30).read().decode()
        try:
            self.assertTrue(cekej(lambda: self.odpovida('127.0.0.1')))
            post('/pruvodce', {'ico': '12345678', 'name': 'Test', 'number': '1', 'city': 'Brno', 'zip': '60200', 'zamestnani': 'ne', 'pojistovna': '111',
                               'social_zalohy': 'neplati', 'health_zalohy': 'neplati', 'vydaje': 'actual', 'dane_rezim': 'standard', 'prvni_zahajeni': 'ne',
                               'username': 'test', 'password': 'heslo-12345', 'password2': 'heslo-12345'}, '/pruvodce')
            html = post('/settings/sit', {'rezim': 'domaci', 'ip': self.ip, 'potvrzeni': 'ano'}, '/settings')
            self.assertIn(f'http://{self.ip}:{self.port}/', html); self.assertIn('Aplikace se restartuje', html)
            p.wait(timeout=20)   # původní běh skončil, nová kopie převzala port
            self.assertTrue(cekej(lambda: self.odpovida(self.ip), 40), 'po restartu odpovídá v síti')
            self.assertTrue(self.odpovida('127.0.0.1'))
        finally:
            if p.poll() is None: p.kill()


if __name__ == '__main__':
    unittest.main()
