"""Moduly (M4) – otázka při vypínání modulu s daty, vyřazení záznamů z výpočtů a řádek „Nezapočteno“.
Běží jen přes tests/spust.sh proti osvc_test; volba modulů je v dočasném souboru, data v DB se nemění."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock
from osvc_app import create_app, moduly, db, annual

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
TABULKY = ('trips', 'fuel_purchases', 'vehicles', 'payments', 'documents', 'income_source_records')


def pocty_tabulek():
    return {t: db.query(f'SELECT COUNT(*) n FROM {t}', one=True)['n'] for t in TABULKY}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); app.config['MODULY_SETTINGS_FILE'] = str(Path(self.tmp.name) / 'moduly.json')
        self.ctx = app.app_context(); self.ctx.push()
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1
        self.pred = pocty_tabulek()
        # rok, kde jsou stažené příjmy i jízdy (jinak nejnovější rok s nějakou platbou)
        roky_jizd = {r['trip_date'].year for r in db.query('SELECT trip_date FROM trips WHERE deleted_at IS NULL')}
        pocet = {}
        for r in db.query("SELECT p.payment_date FROM payments p JOIN income_source_records r ON r.document_id=p.document_id "
                          "WHERE p.deleted_at IS NULL AND p.direction='income' AND p.currency='CZK'"):
            if r['payment_date'].year in roky_jizd: pocet[r['payment_date'].year] = pocet.get(r['payment_date'].year, 0) + 1
        self.assertTrue(pocet, 'osvc_test nemá rok se staženými příjmy a jízdami')
        self.rok = max(pocet, key=pocet.get)

    def tearDown(self):
        self.assertEqual(self.pred, pocty_tabulek(), 'data v DB se změnila')
        self.ctx.pop(); app.config.pop('MODULY_SETTINGS_FILE', None); self.tmp.cleanup()

    def ev(self):
        return annual.evidence(self.rok)

    def post(self, klic, **form):
        return self.client.post(f'/settings/modules/{klic}', data=form)


class Otazka(Base):
    def test_vypnuti_s_daty_se_nejdriv_zepta(self):
        r = self.post('doprava', zapnuto='0')
        self.assertEqual(r.status_code, 302); self.assertIn('potvrdit=doprava', r.headers['Location'])
        self.assertTrue(moduly.zapnuto('doprava'), 'bez odpovědi se modul nesmí vypnout')
        h = self.client.get('/settings?tab=modules&potvrdit=doprava').get_data(as_text=True)
        for text in ('data-module-confirm', 'Ponechat existující záznamy ve výpočtech', 'Nezapočítávat je', 'data-module-cancel', 'Zrušit'):
            self.assertIn(text, h)
        self.assertEqual(h.count('name="zapocitat" value='), 2)
        self.assertNotIn(' checked', h.split('data-module-confirm')[1].split('</form>')[0], 'žádná volba nesmí být předvybraná')
        self.assertNotIn('data-module-confirm', self.client.get('/settings?tab=modules').get_data(as_text=True))

    def test_prazdny_modul_se_vypne_bez_otazky(self):
        with mock.patch.object(moduly, 'pocty', return_value={k: {'x': 0} for k in moduly.MODULY}):
            r = self.post('externi_web', zapnuto='0')
        self.assertNotIn('potvrdit', r.headers['Location']); self.assertFalse(moduly.zapnuto('externi_web'))
        self.assertTrue(moduly.stav()['externi_web']['zapocitat'])

    def test_neplatne_hodnoty(self):
        for form in ({}, {'zapnuto': 'x'}, {'zapocitat': '2'}):
            self.assertEqual(self.post('doprava', **form).status_code, 400, form)
        self.assertEqual(moduly.stav()['doprava'], moduly.VYCHOZI)


class Vypocty(Base):
    def test_ponechat_ve_vypoctech_nic_nemeni(self):
        zaklad = self.ev()
        for klic in moduly.MODULY: self.post(klic, zapnuto='0', zapocitat='1')
        self.assertEqual(moduly.stav(), {k: {'zapnuto': False, 'zapocitat': True} for k in moduly.MODULY})
        po = self.ev()
        for k in ('income', 'ordinary', 'recorded_expenses', 'vehicles'): self.assertEqual(zaklad[k], po[k], k)
        self.assertEqual(po['nezapocteno'], {})
        self.assertNotIn('data-nezapocteno', self.client.get('/').get_data(as_text=True))

    def test_nezapocitat_externi_web(self):
        zaklad = self.ev()
        castky = [r['amount'] for r in db.query("SELECT p.amount FROM payments p WHERE p.deleted_at IS NULL AND p.direction='income' "
                  "AND p.currency='CZK' AND p.payment_date>=%s AND p.payment_date<%s AND p.document_id IN (SELECT document_id FROM income_source_records)",
                  db.rok(self.rok))]
        stazene = {'n': len(castky), 's': sum(castky, Decimal(0))}
        self.assertGreater(stazene['n'], 0)
        self.post('externi_web', zapnuto='0', zapocitat='0')
        po = self.ev()
        self.assertEqual(po['income'], zaklad['income'] - stazene['s'])
        self.assertEqual(po['nezapocteno']['externi_web'], {'prijmy': stazene['n'], 'castka': Decimal(stazene['s'])})
        self.assertEqual(po['vehicles'], zaklad['vehicles']); self.assertEqual(po['ordinary'], zaklad['ordinary'])
        text = moduly.nezapocteno_text(po['nezapocteno'])
        self.assertIn('modul Externí web', text)
        h = self.client.get(f'/annual?year={self.rok}').get_data(as_text=True)
        self.assertIn('data-nezapocteno', h); self.assertIn(text, h)
        pdf = self.client.get(f'/annual/pdf?year={self.rok}')
        self.assertEqual(pdf.status_code, 200); self.assertTrue(pdf.data.startswith(b'%PDF'))
        # znovu zapnout = vše zpět (i volba výpočtů)
        self.post('externi_web', zapnuto='1')
        self.assertEqual(moduly.stav()['externi_web'], moduly.VYCHOZI); self.assertEqual(self.ev()['income'], zaklad['income'])

    def test_nezapocitat_dopravu(self):
        zaklad = self.ev()
        self.post('doprava', zapnuto='0', zapocitat='0')
        po = self.ev()
        self.assertEqual(po['income'], zaklad['income']); self.assertEqual(po['ordinary'], zaklad['ordinary'])
        self.assertTrue(all(v['travel'] == 0 and v['fuel'] == 0 for v in po['vehicles'].values()))
        self.assertGreater(po['nezapocteno']['doprava']['jizdy'], 0)
        rep = annual.build(self.rok, *annual.profile.load(self.rok)[:2], po)
        self.assertEqual(rep['vehicles'], [], 'režim vozidel se při vyřazené Dopravě nepoužije')
        self.assertFalse(rep['missing'].get('vehicles'))
        self.assertIn('modul Doprava', rep['nezapocteno'])

    def test_volbu_jde_zmenit_u_vypnuteho_modulu(self):
        self.post('doprava', zapnuto='0', zapocitat='1')
        h = self.client.get('/settings?tab=modules').get_data(as_text=True)
        self.assertIn('data-module-zapocitat', h); self.assertIn('Nezapočítávat', h)
        self.post('doprava', zapocitat='0')
        self.assertEqual(moduly.stav()['doprava'], {'zapnuto': False, 'zapocitat': False}); self.assertTrue(moduly.vyrazeno('doprava'))
        self.post('doprava', zapocitat='1'); self.assertFalse(moduly.vyrazeno('doprava'))

    def test_zapnuty_modul_volbu_nemeni(self):
        self.post('doprava', zapocitat='0')
        self.assertEqual(moduly.stav()['doprava'], moduly.VYCHOZI)
        self.assertNotIn('data-module-zapocitat', self.client.get('/settings?tab=modules').get_data(as_text=True))


class Text(unittest.TestCase):
    def test_nezapocteno_text(self):
        self.assertEqual(moduly.nezapocteno_text({}), '')
        t = moduly.nezapocteno_text({'doprava': {'jizdy': 2, 'tankovani': 1, 'nahrady': Decimal('1234.5'), 'phm': Decimal(0)},
                                     'externi_web': {'prijmy': 5, 'castka': Decimal('10000')}})
        self.assertEqual(t.replace('\u00a0', ' '), '2 jízdy a 1 tankování (náhrady 1 234,50 Kč) – modul Doprava; 5 stažených příjmů za 10 000,00 Kč – modul Externí web')


if __name__ == '__main__':
    unittest.main()
