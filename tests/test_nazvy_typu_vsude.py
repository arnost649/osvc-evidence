"""Názvy typů: štítky typů záznamů se všude berou z Nastavení → Názvy typů (Příjmy – sloupec Zdroj, Výdaje, Přehled, detail akce,
výběr PHM dokladu), nic natvrdo. Nastaví jedinečné názvy, zkontroluje stránky a původní názvy vrátí. Běží jen přes tests/spust.sh."""
import datetime
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import osvc_app
from osvc_app import create_app, db, cas, system_types

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'MODULY_SETTINGS_FILE': tempfile.mkdtemp() + '/moduly.json'})
ZNACKY = {k: f'Typ{k.title().replace("_", "")}X' for k in system_types.TYPES}


class NazvyVsude(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context(); self.ctx.push()
        self.puvodni = {r['type_key']: r['display_label'] for r in db.query('SELECT type_key, display_label FROM system_types')}
        for k, v in ZNACKY.items(): db.execute('UPDATE system_types SET display_label=%s WHERE type_key=%s', (v, k))
        self.assertEqual(system_types.labels(), ZNACKY)
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1
        self.patch = mock.patch.object(cas, 'today', return_value=datetime.date(2026, 11, 17)); self.patch.start()

    def tearDown(self):
        self.patch.stop()
        for k, v in self.puvodni.items(): db.execute('UPDATE system_types SET display_label=%s WHERE type_key=%s', (v, k))
        self.ctx.pop()

    def html(self, url):
        r = self.client.get(url); self.assertEqual(r.status_code, 200, url); return r.get_data(as_text=True)

    def test_prijmy_rucni_prijem(self):
        h = self.html('/payments/income?year=2026')
        self.assertIn(f'manual-badge">{ZNACKY["income"]}<', h)
        self.assertNotIn('>ručně<', h)

    def test_vydaje_a_prehled(self):
        h = self.html('/payments/expense?year=2026')
        for k in ('trip', 'expense'): self.assertIn(ZNACKY[k], h, k)
        h = self.html('/')
        tabulka = h.split('dashboard-items')[1]
        typy = set(re.findall(r'record-type record-type-[a-z_]+">([^<]+)<', tabulka))
        self.assertTrue(typy, 'Přehled nemá položky')
        zdroje = {r['name'] for r in db.query('SELECT name FROM income_sources')}
        self.assertTrue(typy <= set(ZNACKY.values()) | zdroje, typy)

    def test_detail_akce(self):
        akce = db.execute("INSERT INTO business_events (event_date,name) VALUES ('2026-11-17','Názvy typů test')")
        try:
            p = db.query("SELECT id FROM payments WHERE deleted_at IS NULL AND direction='expense' AND fuel_purchase_id IS NULL ORDER BY id LIMIT 1", one=True)
            puvodni = db.query('SELECT event_id FROM payments WHERE id=%s', (p['id'],), one=True)['event_id']
            db.execute('UPDATE payments SET event_id=%s WHERE id=%s', (akce, p['id']))
            try:
                h = self.html(f'/events/{akce}')
                self.assertIn(f'data-label="Typ">{ZNACKY["expense"]}<', h)
                self.assertNotIn('data-label="Směr"', h)
            finally: db.execute('UPDATE payments SET event_id=%s WHERE id=%s', (puvodni, p['id']))
        finally: db.execute('DELETE FROM business_events WHERE id=%s', (akce,))

    def test_vyber_phm_dokladu_bez_stanice(self):
        from osvc_app.routes import trip_fuel_label
        self.assertIn(ZNACKY['fuel'], trip_fuel_label({'purchase_date': datetime.date(2026, 1, 2), 'station': None, 'total_amount': 100}))

    def test_v_kodu_nejsou_stitky_natvrdo(self):
        kod = (Path(osvc_app.__file__).parent / 'routes.py').read_text()
        self.assertNotIn("'kind_label':'", kod)
        for s in ("'Ruční'", "or 'PHM'", "or 'Tankování'", "'Ruční příjem' if"): self.assertNotIn(s, kod)
        sablony = Path(osvc_app.__file__).parent / 'templates'
        self.assertNotIn('>ručně<', (sablony / 'payments.html').read_text())
        self.assertNotIn("'Příjem' if x.direction", (sablony / 'event_detail.html').read_text())


if __name__ == '__main__':
    unittest.main()
