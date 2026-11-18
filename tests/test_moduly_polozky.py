"""Moduly – seznamy bez záznamů vypnutého modulu (Doprava = jízdy a PHM, Externí web = stažené příjmy) bez ohledu na volbu
výpočtů: Přehled (Posledních 5 položek, místo nich další), Příjmy, Výdaje, Doklady, detail Akce. Součty řídí jen volba výpočtů.
Běží jen přes tests/spust.sh proti osvc_test; volba modulů je v dočasném souboru, data v DB se nemění."""
import re
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from flask import template_rendered
from osvc_app import create_app, moduly, db, annual

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
DRUHY = re.compile(r'record-type record-type-([a-z_]+)')
SOUCTY = re.compile(r'summary-value numeric-value">([^<]+)<')


class Zaklad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); app.config['MODULY_SETTINGS_FILE'] = str(Path(self.tmp.name) / 'moduly.json')
        self.ctx = app.app_context(); self.ctx.push()
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1

    def tearDown(self):
        self.ctx.pop(); app.config.pop('MODULY_SETTINGS_FILE', None); self.tmp.cleanup()

    def prehled(self):
        h = self.client.get('/').get_data(as_text=True)
        tabulka = h.split('dashboard-items')[1].split('</table>')[0]
        return DRUHY.findall(tabulka), SOUCTY.findall(h)[:3]

    def ostatni(self, bez_stazenych):
        """Kolik položek zůstane (ruční příjmy a výdaje), max. 5."""
        sql = ("SELECT COUNT(*) n FROM payments p LEFT JOIN documents d ON d.id=p.document_id WHERE p.deleted_at IS NULL AND p.fuel_purchase_id IS NULL"
               + (" AND NOT (p.direction='income' AND (p.document_id IN (SELECT document_id FROM income_source_records) OR COALESCE(d.source,'manual')<>'manual'))" if bez_stazenych else ''))
        return min(5, db.query(sql, one=True)['n'])

class Polozky(Zaklad):
    def test_vse_zapnuto(self):
        druhy, _ = self.prehled()
        self.assertEqual(len(druhy), 5)

    def test_vypnuta_doprava(self):
        _, soucty = self.prehled()
        for zapocitat in (True, False):
            moduly.uloz('doprava', zapnuto=False, zapocitat=zapocitat)
            druhy, po = self.prehled()
            self.assertFalse({'trip', 'fuel'} & set(druhy), (zapocitat, druhy))
            self.assertEqual(len(druhy), 5, 'místo jízd a PHM se mají ukázat další položky')
            if zapocitat: self.assertEqual(po, soucty, 'součty se nemění')

    def test_vypnuty_externi_web(self):
        _, soucty = self.prehled()
        for zapocitat in (True, False):
            moduly.uloz('externi_web', zapnuto=False, zapocitat=zapocitat)
            druhy, po = self.prehled()
            self.assertNotIn('income_connector', druhy, zapocitat)
            self.assertEqual(len(druhy), 5)
            if zapocitat: self.assertEqual(po, soucty)

    def test_oba_vypnute(self):
        for k in moduly.MODULY: moduly.uloz(k, zapnuto=False)
        druhy, _ = self.prehled()
        self.assertFalse({'trip', 'fuel', 'income_connector'} & set(druhy), druhy)
        self.assertEqual(len(druhy), self.ostatni(True))
        moduly.uloz('doprava', zapnuto=True); moduly.uloz('externi_web', zapnuto=True)
        self.assertEqual(len(self.prehled()[0]), 5)



def nejcastejsi_rok(sql):
    """Rok s nejvíce záznamy (počítá Python – stejně v MySQL i SQLite)."""
    pocet = {}
    for r in db.query(sql): pocet[r['d'].year] = pocet.get(r['d'].year, 0) + 1
    return max(pocet, key=pocet.get)


@contextmanager
def kontext():
    """Zachytí kontext vykreslené šablony (řádky seznamu), nezávisle na podobě HTML."""
    zachyceno = {}
    def ulozit(sender, template, context, **kw): zachyceno.update(context)
    template_rendered.connect(ulozit, app)
    try: yield zachyceno
    finally: template_rendered.disconnect(ulozit, app)


class Seznamy(Zaklad):
    def setUp(self):
        super().setUp()
        self.stazene = {r['id'] for r in db.query("SELECT p.id FROM payments p WHERE p.direction='income' AND p.deleted_at IS NULL AND "
                                                  "(p.system_type='income_connector' OR p.document_id IN (SELECT document_id FROM income_source_records))")}
        self.stazene_doklady = {r['document_id'] for r in db.query('SELECT document_id FROM income_source_records WHERE document_id IS NOT NULL')}
        self.phm_doklady = {r['document_id'] for r in db.query('SELECT document_id FROM payments WHERE fuel_purchase_id IS NOT NULL AND document_id IS NOT NULL')}
        self.rok = nejcastejsi_rok("SELECT payment_date d FROM payments WHERE deleted_at IS NULL AND system_type='income_connector'")

    def radky(self, url):
        with kontext() as c:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        return c

    def test_prijmy(self):
        url = f'/payments/income?year={self.rok}'
        self.assertTrue(self.stazene & {r['id'] for r in self.radky(url)['rows']}, 'zapnutý Externí web: stažené příjmy jsou vidět')
        prijmy = annual.evidence(self.rok)['income']
        for zapocitat in (True, False):
            moduly.uloz('externi_web', zapnuto=False, zapocitat=zapocitat)
            c = self.radky(url)
            self.assertFalse(self.stazene & {r['id'] for r in c['rows']}, zapocitat)
            self.assertTrue(c['rows'], 'ruční příjem zůstává')
            if zapocitat: self.assertEqual(annual.evidence(self.rok)['income'], prijmy, 'Ponechat: součet se nemění, i když nejsou vidět')
        moduly.uloz('externi_web', zapnuto=True)
        self.assertTrue(self.stazene & {r['id'] for r in self.radky(url)['rows']}, 'po zapnutí je vše zpět')

    def test_vydaje(self):
        url = f"/payments/expense?year={nejcastejsi_rok('SELECT trip_date d FROM trips WHERE deleted_at IS NULL')}"
        self.assertIn('trip', {x['source_kind'] for x in self.radky(url)['rows']})
        moduly.uloz('doprava', zapnuto=False, zapocitat=True)
        rows = self.radky(url)['rows']
        self.assertNotIn('trip', {x['source_kind'] for x in rows}); self.assertFalse([x for x in rows if x.get('fuel_purchase_id')])
        moduly.uloz('doprava', zapnuto=True)
        self.assertIn('trip', {x['source_kind'] for x in self.radky(url)['rows']})

    def test_doklady(self):
        vse = {r['id'] for r in self.radky('/documents')['rows']}
        for k in moduly.MODULY: moduly.uloz(k, zapnuto=False, zapocitat=True)
        ids = {r['id'] for r in self.radky('/documents')['rows']}
        self.assertFalse(ids & (self.stazene_doklady | self.phm_doklady), 'stažené faktury ani doklady k PHM nejsou vidět')
        self.assertTrue(ids, 'ostatní doklady zůstávají')
        for k in moduly.MODULY: moduly.uloz(k, zapnuto=True)
        self.assertEqual({r['id'] for r in self.radky('/documents')['rows']}, vse)

    def test_akce(self):
        akce = db.query('SELECT e.id FROM business_events e WHERE e.deleted_at IS NULL LIMIT 1', one=True)
        if not akce: self.skipTest('osvc_test nemá žádnou akci')
        moduly.uloz('doprava', zapnuto=False); moduly.uloz('externi_web', zapnuto=False)
        c = self.radky(f"/events/{akce['id']}")
        self.assertEqual((c['trips'], c['fuels']), ([], []))
        self.assertFalse([p for p in c['payments'] if p.get('fuel_purchase_id') or p['id'] in self.stazene])


if __name__ == '__main__':
    unittest.main()
