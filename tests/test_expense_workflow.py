"""Shared new/edit form contract; HTTP/SQL workflows live in test_system_types."""
import unittest
from werkzeug.datastructures import MultiDict
from unittest.mock import patch
from app import app
from osvc_app.forms import ManualExpenseForm,PaymentForm
class ExpenseFormContract(unittest.TestCase):
 def test_category_free_income(self):
  with app.test_request_context(),patch.dict(app.config,{'WTF_CSRF_ENABLED':False}):
   f=PaymentForm(MultiDict(dict(payment_date='2026-09-27',counterparty_name='Test',description='Test',amount='100')))
   self.assertTrue(f.validate());self.assertFalse(hasattr(f,'category_id'))
 def test_explicit_ratio(self):
  with app.test_request_context(),patch.dict(app.config,{'WTF_CSRF_ENABLED':False}):
   for mode,pct,valid in [('100','',True),('0','',True),('custom','33,30',True),('custom','',False),('custom','101',False),('','',False),('category','',False)]:
    f=ManualExpenseForm(MultiDict(dict(payment_date='2026-09-27',counterparty_name='Test',description='Test',amount='100',tax_mode=mode,tax_pct=pct)))
    self.assertEqual(f.validate(),valid,(mode,pct));self.assertFalse(hasattr(f,'category_id'))
