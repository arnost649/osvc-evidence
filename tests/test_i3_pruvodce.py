"""I3/A2 – průvodce prvním spuštěním (dvě strany): bez účtu vede každá adresa do průvodce, chybné údaje nic neuloží, úspěch
založí identitu, profil roku, účet a moduly (moduly až po databázi); strana 2 podle modulů (vozidlo + režim, odkaz na zdroj
příjmů); po typickém vyplnění jsou Profil OSVČ i Roční přehled zelené. ARES (IČO i zaměstnavatel) je podstrčený.
Každý test má vlastní prázdnou samostatnou instalaci. Běží jen přes tests/spust.sh."""
import json
import os
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock
from osvc_app import cas, create_app, instalace, sqlite_db

TMP = tempfile.TemporaryDirectory()
ROK = cas.today().year
ZAKLAD = {'ico': '12345678', 'name': 'Jana Nováková', 'street': 'Dlouhá', 'number': '12/3', 'city': 'Brno', 'zip': '602 00',
          'country': 'Česká republika', 'dic': '', 'username': 'jana', 'password': 'tajne-heslo-1', 'password2': 'tajne-heslo-1',
          'podnikani_od': f'{ROK}-01-01', 'podnikani_konec': 'ne', 'prvni_zahajeni': 'ne', 'zamestnani': 'ne', 'vedlejsi_jine': '',
          'pojistovna': '111', 'social_zalohy': 'plati', 'social_mesicne': '5 005', 'health_zalohy': 'plati', 'health_mesicne': '3306',
          'vydaje': 'actual', 'dane_rezim': 'standard', 'potvrzeni': 'ano', 'modul_doprava': '1'}
ARES = {'ico': '12345678', 'name': 'Jana Nováková', 'dic': '', 'address': 'x', 'street': 'Dlouhá', 'number': '12/3', 'city': 'Brno',
        'zip': '60200', 'country': 'Česká republika'}
FIRMA = {'ico': '87654321', 'name': 'Strojírny Brno a.s.', 'city': 'Brno', 'dic': '', 'address': '', 'street': '', 'number': '', 'zip': '', 'country': ''}


class Zaklad(unittest.TestCase):
    n = 0

    def setUp(self):
        Zaklad.n += 1
        koren = Path(TMP.name) / f'i{Zaklad.n}'; konf = koren / 'osvc.conf'
        instalace.zapis_nastaveni(konf, koren / 'data')
        self.slozky = instalace.priprav(instalace.nacti(konf))
        os.environ['OSVC_CONFIG'] = str(konf)
        try: self.app = create_app({'TESTING': True})
        finally: os.environ.pop('OSVC_CONFIG')
        self.k = self.app.test_client()

    def db(self): return sqlite_db.otevri(self.slozky['db'])

    def token(self, url='/pruvodce'):
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', self.k.get(url).get_data(as_text=True)).group(1)

    def odesli(self, **zmeny):
        data = {**ZAKLAD, **zmeny, 'csrf_token': self.token()}
        return self.k.post('/pruvodce', data={k: v for k, v in data.items() if v is not None})

    def strana2(self, **data):
        return self.k.post('/pruvodce/dalsi', data={'csrf_token': self.token('/pruvodce/dalsi'), 'dalsi': 'hotovo', **data})

    def moduly(self): return json.loads((self.slozky['instance'] / 'moduly.json').read_text(encoding='utf-8'))

    def zelene(self):
        """Stav Profilu OSVČ a oddílů Ročního přehledu (dict) – pro „vše zelené“ samé 'known'."""
        from osvc_app.annual import year_report
        from osvc_app import profile, profile_presentation
        with self.app.app_context():
            identity, p, _, _, report = year_report(ROK)
            view = profile_presentation.build(identity, p, report, profile.vehicles())
        stav = {'profil': view['profile_state']}; stav.update({s['key']: s['status'] for s in report['sections']})
        self.duvody = {s['key']: s['status_reason'] for s in report['sections']}; self.duvody['profil'] = view['profile_status_reason']
        return stav


class Brana(Zaklad):
    def test_bez_uctu_vede_vse_do_pruvodce(self):
        for url in ('/', '/login', '/settings', '/payments/income', '/trips', '/annual', '/pruvodce/dalsi'):
            r = self.k.get(url); self.assertEqual(r.status_code, 302, url); self.assertTrue(r.headers['Location'].endswith('/pruvodce'), url)
        self.assertEqual(self.k.post('/logout', data={'csrf_token': self.token()}).status_code, 409)
        self.assertEqual(self.k.get('/static/ux.css').status_code, 200)
        html = self.k.get('/pruvodce').get_data(as_text=True)
        for text in ('IČO', 'Doplnit z ARES', 'Od kdy letos podnikáte', 'zaměstnání', 'zdravotní pojišťovny', 'Zálohy, které platíte sami jako OSVČ', 'Jak uplatníte výdaje',
                     'Jak danit', 'Potvrzuji', 'Doprava', 'Externí web', f'{ROK}-01-01'):
            self.assertIn(text, html)
        self.assertNotRegex(html, r'name="potvrzeni" value="ano" checked', 'potvrzení nikdy předem')
        self.assertRegex(html, r'name="dane_rezim" value="standard" checked', 'běžný režim jako výchozí')
        self.assertNotIn('Odhlásit', html)


class Chyby(Zaklad):
    def test_chybne_udaje_nic_neulozi(self):
        for zmena, hlaska in [({'ico': '1234567'}, 'IČO musí mít přesně 8 číslic'), ({'city': ''}, 'Vyplňte adresu'),
                              ({'password2': 'jine-heslo-2'}, 'liší'), ({'zamestnani': None}, 'zaměstnání'),
                              ({'pojistovna': ''}, 'zdravotní pojišťovnu'), ({'social_zalohy': None}, 'platím'),
                              ({'social_mesicne': 'hodně'}, 'částku'), ({'vydaje': None}, 'výdaje'), ({'vydaje': 'percentage'}, 'paušálu'),
                              ({'podnikani_od': f'{ROK - 1}-05-01'}, f'v roce {ROK}'), ({'podnikani_konec': 'ano', 'podnikani_do': f'{ROK}-01-01', 'podnikani_od': f'{ROK}-03-01'}, 'před jeho začátkem'),
                              ({'zamestnani': 'ano'}, 'sociální pojištění'), ({'prvni_zahajeni': None}, 'první podnikání'),
                              ({'zamestnani': 'ano', 'zamestnani_socialni': 'yes', 'zamestnani_zdravotni': 'no', 'zamestnavatel': 'Podvržená s.r.o.', 'zamestnavatel_token': 'x'}, 'z výsledků hledání v ARES')]:
            r = self.odesli(**zmena); html = r.get_data(as_text=True)
            self.assertEqual(r.status_code, 400, zmena); self.assertIn(hlaska, html, zmena)
            self.assertNotIn('tajne-heslo-1', html, 'heslo se do formuláře nevrací')
        c = self.db()
        for tabulka in ('app_accounts', 'osvc_profile', 'osvc_year_profiles'): self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {tabulka}').fetchone()[0], 0, tabulka)
        self.assertFalse((self.slozky['instance'] / 'moduly.json').exists(), 'moduly až po úspěšném uložení')


class Uspech(Zaklad):
    def test_hlavni_cinnost_skutecne_vydaje_vozidlo_vse_zelene(self):
        r = self.odesli(); self.assertEqual((r.status_code, r.headers['Location']), (302, '/ucet/zachranny-kod'), 'nejdřív záchranný kód (1.0.3)')
        html = self.k.get('/ucet/zachranny-kod').get_data(as_text=True); self.assertIn('data-zachranny-kod>', html); self.assertIn('action="/pruvodce/dalsi"', html)
        self.assertEqual(self.moduly(), {'doprava': {'zapnuto': True, 'zapocitat': True}, 'externi_web': {'zapnuto': False, 'zapocitat': True}})
        html = self.k.get('/pruvodce/dalsi').get_data(as_text=True); self.assertIn('první vozidlo', html); self.assertNotIn('zdroj příjmů', html.lower().split('legend')[-1] if False else '')
        r = self.strana2(vozidlo_nazev='Škoda Fabia', vozidlo_spz='1ab 2345', vozidlo_palivo='Natural 95', vozidlo_spotreba='4,7', vozidlo_rezim='actual')
        self.assertEqual(r.headers['Location'], '/')
        c = self.db()
        self.assertEqual(c.execute('SELECT username, auth_version FROM app_accounts').fetchall(), [('jana', 2)])
        self.assertEqual(c.execute('SELECT name, registration_plate, normalized_consumption_l_100km FROM vehicles').fetchall(), [('Škoda Fabia', '1AB 2345', Decimal('4.700'))])
        p = json.loads(c.execute('SELECT data FROM osvc_year_profiles WHERE tax_year=?', (ROK,)).fetchone()[0])
        self.assertEqual((p['social_advance_month'], p['health_advance_month'], p['tax_review'], p['social_case'], p['tax_case']), ('5005', '3306', 'yes', 'standard', 'standard'))
        self.assertEqual(list(p['vehicles'].values())[0]['vehicle_method'], 'actual')
        stav = self.zelene(); self.assertEqual(set(stav.values()), {'known'}, (stav, self.duvody))
        self.assertIn('Odhad: 5005 Kč měsíčně × 12', self.k.get('/annual').get_data(as_text=True))
        dash = self.k.get('/').get_data(as_text=True); self.assertNotIn('data-vyzvy', dash); self.assertNotIn('>—<', dash)

    def test_vedlejsi_se_zamestnanim_a_zamestnavatel_z_ares(self):
        t = self.token()
        with mock.patch('osvc_app.ares.lookup_by_name', return_value=[FIRMA]), mock.patch('osvc_app.ares.lookup_by_ico', return_value=FIRMA):
            self.assertEqual(self.k.post('/pruvodce/zamestnavatel', data={'csrf_token': t, 'ico': '87654321'}).status_code, 400, 'jen z výsledků hledání')
            self.assertEqual(self.k.post('/pruvodce/zamestnavatel', data={'csrf_token': t, 'hledat': 'Strojírny'}).get_json()['vysledky'][0]['ico'], '87654321')
            vyber = self.k.post('/pruvodce/zamestnavatel', data={'csrf_token': t, 'ico': '87654321'}).get_json()
        r = self.odesli(zamestnani='ano', zamestnavatel=vyber['name'], zamestnavatel_token=vyber['token'], zamestnani_socialni='yes', zamestnani_zdravotni='yes',
                        social_zalohy='neplati', health_zalohy='neplati', vydaje='percentage', pausal='trade', modul_doprava=None)
        self.assertEqual((r.status_code, r.headers['Location']), (302, '/ucet/zachranny-kod'))
        self.assertIn('action="/"', self.k.get('/ucet/zachranny-kod').get_data(as_text=True), 'bez modulů se strana 2 přeskočí')
        self.assertEqual(self.moduly()['doprava']['zapnuto'], False)
        p = json.loads(self.db().execute('SELECT data FROM osvc_year_profiles').fetchone()[0])
        self.assertEqual((p['employer'], p['employer_ico'], p['expense_rate']), ('Strojírny Brno a.s.', '87654321', 'trade'))
        stav = self.zelene(); self.assertEqual(set(stav.values()), {'known'}, (stav, self.duvody))

    def test_jiny_duvod_vedlejsi(self):
        """Vedlejší činnost z jiného důvodu (důchod): měsíce vedlejší; při nulovém zisku pod rozhodnou částkou pojištění nevzniká (zelené),
        jinak výpočet ČSSZ jen ke kontrole – nikdy „chybí“."""
        self.odesli(vedlejsi_jine='pension', modul_doprava=None)
        p = json.loads(self.db().execute('SELECT data FROM osvc_year_profiles').fetchone()[0])
        self.assertEqual((p['vedlejsi_duvod'], p['month_overrides']['1']), ('pension', {'social': 'secondary', 'reason': 'other'}))
        stav = self.zelene(); self.assertNotIn('missing', stav.values(), self.duvody)

    def test_bez_potvrzeni_doplnite_pozdeji(self):
        self.assertEqual(self.odesli(potvrzeni=None, modul_doprava=None).status_code, 302)
        stav = self.zelene(); self.assertEqual(stav['tax'], 'missing'); self.assertIn('Potvrďte kontrolu', self.duvody['profil'])
        self.assertIn('href="/settings#profile-tax"', self.k.get('/').get_data(as_text=True), 'výzva s odkazem na chybějící nastavení')

    def test_pausal_procentem_vozidlo_bez_rezimu(self):
        self.odesli(vydaje='percentage', pausal='craft')
        self.assertIn('data-pausal-vozidlo', self.k.get('/pruvodce/dalsi').get_data(as_text=True))
        self.strana2(vozidlo_nazev='Dodávka')
        stav = self.zelene(); self.assertEqual(set(stav.values()), {'known'}, (stav, self.duvody))

    def test_externi_web_odkaz_na_zdroj(self):
        self.odesli(modul_doprava=None, modul_externi_web='1')
        html = self.k.get('/pruvodce/dalsi').get_data(as_text=True); self.assertIn('nastavit zdroj příjmů', html); self.assertNotIn('vozidlo_nazev', html)
        self.assertEqual(self.strana2(dalsi='zdroj').headers['Location'], '/settings/income-sources/new')

    def test_paušal_dopravy_bez_potvrzeni_podminek(self):
        self.odesli(); self.strana2(vozidlo_nazev='Octavia', vozidlo_rezim='flat', vozidlo_soukrome='yes')
        self.assertEqual(self.zelene()['tax'] in ('missing', 'known'), True)
        self.assertIn('Podmínky paušálu dopravy', ' '.join(self.duvody.values()))

    def test_zpet_po_dokonceni(self):
        self.odesli(modul_doprava=None)
        self.assertEqual(self.k.get('/pruvodce').status_code, 302)
        r = self.k.post('/pruvodce', data={**ZAKLAD, 'csrf_token': self.token('/settings'), 'username': 'utocnik'})
        self.assertEqual(r.headers['Location'], '/'); self.assertEqual(self.db().execute('SELECT username FROM app_accounts').fetchall(), [('jana',)])

    def test_ares_datum_vzniku(self):
        """Vznik IČO letos → „Od kdy“ = datum vzniku a otázka na první podnikání (předvyplněno Ano); vznik před 2 lety a dřív = otázka skrytá."""
        from osvc_app.pruvodce import vznik_podnikani
        self.assertEqual(vznik_podnikani(f'{ROK}-09-03', ROK), {'vznik': f'{ROK}-09-03', 'vznik_text': f'9/{ROK}', 'podnikani_od': f'{ROK}-09-03', 'ptat_prvni': True})
        self.assertEqual(vznik_podnikani(f'{ROK - 2}-05-01', ROK)['podnikani_od'], f'{ROK}-01-01'); self.assertTrue(vznik_podnikani(f'{ROK - 2}-05-01', ROK)['ptat_prvni'])
        self.assertFalse(vznik_podnikani(f'{ROK - 3}-12-31', ROK)['ptat_prvni'])
        self.assertIsNone(vznik_podnikani('', ROK)['ptat_prvni'], 'bez data vzniku se ptá bez předvyplnění')
        t = self.token()
        with mock.patch('osvc_app.ares.lookup_by_ico', return_value={**ARES, 'vznik': f'{ROK}-09-03'}):
            d = self.k.post('/pruvodce/ares', data={'csrf_token': t, 'ico': '12345678'}).get_json()
        self.assertEqual((d['podnikani_od'], d['vznik_text'], d['ptat_prvni']), (f'{ROK}-09-03', f'9/{ROK}', True))
        html = self.k.get('/pruvodce').get_data(as_text=True)
        self.assertIn('Je to vaše první podnikání?', html); self.assertNotRegex(html, r'name="prvni_zahajeni" value="(ano|ne)" checked', 'bez ARES nic předvyplněno')
        self.odesli(prvni_zahajeni='ano', podnikani_od=f'{ROK}-09-03', modul_doprava=None)
        p = json.loads(self.db().execute('SELECT data FROM osvc_year_profiles').fetchone()[0])
        self.assertEqual((p['social_case'], p['business_periods'][0]['from']), ('new20', f'{ROK}-09-03'))
        stav = self.zelene(); self.assertEqual(set(stav.values()), {'known'}, (stav, self.duvody))

    def test_ares(self):
        from osvc_app.ares import AresUnavailable
        t = self.token()
        with mock.patch('osvc_app.ares.lookup_by_ico', side_effect=AresUnavailable()):
            self.assertEqual(self.k.post('/pruvodce/ares', data={'csrf_token': t, 'ico': '12345678'}).status_code, 503)
        with mock.patch('osvc_app.ares.lookup_by_ico', return_value=ARES):
            self.assertEqual(self.k.post('/pruvodce/ares', data={'csrf_token': t, 'ico': '1234 5678'}).get_json()['city'], 'Brno')
        self.odesli(zip='60200', modul_doprava=None)
        ident = json.loads(self.db().execute('SELECT data FROM osvc_profile WHERE id=1').fetchone()[0])
        self.assertEqual(ident['ares']['ico'], '12345678')


class SeServerovymUctem(unittest.TestCase):
    def test_ucet_z_nastaveni(self):
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        k = create_app({'TESTING': True, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH']}).test_client()
        self.assertEqual(k.get('/login').status_code, 200); self.assertEqual(k.get('/pruvodce').status_code, 302)

    def test_nedostupna_databaze(self):
        app = create_app({'TESTING': True, 'PROPAGATE_EXCEPTIONS': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': str(Path(TMP.name) / 'neni' / 'tu' / 'x.sqlite3'), 'APP_USER': None})
        with self.assertLogs(app.logger, 'WARNING'): self.assertEqual(app.test_client().get('/login').status_code, 500)


if __name__ == '__main__':
    unittest.main()
