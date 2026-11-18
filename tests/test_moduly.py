"""Moduly: Nastavení → Moduly, uložení volby, ZIP záloha. Běží jen přes tests/spust.sh proti osvc_test.
Volba se ukládá do dočasného souboru (MODULY_SETTINGS_FILE), sdílený stav testů se nemění; data v DB se jen čtou."""
import json
import tempfile
import unittest
from pathlib import Path
from osvc_app import create_app, moduly, backup, db

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})

TABULKY = ('trips', 'fuel_purchases', 'vehicles', 'income_sources', 'payments', 'income_source_records')


class Moduly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.soubor = Path(self.tmp.name) / 'moduly.json'
        app.config['MODULY_SETTINGS_FILE'] = str(self.soubor)
        self.ctx = app.app_context(); self.ctx.push()
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1
        self.pocty_db = {t: db.query(f'SELECT COUNT(*) n FROM {t}', one=True)['n'] for t in TABULKY}

    def tearDown(self):
        # zapnutí/vypnutí nikdy nemění data
        self.assertEqual(self.pocty_db, {t: db.query(f'SELECT COUNT(*) n FROM {t}', one=True)['n'] for t in TABULKY})
        self.ctx.pop(); app.config.pop('MODULY_SETTINGS_FILE', None); self.tmp.cleanup()

    def test_vychozi_oba_zapnute(self):
        self.assertFalse(self.soubor.exists())
        self.assertEqual(moduly.stav(), {'doprava': {'zapnuto': True, 'zapocitat': True}, 'externi_web': {'zapnuto': True, 'zapocitat': True}})

    def test_poskozeny_soubor_je_vychozi(self):
        for obsah in ('{nejson', '[]', '{"neznamy": {"zapnuto": false}}', '{"doprava": {"zapnuto": "ne"}}'):
            self.soubor.write_text(obsah)
            self.assertTrue(moduly.zapnuto('doprava'), obsah)

    def test_ulozeni_a_cteni(self):
        moduly.uloz('doprava', zapnuto=False)
        self.assertEqual(moduly.stav()['doprava'], {'zapnuto': False, 'zapocitat': True})
        self.assertTrue(moduly.zapnuto('externi_web'))
        self.assertEqual(oct(self.soubor.stat().st_mode & 0o777), '0o644')
        moduly.uloz('doprava', zapnuto=True)
        self.assertTrue(moduly.zapnuto('doprava'))

    def test_stranka_nastaveni(self):
        html = self.client.get('/settings').get_data(as_text=True)
        self.assertIn('data-settings-tab="modules"', html)
        self.assertIn('data-module="doprava"', html); self.assertIn('data-module="externi_web"', html)
        self.assertIn('Obsahuje: ', html)
        self.assertEqual(html.count('data-module-toggle'), 2)

    def test_prepnuti_formularem(self):
        r = self.client.post('/settings/modules/externi_web', data={'zapnuto': '0', 'zapocitat': '1'})   # M4: s odpovědí na otázku
        self.assertEqual(r.status_code, 302); self.assertIn('tab=modules', r.headers['Location'])
        self.assertFalse(moduly.zapnuto('externi_web')); self.assertTrue(moduly.zapnuto('doprava'))
        html = self.client.get('/settings').get_data(as_text=True)
        self.assertIn('Modul Externí web je vypnutý. Existující záznamy se dál počítají do výpočtů. Data zůstávají beze změny.', html)
        self.assertIn('module-card is-off" id="modul-externi_web" data-module="externi_web"', html)
        self.client.post('/settings/modules/externi_web', data={'zapnuto': '1'})
        self.assertTrue(moduly.zapnuto('externi_web'))

    def test_neznamy_modul_404(self):
        self.assertEqual(self.client.post('/settings/modules/neco', data={'zapnuto': '0'}).status_code, 404)
        self.assertFalse(self.soubor.exists())

    def test_pocty_a_text(self):
        p = moduly.pocty()
        self.assertEqual(set(p), {'doprava', 'externi_web'})
        self.assertEqual(moduly.obsah_text('doprava', {'jizdy': 1, 'tankovani': 3, 'vozidla': 5}), '1 jízda, 3 tankování, 5 vozidel')
        self.assertEqual(moduly.obsah_text('externi_web', {'zdroje': 0, 'prijmy': 0}), 'zatím nic')
        self.assertEqual(moduly.obsah_text('externi_web', {'zdroje': 1, 'prijmy': 2}), '1 zdroj, 2 stažené příjmy')

    def test_zaloha(self):
        self.assertEqual(backup.settings_paths()['moduly.json'], self.soubor)
        self.assertEqual(moduly.platna_data({'doprava': {'zapnuto': False}}), {'doprava': {'zapnuto': False}})
        for spatne in ([], {'x': {}}, {'doprava': {'zapnuto': 1}}, {'doprava': {'jine': True}}):
            with self.assertRaises(ValueError): moduly.platna_data(spatne)


if __name__ == '__main__':
    unittest.main()
