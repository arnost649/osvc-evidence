"""1.0.3 – pravidla nové zálohy 2027 (tax_rules/zalohy-2027.json): každá hodnota má oficiální zdroj (a u vyhlašovaných i datum
vyhlášení), uložená minima odpovídají výpočtu ze zákona a nařízení vlády, výpočet nové zálohy v Ročním přehledu. Bez databáze."""
import json
import unittest
from datetime import date
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from unittest.mock import patch
import osvc_app
from osvc_app import annual, profile

D = Decimal
up = lambda x: D(x).quantize(D('1'), rounding=ROUND_CEILING)
SOUBOR = Path(osvc_app.__file__).resolve().parent / 'tax_rules' / 'zalohy-2027.json'


class Pravidla(unittest.TestCase):
    def test_zdroje_a_vypocet_minim(self):
        z = json.loads(SOUBOR.read_text(encoding='utf-8'))
        pm = z['prumerna_mzda']
        self.assertEqual((pm['vyhlaseno'], pm['ucinnost']), ('2026-09-29', '2027-01-01'))
        self.assertIn('177/2026 Sb.', pm['zdroj']); self.assertEqual(up(D('48900') * D('1.0565')), D(pm['hodnota']), 'průměrná mzda = VVZ × koeficient, nahoru')
        for sekce in ('social', 'health'):
            for klic, v in z[sekce].items():
                if isinstance(v, dict) and 'hodnota' in v:
                    self.assertTrue(v.get('zdroj') and ('Sb.' in v['zdroj']), (sekce, klic))
                    if 'vyhlaseno' in v and v['vyhlaseno'][:1].isdigit(): date.fromisoformat(v['vyhlaseno'])
        self.assertEqual(z['social']['main_min_ratio']['vyhlaseno'], '2026-06-10'); self.assertIn('90/2026 Sb.', z['social']['main_min_ratio']['zdroj'])
        P, s, h = D(pm['hodnota']), z['social'], z['health']
        for minimum, ratio, zaloha in (('main_min_month', 'main_min_ratio', 'main_min_advance'), ('new_main_min_month', 'new_main_min_ratio', 'new_main_min_advance'),
                                       ('secondary_min_month', 'secondary_min_ratio', 'secondary_min_advance')):
            self.assertEqual(up(P * D(s[ratio]['hodnota'])), D(s[minimum]), minimum)
            self.assertEqual(up(D(s[minimum]) * D(s['rate']['hodnota'])), D(s[zaloha]), zaloha)
        self.assertEqual((s['main_min_advance'], s['secondary_min_advance'], s['new_main_min_advance']), ('5281', '1660', '3772'))
        self.assertEqual(D(h['min_month']), P * D(h['min_ratio']['hodnota'])); self.assertEqual(up(D(h['min_month']) * D(h['rate']['hodnota'])), D(h['min_advance']))
        self.assertEqual(h['min_advance'], '3488'); self.assertEqual(D(s['max_base']['hodnota']), 48 * P)
        self.assertIsNone(profile.zalohy(2028), 'pro nevyhlášený rok nic')


class NovaZaloha(unittest.TestCase):
    def test_vypocet(self):
        p = {'social_case': 'standard'}
        self.assertEqual(annual.nova_zaloha('social', 2026, D('7670'), 12, p, main=12)[0], D('5281'), 'nízký zisk = minimum')
        z, pozn = annual.nova_zaloha('social', 2026, D('600000'), 12, p, main=12)
        self.assertEqual(z, up(up(D('600000') * D('0.55') / 12) * D('0.292')))   # 27 500 → 8 030
        self.assertEqual(z, D('8030')); self.assertIn('vyhlášeno 29. 9. 2026', pozn); self.assertIn('51 663 Kč', pozn)
        self.assertEqual(annual.nova_zaloha('social', 2026, D('-5000'), 6, p, main=6)[0], D('5281'), 'ztráta = minimum')
        self.assertEqual(annual.nova_zaloha('social', 2026, D('100000'), 12, p, secondary=12)[0], up(D('5683') * D('0.292')), 'vedlejší: minimum 11 %')
        self.assertEqual(annual.nova_zaloha('social', 2026, D('100000'), 12, {'social_case': 'new20', 'start': '2025-03-01'}, main=12)[0], D('3772'))
        self.assertEqual(annual.nova_zaloha('social', 2026, D('100000'), 12, {'social_case': 'new20', 'start': '2020-03-01'}, main=12)[0], D('5281'))
        self.assertIsNone(annual.nova_zaloha('social', 2026, D('100000'), 12, p, main=6, secondary=6)[0], 'kombinace se neodhaduje')
        self.assertEqual(annual.nova_zaloha('health', 2026, D('7670'), 12, p, health_min=12)[0], D('3488'))
        self.assertEqual(annual.nova_zaloha('health', 2026, D('600000'), 12, p, health_min=12)[0], D('3488'), '25 000 Kč < minimum 25 831,50 Kč')
        self.assertEqual(annual.nova_zaloha('health', 2026, D('900000'), 12, p, health_min=12)[0], up(D('900000') * D('0.5') / 12 * D('0.135')))   # 5 063
        z, pozn = annual.nova_zaloha('health', 2026, D('100000'), 12, p, health_min=5); self.assertIsNone(z); self.assertIn('ověřte u pojišťovny', pozn)
        self.assertEqual(annual.nova_zaloha('social', 2027, D('100000'), 12, p, main=12), (None, 'stanoví se podle pravidel 2028'), 'nevyhlášený rok = nic neodhadovat')


if __name__ == '__main__':
    unittest.main()
