"""A1 – Roční přehled a Přehled pro novou instalaci: odhad ročního úhrnu záloh z měsíční částky, chybějící pravidla roku
jasně („nainstalujte novou verzi“), běžné okolnosti jako výchozí, Přehled 0,00 Kč a výzvy s odkazem na chybějící nastavení.
Běží jen přes tests/spust.sh."""
import os
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from osvc_app import annual, create_app, instalace, profile

TMP = tempfile.TemporaryDirectory()


class Vypocty(unittest.TestCase):
    def test_odhad_zaloh(self):
        p = {'social_advance_month': '5000', 'health_advance_month': '3306', 'health_paid': '12000'}
        poznamky = annual.odhad_zaloh(p, 10)
        self.assertEqual(p['social_paid'], '50000.00'); self.assertIn('5000 Kč měsíčně × 10', poznamky['social']); self.assertIn('ePortálu ČSSZ', poznamky['social'])
        self.assertEqual(p['health_paid'], '12000', 'skutečný úhrn má přednost'); self.assertNotIn('health', poznamky)

    def test_zachovani_odhadu_pri_ulozeni_profilu(self):
        novy = profile.zachovej_odhad_zaloh({'social_advance_month': '5000'}, {'social_paid': ''})
        self.assertEqual(novy['social_advance_month'], '5000')
        self.assertNotIn('social_advance_month', profile.zachovej_odhad_zaloh({'social_advance_month': '5000'}, {'social_paid': '60000'}))


class NovaInstalace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        konf = Path(TMP.name) / 'osvc.conf'; instalace.zapis_nastaveni(konf, Path(TMP.name) / 'data'); instalace.priprav(instalace.nacti(konf))
        os.environ['OSVC_CONFIG'] = str(konf)
        try: cls.app = create_app({'TESTING': True})
        finally: os.environ.pop('OSVC_CONFIG')
        cls.k = cls.app.test_client()
        t = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', cls.k.get('/pruvodce').get_data(as_text=True)).group(1)
        cls.k.post('/pruvodce', data={'csrf_token': t, 'zamestnani': 'ne', 'pojistovna': '111', 'social_zalohy': 'neplati', 'health_zalohy': 'neplati', 'vydaje': 'actual', 'dane_rezim': 'standard', 'prvni_zahajeni': 'ne', 'ico': '12345678', 'name': 'Test', 'number': '1', 'city': 'Brno', 'zip': '60200',
                                      'username': 'test', 'password': 'heslo-12345', 'password2': 'heslo-12345'})

    def test_prehled_nula_a_vyzvy(self):
        html = self.k.get('/').get_data(as_text=True)
        self.assertNotIn('>—<', html); self.assertGreaterEqual(html.count('0,00 Kč'), 3)
        self.assertIn('data-vyzvy', html); self.assertRegex(html, r'href="/settings#profile-(business|employment|social|health|tax)"')

    def test_chybejici_pravidla(self):
        with self.app.app_context():
            *_, r = annual.year_report(2031)
        self.assertIn('Pravidla pro rok 2031 zatím nejsou – nainstalujte novou verzi aplikace.', r['reviews'])
        self.assertIn('Pravidla pro rok 2031 zatím nejsou', self.k.get('/settings?year=2031').get_data(as_text=True))

    def test_zaloha_na_pristi_rok_jen_informace(self):
        with self.app.app_context():
            *_, r = annual.year_report(2026)
        stavy = {f['field_key']: f['status'] for s in r['sections'] if s['key'] == 'social' for f in s['fields']}
        self.assertIn(stavy['advance'], ('info', 'known'))


if __name__ == '__main__':
    unittest.main()
