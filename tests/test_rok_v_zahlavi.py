"""Seznamy Příjmy, Výdaje, Jízdy, PHM: výběr roku v záhlaví vedle nadpisu a součet za vybraný rok vpravo před Upravit (bez bloku „Rok“ s tlačítkem Filtrovat),
nabízí roky se záznamy + aktuální a zvolený rok. Běží jen přes tests/spust.sh."""
import os
import re
import unittest
from osvc_app import create_app, cas
from osvc_app.db import roky_zaznamu


class RokVZahlavi(unittest.TestCase):
    def setUp(self):
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH']})
        self.k = self.app.test_client()
        with self.k.session_transaction() as s: s['user'] = self.app.config['APP_USER']; s['local_auth'] = 1

    def test_vyber_roku_v_zahlavi(self):
        rok = cas.today().year
        for url in ('/payments/income', '/payments/expense', '/trips', '/fuel'):
            html = self.k.get(url).get_data(as_text=True)
            self.assertNotIn('class="filter"', html, url); self.assertNotIn('<span>Filtrovat</span>', html, url)
            hlava = re.search(r'<div class="list-title">.*?</form></div>', html, re.S); self.assertTrue(hlava, url)
            self.assertIn('onchange="this.form.requestSubmit()"', hlava.group(0)); self.assertIn('<noscript><button class="year-filter-go"', hlava.group(0))
            self.assertIn(f'<option value="{rok}" selected>{rok}</option>', hlava.group(0), url)
            self.assertNotIn('Součet za', html, url + ': součet už není nahoře na stránce')
            self.assertEqual(html.count('data-sum-column'), 1, url + ': sloupec, se kterým součet lícuje')
            self.assertRegex(html, r'<div class="list-heading-end"><p class="list-sum">Součet: <span class="list-sum-value">[^<]+(km|Kč)</span></p>', url)
        html = self.k.get('/trips?year=2019').get_data(as_text=True)
        self.assertIn('<option value="2019" selected>2019</option>', html, 'zvolený rok je v nabídce, i když nemá záznamy')

    def test_rocni_prehled_jen_roky_s_daty(self):
        from osvc_app.annual_routes import roky_prehledu
        with self.app.app_context(): roky = roky_prehledu()
        html = self.k.get('/annual').get_data(as_text=True)
        nabidka = [int(y) for y in re.findall(r'<option value="(\d{4})"', re.search(r'<form class="panel-year-control".*?</form>', html, re.S).group(0))]
        self.assertEqual(nabidka, roky or [cas.today().year], 'jen roky s daty (bez dat jen letošní)')
        html = self.k.get('/annual?year=2003').get_data(as_text=True)
        self.assertIn('<option value="2003" selected>2003</option>', html, 'zvolený rok z odkazu zůstane v nabídce')

    def test_roky_zaznamu(self):
        with self.app.app_context():
            self.assertEqual(roky_zaznamu([], (2024, '2026', 'nesmysl', 2024)), [2026, 2024])
            roky = roky_zaznamu([('payments', 'payment_date', 'deleted_at IS NULL', ())])
            self.assertEqual(roky, sorted(roky, reverse=True))


if __name__ == '__main__':
    unittest.main()
