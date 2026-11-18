"""Zdroje příjmů. Běží jen přes tests/spust.sh proti kopii osvc_test.
Řádek zdroje se před každým testem uloží a po něm vrátí; e-shop ani jiná síť se nevolá (přístupy jsou podvržené)."""
import json
from datetime import datetime, timedelta, timezone
import re
from html.parser import HTMLParser
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from osvc_app import create_app, db
from osvc_app import income_sources as src
from osvc_app import connectors

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
COLUMNS = ('name', 'url', 'active', 'automatic_sync', 'import_documents', 'sync_from', 'last_sync_at', 'last_error', 'last_summary',
           'configuration', 'secret_profile', 'sync_state', 'diagnostics')
OK_CHECKS = [{'key': 'server', 'label': 'Server dostupný', 'state': 'ok', 'detail': ''},
             {'key': 'archive', 'label': 'Přístup do archivu', 'state': 'ok', 'detail': ''}]


def configured_checks(self):
    return [{'key': k, 'label': k, 'ok': True, 'detail': ''} for k in ('connection', 'authentication', 'mapping', 'documents', 'synchronization')]


class Base(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context(); self.ctx.push()
        self.source = src.default_source(); self.assertIsNotNone(self.source, 'kopie DB nemá žádný zdroj příjmů')
        self.ident = self.source['id']
        self.saved = db.query('SELECT ' + ','.join(COLUMNS) + ' FROM income_sources WHERE id=%s', (self.ident,), one=True)
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1

    def tearDown(self):
        db.execute('UPDATE income_sources SET ' + ','.join(c + '=%s' for c in COLUMNS) + ' WHERE id=%s',
                   tuple(self.saved[c] for c in COLUMNS) + (self.ident,))
        self.ctx.pop()

    def row(self):
        return db.query('SELECT * FROM income_sources WHERE id=%s', (self.ident,), one=True)

    def set(self, **values):
        db.execute('UPDATE income_sources SET ' + ','.join(k + '=%s' for k in values) + ' WHERE id=%s', tuple(values.values()) + (self.ident,))

    def page(self):
        r = self.client.get('/settings?tab=sources')
        self.assertEqual(r.status_code, 200)
        return r.get_data(as_text=True)

    def flashes(self):
        with self.client.session_transaction() as s: return [m for _, m in s.get('_flashes', [])]

    def old_good_diagnostic(self, signature='stará-konfigurace'):
        self.set(diagnostics=json.dumps({'at': '2026-10-09T10:00:00+00:00', 'signature': signature, 'checks': OK_CHECKS,
                                         'capabilities': {'incremental_sync': True}, 'activation_ok': True}))


class Overeni(Base):
    """1a – „Ověřit připojení“ vždy ukáže čerstvý výsledek."""

    def test_chybejici_nastaveni_prepise_stare_overeni(self):
        self.old_good_diagnostic()
        r = self.client.post(f'/settings/income-sources/{self.ident}/test')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(any('nelze ověřit, chybí' in m for m in self.flashes()))
        d = json.loads(self.row()['diagnostics'])
        self.assertFalse(d['activation_ok'])
        self.assertTrue(d['checks'] and all(c['state'] == 'error' for c in d['checks']))
        self.assertEqual(d['capabilities'], {'incremental_sync': True}, 'schopnosti API zůstanou (inkrementální sync)')
        status = src.provider(self.row()).get_status()
        self.assertTrue(status['diagnostics_current']); self.assertFalse(status['tested']); self.assertEqual(status['state'], 'CHYBA')
        html = self.page()
        self.assertNotIn('Server dostupný', html)

    def test_neplatne_stare_overeni_se_neukazuje(self):
        self.old_good_diagnostic()
        html = self.page()
        self.assertIn('data-diagnostics-stale', html)
        self.assertNotIn('Server dostupný', html)

    def test_platne_overeni_se_ukazuje(self):
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks):
            self.old_good_diagnostic(connectors.access_signature(self.row()))
            html = self.page()
        self.assertIn('Server dostupný', html); self.assertNotIn('data-diagnostics-stale', html)

    def test_neocekavana_chyba_ulozi_chybu(self):
        self.old_good_diagnostic()
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks), \
             patch.object(connectors.WooCommerceProvider, 'test_connection', side_effect=RuntimeError('tajné detaily')):
            r = self.client.post(f'/settings/income-sources/{self.ident}/test')
        self.assertEqual(r.status_code, 400)
        d = json.loads(self.row()['diagnostics'])
        self.assertEqual([c['key'] for c in d['checks']], ['test']); self.assertFalse(d['activation_ok'])
        self.assertNotIn('tajné', json.dumps(d) + ' '.join(self.flashes()))

    def test_uspesne_overeni_hlaska(self):
        def fake_test(provider):
            return connectors.store_failed_diagnostic(provider.source, OK_CHECKS) | {'activation_ok': True}
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks), \
             patch.object(connectors.WooCommerceProvider, 'test_connection', fake_test):
            r = self.client.post(f'/settings/income-sources/{self.ident}/test')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Připojení ověřeno.', self.flashes())


class Varovani(Base):
    """1b – varování ze synchronizace nejsou chyba."""
    W = ['Objednávka 7001: částečný refund k ruční kontrole', 'Objednávka 7002: měna není CZK; vyžaduje ruční převod.']

    def test_stara_varovani_v_last_error_nejsou_chyba(self):
        self.set(active=1, last_summary=json.dumps({'warnings': self.W}), last_error='; '.join(self.W))
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks):
            status = src.provider(self.row()).get_status()
            html = self.page()
        self.assertIsNone(status['error']); self.assertEqual(status['state'], 'AKTIVNÍ'); self.assertEqual(status['warnings'], self.W)
        self.assertIn('data-source-warnings', html); self.assertNotIn('data-source-error', html)

    def test_selhani_je_chyba(self):
        self.set(active=1, last_summary=json.dumps({'warnings': self.W}), last_error='Zdroj není dostupný nebo import selhal. Zkontrolujte připojení.')
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks):
            status = src.provider(self.row()).get_status()
            html = self.page()
        self.assertEqual(status['state'], 'CHYBA'); self.assertIn('data-source-error', html)

    def test_synchronizace_s_varovanim_nenastavi_chybu(self):
        self.set(active=1, last_error='Zdroj není dostupný nebo import selhal. Zkontrolujte připojení.')
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks), \
             patch.object(connectors.WooCommerceProvider, 'sync', return_value={'seen': 2, 'warnings': self.W}):
            src.synchronize(self.ident)
        row = self.row()
        self.assertIsNone(row['last_error']); self.assertEqual(json.loads(row['last_summary'])['warnings'], self.W)


class DuvodyPristupu(Base):
    """1c – konkrétní důvod, proč přístupy nefungují, bez hodnot tajemství."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.pw = os.path.join(self.tmp.name, 'sftp-heslo'); Path(self.pw).write_text('TAJNE-HESLO'); os.chmod(self.pw, 0o600)
        self.kh = os.path.join(self.tmp.name, 'known_hosts'); Path(self.kh).write_text('x')
        self.file = os.path.join(self.tmp.name, 'zdroje.json')
        conf = json.loads(self.row()['configuration'] or '{}')
        conf.update(invoice_mode='sftp_archive', sftp_host='sftp.example.test', sftp_user='u', private_dir='/p', legacy_dir='/l')
        self.set(secret_profile='testprofil', import_documents=1, automatic_sync=0, url='https://shop.example.test', configuration=json.dumps(conf))

    def tearDown(self):
        self.tmp.cleanup(); super().tearDown()

    def write(self, data, mode=0o600):
        Path(self.file).write_text(json.dumps(data)); os.chmod(self.file, mode)

    def checks(self, **config):
        with patch.dict(app.config, {'INCOME_SOURCE_SECRETS_FILE': self.file, **config}):
            return {c['key']: c for c in src.provider(self.row()).validate_config()}

    def profile(self, **extra):
        return {'testprofil': {'consumer_key': 'CK-TAJNE', 'consumer_secret': 'CS-TAJNE', 'sftp_password_file': self.pw, 'known_hosts': self.kh, **extra}}

    def test_vse_v_poradku(self):
        self.write(self.profile())
        self.assertTrue(all(c['ok'] for c in self.checks().values()))

    def test_soubor_neni_nastaven(self):
        with patch.dict(os.environ, {'INCOME_SOURCE_SECRETS_FILE': ''}):
            c = self.checks(INCOME_SOURCE_SECRETS_FILE='')
        self.assertIn('INCOME_SOURCE_SECRETS_FILE', c['authentication']['detail'])

    def test_spatna_prava(self):
        self.write(self.profile(), 0o640)
        c = self.checks()
        self.assertFalse(c['authentication']['ok']); self.assertIn('práva 600', c['authentication']['detail'])

    def test_profil_chybi(self):
        self.write({'jiny': {}})
        self.assertIn('Profil „testprofil“', self.checks()['authentication']['detail'])

    def test_chybi_klic(self):
        p = self.profile(); del p['testprofil']['consumer_secret']; self.write(p)
        self.assertIn('chybí consumer_secret', self.checks()['authentication']['detail'])

    def test_heslo_sftp_v_home_a_prava(self):
        self.write(self.profile(sftp_password_file='/home/uzivatel/neexistuje'))
        self.assertIn('/home', self.checks()['documents']['detail'])
        os.chmod(self.pw, 0o644); self.write(self.profile())
        self.assertIn('práva 600', self.checks()['documents']['detail'])

    def test_stranka_ukaze_duvod_bez_tajemstvi(self):
        self.write(self.profile(), 0o644)
        with patch.dict(app.config, {'INCOME_SOURCE_SECRETS_FILE': self.file}):
            html = self.page()
        self.assertIn('data-source-problems', html); self.assertIn('práva 600', html)
        for secret in ('CK-TAJNE', 'CS-TAJNE', 'TAJNE-HESLO'): self.assertNotIn(secret, html)


class DuvodTlacitka(Base):
    """1d – zašedlé Synchronizovat vždy s důvodem (Přehled, karta zdroje; v Příjmech synchronizace není – 2026-11-17)."""

    def test_vypnuty_zdroj(self):
        self.set(active=0)
        self.assertIn('vypnutý', src.sync_block_reason(self.row()))
        self.assertNotIn('data-sync-block', self.client.get('/payments/income').get_data(as_text=True))
        for url in ('/',):
            html = self.client.get(url).get_data(as_text=True)
            self.assertIn('data-sync-block', html, url); self.assertIn('vypnutý', html, url)
        self.assertIn('data-sync-block', self.page())

    def test_nepripraveny_zdroj(self):
        self.set(active=1)
        reason = src.sync_block_reason(self.row())
        self.assertIn('není připravený', reason); self.assertIn('Autentizace', reason)

    def test_pripraveny_zdroj_bez_duvodu(self):
        self.set(active=1)
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks):
            self.assertIsNone(src.sync_block_reason(self.row()))
            for url in ('/', '/payments/income'):
                self.assertNotIn('data-sync-block', self.client.get(url).get_data(as_text=True), url)

    def test_bez_zdroje(self):
        self.assertIn('Žádný zdroj', src.sync_block_reason(None))



class FormFields(HTMLParser):
    """Pole jednoho formuláře tak, jak by je odeslal prohlížeč (zaškrtávátka jen zaškrtnutá, select = vybraná volba)."""
    def __init__(self, form_id):
        super().__init__(); self.form_id = form_id; self.inside = False; self.select = None; self.fields = {}; self.names = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form': self.inside = a.get('id') == self.form_id
        if not self.inside: return
        if tag == 'input' and a.get('name'):
            self.names.add(a['name'])
            if a.get('type') != 'checkbox' or 'checked' in a: self.fields[a['name']] = a.get('value') or ''
        elif tag == 'select':
            self.select = a['name']; self.names.add(self.select)
        elif tag == 'option' and self.select and ('selected' in a or self.select not in self.fields):
            self.fields[self.select] = a.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form': self.inside = False
        if tag == 'select': self.select = None


class ZjednodusenaKarta(Base):
    """1e – zjednodušená karta: stejná pole formuláře, technické věci pod „Pro správce“."""
    NAMES = {'csrf_token', 'name', 'url', 'sync_from', 'import_documents', 'automatic_sync', 'secret_profile', 'api_root',
             'invoice_mode', 'sftp_host', 'sftp_port', 'sftp_user', 'invoice_template', 'private_dir', 'legacy_dir'}

    def card(self):
        html = self.page()
        return html[html.index(f'id="source-{self.ident}"'):].split('</article>')[0]

    def form(self, html=None):
        p = FormFields(f'income-source-{self.ident}'); p.feed(html or self.page()); return p

    def test_stejna_pole_jako_driv(self):
        self.assertEqual(self.form().names, self.NAMES)

    def test_ulozeni_beze_zmen_nic_nezmeni(self):
        self.set(active=1)
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks):
            self.old_good_diagnostic(connectors.access_signature(self.row()))
            before = self.row(); fields = self.form().fields
            r = self.client.post(f'/settings/income-sources/{self.ident}', data=fields)
        self.assertEqual(r.status_code, 302)
        after = self.row()
        self.assertEqual(after['active'], 1); self.assertEqual(after['diagnostics'] is None, False)
        for k in ('name', 'url', 'secret_profile', 'sync_from', 'automatic_sync', 'import_documents'):
            self.assertEqual(after[k], before[k], k)
        old, new = json.loads(before['configuration'] or '{}'), json.loads(after['configuration'])
        for k, v in old.items(): self.assertEqual(str(new.get(k, '')), str(v), k)
        self.assertTrue(any(m.startswith('Konfigurace uložena.') for m in self.flashes()), self.flashes())

    def test_zaskrtavatka_se_ulozi(self):
        fields = self.form().fields; fields.pop('automatic_sync', None); fields['import_documents'] = 'on'
        self.client.post(f'/settings/income-sources/{self.ident}', data=fields)
        row = self.row(); self.assertEqual(row['automatic_sync'], 0); self.assertEqual(row['import_documents'], 1)
        fields['automatic_sync'] = 'on'; fields.pop('import_documents')
        self.client.post(f'/settings/income-sources/{self.ident}', data=fields)
        row = self.row(); self.assertEqual(row['automatic_sync'], 1); self.assertEqual(row['import_documents'], 0)

    def test_bez_mapovani_a_moznosti_konektoru(self):
        card = self.card()
        for text in ('Mapování', 'Možnosti konektoru', 'date_paid', 'Docker', '/run/secrets'): self.assertNotIn(text, card)
        for text in ('Stahovat PDF faktury', 'Synchronizovat automaticky', 'Importovat od', 'Pro správce', 'Ověřit připojení'): self.assertIn(text, card)

    def test_pro_spravce_zavrene_kdyz_je_vse_v_poradku(self):
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks):
            card = self.card()
        self.assertRegex(card, r'<details class="source-admin" data-source-admin\s*>')

    def test_pro_spravce_otevrene_pri_problemu(self):
        def broken(provider):
            return [c | ({'ok': False, 'detail': 'profil chybí'} if c['key'] == 'authentication' else {}) for c in configured_checks(provider)]
        with patch.object(connectors.WooCommerceProvider, 'validate_config', broken):
            card = self.card()
        self.assertRegex(card, r'<details class="source-admin" data-source-admin\s+open>')
        self.assertIn('profil chybí', card)

    def test_overeni_nahore_a_vysledek(self):
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks):
            self.old_good_diagnostic(connectors.access_signature(self.row()))
            card = self.card()
        self.assertLess(card.index('Ověřit připojení'), card.index('Nastavení zdroje'))
        self.assertIn('data-diagnostics', card); self.assertIn('Server dostupný', card)




class OvereniVzdyDobehne(Base):
    """1e2 – „Ověřit připojení“: zápis do logu, souběh se synchronizací, verze skriptů, SFTP se nezasekne."""

    def test_uspech_v_logu(self):
        def fake_test(provider):
            return connectors.store_failed_diagnostic(provider.source, OK_CHECKS) | {'activation_ok': True}
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks), \
             patch.object(connectors.WooCommerceProvider, 'test_connection', fake_test), self.assertLogs('osvc.zdroje', 'INFO') as logs:
            self.client.post(f'/settings/income-sources/{self.ident}/test')
        self.assertTrue(any(f'ověření zdroje {self.ident}: OK' in line for line in logs.output), logs.output)

    def test_bezici_synchronizace(self):
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks), src.source_lock(self.ident):
            r = self.client.post(f'/settings/income-sources/{self.ident}/test', headers={'Accept': 'application/json'})
        self.assertEqual(r.status_code, 400); self.assertTrue(r.is_json)
        self.assertTrue(any('právě běží synchronizace' in m for m in self.flashes()), self.flashes())

    def test_skripty_maji_verzi(self):
        html = self.page()
        self.assertRegex(html, r'/static/income-sources\.js\?v=\d+'); self.assertRegex(html, r'/static/ux\.css\?v=\d+')
        self.assertEqual(self.client.get(re.search(r'/static/income-sources\.js\?v=\d+', html).group()).status_code, 200)

    def test_sftp_ma_casovy_limit(self):
        from osvc_app import woocommerce as wc
        import paramiko
        tmp = tempfile.TemporaryDirectory(); pw = Path(tmp.name, 'pw'); pw.write_text('x'); pw.chmod(0o600); kh = Path(tmp.name, 'kh'); kh.write_text('')
        seen = {}
        class Channel:
            def settimeout(self, value): seen['timeout'] = value
        class Sftp:
            def get_channel(self): return Channel()
            def close(self): pass
        class Client:
            def load_host_keys(self, path): pass
            def set_missing_host_key_policy(self, policy): pass
            def connect(self, *a, **k): pass
            def open_sftp(self): return Sftp()
            def close(self): pass
        conf = {'WPO_INVOICE_SFTP_PASSWORD_FILE': str(pw), 'WPO_INVOICE_SFTP_KNOWN_HOSTS': str(kh), 'WPO_INVOICE_SFTP_HOST': 'h', 'WPO_INVOICE_SFTP_PORT': 22, 'WPO_INVOICE_SFTP_USER': 'u'}
        with patch.object(wc, 'runtime_config', conf.get), patch.object(paramiko, 'SSHClient', Client):
            with wc._open_invoice_sftp(): pass
        tmp.cleanup()
        self.assertEqual(seen.get('timeout'), 60)



class Planovac(Base):
    """1f – stav plánovače ze skutečného běhu (instance/income-sync-last.json), ne z proměnné."""

    def setUp(self):
        super().setUp()
        from osvc_app.backup import state_dir
        self.file = state_dir() / connectors.SCHEDULER_FILE
        self.backup = self.file.read_bytes() if self.file.exists() else None
        if self.file.exists(): self.file.unlink()
        self.env = patch.dict(app.config, {'INCOME_SYNC_SCHEDULER': None}); self.env.start()
        os.environ.pop('INCOME_SYNC_SCHEDULER', None)

    def tearDown(self):
        self.env.stop()
        if self.backup is None:
            if self.file.exists(): self.file.unlink()
        else: self.file.write_bytes(self.backup)
        super().tearDown()

    def run_at(self, minutes_ago, sources):
        at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
        self.file.write_text(json.dumps({'at': at, 'ok': True, 'sources': sources}))

    def automation(self):
        with patch.object(connectors.WooCommerceProvider, 'validate_config', configured_checks):
            html = self.page()
        card = html[html.index(f'id="source-{self.ident}"'):].split('</article>')[0]
        m = re.search(r'<p class="settings-help" data-automation="([a-z]+)">(.*?)</p>', card, re.S)
        return m.group(1), re.sub(r'\s+', ' ', m.group(2))

    def test_stavy(self):
        self.assertEqual(connectors.scheduler_status()['state'], 'missing')
        with patch.dict(app.config, {'INCOME_SYNC_SCHEDULER': 'systemd-15min'}):
            self.assertEqual(connectors.scheduler_status()['state'], 'waiting')
        self.run_at(5, {}); st = connectors.scheduler_status(); self.assertEqual(st['state'], 'ok'); self.assertTrue(st['enabled'])
        self.run_at(90, {}); st = connectors.scheduler_status(); self.assertEqual(st['state'], 'stale'); self.assertFalse(st['enabled'])
        self.file.write_text('nesmysl'); self.assertEqual(connectors.scheduler_status()['state'], 'missing')

    def test_karta_ukaze_posledni_beh(self):
        self.set(active=1, automatic_sync=1)
        self.run_at(3, {str(self.ident): {'state': 'ok', 'message': ''}})
        state, text = self.automation(); self.assertEqual(state, 'ok'); self.assertIn('naposled', text); self.assertIn('OK', text)
        self.run_at(3, {str(self.ident): {'state': 'error', 'message': 'Zdroj není dostupný.'}})
        self.assertIn('CHYBA</strong> – Zdroj není dostupný.', self.automation()[1])
        self.run_at(120, {})
        state, text = self.automation(); self.assertEqual(state, 'stale'); self.assertIn('Pozor', text)
        self.file.unlink()
        self.assertEqual(self.automation()[0], 'missing')

    def test_rucni_a_vypnuty(self):
        self.run_at(3, {})
        self.set(active=1, automatic_sync=0); self.assertEqual(self.automation()[0], 'manual')
        self.set(active=0, automatic_sync=1); self.assertEqual(self.automation()[0], 'inactive')

    def test_planovac_neblokuje_rucni_synchronizaci(self):
        self.set(active=1, automatic_sync=1)
        checks = {c['key']: c for c in src.provider(self.row()).validate_config()}
        self.assertTrue(checks['synchronization']['ok'])

    def test_cli_zapise_vysledek(self):
        self.set(active=1, automatic_sync=1)
        with patch.object(src, 'synchronize', return_value={'seen': 3, 'warnings': []}):
            r = app.test_cli_runner().invoke(args=['sync-income-sources'])
        self.assertEqual(r.exit_code, 0, r.output)
        data = json.loads(self.file.read_text())
        self.assertTrue(data['ok']); self.assertEqual(data['sources'][str(self.ident)], {'state': 'ok', 'message': '', 'counts': {'seen': 3}})
        self.set(automatic_sync=0)
        with patch.object(src, 'synchronize', side_effect=AssertionError('nemá se volat')):
            app.test_cli_runner().invoke(args=['sync-income-sources'])
        self.assertEqual(json.loads(self.file.read_text())['sources'][str(self.ident)]['state'], 'skipped')

    def test_cli_chyba_zdroje(self):
        self.set(active=1, automatic_sync=1)
        with patch.object(src, 'synchronize', side_effect=src.SourceError('Zdroj není dostupný.')):
            r = app.test_cli_runner().invoke(args=['sync-income-sources'])
        self.assertEqual(r.exit_code, 1)
        data = json.loads(self.file.read_text())
        self.assertFalse(data['ok']); self.assertEqual(data['sources'][str(self.ident)]['state'], 'error')



class PridaniNaJedneStrance(Base):
    """1g – přidání zdroje na jedné stránce: stejná pole jako karta, při chybě se nic nevyplněného neztratí."""

    def setUp(self):
        super().setUp(); self.created = []

    def tearDown(self):
        for ident in self.created: db.execute('DELETE FROM income_sources WHERE id=%s', (ident,))
        super().tearDown()

    def new_form(self):
        r = self.client.get('/settings/income-sources/new'); self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True); p = FormFields('income-source-new'); p.feed(html); return html, p

    def test_jedna_stranka_se_vsemi_poli(self):
        html, p = self.new_form()
        self.assertEqual(p.names, ZjednodusenaKarta.NAMES | {'provider'})
        self.assertNotIn('data-wizard-step', html); self.assertNotIn('Krok 1 ze', html); self.assertNotIn('Mapování', html)
        self.assertRegex(html, r'<details class="source-admin" data-source-admin\s+open>')
        self.assertIn('Uložit a ověřit', html)

    def test_pridani_vytvori_vypnuty_zdroj_a_spusti_overeni(self):
        _, p = self.new_form()
        fields = p.fields | {'name': 'Testovací e-shop 1g', 'url': 'https://shop.example.test', 'secret_profile': 'test1g', 'automatic_sync': 'on'}
        r = self.client.post('/settings/income-sources/add', data=fields)
        self.assertEqual(r.status_code, 302)
        row = db.query("SELECT * FROM income_sources WHERE name='Testovací e-shop 1g'", one=True); self.created.append(row['id'])
        self.assertIn(f'configure={row["id"]}', r.headers['Location']); self.assertIn('test=1', r.headers['Location'])
        self.assertEqual(row['active'], 0); self.assertEqual(row['automatic_sync'], 1); self.assertEqual(row['secret_profile'], 'test1g')
        self.assertEqual(json.loads(row['configuration'])['api_root'], 'wp-json/wc/v3')

    def test_chyba_vrati_vyplneny_formular(self):
        _, p = self.new_form()
        fields = p.fields | {'name': 'Rozpracovaný 1g', 'url': 'http://nezabezpeceny.example.test', 'secret_profile': 'prof1g', 'sftp_host': 'sftp.example.test', 'import_documents': 'on'}
        r = self.client.post('/settings/income-sources/add', data=fields)
        self.assertEqual(r.status_code, 400)
        html = r.get_data(as_text=True)
        for value in ('Rozpracovaný 1g', 'http://nezabezpeceny.example.test', 'prof1g', 'sftp.example.test', 'HTTPS'): self.assertIn(value, html)
        self.assertIsNone(db.query("SELECT id FROM income_sources WHERE name='Rozpracovaný 1g'", one=True))



class PdfJednimPruchodem(Base):
    """1h – synchronizace zkontroluje každé lokální PDF jen jednou; chybějící fakturu automatika zkouší nejvýš 1× denně."""
    DOCS = [{'id': 9001, 'number': 'A1', 'external_id': '701'}, {'id': 9002, 'number': 'A2', 'external_id': '702'},
            {'id': 9003, 'number': 'A3', 'external_id': '703'}]

    def run_sync(self, automatic, has=(9001, 9002)):
        from osvc_app import woocommerce as wc
        reads, fetched = [], []
        def valid(att): reads.append(att['id']); return att['id'] in has
        def attachments(sql, params=(), one=False):
            if 'FROM attachments' in sql: return [{'id': params[0], 'stored_filename': 'x.pdf', 'sha256': ''}]
            return db.query(sql, params, one=one)
        def fetch_order(ident): fetched.append(str(ident)); return {'id': int(ident)}
        self.set(import_documents=1, active=1)
        with patch.object(wc, 'fetch_orders', return_value=[]), patch.object(wc, 'source_documents', return_value=self.DOCS), \
             patch.object(wc, '_valid_invoice_attachment', valid), patch.object(wc, 'query', attachments), \
             patch.object(wc, 'fetch_order', fetch_order), patch.object(wc, '_sync_invoice_for_document', return_value='missing'):
            summary = src.provider(self.row()).sync(automatic=automatic)
        return summary, reads, fetched

    def test_kazde_pdf_jen_jednou(self):
        summary, reads, fetched = self.run_sync(False)
        self.assertEqual(sorted(reads), [9001, 9002, 9003], 'dřív 3–4 čtení každého PDF')
        self.assertEqual(summary['pdf_missing'], 1); self.assertEqual(summary['pdf_missing_orders'], ['A3'])
        self.assertEqual(fetched, ['703'])

    def test_automatika_zkousi_chybejici_jen_jednou_denne(self):
        self.set(sync_state=None)
        self.assertEqual(self.run_sync(True)[2], ['703'])
        self.assertEqual(self.run_sync(True)[2], [], 'druhý automatický běh téhož dne se e-shopu neptá')
        self.assertEqual(self.run_sync(False)[2], ['703'], 'ruční Synchronizovat zkouší vždy')
        state = json.loads(self.row()['sync_state']); self.assertIn('9003', state['pdf_retry'])

    def test_vcerejsi_pokus_se_zopakuje(self):
        conf = {'pdf_retry': {'9003': '2000-01-01'}}
        self.set(sync_state=json.dumps(conf))
        self.assertEqual(self.run_sync(True)[2], ['703'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
