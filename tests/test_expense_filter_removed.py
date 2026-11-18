"""Read-only route checks; all payment saving is mocked, never writes accounting data."""
import unittest
from unittest.mock import patch
from app import app
from osvc_app.db import query
from osvc_app.expense_tax import resolve_submission

class ExpenseFilterRemoved(unittest.TestCase):
 def setUp(self):
  self.client=app.test_client()
  with self.client.session_transaction() as s:s['user']='osvc';s['local_auth']=1
 def test_list_and_legacy_links(self):
  response=self.client.get('/payments/expense?year=2026')
  self.assertEqual(response.status_code,200)
  self.assertNotIn('<label>Daňový stav',response.text)
  self.assertNotIn('tax_status',response.text)
  for path in ['/payments/expense?year=2026&tax_status=missing','/payments/expense?year=2026&tax_status=resolved','/payments/expense/tax?year=2026']:
   r=self.client.get(path);self.assertEqual(r.status_code,302)
   self.assertEqual(r.location,'/payments/expense?year=2026')
 def test_create_and_edit_validation_blocks_save(self):
  with app.app_context():
   row=query("SELECT id FROM payments WHERE direction='expense' AND fuel_purchase_id IS NULL AND deleted_at IS NULL LIMIT 1",one=True)
  self.assertIsNotNone(row)
  with patch.dict(app.config,{'WTF_CSRF_ENABLED':False}),patch('osvc_app.routes.save_manual_payment') as save:
   for path in ['/payments/expense',f'/payments/expense/{row["id"]}']:
    for mode,pct in [('', ''),('custom',''),('custom','101'),('custom','-1'),('custom','NaN'),('category','')]:
     r=self.client.post(path,data=dict(payment_date='2026-09-27',description='Validation only',counterparty_name='Test',amount='100',tax_mode=mode,tax_pct=pct))
     self.assertEqual(r.status_code,200);save.assert_not_called()
 def test_custom_only(self):
  for mode,pct,result in [('100','',100),('0','',0),('100','50',100),('custom','50',50)]:
   self.assertEqual(resolve_submission({'tax_mode':mode,'tax_pct':pct}),result)
