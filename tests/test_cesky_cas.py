"""Český čas. Běží přes tests/spust.sh proti osvc_test; data se nemění."""
import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from osvc_app import create_app, db, cas
from osvc_app import income_sources as src

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
F = app.jinja_env.filters


class Prevod(unittest.TestCase):
    def test_utc_na_prahu_zima_a_leto(self):
        self.assertEqual(F['cz_datetime']('2026-11-13T19:51:00+00:00'), '13. 11. 2026 20:51')   # SEČ +1
        self.assertEqual(F['cz_datetime']('2026-07-01T10:00:00+00:00'), '1. 7. 2026 12:00')     # SELČ +2
        self.assertEqual(F['cz_datetime']('2026-11-13T19:51:00Z'), '13. 11. 2026 20:51')

    def test_prechod_casu(self):
        self.assertEqual(F['cz_datetime']('2026-03-29T00:59:00+00:00'), '29. 3. 2026 01:59')
        self.assertEqual(F['cz_datetime']('2026-03-29T01:00:00+00:00'), '29. 3. 2026 03:00')
        self.assertEqual(F['cz_datetime']('2026-10-25T00:30:00+00:00'), '25. 10. 2026 02:30')
        self.assertEqual(F['cz_datetime']('2026-10-25T01:30:00+00:00'), '25. 10. 2026 02:30')

    def test_naivni_hodnota_z_db_je_utc(self):
        self.assertEqual(F['cz_datetime'](datetime(2026, 11, 13, 19, 51)), '13. 11. 2026 20:51')
        self.assertEqual(F['cz_datetime']('2026-11-13 19:51:07'), '13. 11. 2026 20:51')

    def test_ciste_datum_a_prazdne_beze_zmeny(self):
        self.assertEqual(F['cz_datetime'](date(2026, 11, 13)), '13. 11. 2026')
        self.assertEqual(F['cz_datetime']('2026-11-13'), '13. 11. 2026')
        self.assertEqual(F['cz_datetime'](None), 'zatím neproběhla')
        self.assertEqual(F['cz_datetime']('nesmysl'), 'nesmysl')

    def test_datum_overeni_zamestnavatele(self):
        self.assertEqual(F['local_date_iso']('2026-11-13T23:30:00+00:00'), '2026-11-14')
        self.assertEqual(F['local_date_iso'](''), '')

    def test_dnes_podle_ceska(self):
        class Utc23(datetime):
            @classmethod
            def now(cls, tz=None): return datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc).astimezone(tz) if tz else datetime(2026, 11, 13, 23, 30)
        with patch.object(cas, 'datetime', Utc23):
            self.assertEqual(cas.today(), date(2026, 11, 14))
            self.assertEqual(cas.utc_now_naive(), datetime(2026, 11, 13, 23, 30))


class Stranky(unittest.TestCase):
    COLUMNS = ('diagnostics', 'last_sync_at')

    def setUp(self):
        self.ctx = app.app_context(); self.ctx.push()
        self.source = src.default_source(); self.ident = self.source['id']
        self.saved = db.query('SELECT diagnostics,last_sync_at FROM income_sources WHERE id=%s', (self.ident,), one=True)
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1

    def tearDown(self):
        db.execute('UPDATE income_sources SET diagnostics=%s,last_sync_at=%s WHERE id=%s', (self.saved['diagnostics'], self.saved['last_sync_at'], self.ident))
        self.ctx.pop()

    def test_karta_zdroje_a_prijmy_v_ceskem_case(self):
        db.execute('UPDATE income_sources SET last_sync_at=%s WHERE id=%s', (datetime(2026, 11, 13, 19, 51), self.ident))
        settings = self.client.get('/settings?tab=sources').get_data(as_text=True)
        # čas poslední synchronizace je jen na kartě zdroje (záhlaví Příjmů ho od 2026-11-17 neukazuje)
        self.assertIn('13. 11. 2026 20:51', settings); self.assertNotIn('13. 11. 2026 19:51', settings)


if __name__ == '__main__':
    unittest.main(verbosity=2)
