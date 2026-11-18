"""Moduly – schovávání vypnutých modulů (menu, Přehled, formuláře) a přesměrování jejich adres na Přehled.
Běží jen přes tests/spust.sh proti osvc_test; volba modulů je v dočasném souboru, data v DB se nemění."""
import tempfile
import unittest
from pathlib import Path
from osvc_app import create_app, moduly, db

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
TABULKY = ('trips', 'fuel_purchases', 'vehicles', 'income_sources', 'payments')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); app.config['MODULY_SETTINGS_FILE'] = str(Path(self.tmp.name) / 'moduly.json')
        self.ctx = app.app_context(); self.ctx.push()
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1
        self.pocty = {t: db.query(f'SELECT COUNT(*) n FROM {t} WHERE deleted_at IS NULL' if t != 'income_sources' else f'SELECT COUNT(*) n FROM {t}', one=True)['n'] for t in TABULKY}

    def tearDown(self):
        self.assertEqual(self.pocty, {t: db.query(f'SELECT COUNT(*) n FROM {t} WHERE deleted_at IS NULL' if t != 'income_sources' else f'SELECT COUNT(*) n FROM {t}', one=True)['n'] for t in TABULKY})
        self.ctx.pop(); app.config.pop('MODULY_SETTINGS_FILE', None); self.tmp.cleanup()

    def html(self, url):
        r = self.client.get(url); self.assertEqual(r.status_code, 200, url); return r.get_data(as_text=True)

    def presmerovano(self, url, method='get', **kw):
        r = getattr(self.client, method)(url, **kw)
        self.assertEqual(r.status_code, 302, url); self.assertEqual(r.headers['Location'], '/', url)


class Adresy(Base):
    def test_modul_adresy(self):
        for path, klic in (('/trips', 'doprava'), ('/trips/5/edit', 'doprava'), ('/trips/cost-preview', 'doprava'), ('/fuel/verify', 'doprava'),
                           ('/fuel/3/cancel', 'doprava'), ('/settings/vehicles/1/consumption', 'doprava'), ('/settings/income-sources/new', 'externi_web'),
                           ('/settings/income-sources/1/sync', 'externi_web'), ('/tripsx', None), ('/settings', None), ('/payments/income', None), ('/', None)):
            self.assertEqual(moduly.modul_adresy(path), klic, path)


class ObaZapnute(Base):
    def test_vse_je_videt(self):
        h = self.html('/')
        for text in ('href="/trips"', 'href="/fuel"', 'Zapsat jízdu', 'Zapsat PHM', 'Synchronizovat příjmy'): self.assertIn(text, h)
        s = self.html('/settings')
        self.assertIn('data-settings-tab="vehicles"', s); self.assertIn('data-settings-tab="sources"', s)
        p = self.html('/payments/income')   # synchronizace jen na Přehledu a v Nastavení → Zdroje příjmů (ne v záhlaví Příjmů)
        self.assertNotIn('data-source-action="sync"', p); self.assertNotIn('Poslední synchronizace', p); self.assertIn('data-edit-toggle', p)
        self.assertIn('data-source-action="sync"', self.html('/'))
        self.assertEqual(self.client.get('/trips').status_code, 200)


class DopravaVypnuta(Base):
    def setUp(self):
        super().setUp(); moduly.uloz('doprava', zapnuto=False)

    def test_menu_prehled_nastaveni(self):
        h = self.html('/')
        for text in ('href="/trips"', 'href="/fuel"', 'Zapsat jízdu', 'Zapsat PHM', 'data-dashboard-item="/trips/', 'data-dashboard-item="/fuel/'):
            self.assertNotIn(text, h)
        for text in ('href="/payments/income"', 'href="/payments/expense"', 'Zapsat nákup', 'Synchronizovat příjmy'): self.assertIn(text, h)
        s = self.html('/settings')
        self.assertNotIn('data-settings-tab="vehicles"', s); self.assertNotIn('settings-panel-vehicles', s)
        self.assertIn('data-settings-tab="sources"', s); self.assertIn('data-settings-tab="modules"', s)
        self.assertNotIn('href="/trips/', self.html('/payments/expense'))

    def test_adresy_presmeruji_s_hlaskou(self):
        trip = db.query('SELECT id FROM trips WHERE deleted_at IS NULL LIMIT 1', one=True)
        for url in ('/trips', '/fuel', f"/trips/{trip['id']}/edit", '/trips/cost-preview'): self.presmerovano(url)
        self.presmerovano('/settings/vehicles', 'post', data={'name': 'Test M2'})
        self.presmerovano(f"/trips/{trip['id']}/cancel", 'post')
        self.assertIn('Modul Doprava je vypnutý. Zapnete ho v Nastavení → Moduly.', self.html('/'))
        self.assertIsNone(db.query("SELECT id FROM vehicles WHERE name='Test M2'", one=True))

    def test_znovu_zapnuti_vrati_vse(self):
        moduly.uloz('doprava', zapnuto=True)
        self.assertIn('Zapsat jízdu', self.html('/')); self.assertEqual(self.client.get('/trips').status_code, 200)


class ExterniWebVypnuty(Base):
    def setUp(self):
        super().setUp(); moduly.uloz('externi_web', zapnuto=False)

    def test_prehled_prijmy_nastaveni(self):
        h = self.html('/')
        self.assertNotIn('Synchronizovat příjmy', h); self.assertIn('Zapsat jízdu', h)
        p = self.html('/payments/income')
        self.assertNotIn('data-source-action="sync"', p); self.assertNotIn('data-sync-block', p)
        s = self.html('/settings')
        self.assertNotIn('data-settings-tab="sources"', s); self.assertIn('data-settings-tab="vehicles"', s)

    def test_adresy_presmeruji(self):
        src = db.query('SELECT id FROM income_sources LIMIT 1', one=True)
        self.presmerovano('/settings/income-sources/new')
        self.presmerovano(f"/settings/income-sources/{src['id']}/sync", 'post')
        self.assertIn('Modul Externí web je vypnutý.', self.html('/'))

    def test_stazeny_prijem_nejde_smazat(self):
        p = db.query("SELECT p.id FROM payments p JOIN income_source_records r ON r.document_id=p.document_id WHERE p.direction='income' AND p.deleted_at IS NULL LIMIT 1", one=True)
        self.assertIsNotNone(p, 'kopie DB nemá stažený příjem')
        try:
            r = self.client.post(f"/payments/income/{p['id']}/cancel")
            self.assertEqual(r.status_code, 302)
            self.assertIsNone(db.query('SELECT deleted_at FROM payments WHERE id=%s', (p['id'],), one=True)['deleted_at'])
            self.assertIn('Stažený příjem jde smazat jen se zapnutým modulem Externí web', self.html('/payments/income'))
        finally:
            db.execute('UPDATE payments SET deleted_at=NULL WHERE id=%s', (p['id'],))   # pojistka, kdyby test selhal


if __name__ == '__main__':
    unittest.main()
