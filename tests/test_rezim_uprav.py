"""Režim úprav: přepínač „Upravit“ v záhlaví seznamů; vypnutý po načtení, sloupec Akce označený .akce-sloupec (schovává CSS).
Běží jen přes tests/spust.sh proti osvc_test."""
import re
import tempfile
import unittest
from pathlib import Path
import osvc_app
from osvc_app import create_app

app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
app.config['MODULY_SETTINGS_FILE'] = tempfile.mkdtemp() + '/moduly.json'


class RezimUprav(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as s: s['user'] = app.config['APP_USER']; s['local_auth'] = 1

    def test_seznamy_maji_prepinac_a_oznacene_akce(self):
        for url in ('/payments/income?year=2026', '/payments/expense?year=2026', '/trips?year=2026', '/fuel?year=2026', '/address-book'):
            h = self.client.get(url).get_data(as_text=True)
            self.assertIn('data-edit-toggle', h, url)
            self.assertNotRegex(h, r'data-edit-toggle[^>]*checked', url)   # po načtení vždy vypnutý
            self.assertIn('autocomplete="off"', re.search(r'<input[^>]*data-edit-toggle[^>]*>', h).group(0), url)
            self.assertIn('akce-sloupec', h, url)
            self.assertNotIn('<th>Akce</th>', h, url)
            self.assertNotIn('<td data-label="Akce">', h, url)

    def test_text_nejvys_dva_radky(self):
        for url in ('/payments/income?year=2026', '/payments/expense?year=2026', '/trips?year=2026', '/fuel?year=2026', '/address-book', '/documents', '/'):   # seznam akcí je v osvc_test prázdný
            self.assertIn('class="text-2r"', self.client.get(url).get_data(as_text=True), url)
        css = (Path(osvc_app.__file__).parent / 'static' / 'ux.css').read_text()
        self.assertIn('.text-2r{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2', css)
        self.assertIn('tbody td{height:calc(3em + 1.56rem + 1px)', css)          # stejná výška řádků na počítači
        self.assertIn('td.akce-sloupec{display:flex!important;visibility:hidden}', css)   # mobil: místo pro Akce zůstává

    def test_css_a_reset(self):
        static = Path(osvc_app.__file__).parent / 'static'
        self.assertIn('[data-edit-toggle]:not(:checked)) .akce-sloupec{display:none', (static / 'ux.css').read_text())
        self.assertIn("addEventListener('pageshow'", (static / 'ui.js').read_text())


if __name__ == '__main__':
    unittest.main()
