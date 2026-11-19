"""Úklid kódu: struktura DB, staré záložní cesty, rozdělení stránek, sdílené spojení. Spouští se jen přes tests/spust.sh proti osvc_test."""
import unittest
from unittest.mock import patch
from osvc_app import create_app, routes, schema


class KontrolyStruktury(unittest.TestCase):
    """3b2 – žádné kontroly information_schema za běhu; jedna kontrola při startu jen do logu."""

    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only'})

    def test_routes_bez_kontrol(self):
        src = open('osvc_app/routes.py', encoding='utf-8').read()
        for name in ('events_ready', 'payment_schema_ready', 'trip_cost_schema_ready', 'fuel_link_ready',
                     'fuel_counterparty_ready', 'information_schema'):
            self.assertNotIn(name, src)
        for f in ('events.html', 'event_new.html', 'event_detail.html'):
            self.assertNotIn('čeká na aktualizaci databáze', open('osvc_app/templates/' + f, encoding='utf-8').read())

    def test_testovaci_db_ma_vse(self):
        """Testovací kopie (struktura z ostré DB 13. 11.) má všechny sloupce, na které kód spoléhá."""
        with self.app.app_context():
            self.assertEqual(schema.missing(), [])

    def test_start_zapise_vysledek(self):
        with self.assertLogs('osvc.schema', 'INFO') as logs:
            self.assertEqual(schema.check_at_start(self.app), [])
        self.assertIn('struktura DB v pořádku', logs.output[0])
        with patch('osvc_app.schema.query', return_value=[]), self.assertLogs('osvc.schema', 'WARNING') as logs:
            gone = schema.check_at_start(self.app)
        self.assertIn('payments.fuel_purchase_id', gone); self.assertIn('v databázi chybí', logs.output[0])
        with patch('osvc_app.schema.query', side_effect=OSError('db')), self.assertLogs('osvc.schema', 'WARNING') as logs:
            self.assertIsNone(schema.check_at_start(self.app))
        self.assertIn('nešlo provést', logs.output[0])

    def test_akce_a_jizdy_a_phm_se_otevrou(self):
        c = self.app.test_client()
        with c.session_transaction() as s:
            s['user'] = self.app.config['APP_USER']; s['local_auth'] = 1
        for url in ('/events', '/events/new', '/trips', '/fuel', '/payments/income', '/payments/expense', '/settings', '/documents', '/address-book', '/'):
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotIn('čeká na aktualizaci databáze', r.get_data(as_text=True), url)
        html = c.get('/events/new').get_data(as_text=True)
        button = html[html.index('form="event-form"'):].split('>')[0]
        self.assertNotIn('disabled', button)          # Uložit u nové akce není zašedlé


class StareZalozniCesty(unittest.TestCase):
    """3c – bez WC_*/WPO_* z prostředí, bez woocommerce_sync.json, bez route sync-woocommerce; staré ZIP zálohy dál projdou."""

    def test_konfigurace_a_kod(self):
        app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only'})
        for key in ('WC_URL', 'WC_CONSUMER_KEY', 'WC_SYNC_FROM', 'WPO_INVOICE_SFTP_HOST', 'WPO_INVOICE_REMOTE_DIR'):
            self.assertNotIn(key, app.config)
        self.assertIn('WPO_INVOICE_MAX_BYTES', app.config)          # limit velikosti PDF zůstává
        from osvc_app import woocommerce as wc
        self.assertFalse(hasattr(wc, 'save_last_sync')); self.assertFalse(hasattr(wc, 'last_sync'))
        self.assertNotIn('main.sync_woocommerce', app.view_functions)
        with app.test_request_context():
            self.assertIsNone(wc.runtime_config('WC_CONSUMER_KEY'))   # bez zdroje nic (dřív záloha z prostředí)
            self.assertEqual(wc.source_documents(), [])
            with self.assertRaises(wc.SyncConfigurationError):
                wc._sync_orders([])

    def test_stare_zip_zalohy(self):
        from osvc_app import backup
        src = open(backup.__file__, encoding='utf-8').read()
        self.assertIn("'woocommerce_sync.json'", src)              # soubor ze starých záloh se dál přijímá


class RozdeleniRoutes(unittest.TestCase):
    """3d – po rozdělení routes.py jsou všechny URL, endpointy a metody přesně jako před ním (snímek tests/url_map_pred_3d.json)."""

    def test_url_mapa_beze_zmeny(self):
        import json
        app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only'})
        now = sorted([r.rule, r.endpoint, sorted(r.methods - {'HEAD', 'OPTIONS'})] for r in app.url_map.iter_rules())
        before = json.load(open('tests/url_map_pred_3d.json', encoding='utf-8'))
        # Všechny adresy ze snímku zůstávají přesně stejné; nové funkce smějí jen přidat adresy z tohoto seznamu.
        nove_po_3d = [['/settings/modules/<klic>', 'main.update_module', ['POST']],   # Nastavení → Moduly
                      ['/settings/account', 'main.update_account', ['POST']],   # I2: Nastavení → Účet
                      ['/pruvodce', 'pruvodce.formular', ['GET', 'POST']], ['/pruvodce/ares', 'pruvodce.ares', ['POST']],   # I3: průvodce
                      ['/pruvodce/zamestnavatel', 'pruvodce.zamestnavatel', ['POST']], ['/pruvodce/dalsi', 'pruvodce.dalsi', ['GET', 'POST']],   # A2
                      ['/settings/aktualizace', 'main.update_aktualizace', ['POST']],   # V2: upozornění na novou verzi
                      ['/settings/sit', 'main.update_sit', ['POST']], ['/settings/sit/adaptery', 'main.sit_adaptery', ['GET']],   # síťový přístup
                      ['/aktualizace/okno', 'main.aktualizace_okno', ['GET']], ['/aktualizace/zkontrolovat', 'main.aktualizace_zkontrolovat', ['POST']],
                      ['/aktualizace/instalovat', 'main.aktualizace_instalovat', ['POST']], ['/aktualizace/prubeh', 'main.aktualizace_prubeh', ['GET']]]   # aktualizace
        self.assertEqual([r for r in now if r not in nove_po_3d], before)

    def test_moduly_oblasti(self):
        from osvc_app import events_routes
        self.assertEqual(events_routes.events.__module__, 'osvc_app.events_routes')
        from osvc_app import address_routes
        self.assertEqual(address_routes.address_book.__module__, 'osvc_app.address_routes')
        from osvc_app import settings_routes
        self.assertEqual(settings_routes.settings.__module__, 'osvc_app.settings_routes')
        from osvc_app import documents_routes
        self.assertEqual(documents_routes.attachment_view.__module__, 'osvc_app.documents_routes')
        from osvc_app import trips_fuel_routes
        self.assertEqual(trips_fuel_routes.fuels.__module__, 'osvc_app.trips_fuel_routes')
        from osvc_app import system_routes
        self.assertEqual(system_routes.login.__module__, 'osvc_app.system_routes')
        self.assertNotIn("@bp.route('/login'", open('osvc_app/routes.py', encoding='utf-8').read())
        self.assertNotIn("@bp.route('/events", open('osvc_app/routes.py', encoding='utf-8').read())
        app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only'})
        c = app.test_client()
        with c.session_transaction() as s:
            s['user'] = app.config['APP_USER']; s['local_auth'] = 1
        with app.app_context():
            from osvc_app.db import query
            row = query('SELECT id FROM business_events WHERE deleted_at IS NULL ORDER BY id LIMIT 1', one=True)
        if row:
            self.assertEqual(c.get(f"/events/{row['id']}").status_code, 200)
        self.assertEqual(c.get('/events/999999999').status_code, 404)
        with app.app_context():
            doc = query('SELECT id FROM documents WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1', one=True)
        if doc:
            self.assertEqual(c.get(f"/documents/{doc['id']}").status_code, 200)
            self.assertEqual(c.get(f"/documents/{doc['id']}/edit").status_code, 200)
        self.assertEqual(c.get('/attachments/999999999/view').status_code, 404)
        with app.app_context():
            trip = query('SELECT id,vehicle_id,trip_date FROM trips WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1', one=True)
            fuel = query('SELECT id FROM fuel_purchases WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 1', one=True)
        if trip:
            self.assertEqual(c.get(f"/trips/{trip['id']}/edit").status_code, 200)
            r = c.get(f"/trips/cost-preview?vehicle_id={trip['vehicle_id']}&trip_date={trip['trip_date']}&distance_km=10")
            self.assertEqual(r.status_code, 200); self.assertTrue(r.get_json()['ready'])
        if fuel:
            self.assertEqual(c.get(f"/fuel/{fuel['id']}/edit").status_code, 200)


class JednoSpojeni(unittest.TestCase):
    """3e – query()/execute() sdílí jedno spojení na požadavek; vidí čerstvá data; explicitní transakce mají vlastní spojení."""

    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'DB_SHARE_CONNECTION': True})

    def count_connections(self, url):
        calls = []
        c = self.app.test_client()
        with c.session_transaction() as s:
            s['user'] = self.app.config['APP_USER']; s['local_auth'] = 1
        if (self.app.config.get('DB_ENGINE') or 'mysql') == 'sqlite':   # S4: spojení SQLite
            from osvc_app import sqlite_db
            real = sqlite_db.Connection.__init__
            def counting(self_, path, autocommit=False): calls.append(autocommit); real(self_, path, autocommit)
            target = patch.object(sqlite_db.Connection, '__init__', counting)
        else:
            import pymysql
            real = pymysql.connect
            def counting(*a, **k): calls.append(k.get('autocommit')); return real(*a, **k)
            target = patch('pymysql.connect', side_effect=counting)
        with target:
            r = c.get(url)
        self.assertEqual(r.status_code, 200, url)
        return calls

    def test_stranky_maji_jedno_spojeni(self):
        for url in ('/', '/payments/income', '/payments/expense', '/trips', '/fuel', '/settings', '/address-book', '/documents', '/events'):
            calls = self.count_connections(url)
            self.assertEqual(calls.count(True), 1, url)        # jedno sdílené (autocommit)
            self.assertLessEqual(len(calls), 3, (url, calls))  # + nanejvýš pár explicitních transakcí

    def test_vidi_cerstva_data_a_po_pozadavku_zavre(self):
        from flask import g
        from osvc_app import db
        with self.app.app_context():
            label = lambda: db.query("SELECT display_label FROM system_types WHERE type_key='system_adjustment'", one=True)['display_label']
            before = label(); shared = g._osvc_db
            other = db.connection()
            try:
                with other.cursor() as cur:
                    cur.execute("UPDATE system_types SET display_label=%s WHERE type_key='system_adjustment'", ('Korekce (test 3e)',))
                other.commit()
                self.assertEqual(label(), 'Korekce (test 3e)')    # bez autocommit by viselo staré čtení
                self.assertIs(g._osvc_db, shared)
            finally:
                with other.cursor() as cur:
                    cur.execute("UPDATE system_types SET display_label=%s WHERE type_key='system_adjustment'", (before,))
                other.commit(); other.close()
            self.assertEqual(label(), before)
        self.assertFalse(shared.open)                           # konec kontextu = spojení zavřené

    def test_v_testech_vypnuto(self):
        app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only'})
        self.assertFalse(app.config['DB_SHARE_CONNECTION'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
