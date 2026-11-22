"""Záloha a obnova: průběh kroků (soubor + GET /settings/backup/progress/<job> bez zámku dat), srovnání po vytvoření zálohy
a po obnově se stránka vždy znovu načte (dřív zůstala na „Probíhá zpracování…“). Běží jen přes tests/spust.sh."""
import base64
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from osvc_app import create_app, backup as b
from osvc_app import zamky

import osvc_app
STATIC = Path(osvc_app.__file__).resolve().parent / 'static'


class ZalohaPrubeh(unittest.TestCase):
    def setUp(self):
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH'],
                               'DATA_STATE_DIR': self.tmp.name, 'MODULY_SETTINGS_FILE': self.tmp.name + '/moduly.json'})
        self.k = self.app.test_client()
        with self.k.session_transaction() as s: s['user'] = self.app.config['APP_USER']; s['local_auth'] = 1

    def test_prubeh_a_zamek(self):
        job = 'a' * 32
        with self.app.test_request_context():
            krok = b.reporter(job); krok('doklady', 'Obnovuji doklady… (3 z 10)', 72)
        self.assertEqual(self.k.get('/settings/backup/progress/' + job).get_json(), {'krok': 'doklady', 'popis': 'Obnovuji doklady… (3 z 10)', 'procento': 72})
        self.assertEqual(self.k.get('/settings/backup/progress/neplatny').status_code, 400)
        # během výhradního zámku (obnova) průběh odpovídá – ostatní stránky by čekaly
        with open(Path(self.tmp.name) / '.data.lock', 'ab') as f:
            zamky.zamkni(f, vyhradni=True)
            vysledek = {}
            t = threading.Thread(target=lambda: vysledek.setdefault('r', self.k.get('/settings/backup/progress/' + job).status_code)); t.start(); t.join(5)
            self.assertEqual(vysledek.get('r'), 200, 'průběh nesmí čekat na zámek dat')
            zamky.uvolni(f)

    def test_vytvoreni_se_srovnanim_a_obnova(self):
        job = 'b' * 32
        r = self.k.post('/settings/backup/export', data={'drafts': '{}', 'job': job})
        self.assertEqual(r.status_code, 200)
        radky = json.loads(base64.b64decode(r.headers['X-Backup-Comparison']))
        self.assertTrue(radky and all(x[3] == 'OK' for x in radky), radky)
        self.assertIn('Příjmy (počet)', [x[0] for x in radky])
        self.assertEqual(self.k.get('/settings/backup/progress/' + job).get_json()['krok'], 'stahovani')
        zip_cesta = Path(self.tmp.name) / 'z.zip'; zip_cesta.write_bytes(r.data)
        with zip_cesta.open('rb') as f:
            html = self.k.post('/settings/backup/validate', data={'backup': (f, 'z.zip')}, headers={'X-Backup-Fragment': '1'}, content_type='multipart/form-data').get_data(as_text=True)
        token = re.search(r'name="token" value="([0-9a-f]{32})"', html).group(1)
        job2 = 'c' * 32
        r = self.k.post('/settings/backup/restore', data={'token': token, 'drafts': '{}', 'job': job2}).get_json()
        self.assertTrue(r['ok']); self.assertTrue(r['vse_sedi'])
        self.assertEqual(self.k.get('/settings/backup/progress/' + job2).get_json()['krok'], 'hotovo')
        self.assertIn('Obnova dokončena – vše sedí', self.k.get('/settings?obnova=1').get_data(as_text=True))

    def test_po_obnove_jina_adresa(self):
        js = (STATIC / 'backup.js').read_text(encoding='utf-8')
        self.assertNotIn("location.href='/settings#backup'", js, 'stejná adresa s kotvou stránku nenačte znovu')
        self.assertIn("/settings?obnova='+Date.now()+'#backup'", js)


if __name__ == '__main__':
    unittest.main()
