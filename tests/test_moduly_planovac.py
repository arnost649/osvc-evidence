"""Moduly – plánovač synchronizace (flask sync-income-sources) přeskočí zdroje, když je vypnutý modul Externí web.
Bez sítě a bez zápisu do DB: zdroje, synchronizace i zápis stavu plánovače jsou podvržené."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from osvc_app import create_app, moduly

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
ZDROJE = [{'id': 1, 'name': 'E-shop', 'active': 1, 'automatic_sync': 1}, {'id': 2, 'name': 'Druhý', 'active': 1, 'automatic_sync': 0}]


class Planovac(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); app.config['MODULY_SETTINGS_FILE'] = str(Path(self.tmp.name) / 'moduly.json')
        self.zapsano = []

    def tearDown(self):
        app.config.pop('MODULY_SETTINGS_FILE', None); self.tmp.cleanup()

    def beh(self):
        with patch('osvc_app.income_sources.sources', return_value=ZDROJE), \
             patch('osvc_app.income_sources.synchronize', return_value={'imported': 2}) as sync, \
             patch('osvc_app.connectors.record_scheduler_run', side_effect=self.zapsano.append):
            r = app.test_cli_runner().invoke(args=['sync-income-sources'])
        return r, sync

    def test_zapnuty_modul_synchronizuje(self):
        r, sync = self.beh()
        self.assertEqual(r.exit_code, 0, r.output); sync.assert_called_once_with(1, automatic=True)
        self.assertEqual(self.zapsano[0][1]['state'], 'ok'); self.assertEqual(self.zapsano[0][2]['state'], 'skipped')

    def test_vypnuty_modul_preskoci_vse(self):
        with app.app_context(): moduly.uloz('externi_web', zapnuto=False)
        r, sync = self.beh()
        self.assertEqual(r.exit_code, 0, r.output); sync.assert_not_called()
        self.assertIn('Modul Externí web je vypnutý – synchronizace přeskočena.', r.output)
        self.assertEqual({k: v['message'] for k, v in self.zapsano[0].items()}, {1: 'modul Externí web je vypnutý', 2: 'modul Externí web je vypnutý'})

    def test_vypnuta_doprava_synchronizaci_nemeni(self):
        with app.app_context(): moduly.uloz('doprava', zapnuto=False)
        r, sync = self.beh()
        self.assertEqual(r.exit_code, 0, r.output); sync.assert_called_once()


if __name__ == '__main__':
    unittest.main()
