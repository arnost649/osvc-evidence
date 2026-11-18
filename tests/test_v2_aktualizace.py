"""V2 – upozornění na novou verzi: jen samostatná instalace (server nikdy), jednou denně, bez osobních údajů, lišta s odkazem,
vypínač v Nastavení. GitHub se nevolá – odpověď je podstrčená. Běží jen přes tests/spust.sh."""
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from osvc_app import aktualizace, create_app, instalace, verze

TMP = tempfile.TemporaryDirectory()


class Odpoved(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass


def github(tag='v9.9.9', odkaz='https://github.com/vlastnik/osvc/releases/tag/v9.9.9'):
    volani = []
    def otevri(req, timeout=None):
        volani.append(req); return Odpoved(json.dumps({'tag_name': tag, 'html_url': odkaz}).encode())
    otevri.volani = volani
    return otevri


class Cisla(unittest.TestCase):
    def test_porovnani(self):
        self.assertGreater(aktualizace.cislo('v1.2.10'), aktualizace.cislo('1.2.9'))
        self.assertGreater(aktualizace.cislo('v1.0.0'), aktualizace.cislo('1.0.0-test'))
        self.assertGreater(aktualizace.cislo('0.1.0'), aktualizace.cislo(verze.VERZE))
        self.assertIsNone(aktualizace.cislo('nesmysl'))


class Samostatna(unittest.TestCase):
    n = 0

    def setUp(self):
        Samostatna.n += 1
        konf = Path(TMP.name) / f's{Samostatna.n}' / 'osvc.conf'; instalace.zapis_nastaveni(konf, konf.parent / 'data')
        self.slozky = instalace.priprav(instalace.nacti(konf))
        os.environ['OSVC_CONFIG'] = str(konf)
        try: self.app = create_app({'TESTING': True, 'OSVC_AKTUALIZACE_REPO': 'vlastnik/osvc'})
        finally: os.environ.pop('OSVC_CONFIG')
        self.k = self.app.test_client()
        t = self.token('/pruvodce')
        self.k.post('/pruvodce', data={'csrf_token': t, 'zamestnani': 'ne', 'pojistovna': '111', 'social_zalohy': 'neplati', 'health_zalohy': 'neplati', 'vydaje': 'actual', 'dane_rezim': 'standard', 'prvni_zahajeni': 'ne', 'ico': '12345678', 'name': 'Test', 'number': '1', 'city': 'Brno', 'zip': '60200',
                                       'username': 'test', 'password': 'heslo-12345', 'password2': 'heslo-12345'})

    def token(self, url='/settings'):
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.k.get(url).get_data(as_text=True)).group(1)

    def test_nova_verze_lista_a_jednou_denne(self):
        g = github(); ted = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        with self.app.app_context():
            stav = aktualizace.zkontroluj(ted, otevri=g)
            self.assertEqual(stav['nejnovejsi'], '9.9.9')
            self.assertIsNone(aktualizace.zkontroluj(ted + timedelta(hours=23), otevri=g), 'do 24 hodin se znovu neptá')
            aktualizace.zkontroluj(ted + timedelta(hours=25), otevri=g)
        self.assertEqual(len(g.volani), 2)
        req = g.volani[0]
        self.assertEqual(req.full_url, 'https://api.github.com/repos/vlastnik/osvc/releases/latest')
        self.assertEqual(set(k.lower() for k in req.headers), {'user-agent', 'accept'}); self.assertEqual(req.get_header('User-agent'), f'osvc-evidence/{verze.VERZE}')
        html = self.k.get('/').get_data(as_text=True)
        self.assertIn('data-aktualizace', html); self.assertIn('https://github.com/vlastnik/osvc/releases/tag/v9.9.9', html); self.assertIn('9.9.9', html)
        self.assertIn('Upozorňovat na nové verze', self.k.get('/settings').get_data(as_text=True))

    def test_stejna_nebo_starsi_verze_bez_listy(self):
        with self.app.app_context(), mock.patch.object(verze, 'VERZE', '1.2.0'):
            aktualizace.zkontroluj(otevri=github('v1.2.0'))
            self.assertIsNone(aktualizace.upozorneni())
            self.assertNotIn('data-aktualizace', self.k.get('/').get_data(as_text=True))

    def test_chyba_githubu_nevadi(self):
        def spatne(req, timeout=None): raise OSError('nedostupné')
        ted = datetime(2026, 11, 18, tzinfo=timezone.utc)
        with self.app.app_context():
            aktualizace.zkontroluj(ted, otevri=github())
            stav = aktualizace.zkontroluj(ted + timedelta(days=2), otevri=spatne)
        self.assertEqual((stav['chyba'], stav['nejnovejsi']), ('OSError', '9.9.9'), 'předchozí známá verze zůstane')
        self.assertIn('data-aktualizace', self.k.get('/').get_data(as_text=True))

    def test_vypnuti_v_nastaveni(self):
        g = github()
        with self.app.app_context(): aktualizace.zkontroluj(otevri=g)
        r = self.k.post('/settings/aktualizace', data={'csrf_token': self.token()})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('data-aktualizace', self.k.get('/').get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(aktualizace.zkontroluj(datetime.now(timezone.utc) + timedelta(days=3), otevri=g)); self.assertFalse(aktualizace.zapnuto())
        self.assertEqual(len(g.volani), 1, 'vypnuto = GitHub se vůbec nevolá')
        self.k.post('/settings/aktualizace', data={'csrf_token': self.token(), 'kontrolovat': '1'})
        self.assertIn('data-aktualizace', self.k.get('/').get_data(as_text=True))

    def test_bez_repozitare_se_nekontroluje(self):
        with self.app.app_context():
            self.app.config['OSVC_AKTUALIZACE_REPO'] = None
            g = github(); self.assertIsNone(aktualizace.zkontroluj(otevri=g)); self.assertEqual(g.volani, [])


class Server(unittest.TestCase):
    def test_server_nikdy(self):
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH'], 'OSVC_AKTUALIZACE_REPO': 'vlastnik/osvc'})
        g = github()
        with app.app_context():
            self.assertIsNone(aktualizace.zkontroluj(otevri=g)); self.assertIsNone(aktualizace.upozorneni())
        self.assertEqual(g.volani, [])
        k = app.test_client()
        with k.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1
        self.assertNotIn('Upozorňovat na nové verze', k.get('/settings').get_data(as_text=True))
        self.assertEqual(k.post('/settings/aktualizace', data={'kontrolovat': '1'}).status_code, 404)


class Sestaveni(unittest.TestCase):
    def test_verze_py(self):
        import sys
        sys.path.insert(0, str(Path.cwd() / 'scripts' / 'windows'))
        try: import sestav
        finally: sys.path.pop(0)
        ns = {}; exec(sestav.verze_py('1.2.3', 'vlastnik/osvc'), ns)
        self.assertEqual((ns['VERZE'], ns['REPO']), ('1.2.3', 'vlastnik/osvc'))
        self.assertNotIn('REPO', Path('osvc_app/verze.py').read_text(encoding='utf-8').split('"""')[-1], 've zdrojích žádný účet')


if __name__ == '__main__':
    unittest.main()
