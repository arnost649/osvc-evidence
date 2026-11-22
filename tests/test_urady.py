"""1.0.3 – Roční přehled: příslušné úřady (FÚ podle kraje, OSSZ podle okresu, pojišťovna z profilu), formuláře a termíny roku.
Data jen z oficiálních zdrojů se zdrojem a datem ověření; příslušnost obecně podle adresy (ARES), bez odhadu. Bez databáze a bez sítě."""
import json
import re
import unicodedata
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import osvc_app
from osvc_app import create_app, urady

DATA = Path(osvc_app.__file__).resolve().parent / 'data'
OKRESY = ('Benešov,Beroun,Blansko,Brno-město,Brno-venkov,Bruntál,Břeclav,Česká Lípa,České Budějovice,Český Krumlov,Děčín,Domažlice,Frýdek-Místek,'
          'Havlíčkův Brod,Hodonín,Hradec Králové,Cheb,Chomutov,Chrudim,Jablonec nad Nisou,Jeseník,Jičín,Jihlava,Jindřichův Hradec,Karlovy Vary,Karviná,'
          'Kladno,Klatovy,Kolín,Kroměříž,Kutná Hora,Liberec,Litoměřice,Louny,Mělník,Mladá Boleslav,Most,Náchod,Nový Jičín,Nymburk,Olomouc,Opava,'
          'Ostrava-město,Pardubice,Pelhřimov,Písek,Plzeň-jih,Plzeň-město,Plzeň-sever,Prachatice,Praha-východ,Praha-západ,Prostějov,Přerov,Příbram,'
          'Rakovník,Rokycany,Rychnov nad Kněžnou,Semily,Sokolov,Strakonice,Svitavy,Šumperk,Tábor,Tachov,Teplice,Trutnov,Třebíč,Uherské Hradiště,'
          'Ústí nad Labem,Ústí nad Orlicí,Vsetín,Vyškov,Zlín,Znojmo,Žďár nad Sázavou').split(',')
KRAJE = ['Hlavní město Praha', 'Středočeský kraj', 'Jihočeský kraj', 'Plzeňský kraj', 'Karlovarský kraj', 'Ústecký kraj', 'Liberecký kraj',
         'Královéhradecký kraj', 'Pardubický kraj', 'Kraj Vysočina', 'Jihomoravský kraj', 'Olomoucký kraj', 'Moravskoslezský kraj', 'Zlínský kraj']
SVATKY_2027 = {date(2027, 1, 1), date(2027, 3, 26), date(2027, 3, 29), date(2027, 5, 1), date(2027, 5, 8), date(2027, 7, 5), date(2027, 7, 6),
               date(2027, 9, 28), date(2027, 10, 28), date(2027, 11, 17), date(2027, 12, 24), date(2027, 12, 25), date(2027, 12, 26)}


class Data(unittest.TestCase):
    def test_adresar(self):
        a = json.loads((DATA / 'urady.json').read_text(encoding='utf-8'))
        fu = a['financni_urady']; self.assertEqual(sorted(fu['urady']), sorted(KRAJE)); self.assertTrue(fu['zdroj'] and fu['url'].startswith('https://financnisprava.gov.cz'))
        self.assertEqual(fu['urady']['Hlavní město Praha']['id_ds'], '7nyn2d9'); self.assertEqual(fu['urady']['Královéhradecký kraj']['id_ds'], 'fj8ny4i')
        o = a['ossz']; self.assertTrue(o['url'].startswith('https://www.cssz.gov.cz'))
        for okres in OKRESY:
            klic = o['okresy'].get(urady.slug(okres)); self.assertIn(klic, o['spravy'], okres)
            self.assertRegex(o['spravy'][klic]['id_ds'], r'^[a-z0-9]{7}$', okres)
        self.assertEqual(o['spravy'][o['okresy']['praha-vychod']]['id_ds'], 'hnhacvt', 'Praha-východ pod PSSZ od 1. 7. 2024')
        self.assertEqual(o['spravy'][o['okresy']['plzen-jih']]['id_ds'], '4k9ac38', 'Plzeň-jih pod OSSZ Plzeň od 1. 7. 2024')
        self.assertEqual(o['spravy'][o['okresy']['nachod']]['id_ds'], 'bmkac98')
        self.assertEqual(sorted(a['pojistovny']['web']), ['111', '201', '205', '207', '209', '211', '213'])
        for d in (a['overeno'], fu['overeno'], o['overeno']): date.fromisoformat(d)

    def test_podani_2026(self):
        d = urady.podani(2026); self.assertEqual(d['rok'], 2026); date.fromisoformat(d['overeno'])
        for klic in ('tax', 'social', 'health'):
            f = d[klic]['formular']
            self.assertIn(f['stav'], ('vydáno', 'zatím nevydáno', 'neověřeno')); self.assertTrue(f['zdroj'] and f['url'].startswith('https://')); date.fromisoformat(f['overeno'])
            for t in d[klic]['terminy']:
                den = date.fromisoformat(t['datum']); self.assertLess(den.weekday(), 5, t); self.assertNotIn(den, SVATKY_2027, t)
                self.assertIn('Sb.', t['zdroj'], t)
            self.assertIn('Sb.', d[klic]['doplatek']['zdroj'])
        self.assertEqual([t['datum'] for t in d['tax']['terminy']], ['2027-04-01', '2027-05-03', '2027-07-01'])
        self.assertEqual([t['datum'] for t in d['social']['terminy']], ['2027-05-03', '2027-06-03', '2027-08-02'])
        self.assertIsNone(urady.podani(2027), 'rok bez ověřených dat = nic')


def ares(odpovedi):
    """Falešné ARES: seznam odpovědí v pořadí volání."""
    volani = []
    def request(path, payload=None, timeout=5):
        volani.append(payload); return odpovedi[min(len(volani) - 1, len(odpovedi) - 1)]
    return request, volani


ADRESA = lambda obec, okres, kraj, psc: {'nazevObce': obec, 'nazevOkresu': okres, 'nazevKraje': kraj, 'psc': psc}


class Prislusnost(unittest.TestCase):
    def setUp(self):
        self.state = TemporaryDirectory(); self.addCleanup(self.state.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'x', 'DATA_STATE_DIR': self.state.name})
        self.ctx = self.app.test_request_context('/'); self.ctx.push(); self.addCleanup(self.ctx.pop)
        self.app.config['TESTING'] = False   # povolit „síť“ – _request je vždy podstrčený

    def test_obecne_podle_adresy(self):
        request, volani = ares([{'standardizovaneAdresy': [ADRESA('Náchod', 'Náchod', 'Královéhradecký kraj', 54701)]}])
        with patch('osvc_app.ares._request', request):
            u = urady.prislusne({'street': 'Masarykovo náměstí', 'number': '40', 'zip': '547 01', 'city': 'Náchod'}, {'insurer_code': '205'})
        self.assertEqual((u['tax']['id_ds'], u['social']['id_ds'], u['health']['id_ds']), ('fj8ny4i', 'bmkac98', 'mk5ab8i'))
        self.assertEqual(u['health']['web'], 'https://www.cpzp.cz/'); self.assertIn('trvalého pobytu', u['social']['prislusnost'])
        self.assertEqual(volani[0]['textovaAdresa'], 'Masarykovo náměstí 40, Náchod')
        with patch('osvc_app.ares._request', side_effect=AssertionError('podruhé bez sítě')):
            self.assertEqual(urady.prislusne({'street': 'Masarykovo náměstí', 'number': '40', 'zip': '547 01', 'city': 'Náchod'}, {})['social']['id_ds'], 'bmkac98')

    def test_stejnojmenne_obce_jen_podle_psc(self):
        request, _ = ares([{'standardizovaneAdresy': [ADRESA('Říčany', 'Praha-východ', 'Středočeský kraj', 25101)]},
                           {'standardizovaneAdresy': [ADRESA('Říčany', 'Praha-východ', 'Středočeský kraj', 25101), ADRESA('Říčany', 'Brno-venkov', 'Jihomoravský kraj', 66482)]}])
        with patch('osvc_app.ares._request', request):
            u = urady.prislusne({'street': '', 'number': '5', 'zip': '66482', 'city': 'Říčany'}, {})
        self.assertEqual((u['misto']['okres'], u['tax']['nazev'], u['social']['id_ds']), ('Brno-venkov', 'Finanční úřad pro Jihomoravský kraj', 'hxuadbz'))

    def test_bez_shody_nic_neodhaduje(self):
        request, _ = ares([{'standardizovaneAdresy': [ADRESA('Brno', 'Brno-město', 'Jihomoravský kraj', 60200)]}])
        with patch('osvc_app.ares._request', request):
            u = urady.prislusne({'street': 'Vzorová', 'number': '1', 'zip': '99999', 'city': 'Brno'}, {})
        self.assertEqual((u['misto'], u['tax'], u['social'], u['health']), (None, None, None, None))
        from osvc_app.ares import AresUnavailable
        with patch('osvc_app.ares._request', side_effect=AresUnavailable('x')):
            self.assertIsNone(urady.prislusne({'street': 'Jiná', 'number': '2', 'zip': '60200', 'city': 'Brno'}, {})['tax'], 'ARES nedostupný = neurčeno')

    def test_praha_bez_site_a_karty(self):
        with patch('osvc_app.ares._request', side_effect=AssertionError('Praha bez ARES')):
            k = urady.karty({'street': 'Letenská', 'number': '525/15', 'zip': '11800', 'city': 'Praha 1'}, {'insurer_code': '111'}, 2026)
        self.assertEqual([x['urad']['id_ds'] for x in k['karty']], ['7nyn2d9', 'hnhacvt', 'i48ae3q'])
        self.assertEqual(k['karty'][0]['terminy'][0]['text'], '1. 4. 2027 (čt)'); self.assertEqual(k['karty'][0]['formular']['stav'], 'zatím nevydáno')
        k2 = urady.karty({'city': 'Praha'}, {'insurer_code': '207'}, 2026)
        self.assertEqual(k2['karty'][2]['formular']['stav'], 'neověřeno', 'formulář jiné pojišťovny než VZP neověřen')
        bez = urady.karty({'city': 'Praha'}, {}, 2025)
        self.assertFalse(bez['data_roku']); self.assertIsNone(bez['karty'][0]['formular']); self.assertEqual(bez['karty'][0]['terminy'], [])


class TrvalyPobyt(Prislusnost):
    def test_kontrola_a_pruvodce(self):
        from osvc_app import profile, pruvodce
        self.assertEqual(profile.parse_pobyt({}, 'identity_'), ('', None), 'výchozí: stejná adresa')
        self.assertEqual(profile.parse_pobyt({'identity_pobyt_jinde': 'ano', 'identity_pobyt_street': 'Dlouhá', 'identity_pobyt_number': '5',
                                              'identity_pobyt_city': 'Náchod', 'identity_pobyt_zip': '547 01'}, 'identity_'),
                         ('ano', {'street': 'Dlouhá', 'number': '5', 'city': 'Náchod', 'zip': '54701'}))
        with self.assertRaisesRegex(ValueError, 'adresu trvalého pobytu'): profile.parse_pobyt({'identity_pobyt_jinde': 'ano', 'identity_pobyt_city': 'Náchod'}, 'identity_')
        with self.assertRaisesRegex(ValueError, '5 číslic'): profile.parse_pobyt({'pobyt_jinde': 'ano', 'pobyt_number': '1', 'pobyt_city': 'X', 'pobyt_zip': '123'}, '')
        zaklad = {'ico': '12345678', 'name': 'Test', 'number': '1', 'city': 'Brno', 'zip': '60200'}
        self.assertEqual(pruvodce.identita(zaklad)['pobyt_jinde'], '')
        ident = pruvodce.identita({**zaklad, 'pobyt_jinde': 'ano', 'pobyt_number': '12', 'pobyt_city': 'Smetanova Lhota', 'pobyt_zip': '39804'})
        self.assertEqual((ident['pobyt_jinde'], ident['pobyt']['city']), ('ano', 'Smetanova Lhota'))

    def test_urady_podle_trvaleho_pobytu(self):
        identity = {'street': 'Masarykovo náměstí', 'number': '40', 'zip': '54701', 'city': 'Náchod', 'pobyt_jinde': 'ano',
                    'pobyt': {'street': '', 'number': '12', 'city': 'Smetanova Lhota', 'zip': '39804'}}
        request, volani = ares([{'standardizovaneAdresy': [ADRESA('Smetanova Lhota', 'Písek', 'Jihočeský kraj', 39804)]}])
        with patch('osvc_app.ares._request', request):
            k = urady.karty(identity, {'insurer_code': '111'}, 2026)
        self.assertEqual(volani[0]['textovaAdresa'], 'Smetanova Lhota 12', 'dotaz na trvalý pobyt, ne na adresu podnikání')
        self.assertEqual((k['karty'][0]['urad']['nazev'], k['karty'][1]['urad']['id_ds']), ('Finanční úřad pro Jihočeský kraj', 'wazacze'))
        self.assertEqual(k['podle'], 'adresy trvalého pobytu')
        with patch('osvc_app.ares._request', side_effect=AssertionError('uloženo')):
            stejna = urady.karty({**identity, 'pobyt_jinde': ''}, {}, 2026, sit=False)
        self.assertIn('adresy podnikání', stejna['podle']); self.assertIsNone(stejna['karty'][0]['urad'], 'nezaškrtnuto = adresa podnikání (zde neověřená)')


if __name__ == '__main__':
    unittest.main()
