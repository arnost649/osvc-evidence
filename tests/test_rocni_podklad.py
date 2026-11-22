"""1.0.3 – Roční přehled jako podklad k opsání: hlavička, upozornění jen když něco chybí, tři tabulky „řádek | hodnota“,
PDF na jednu stranu A4 bez řádků Stav / Kam patří / Co to je a bez rozpadu výdajů a měsíčních korekcí. Bez databáze."""
import re
import unittest
from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch
from osvc_app import annual, create_app
from osvc_app import annual_pdf
from osvc_app.annual_podklad import podklad


class Podklad(unittest.TestCase):
    def setUp(self):
        self.state = TemporaryDirectory(); self.addCleanup(self.state.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'APP_USER': 'test', 'APP_PASSWORD_HASH': 'x', 'DATA_STATE_DIR': self.state.name})
        self.identity = dict(ico='12345678', name='Jana Test', street='Dlouhá', number='5', city='Brno', zip='60200', country='Česká republika')
        self.p = dict(months=[dict(month=m, activity='yes', employment='no', social='main', minimum='yes') for m in range(1, 13)], vehicles={},
                      social_paid='60000', health_paid='40000', social_case='standard', insurer='VZP', insurer_code='111', health_from='2026-01-01',
                      health_to='2026-12-31', health_case='standard', expense_method='percentage', expense_rate='trade', base_adjustment='0',
                      tax_case='standard', tax_review='yes', overrides_enabled=True)
        self.ev = dict(income=Decimal('500000'), ordinary=Decimal('0'), vehicles={}, issues=[], counts={'Příjmy': 3, 'Výdaje': 0, 'Jízdy': 0, 'PHM': 0},
                       recorded_expenses=Decimal('1234'), ordinary_total=Decimal('1234'))

    def report(self, p=None):
        with self.app.test_request_context('/annual?year=2026'), patch('osvc_app.cas.today', return_value=date(2027, 2, 1)), \
             patch('osvc_app.profile.vehicles', return_value=[]), patch('osvc_app.db.connection', side_effect=AssertionError('bez databáze')):
            return annual.build(2026, self.identity, p or self.p, self.ev)

    def test_tabulky_a_hlavicka(self):
        d = podklad(self.report())
        self.assertIsNone(d['upozorneni'], 'vše vyplněné = bez upozornění')
        self.assertEqual(dict(d['hlavicka'])['Adresa'], 'Dlouhá 5, 602 00 Brno')
        self.assertEqual(dict(d['hlavicka'])['Období podnikání'], 'Celý rok')
        self.assertIn('111', dict(d['hlavicka'])['Zdravotní pojišťovna'])
        self.assertEqual([t['urad'] for t in d['tabulky']], ['Finanční úřad', 'ČSSZ', 'Zdravotní pojišťovna'])
        fu = {r['nazev']: r['hodnota'] for r in d['tabulky'][0]['radky']}
        self.assertEqual(fu, {'Příjmy': '500 000,00 Kč', 'Výdaje': '300 000,00 Kč', 'Způsob uplatnění výdajů': 'Procentní výdajový paušál (60 %)',
                              'Dílčí základ daně (ztráta) z § 7': '200 000,00 Kč'}, 'bez úprav základu se rozdíl a úpravy neopakují')
        cssz = {r['nazev']: r for r in d['tabulky'][1]['radky']}
        for nazev in ('Počet měsíců výkonu SVČ', 'z toho hlavní SVČ', 'z toho vedlejší SVČ', 'Zaplacené zálohy', 'Vyměřovací základ', 'Pojistné', 'Doplatek / přeplatek', 'Nová měsíční záloha'):
            self.assertIn(nazev, cssz)
        self.assertNotIn('Důvod vedlejší SVČ', cssz, 'bez vedlejší SVČ se důvod neuvádí')
        self.assertRegex(cssz['Doplatek / přeplatek']['hodnota'], r'^(doplatek|přeplatek) [\d ]+,\d\d Kč$')
        self.assertEqual((cssz['Nová měsíční záloha']['hodnota'], cssz['Nová měsíční záloha']['stav']), ('5 281,00 Kč', 'ok'), 'pravidla 2027: minimum hlavní SVČ')
        zp_nova = {r['nazev']: r for r in d['tabulky'][2]['radky']}['Nová měsíční záloha']
        self.assertEqual(zp_nova['hodnota'], '3 488,00 Kč')
        with patch('osvc_app.profile.zalohy', return_value=None):
            bez = {r['nazev']: r for r in podklad(self.report())['tabulky'][1]['radky']}['Nová měsíční záloha']
        self.assertEqual((bez['hodnota'], bez['stav']), ('stanoví se podle pravidel 2027', 'info'), 'bez vyhlášených pravidel nic neodhadovat')
        zp = [r['nazev'] for r in d['tabulky'][2]['radky']]
        self.assertIn('z toho měsíce s minimálním vyměřovacím základem', zp)

    def test_upozorneni_jen_kdyz_chybi(self):
        p = dict(self.p, social_paid='', insurer_code='')
        d = podklad(self.report(p))
        self.assertRegex(d['upozorneni'], r'^Chybí údaje v Profilu OSVČ \(.*ČSSZ.*\) – doplňte je; hodnoty označené „chybí“ zatím nejdou opsat\.$')
        self.assertEqual(d['upozorneni'].count('.'), 1, 'jedna věta')
        cssz = {r['nazev']: r for r in d['tabulky'][1]['radky']}
        self.assertEqual((cssz['Zaplacené zálohy']['hodnota'], cssz['Zaplacené zálohy']['stav']), ('chybí', 'chybi'))

    def pdf_texty(self, report):
        texty = []
        class Zaznam(annual_pdf.Paragraph):
            def __init__(self, text, *a, **k): texty.append(text); super().__init__(text, *a, **k)
        with patch('osvc_app.annual_pdf.Paragraph', Zaznam): data = annual_pdf.generate(report).read()
        return data, ' | '.join(texty)

    def test_pdf_jedna_strana_jen_hodnoty(self):
        for p in (self.p, dict(self.p, social_paid='', insurer_code='', expense_method='actual', expense_adjustment='0')):
            data, text = self.pdf_texty(self.report(p))
            self.assertTrue(data.startswith(b'%PDF'))
            self.assertEqual(len(re.findall(rb'/Type /Page[^s]', data)), 1, 'jedna strana A4')
            for nesmi in ('Stav:', 'Kam patří', 'Co to je', 'Běžné nákupy', 'Neuznatelné', 'aktivita', 'korekce'):
                self.assertNotIn(nesmi, text, nesmi)
            for musi in ('Finanční úřad', 'ČSSZ', 'Zdravotní pojišťovna', 'Příjmy', 'Dílčí základ daně', 'Vyměřovací základ', 'Nová měsíční záloha', '12345678', 'Dlouhá 5, 602 00 Brno'):
                self.assertIn(musi, text, musi)
        self.assertIn('Chybí údaje v Profilu OSVČ', text)
        _, text = self.pdf_texty(self.report())
        self.assertNotIn('Chybí údaje', text, 'upozornění jen když něco chybí')

    def test_stranka(self):
        from flask import render_template
        from osvc_app import profile_presentation
        report = self.report()
        with self.app.test_request_context('/annual?year=2026'), patch('osvc_app.profile.vehicles', return_value=[]), \
             patch('osvc_app.income_sources.default_source', return_value=None):
            from osvc_app import urady
            html = render_template('annual.html', profile_report=report, profile_view=profile_presentation.build(self.identity, self.p, report, []),
                                   podklad=podklad(report), urady=urady.karty(self.identity, self.p, 2026, sit=False), profile_year=2026, profile_years=[2026],
                                   year_profile=self.p, display=annual.display)
        self.assertNotIn('data-podklad-upozorneni', html); self.assertIn('Vše je vyplněné', html); self.assertIn('Stáhnout podklady (PDF)', html)
        self.assertEqual(html.count('data-urad='), 3, 'karty Finanční úřad, ČSSZ, zdravotní pojišťovna')
        horni, jak = html.split('<details class="settings-card annual-jak" data-annual-jak>', 1)
        self.assertNotIn('data-podklad-tabulka=', horni, 'čísla nahoře nejsou – jsou v PDF a v „Jak se počítá“')
        self.assertEqual(jak.count('data-podklad-tabulka='), 3); self.assertIn('500 000,00 Kč', jak)
        self.assertIn('Rozpis evidovaných výdajů', jak); self.assertNotIn('Rozpis evidovaných výdajů', horni)
        self.assertNotIn('<details class="settings-card annual-jak" data-annual-jak open', html, '„Jak se počítá“ je zavřené')


if __name__ == '__main__':
    unittest.main()
