"""I4 – samostatná instalace pro Windows: přenosné zámky, české datum bez %-d, plánovač (denní záloha, synchronizace),
spouštěč (první spuštění, jedna instance, cizí port, zastavení), ukončení z aplikace, šablony bez vypnutí počítače,
sestavení (cesty vložitelného Pythonu). Windows větve (LockFileEx, MessageBox) ověří až zkušební instalace na PC.
Běží jen přes tests/spust.sh."""
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from osvc_app import cas, create_app, instalace, zamky

TMP = tempfile.TemporaryDirectory()
KOREN = Path.cwd()   # tests/spust.sh spouští testy z kořene repozitáře


def cekej(podminka, limit=20):
    konec = time.time() + limit
    while time.time() < konec:
        try:
            v = podminka()
            if v: return v
        except OSError: pass
        time.sleep(0.2)
    return None


class Zamky(unittest.TestCase):
    def test_sdileny_vyhradni_a_zmena(self):
        cesta = Path(TMP.name) / 'z.lock'
        with open(cesta, 'a') as a, open(cesta, 'a') as b, open(cesta, 'a') as c:
            zamky.zamkni(a); zamky.zamkni(b)                     # dva sdílené vedle sebe
            with self.assertRaises(BlockingIOError): zamky.zamkni(c, vyhradni=True, necekat=True)
            zamky.uvolni(a); zamky.uvolni(b)
            zamky.zamkni(c, vyhradni=True, necekat=True)
            with self.assertRaises(BlockingIOError): zamky.zamkni(a, necekat=True)
            zamky.zamkni(c)                                      # změna na sdílený
            zamky.zamkni(a, necekat=True)
        with open(cesta, 'a') as d: zamky.zamkni(d, vyhradni=True, necekat=True)   # zavření souboru zámky uvolní

    def test_nikde_neni_fcntl_ani_procento_minus(self):
        for p in (KOREN / 'osvc_app').rglob('*.py'):
            if p.name == 'zamky.py': continue
            text = p.read_text(encoding='utf-8')
            self.assertNotIn('fcntl', text, p); self.assertNotRegex(text, r"strftime\([^)]*%-", p)


class Datum(unittest.TestCase):
    def test_cesky(self):
        self.assertEqual(cas.datum(date(2026, 1, 5)), '5. 1. 2026')
        self.assertEqual(cas.datum(datetime(2026, 11, 18, 9, 3), s_casem=True), '18. 11. 2026 09:03')


class Samostatna(unittest.TestCase):
    """Aplikace přes OSVC_CONFIG po průvodci: Napájení jen „Zastavit aplikaci“ (přes spouštěč), zálohy místní."""
    @classmethod
    def setUpClass(cls):
        konf = Path(TMP.name) / 's' / 'osvc.conf'; instalace.zapis_nastaveni(konf, Path(TMP.name) / 's' / 'data')
        cls.slozky = instalace.priprav(instalace.nacti(konf))
        os.environ['OSVC_CONFIG'] = str(konf)
        try: cls.app = create_app({'TESTING': True})
        finally: os.environ.pop('OSVC_CONFIG')
        cls.k = cls.app.test_client()
        t = cls.token(cls, '/pruvodce')
        r = cls.k.post('/pruvodce', data={'csrf_token': t, 'zamestnani': 'ne', 'pojistovna': '111', 'social_zalohy': 'neplati', 'health_zalohy': 'neplati', 'vydaje': 'actual', 'dane_rezim': 'standard', 'prvni_zahajeni': 'ne', 'ico': '12345678', 'name': 'Test', 'number': '1', 'city': 'Brno', 'zip': '60200',
                                          'username': 'test', 'password': 'heslo-12345', 'password2': 'heslo-12345'})
        assert r.status_code == 302, r.status_code

    def token(self, url='/settings'):
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.k.get(url).get_data(as_text=True)).group(1)

    def test_nastaveni(self):
        c = self.app.config
        self.assertEqual((c['SYSTEM_SHUTDOWN_ENABLED'], c['INCOME_SYNC_SCHEDULER'], c['OSVC_ZALOHY_DIR']), (False, 'spoustec-15min', str(self.slozky['zalohy'])))

    def test_napajeni_jen_zastavit(self):
        html = self.k.get('/').get_data(as_text=True)
        self.assertIn('data-system-choice="stop"', html); self.assertNotIn('data-system-choice="poweroff"', html)
        self.assertIn('zástupcem OSVČ evidence v nabídce Start' if os.name == 'nt' else 'sudo systemctl start osvc-evidence', html)
        zastav = mock.Mock(); self.app.config['OSVC_ZASTAV'] = zastav
        try: r = self.k.post('/system/stop', data={'csrf_token': self.token()})
        finally: self.app.config.pop('OSVC_ZASTAV')
        self.assertEqual(r.status_code, 202); zastav.assert_called_once(); self.assertIn('ukončuje', r.get_json()['message'])
        self.assertEqual(self.k.post('/system/shutdown', data={'csrf_token': self.token()}).status_code, 503)

    def test_mistni_zalohy_v_nastaveni(self):
        from osvc_app import zaloha_db
        with self.app.app_context():
            self.assertEqual(zaloha_db.stav_samostatne()[0]['state'], 'unknown')
            cil = zaloha_db.vytvor(self.slozky['zalohy'])
            self.assertEqual(zaloha_db.stav_samostatne()[0]['state'], 'ok')
        html = self.k.get('/settings').get_data(as_text=True)
        self.assertIn('Automatické zálohy</h3>', html); self.assertIn('Denní záloha databáze', html); self.assertIn(str(self.slozky['zalohy']), html)
        os.utime(cil, (time.time() - 4 * 86400,) * 2)
        with self.app.app_context(): self.assertEqual(zaloha_db.stav_samostatne()[0]['state'], 'old')

    def test_uklid_a_je_cas(self):
        from osvc_app import zaloha_db
        slozka = Path(TMP.name) / 'uklid'; slozka.mkdir()
        self.assertTrue(zaloha_db.je_cas(slozka))
        for i in range(33): (slozka / f'osvc_2026-10-{i // 2 + 1:02d}_00-00-{i:02d}.sqlite3.gz').write_bytes(b'x')
        self.assertEqual(len(zaloha_db.uklid(slozka)), 3); self.assertEqual(len(zaloha_db.seznam(slozka)), 30)
        self.assertEqual(zaloha_db.seznam(slozka)[0].name, 'osvc_2026-10-02_00-00-03.sqlite3.gz')
        self.assertFalse(zaloha_db.je_cas(slozka))
        self.assertTrue(zaloha_db.je_cas(slozka, ted=datetime.now() + timedelta(hours=25)))

    def test_planovana_synchronizace_s_vypnutym_modulem(self):
        from osvc_app import moduly
        from osvc_app.income_sources import planovana_synchronizace
        vystup = []
        with self.app.app_context():
            moduly.uloz('externi_web', zapnuto=False)
            v = planovana_synchronizace(lambda t, chyba=False: vystup.append(t))
        self.assertEqual((v['chyb'], v['hotovo'], v['modul_vypnuty']), (0, 0, True))
        self.assertTrue(json.loads((self.slozky['instance'] / 'income-sync-last.json').read_text())['ok'])
        with self.app.app_context(): moduly.uloz('externi_web', zapnuto=True)


class Spoustec(unittest.TestCase):
    def spust(self, *args):
        return subprocess.Popen([sys.executable, '-m', 'osvc_app.spoustec', *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=KOREN)

    def test_prvni_spusteni_jedna_instance_a_zastaveni(self):
        koren = Path(TMP.name) / 'sp'; konf = koren / 'osvc.conf'; data = koren / 'data'
        proc = self.spust('spust', '--config', str(konf), '--data', str(data))
        try:
            self.assertTrue(cekej(konf.exists), 'první spuštění založí nastavení')
            port = instalace.nacti(konf)['PORT']; self.assertIn(port, range(8765, 8800))
            html = cekej(lambda: urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=2).read().decode())
            self.assertIn('Vítejte v evidenci OSVČ', html, 'nová instalace = průvodce')
            self.assertTrue(cekej(lambda: list((data / 'zalohy').glob('osvc_*.sqlite3.gz'))), 'plánovač hned udělá první zálohu')
            self.assertTrue((data / 'instance' / 'spoustec.pid').is_file())
            druhy = subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'spust', '--config', str(konf)], capture_output=True, text=True, timeout=30, cwd=KOREN)
            self.assertEqual(druhy.returncode, 0); self.assertIn('už běží', druhy.stdout)
            z = subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'zastav', '--config', str(konf)], capture_output=True, text=True, timeout=30, cwd=KOREN)
            self.assertIn('ukončeno', z.stdout)
            proc.wait(timeout=15)
            self.assertFalse((data / 'instance' / 'spoustec.pid').exists())
            log = (data / 'logy' / 'osvc.log').read_text(encoding='utf-8')
            self.assertIn('spuštěno na', log); self.assertIn('denní záloha databáze', log)
        finally:
            if proc.poll() is None: proc.kill()
            proc.communicate(timeout=10)

    def test_hned_po_zastaveni_znovu(self):
        """Aktualizace = zastavit starou verzi a hned spustit novou; port po ukončení (TIME_WAIT) nesmí vypadat jako cizí program."""
        koren = Path(TMP.name) / 'znovu'; konf = koren / 'osvc.conf'
        for kolo in range(2):
            proc = self.spust('spust', '--config', str(konf), '--data', str(koren / 'data'), '--bez-planovace')
            try:
                port = cekej(lambda: konf.exists() and instalace.nacti(konf)['PORT'])
                self.assertTrue(cekej(lambda: urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=2).read()), f'kolo {kolo}')
            finally:
                subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'zastav', '--config', str(konf)], capture_output=True, timeout=30, cwd=KOREN)
                vystup = proc.communicate(timeout=15)[0]
            self.assertNotIn('jiný program', vystup, f'kolo {kolo}')

    def test_cizi_program_na_portu(self):
        s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1); port = s.getsockname()[1]
        konf = Path(TMP.name) / 'cizi' / 'osvc.conf'; instalace.zapis_nastaveni(konf, Path(TMP.name) / 'cizi' / 'data', port)
        try:
            proc = self.spust('spust', '--config', str(konf)); vystup = proc.communicate(timeout=30)[0]
        finally: s.close()
        self.assertEqual(proc.returncode, 3); self.assertIn('používá jiný program', vystup)

    def test_zastav_kdyz_nebezi(self):
        self.assertEqual(subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'zastav', '--config', str(Path(TMP.name) / 'nic.conf')], cwd=KOREN).returncode, 0)


class Sestaveni(unittest.TestCase):
    def test_cesty_vlozitelneho_pythonu(self):
        sys.path.insert(0, str(KOREN / 'scripts' / 'windows'))
        try: import sestav
        finally: sys.path.pop(0)
        z = Path(TMP.name) / 'emb.zip'
        with zipfile.ZipFile(z, 'w') as f: f.writestr(sestav.PTH, 'python314.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n')
        cil = Path(TMP.name) / 'emb'; sestav.python_pro_windows(z, cil)
        self.assertEqual((cil / sestav.PTH).read_text().split(), ['python314.zip', '.', r'Lib\site-packages', r'..\app', 'import', 'site'])
        self.assertTrue(sestav.SPUSTIT_CMD.isascii()); self.assertIn('--data', sestav.SPUSTIT_CMD)
        iss = (KOREN / 'scripts' / 'windows' / 'osvc.iss').read_text(encoding='utf-8')
        self.assertIn('#define Verze "0.0.0"', iss); self.assertIn('PrivilegesRequired=lowest', iss); self.assertIn('Czech.isl', iss)
        self.assertNotIn('{app}\\data', iss, 'data nesmí být ve složce programu (odinstalace je nesmaže)')
        self.assertTrue((KOREN / 'sql' / 'sqlite' / 'schema.sql').is_file()); self.assertIn('sql/sqlite', sestav.KOD)


class WindowsZapisSouboru(unittest.TestCase):
    """Chyby ze zkoušky na Windows 11 (2026-11-18): text bez kódování (cp1250), fsync složky / souboru jen pro čtení, přepsání
    souboru drženého antivirem. Windows tu není – kontrola zdrojového kódu + chování funkcí se simulovaným os.name."""
    def test_zadny_text_bez_kodovani(self):
        for p in (KOREN / 'osvc_app').rglob('*.py'):
            text = p.read_text(encoding='utf-8')
            self.assertNotIn('.read_text()', text, p)
            self.assertNotIn(".open('a')", text, f'{p}: zámkové soubory binárně (ab)')
            for m in re.finditer(r'\.write_text\((.*)', text): self.assertIn('encoding', m.group(1) + text[m.end():m.end() + 200], p)
            self.assertNotRegex(text, r"fdopen\([^)]*'w'\)", p)
            if p.name != 'zamky.py':
                self.assertNotIn('O_RDONLY', text, f'{p}: fsync složky jen přes zamky.zapis_slozku'); self.assertNotIn('os.replace(', text, f'{p}: přes zamky.nahrad')

    def test_windows_slozka_a_opakovane_prepsani(self):
        with mock.patch.object(zamky.os, 'name', 'nt'), mock.patch.object(zamky.os, 'open', side_effect=AssertionError('složka se ve Windows neotevírá')):
            zamky.zapis_slozku(TMP.name)
        a = Path(TMP.name) / 'a.txt'; b = Path(TMP.name) / 'b.txt'; a.write_text('nový', encoding='utf-8'); b.write_text('starý', encoding='utf-8')
        zamky.zapis_soubor(a)
        skutecne = os.replace; pokusy = []
        def drzeny(src, dst):
            pokusy.append(1)
            if len(pokusy) < 3: raise PermissionError(32, 'soubor používá jiný proces')
            return skutecne(src, dst)
        with mock.patch.object(zamky.os, 'name', 'nt'), mock.patch.object(zamky.os, 'replace', side_effect=drzeny), mock.patch('time.sleep'):
            zamky.nahrad(a, b)
        self.assertEqual((len(pokusy), b.read_text(encoding='utf-8')), (3, 'nový'))
        with mock.patch.object(zamky.os, 'replace', side_effect=PermissionError(13, 'x')):
            self.assertRaises(PermissionError, zamky.nahrad, b, a)   # Linux: hned chyba, žádné čekání

    def test_celý_beh_bez_vychoziho_kodovani(self):
        """Spouštěč s -X warn_default_encoding -W error::EncodingWarning: každé čtení/zápis textu bez kódování = chyba
        (ve Windows by se četlo v cp1250). Průvodce, Přehled, Nastavení, Roční přehled, PDF a záloha musí projít."""
        import http.cookiejar
        koren = Path(TMP.name) / 'kod'; konf = koren / 'osvc.conf'; data = koren / 'data'
        proc = subprocess.Popen([sys.executable, '-X', 'warn_default_encoding', '-W', 'error::EncodingWarning', '-m', 'osvc_app.spoustec', 'spust',
                                 '--config', str(konf), '--data', str(data)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=KOREN)
        try:
            self.assertTrue(cekej(konf.exists)); port = instalace.nacti(konf)['PORT']; url = f'http://127.0.0.1:{port}'
            o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            html = cekej(lambda: o.open(url + '/pruvodce', timeout=5).read().decode())
            t = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)
            from urllib.parse import urlencode
            r = o.open(url + '/pruvodce', urlencode({'csrf_token': t, 'zamestnani': 'ne', 'pojistovna': '111', 'social_zalohy': 'neplati', 'health_zalohy': 'neplati', 'vydaje': 'actual', 'dane_rezim': 'standard', 'prvni_zahajeni': 'ne', 'ico': '12345678', 'name': 'Žluťoučký kůň', 'street': 'Šťastná', 'number': '1',
                       'city': 'Česká Lípa', 'zip': '47001', 'username': 'test', 'password': 'heslo-12345', 'password2': 'heslo-12345', 'modul_doprava': '1'}).encode(), timeout=30)
            html2 = r.read().decode(); self.assertEqual(r.status, 200); self.assertIn('Ještě chvilku', html2, 'se zapnutou Dopravou strana 2')
            t = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html2).group(1)   # po přihlášení nová session
            r = o.open(url + '/pruvodce/dalsi', urlencode({'csrf_token': t, 'vozidlo_nazev': 'Škoda Fabia', 'vozidlo_rezim': 'actual', 'dalsi': 'hotovo'}).encode(), timeout=30)
            self.assertIn('Přehled', r.read().decode(), 'po průvodci Přehled (ve Windows tu byl pád)')
            for cesta in ('/', '/settings', '/annual', '/annual/pdf', '/payments/income', '/trips'):
                self.assertEqual(o.open(url + cesta, timeout=30).status, 200, cesta)
            # Zpět + znovu odeslat průvodce = Přehled s hláškou, ne „400 Bad Request“
            r = o.open(url + '/pruvodce', urlencode({'csrf_token': t, 'ico': '12345678'}).encode(), timeout=10)
            self.assertIn('Průvodce už je dokončený', r.read().decode())
            self.assertTrue(cekej(lambda: list((data / 'zalohy').glob('osvc_*.sqlite3.gz'))))
        finally:
            proc.terminate(); vystup = proc.communicate(timeout=15)[0]
        log = (data / 'logy' / 'osvc.log').read_text(encoding='utf-8')
        for chyba in ('EncodingWarning', 'Traceback', 'selhala', 'nezachycená'): self.assertNotIn(chyba, log + vystup, chyba)
        self.assertTrue((data / 'logy' / 'pady.log').exists())


class CsrfCesky(unittest.TestCase):
    def test_zastaraly_formular(self):
        app = create_app({'TESTING': True, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ.get('DB_PATH', str(Path(TMP.name) / 'x.sqlite3'))})
        k = app.test_client()
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        r = k.post('/login', data={'username': 'x', 'password': 'y'}, headers={'Referer': 'http://localhost/login'})
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 400); self.assertIn('Formulář je zastaralý', html); self.assertIn('href="http://localhost/login"', html)
        self.assertNotIn('Bad Request', html)
        self.assertIn('href="/"', k.post('/login', data={}, headers={'Referer': 'http://jinde.cz/'}).get_data(as_text=True))
        r = k.post('/pruvodce/ares', data={'ico': '12345678'}); self.assertEqual(r.status_code, 400); self.assertIn('Načtěte ji znovu', r.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
