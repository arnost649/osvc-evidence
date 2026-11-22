"""I2 – přihlášení uložené v aplikaci: převzetí z nastavení serveru, starý řádek (auth_version 1) se ignoruje, změna jména a hesla
v Nastavení → Účet, odhlášení ostatních zařízení po změně hesla, samostatná instalace bez účtu. Pracuje s kopií SQLite od
tests/spust.sh (DB_PATH). Běží jen přes tests/spust.sh (výchozí SQLite)."""
import os
import re
import tempfile
import unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from osvc_app import create_app, db, ucet

TMP = tempfile.TemporaryDirectory()


def setUpModule():
    if os.environ.get('DB_ENGINE') != 'sqlite': raise unittest.SkipTest('jen pro SQLite (kopie vzoru)')


class Ucet(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH'], 'MODULY_SETTINGS_FILE': TMP.name + '/m.json'})
        self.ctx = self.app.app_context(); self.ctx.push()
        # starý řádek z doby Dockeru s jiným heslem – nesmí se použít
        db.execute("UPDATE app_accounts SET username='osvc', password_hash=%s, auth_version=1 WHERE id=1", (generate_password_hash('stare-heslo-docker'),))

    def tearDown(self): self.ctx.pop()

    def klient(self):
        return self.app.test_client()

    def prihlas(self, k, jmeno, heslo):
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', k.get('/login').get_data(as_text=True))
        return k.post('/login', data={'csrf_token': m.group(1) if m else '', 'username': jmeno, 'password': heslo})

    def test_pred_prevzetim_z_nastaveni_stary_radek_se_ignoruje(self):
        self.assertIsNone(ucet.ucet())
        k = self.klient()
        self.assertEqual(self.prihlas(k, 'osvc', 'stare-heslo-docker').status_code, 200, 'staré heslo z doby Dockeru nesmí projít')
        r = self.prihlas(k, 'osvc', 'osvc'); self.assertEqual(r.status_code, 302)
        self.assertEqual(k.get('/settings').status_code, 200)

    def test_prevzeti(self):
        self.assertTrue(ucet.prevezmi_z_nastaveni())
        u = ucet.ucet(); self.assertEqual((u['id'], u['username'], u['auth_version']), (1, 'osvc', 2))
        self.assertFalse(ucet.prevezmi_z_nastaveni(), 'převzetí jen jednou')
        self.assertEqual(self.prihlas(self.klient(), 'osvc', 'osvc').status_code, 302)

    def test_zmena_hesla_a_jmena(self):
        ucet.prevezmi_z_nastaveni()
        k, jiny = self.klient(), self.klient()
        self.prihlas(k, 'osvc', 'osvc'); self.prihlas(jiny, 'osvc', 'osvc')
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', k.get('/settings').get_data(as_text=True)); token = m.group(1) if m else ''
        def zmen(**d): return k.post('/settings/account', data={'csrf_token': token, **d}, follow_redirects=True).get_data(as_text=True)
        self.assertIn('Současné heslo nesouhlasí', zmen(username='osvc', current_password='spatne', new_password='noveheslo1', new_password2='noveheslo1'))
        self.assertIn('aspoň 8 znaků', zmen(username='osvc', current_password='osvc', new_password='kratke', new_password2='kratke'))
        self.assertIn('se liší', zmen(username='osvc', current_password='osvc', new_password='noveheslo1', new_password2='noveheslo2'))
        self.assertIn('nesmí obsahovat mezery', zmen(username='o s', current_password='osvc'))
        self.assertEqual(ucet.ucet()['auth_version'], 2, 'chybné pokusy nic nezměnily')
        h = zmen(username='majitel', current_password='osvc', new_password='noveheslo1', new_password2='noveheslo1')
        self.assertIn('Přihlašovací údaje jsou uložené', h); self.assertIn('data-zachranny-kod>', h, 'nové heslo = nový záchranný kód (1.0.3)')
        self.assertIn('<code>majitel</code>', k.get('/settings').get_data(as_text=True))
        self.assertEqual(k.get('/').status_code, 200, 'toto přihlášení platí dál')
        self.assertEqual(jiny.get('/').status_code, 302, 'ostatní přihlášení se odhlásí')
        self.assertEqual(self.prihlas(self.klient(), 'osvc', 'osvc').status_code, 200)
        self.assertEqual(self.prihlas(self.klient(), 'majitel', 'noveheslo1').status_code, 302)
        u = db.query('SELECT password_hash, auth_version, password_changed_at FROM app_accounts WHERE id=1', one=True)
        self.assertNotIn('noveheslo1', u['password_hash']); self.assertEqual(u['auth_version'], 3); self.assertIsNotNone(u['password_changed_at'])
        # jen jméno: verze se nemění
        zmen(username='majitel2', current_password='noveheslo1'); self.assertEqual(ucet.ucet()['auth_version'], 3)

    def test_zaloha_bez_uctu(self):
        from osvc_app import backup as b
        import zipfile, json
        ucet.prevezmi_z_nastaveni()
        cesta = Path(TMP.name) / 'z.zip'
        with b.data_lock(exclusive=True): b.create_backup(cesta)
        self.assertNotIn('app_accounts', json.loads(zipfile.ZipFile(cesta).read('database/data.json'))['tables'])


class SamostatnaBezUctu(unittest.TestCase):
    def test_bez_prihlaseni_v_nastaveni(self):
        from osvc_app import instalace
        konf = Path(TMP.name) / 's' / 'osvc.conf'; instalace.zapis_nastaveni(konf, Path(TMP.name) / 's' / 'data')
        instalace.priprav(instalace.nacti(konf))
        os.environ['OSVC_CONFIG'] = str(konf)
        try: app = create_app({'TESTING': True, 'APP_USER': None, 'APP_PASSWORD_HASH': None})
        finally: os.environ.pop('OSVC_CONFIG')
        with app.app_context(): self.assertIsNone(ucet.aktualni())
        k = app.test_client()
        for url in ('/login', '/'):   # bez účtu vede vše do průvodce prvním spuštěním (I3)
            r = k.get(url); self.assertEqual(r.status_code, 302); self.assertTrue(r.headers['Location'].endswith('/pruvodce'))


if __name__ == '__main__':
    unittest.main()
