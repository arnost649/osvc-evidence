"""Adresář – formulář kontaktu: jen veřejné údaje (název, IČO, DIČ, adresa), role jako štítky (aspoň jedna), ARES (fresh/keep),
e-mail, telefon a poznámka se nezobrazují ani nemažou. ARES je nahrazený mockem. Běží jen přes tests/spust.sh."""
import os
import re
import unittest
from unittest.mock import patch
from osvc_app import create_app
from osvc_app import db

ARES = {'name': 'Zkušební úřad', 'ico': '12345679', 'dic': 'CZ12345679', 'address': 'Dlouhá 1/2, 11000 Praha', 'city': 'Praha',
        'street': 'Dlouhá', 'number': '1/2', 'zip': '11000', 'country': 'Česká republika', 'country_code': 'CZ', 'part': '', 'vznik': ''}


class AdresarFormular(unittest.TestCase):
    def setUp(self):
        if os.environ.get('DB_ENGINE') != 'sqlite': self.skipTest('jen SQLite')
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH']})
        self.k = self.app.test_client()
        with self.k.session_transaction() as s: s['user'] = self.app.config['APP_USER']; s['local_auth'] = 1
        self.ctx = self.app.app_context(); self.ctx.push(); self.addCleanup(self.ctx.pop)

    def token(self):
        return re.search(r'name="csrf_token" value="([^"]+)"', self.k.get('/address-book').get_data(as_text=True)).group(1)

    def post(self, url, data): return self.k.post(url, data=dict(data, csrf_token=self.token()))

    def row(self, name): return db.query("SELECT * FROM counterparties WHERE name=%s AND deleted_at IS NULL", (name,), one=True)

    def test_stranka_bez_kontaktnich_poli(self):
        html = self.k.get('/address-book').get_data(as_text=True)
        for pole in ('name="email"', 'name="phone"', 'name="note"', 'telefonu nebo e-mailu'): self.assertNotIn(pole, html)
        self.assertIn('data-ares-fill', html); self.assertIn('class="role-chip"', html); self.assertIn('data-address-new', html)
        form = re.search(r'<form class="address-edit-form[^"]*"[^>]*data-new-contact.*?</form>', html, re.S).group(0)
        poradi = re.findall(r'name="(roles|name|ico|dic|street|city|postal_code|country_code)"', form)
        self.assertEqual([p for i, p in enumerate(poradi) if p not in poradi[:i]], ['roles', 'name', 'ico', 'dic', 'street', 'city', 'postal_code', 'country_code'])

    def test_rucni_kontakt_a_role(self):
        r = self.post('/address-book', {'name': 'Test Ruční Osoba', 'roles': ['customer'], 'street': 'Polní 5', 'city': 'Brno', 'postal_code': '60200'})
        self.assertEqual(r.status_code, 302); c = self.row('Test Ruční Osoba')
        self.assertEqual((c['role'], c['street'], c['country_code'], c['verified_at']), ('customer', 'Polní 5', 'CZ', None))
        db.execute("UPDATE counterparties SET email='a@example.invalid',phone='123',note='pozn' WHERE id=%s", (c['id'],))
        self.post(f"/address-book/{c['id']}", {'name': 'Test Ruční Osoba', 'roles': ['customer', 'supplier'], 'city': 'Olomouc'})
        c = self.row('Test Ruční Osoba')
        self.assertEqual((c['role'], c['city'], c['email'], c['phone'], c['note']), ('both', 'Olomouc', 'a@example.invalid', '123', 'pozn'), 'kontaktní údaje zůstaly v DB')
        self.post(f"/address-book/{c['id']}", {'name': 'Test Ruční Osoba', 'city': 'Zlín'})
        self.assertEqual(self.row('Test Ruční Osoba')['city'], 'Olomouc', 'bez role se neuloží')
        self.post(f"/address-book/{c['id']}", {'name': 'Test Ruční Osoba', 'roles': ['customer'], 'ico': '123'})
        self.assertIsNone(self.row('Test Ruční Osoba')['ico'], 'IČO musí mít 8 číslic')

    def test_ares_fresh_a_keep(self):
        with patch('osvc_app.address_routes.lookup_by_ico', return_value=dict(ARES)):
            j = self.k.get('/address-book/ares/12345679').get_json()
            self.assertEqual((j['contact']['street'], j['contact']['postal_code']), ('Dlouhá 1/2', '11000'))
            self.post('/address-book', {'name': 'cokoli', 'ico': '12345679', 'ares': 'fresh', 'roles': ['supplier'], 'street': 'jiná'})
        c = self.row('Zkušební úřad'); self.assertIsNotNone(c, 'název z ARES')
        self.assertEqual((c['dic'], c['street'], c['city'], c['verification_source']), ('CZ12345679', 'Dlouhá 1/2', 'Praha', 'ares')); self.assertTrue(c['verified_at'])
        with patch('osvc_app.address_routes.lookup_by_ico', side_effect=AssertionError('keep nevolá ARES')):
            self.post(f"/address-book/{c['id']}", {'name': 'Přepsáno', 'ico': '12345679', 'ares': 'keep', 'roles': ['supplier', 'customer'], 'street': 'Přepsáno'})
        c2 = self.row('Zkušební úřad')
        self.assertEqual((c2['street'], c2['role'], c2['verified_at']), ('Dlouhá 1/2', 'both', c['verified_at']), 'ověřené údaje zůstaly, role se změnila')
        self.post(f"/address-book/{c['id']}", {'name': 'Zkušební úřad ručně', 'roles': ['supplier']})
        c3 = db.query('SELECT * FROM counterparties WHERE id=%s', (c['id'],), one=True)
        self.assertEqual((c3['name'], c3['ico'], c3['verified_at']), ('Zkušební úřad ručně', None, None), 'bez IČO ruční údaje bez ověření')


if __name__ == '__main__':
    unittest.main()
