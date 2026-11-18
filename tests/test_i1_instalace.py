"""I1 – samostatná instalace: soubor nastavení (OSVC_CONFIG), složka dat, tajný klíč, prázdná databáze s výchozími daty, spouštěč.
Vše v dočasné složce; na serveru (bez OSVC_CONFIG) se nic nemění. Běží jen přes tests/spust.sh."""
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from osvc_app import instalace, sqlite_db

TMP = tempfile.TemporaryDirectory()


def volny_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


class Nastaveni(unittest.TestCase):
    def test_init_a_priprava(self):
        konf = Path(TMP.name) / 'a' / 'osvc.conf'; data = Path(TMP.name) / 'a' / 'data'
        instalace.zapis_nastaveni(konf, data, 8123)
        with self.assertRaises(FileExistsError): instalace.zapis_nastaveni(konf, data)
        h = instalace.nacti(konf)
        self.assertEqual((h['PORT'], h['HOST'], h['DATA_DIR']), (8123, '127.0.0.1', str(data)))
        s = instalace.priprav(h)
        for k in ('uploads', 'instance'): self.assertTrue(s[k].is_dir())
        self.assertEqual(stat.S_IMODE(s['klic'].stat().st_mode), 0o600)
        klic = s['klic'].read_text(); instalace.priprav(h)
        self.assertEqual(s['klic'].read_text(), klic, 'tajný klíč se při dalším spuštění nemění')
        conn = sqlite_db.otevri(s['db'])
        self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM system_types').fetchone()[0], 6)
        self.assertEqual(conn.execute("SELECT base_rate_per_km FROM travel_rates WHERE fuel_type='Natural 95'").fetchone()[0], __import__('decimal').Decimal('5.900'))
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0], 0)

    def test_neplatne_nastaveni(self):
        konf = Path(TMP.name) / 'zly.conf'
        konf.write_text('PORT=80000\n'); self.assertRaises(ValueError, instalace.nacti, konf)
        konf.write_text('DATA_DIR=/x\nPORT=abc\n'); self.assertRaises(ValueError, instalace.nacti, konf)
        self.assertRaises(FileNotFoundError, instalace.nacti, Path(TMP.name) / 'neni.conf')


class PrazdnaInstalace(unittest.TestCase):
    """Aplikace přes OSVC_CONFIG na prázdné databázi: všechny stránky fungují, dá se zapisovat."""
    @classmethod
    def setUpClass(cls):
        cls.konf = Path(TMP.name) / 'b' / 'osvc.conf'
        instalace.zapis_nastaveni(cls.konf, Path(TMP.name) / 'b' / 'data')
        cls.slozky = instalace.priprav(instalace.nacti(cls.konf))
        os.environ['OSVC_CONFIG'] = str(cls.konf)
        try:
            from osvc_app import create_app
            cls.app = create_app({'TESTING': True})
        finally: os.environ.pop('OSVC_CONFIG')

    def test_nastaveni_odvozena_ze_slozky_dat(self):
        c = self.app.config
        self.assertEqual((c['DB_ENGINE'], c['DB_PATH']), ('sqlite', str(self.slozky['db'])))
        self.assertEqual(c['UPLOAD_FOLDER'], str(self.slozky['uploads'])); self.assertEqual(c['DATA_STATE_DIR'], str(self.slozky['instance']))
        self.assertEqual(c['SECRET_KEY'], self.slozky['klic'].read_text())

    def test_stranky_na_prazdne_databazi(self):
        k = self.app.test_client()   # nejdřív průvodce prvním spuštěním (I3) – založí účet a přihlásí
        t = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', k.get('/pruvodce').get_data(as_text=True)).group(1)
        r = k.post('/pruvodce', data={'csrf_token': t, 'zamestnani': 'ne', 'pojistovna': '111', 'social_zalohy': 'neplati', 'health_zalohy': 'neplati', 'vydaje': 'actual', 'dane_rezim': 'standard', 'prvni_zahajeni': 'ne', 'ico': '12345678', 'name': 'Test', 'number': '1', 'city': 'Brno', 'zip': '60200',
                                      'username': 'test', 'password': 'heslo-12345', 'password2': 'heslo-12345', 'modul_doprava': '1'})
        self.assertEqual(r.status_code, 302)
        for url in ('/', '/payments/income', '/payments/expense', '/trips', '/fuel', '/annual', '/settings', '/address-book', '/documents', '/events', '/annual/pdf'):
            self.assertEqual(k.get(url).status_code, 200, url)
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', k.get('/settings').get_data(as_text=True)).group(1)
        r = k.post('/payments/expense', data={'csrf_token': token, 'payment_date': '2026-11-18', 'counterparty_name': 'První dodavatel', 'description': 'První nákup', 'amount': '100.50', 'tax_mode': '100'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('První nákup', k.get('/payments/expense?year=2026').get_data(as_text=True))
        self.assertIn('100,50', k.get('/').get_data(as_text=True))


class Spoustec(unittest.TestCase):
    def test_server_bezi_na_portu(self):
        konf = Path(TMP.name) / 'c' / 'osvc.conf'; port = volny_port()
        r = subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'init', '--config', str(konf), '--data', str(Path(TMP.name) / 'c' / 'data'), '--port', str(port)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        proc = subprocess.Popen([sys.executable, '-m', 'osvc_app.spoustec', 'spust', '--config', str(konf)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            kod = None
            for _ in range(60):
                try: kod = urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=2).status; break
                except OSError: time.sleep(0.25)
            self.assertEqual(kod, 200)
            self.assertTrue((Path(TMP.name) / 'c' / 'data' / 'osvc.sqlite3').is_file())
        finally:
            proc.terminate(); vystup = proc.communicate(timeout=10)[0]
        self.assertIn(f'localhost:{port}', vystup)


if __name__ == '__main__':
    unittest.main()
