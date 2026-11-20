"""Výdaje – formulář Zapsat/Upravit nákup: pole „Popis“, jedno pole Daňové uplatnění (100 % předvybráno / 50 % / Vlastní…, pak číselné pole s %
a křížkem zpět), bez nápovědy (i), Uložit ve stejném řádku. Běží jen přes tests/spust.sh."""
import os
import re
import unittest
from osvc_app import create_app


class VydajFormular(unittest.TestCase):
    def setUp(self):
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH']})
        self.k = self.app.test_client()
        with self.k.session_transaction() as s: s['user'] = self.app.config['APP_USER']; s['local_auth'] = 1

    def test_formular(self):
        html = self.k.get('/payments/expense').get_data(as_text=True)
        form = re.search(r'<form id="expense-form".*?</form>', html, re.S).group(0)
        self.assertIn('>Popis</label>', form); self.assertNotIn('Co jsem koupil', form); self.assertNotIn('Vyberte režim', form); self.assertNotIn('Jiný podíl', form)
        opts = re.findall(r'<option value="([^"]*)"( selected)?>([^<]*)</option>', re.search(r'<select name="tax_mode".*?</select>', form, re.S).group(0))
        self.assertEqual(opts, [('100', ' selected', '100 %'), ('50', '', '50 %'), ('custom', '', 'Vlastní…')], 'výchozí 100 %, bez „Vyberte režim“')
        self.assertNotIn('help-trigger', form, 'bez ikonky (i)')
        self.assertRegex(form, r'<span class="tax-pct-box" data-tax-custom hidden><input[^>]*name="tax_pct"[^>]*disabled')
        self.assertNotIn('data-tax-reset', form, 'místo křížku šipka – tentýž select')
        self.assertIn('<span class="tax-field-errors">', form, 'hlášky mimo tok – výška se nemění')
        sit = re.search(r'<div class="expense-tax-save">.*?</div>\s*</div>', form, re.S).group(0)
        self.assertIn('save-button', sit, 'Uložit ve stejném řádku jako Daňové uplatnění')


if __name__ == '__main__':
    unittest.main()
