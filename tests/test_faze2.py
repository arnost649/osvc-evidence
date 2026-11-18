"""Texty a drobnosti v rozhraní. Běží přes tests/spust.sh proti osvc_test."""
import re
import unittest
from unittest.mock import patch
from osvc_app import create_app, db

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})


class Base(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context(); self.ctx.push()
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1

    def tearDown(self):
        self.ctx.pop()

    def get(self, url):
        r = self.client.get(url); self.assertEqual(r.status_code, 200, url); return r.get_data(as_text=True)


class Ucet(Base):
    """2a – Účet: skutečné jméno, heslo nikdy."""

    def test_skutecne_jmeno_bez_hesla(self):
        # I2: jméno se ukazuje z účtu v aplikaci (před převzetím z nastavení serveru)
        ucet = {'id': None, 'username': 'jmeno-z-konfigurace', 'password_hash': 'x', 'auth_version': 0}
        with patch('osvc_app.ucet.aktualni', return_value=ucet):
            with self.client.session_transaction() as s: s['user'] = 'jmeno-z-konfigurace'
            html = self.get('/settings')
        block = html[html.index('data-account'):].split('</dl>')[0]
        self.assertIn('<code>jmeno-z-konfigurace</code>', block)
        self.assertNotIn('<code>osvc</code>', block); self.assertIn('nezobrazuje', block)
        self.assertNotIn('pevně nastavené', html)



class Prehled(Base):
    """2b – Přehled: text řazení, název zdroje jednou, klik na importovaný příjem podle typu."""

    def recent(self, payments, source=None):
        from datetime import date
        from decimal import Decimal
        from flask import template_rendered
        def query(sql, *a, **k):
            if 'FROM payments p ' in sql: return payments
            if 'SUM(distance_km)' in sql: return {'total': Decimal('0')}
            return []
        report = {'sections': [{'key': 'tax', 'fields': [{'field_key': k, 'value': Decimal('0')} for k in ('income', 'expenses', 'result')]}]}
        captured = []
        with patch('osvc_app.routes.query', side_effect=query), patch('osvc_app.annual.year_report', return_value=(None, None, None, None, report)), \
             patch('osvc_app.income_sources.default_source', return_value=source), \
             template_rendered.connected_to(lambda sender, template, context, **kw: captured.append(context), app):
            html = self.get('/')
        return {i['id']: i['href'] for i in captured[-1]['recent_items']}, html

    def row(self, ident, source_name=None, attachment=None, manual=False):
        from datetime import date
        from decimal import Decimal
        return dict(id=ident, payment_date=date(2026, 10, 5), direction='income', system_type='income' if manual else 'income_connector',
                    description='x', amount=Decimal('1'), document_source='manual' if manual else 'woocommerce',
                    income_source_id=None if manual else 1, income_source_name=source_name, attachment_id=attachment)

    def test_klik_podle_typu_ne_podle_nazvu(self):
        hrefs, html = self.recent([self.row(1, 'muj-eshop.example', 55), self.row(2, 'Jiný e-shop', None), self.row(3, 'Přejmenovaný e-shop', 77), self.row(4, manual=True)])
        self.assertEqual(hrefs[1], '/attachments/55/view'); self.assertIsNone(hrefs[2])
        self.assertEqual(hrefs[3], '/attachments/77/view'); self.assertEqual(hrefs[4], '/payments/income/4')
        self.assertNotIn('podle data vložení', html); self.assertIn('nejnovější podle data', html)

    def test_nazev_zdroje_jednou(self):
        from osvc_app import income_sources as src
        source = src.default_source(); self.assertIsNotNone(source)
        _, html = self.recent([], source)
        card = html[html.index('class="system-action"'):].split('</article>')[0]
        self.assertEqual(card.count(source['name']), 1); self.assertIn('Synchronizovat příjmy', card)

    def test_bez_zdroje_odkaz_na_pridani(self):
        _, html = self.recent([], None)
        card = html[html.index('class="system-action"'):].split('</article>')[0]
        self.assertNotIn('/0/sync', card); self.assertIn('/settings/income-sources/new', card)



class Napajeni(Base):
    """2c – Napájení: před akcí potvrzení s jasným popisem, co se vypne."""

    def test_potvrzeni_a_popis(self):
        import socket
        html = self.get('/')
        menu = html[html.index('id="power-menu"'):].split('</div>')[0]
        stop = re.search(r'data-system-choice="stop" data-confirm-title="([^"]+)" data-confirm-ok="[^"]+" data-confirm="([^"]+)"', menu)
        off = re.search(r'data-system-choice="poweroff" data-confirm-title="([^"]+)" data-confirm-ok="[^"]+" data-confirm="([^"]+)"', menu)
        self.assertIn('Zastavit aplikaci', stop.group(1)); self.assertIn(socket.gethostname(), off.group(1))
        stop, off = stop.group(2), off.group(2)
        self.assertIn('správce serveru', stop)
        self.assertIn('celý server', off); self.assertIn('zálohy', off)
        self.assertIn('jen OSVČ', menu)

    def test_skript_se_pta(self):
        js = open('osvc_app/static/feedback.js', encoding='utf-8').read()
        self.assertIn("if(!(await confirmPower(button)))return;busy=true;", js)

    def test_predvybrane_zrusit(self):
        """2c2 – v potvrzení je fokus na „Zrušit“ (omylem stisknutý Enter nic nevypne), Esc zruší."""
        html = self.get('/')
        box = html[html.index('id="power-confirm"'):].split('</div>\n</div>')[0]
        self.assertLess(box.index('data-power-cancel>Zrušit'), box.index('data-power-ok'))
        js = open('osvc_app/static/feedback.js', encoding='utf-8').read()
        self.assertIn("cancel.focus({preventScroll:true})", js)
        self.assertIn("if(e.key==='Escape'){e.preventDefault();done(false,e);}", js)
        self.assertNotIn("ok.focus({preventScroll", js)



class NazvyTypu(Base):
    """2d – záložka „Kategorie“ → „Názvy typů“, bez interních klíčů na očích."""

    def test_nazvy_typu(self):
        html = self.get('/settings?tab=categories')
        self.assertIn('<span>Názvy typů</span>', html); self.assertNotIn('<span>Kategorie</span>', html)
        panel = html[html.index('id="settings-panel-categories"'):].split('</section>')[0]
        self.assertNotIn('<code', panel); self.assertNotIn('Interní typ', panel)
        self.assertNotIn('title=', panel)   # bez nápověd po najetí myší (interní označení se už neukazuje)
        self.assertIn('name="label_income_connector"', panel)

    def test_ulozeni_nazvu_funguje(self):
        from osvc_app import system_types
        labels = system_types.labels()
        data = {f'label_{k}': v for k, v in labels.items()}
        try:
            data['label_income_connector'] = 'E-shop (test 2d)'
            r = self.client.post('/settings/system-types', data=data)
            self.assertIn(r.status_code, (200, 302))
            self.assertEqual(system_types.labels()['income_connector'], 'E-shop (test 2d)')
        finally:
            self.client.post('/settings/system-types', data={f'label_{k}': v for k, v in labels.items()})
        self.assertEqual(system_types.labels()['income_connector'], labels['income_connector'])


    def test_popisy_a_vychozi_nazvy(self):
        """2d2 – popis říká, co typ znamená a kde se zobrazuje; odlišný uložený název ukáže výchozí návrh."""
        from osvc_app import system_types
        self.assertEqual(system_types.TYPES['income'][0], 'Ruční příjem')
        self.assertEqual(system_types.TYPES['income_connector'][0], 'Příjem z e-shopu')
        self.assertIn('e-shop', system_types.TYPES['income_connector'][1])
        html = self.get('/settings?tab=categories')
        panel = html[html.index('id="settings-panel-categories"'):].split('</section>')[0]
        row = panel[panel.index('id="system-type-income_connector"'):].split('</div>')[0]
        self.assertIn('objednávky z e-shopu', row)
        if system_types.labels()['income_connector'] != 'Příjem z e-shopu':
            self.assertIn('výchozí: Příjem z e-shopu', row)
        else:
            self.assertNotIn('data-type-default', row)

    def test_prehled_bere_nazev_rucniho_prijmu(self):
        """2d2 – ruční příjem na Přehledu používá název z Nastavení (dřív natvrdo)."""
        src = open('osvc_app/routes.py', encoding='utf-8').read()
        self.assertIn("item['kind_label']=item.get('source_label') or names[item['kind']]", src)
        self.assertNotIn("('Ruční příjem' if item['kind']=='income'", src)



class LidskeHlasky(unittest.TestCase):
    """2e – žádné hlášky typu „ALTER TABLE“, „databázové schéma“ pro uživatele."""
    TECH = ('ALTER TABLE payments podle README', 'databázové schéma', 'databázového schématu', 'SQL změny', 'databázovou aktualizaci')

    def test_bez_technickych_hlasek(self):
        import glob
        files = [f for f in glob.glob('osvc_app/**/*.py', recursive=True) + glob.glob('osvc_app/templates/*.html') if '.bak' not in f]
        for f in files:
            text = open(f, encoding='utf-8').read()
            for t in self.TECH: self.assertNotIn(t, text, f)



class BezDockeru(unittest.TestCase):
    """2f – aktuální texty a dokumentace bez Dockeru a cest do domovských složek (historické dokumenty jsou označené).
    Ve veřejném repozitáři docs/, scripts/ a systemd/ nejsou – kontrolují se jen existující soubory."""
    HISTORICAL = ('docs/data-flow-audit.md', 'docs/data-flow-remediation-plan.md', 'docs/payment-settlement-20261009.md', 'docs/backup-report.md')

    def test_aktualni_texty(self):
        import glob
        import os, re
        files = [f for f in ('README.md', 'scripts/backfill_invoices.py') if os.path.exists(f)] + glob.glob('docs/*.md') + [f for f in glob.glob('osvc_app/templates/*.html') if f.endswith('_connector_fields.html') is False]
        for f in files:
            text = open(f, encoding='utf-8').read()
            if f in self.HISTORICAL: self.assertIn('Historický dokument', text, f); continue
            for bad in ('docker compose', '/run/secrets', 'v Dockeru'): self.assertNotIn(bad, text, f)
            self.assertIsNone(re.search(r'/home/[a-z]', text), f)

    def test_jednotky_jsou_kopie_skutecnych(self):
        import os, re
        files = [f for f in ('systemd/osvc-evidence.service', 'deploy/osvc-evidence.service') if os.path.exists(f)]
        if not files: self.skipTest('jednotky systemd nejsou součástí repozitáře')
        for f in files:
            text = open(f, encoding='utf-8').read()
            self.assertNotIn('docker', text.lower()); self.assertRegex(text, r'(?m)^User=osvc$')



class ZalohyServeru(Base):
    """2g – stav automatických záloh serveru v Nastavení → Záloha (jen čtení přes systemctl show)."""

    def fake(self, service, timer):
        def show(unit, props): return service if unit.endswith('.service') else timer
        return patch('osvc_app.backup._systemctl_show', side_effect=show)

    def items(self):
        html = self.get('/settings?tab=backup')
        block = html[html.index('data-server-backups'):].split('</div>')[0]
        return re.findall(r'data-server-backup="([a-z_]+)"', block), re.sub(r'\s+', ' ', block)

    def test_ok_a_cesky_cas(self):
        from datetime import datetime, timezone
        with self.fake({'ActiveState': 'inactive', 'Result': 'success', 'ExecMainStatus': '0', 'ExecMainExitTimestamp': datetime.now(timezone.utc).replace(hour=2, minute=15)},
                       {'NextElapseUSecRealtime': datetime(2030, 1, 1, 2, 15, tzinfo=timezone.utc)}):
            states, text = self.items()
        self.assertEqual(states, ['ok', 'ok']); self.assertIn('03:15 – OK', text); self.assertIn('další 1. 1. 2030 03:15', text)

    def test_chyba_stara_a_nedostupna(self):
        from datetime import datetime, timezone
        with self.fake({'ActiveState': 'failed', 'Result': 'exit-code', 'ExecMainStatus': '1', 'ExecMainExitTimestamp': datetime.now(timezone.utc)}, {}):
            self.assertEqual(self.items()[0], ['error', 'error'])
        with self.fake({'ActiveState': 'inactive', 'Result': 'success', 'ExecMainStatus': '0', 'ExecMainExitTimestamp': datetime(2026, 1, 1, tzinfo=timezone.utc)}, {}):
            self.assertEqual(self.items()[0], ['old', 'old'])
        with patch('osvc_app.backup._systemctl_show', side_effect=OSError('bez systemd')):
            states, text = self.items()
        self.assertEqual(states, ['unavailable', 'unavailable']); self.assertIn('stav nejde zjistit', text)

    def test_po_restartu_serveru(self):
        from datetime import datetime, timezone
        with self.fake({'ActiveState': 'inactive', 'Result': 'success', 'ExecMainStatus': '0'}, {'LastTriggerUSec': datetime(2026, 11, 14, 2, 15, tzinfo=timezone.utc)}):
            self.assertEqual(self.items()[0], ['since_boot', 'since_boot'])

    def test_skutecny_server(self):
        from osvc_app.backup import server_backup_status
        states = [b['state'] for b in server_backup_status()]
        self.assertEqual(len(states), 2); self.assertNotIn('unavailable', states)


if __name__ == '__main__':
    unittest.main(verbosity=2)
