"""v kódu nejsou názvy konkrétního e-shopu – pole s vyúčtováním platby a meta klíč PDF jsou v nastavení zdroje.
Bez DB zápisů a bez sítě (zdroj je podvržený v g.income_source)."""
import json
import re
import unittest
from decimal import Decimal as D
from pathlib import Path
from flask import g
from osvc_app import create_app
from osvc_app import woocommerce as wc

app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only'})
import osvc_app
ROOT = Path(osvc_app.__file__).resolve().parent.parent   # spust.sh čte test ze vstupu, __file__ tu nepomůže
PAYLOAD = {'schema_version': 1, 'order_id': 7, 'invoice_amount_czk': '100.00', 'payment_received_czk': '100.00', 'payment_currency': 'CZK',
           'fx_settlement_diff_czk': '0.00', 'verification_required': False, 'evidence_source': 'shop.example',
           'evidence_kind': 'fio_czk_account_movement', 'transaction_ids': ['1']}


def zdroj(**config):
    base = {'invoice_mode': 'sftp_archive', 'private_dir': '/archiv', 'legacy_dir': '/stare'}
    return {'id': 5, 'name': 'Můj e-shop', 'url': 'https://shop.example', 'configuration': json.dumps({**base, **config})}


class ObecneNazvy(unittest.TestCase):
    def test_v_kodu_neni_nazev_eshopu(self):
        """Adresy a názvy skutečných zdrojů příjmů (z testovací DB) se v kódu aplikace nevyskytují."""
        from urllib.parse import urlsplit
        from osvc_app import db
        self.assertTrue((ROOT / 'osvc_app' / 'woocommerce.py').is_file())
        with app.app_context():
            zdroje = db.query('SELECT name,url FROM income_sources')
        nazvy = set()
        for z in zdroje:
            host = (urlsplit(z['url'] or '').hostname or '').lower().removeprefix('www.')
            nazvy |= {n for n in (host, host.split('.')[0], (z['name'] or '').strip().lower()) if len(n) >= 4}
        if not nazvy: self.skipTest('testovací DB nemá žádný zdroj příjmů')
        vzor = re.compile('|'.join(re.escape(n) for n in sorted(nazvy)), re.I)
        nalezeno = [str(p.relative_to(ROOT)) for p in (ROOT / 'osvc_app').rglob('*')
                    if p.is_file() and p.suffix in ('.py', '.html', '.js', '.css', '.json') and vzor.search(p.read_text(errors='ignore'))]
        self.assertEqual(nalezeno, [])

    def test_pdf_podle_meta_klice_z_nastaveni(self):
        order = {'id': 7, 'meta_data': [{'key': '_shop_invoice_pdf', 'value': 'invoice-7-abc123.pdf'}]}
        with app.test_request_context():
            g.income_source = zdroj(invoice_meta_key='_shop_invoice_pdf')
            self.assertEqual(wc._invoice_sources(order), ['/archiv/invoice-7-abc123.pdf'])
            g.income_source = zdroj()   # bez nastaveného klíče se meta nečte → staré cesty
            self.assertEqual(wc._invoice_sources(order), ['/archiv/legacy-wpo/faktura-7.pdf', '/stare/faktura-7.pdf'])

    def test_nazev_souboru_faktury(self):
        with app.test_request_context():
            g.income_source = zdroj(); self.assertEqual(wc.invoice_filename(7), 'source-5-order-7-invoice.pdf')
            g.income_source = {}; self.assertEqual(wc.invoice_filename(7), 'order-7-invoice.pdf')

    def test_vyuctovani_podle_nastaveni_zdroje(self):
        order = {'id': 7, 'number': '7', 'total': '100.00', 'date_paid': '2026-11-01T10:00:00', 'billing': {'first_name': 'Test'},
                 'shop_settlement': PAYLOAD}
        with app.test_request_context():
            g.income_source = zdroj(settlement_field='shop_settlement')
            i = wc.normalize_income(order)
            self.assertEqual(i.payment_received_czk, D('100.00')); self.assertFalse(i.payment_needs_review)
            g.income_source = zdroj()   # zdroj bez smlouvy o vyúčtování: pole se ignoruje, nic ke kontrole
            i = wc.normalize_income(order)
            self.assertIsNone(i.payment_received_czk); self.assertFalse(i.payment_needs_review)


if __name__ == '__main__':
    unittest.main()
