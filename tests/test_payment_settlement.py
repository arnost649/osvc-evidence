"""Pure accounting-contract regressions. No network, SQL, or application secrets.
The settlement field and evidence source come from the income source configuration (here F and URL)."""
import copy,unittest
from decimal import Decimal as D
from osvc_app.payment_settlement import settlement,preserve_verified

F='shop_payment_settlement'; URL='https://www.shop.example'

class SettlementTests(unittest.TestCase):
 def order(self):
  return {'id':123,'total':'90.00',F:{
   'schema_version':1,'order_id':123,'invoice_amount_czk':'90.00',
   'payment_received_czk':'87.27','payment_currency':'EUR','fx_settlement_diff_czk':'-2.73',
   'verification_required':False,'evidence_source':'shop.example','evidence_kind':'fio_czk_account_movement','transaction_ids':['123456']}}
 def s(self,order,url=URL,**kw):return settlement(order,url,kw.pop('field',F),**kw)
 def test_actual_cash_does_not_reprice_invoice(self):
  order=self.order();original=copy.deepcopy(order);r=self.s(order)
  self.assertEqual((r['invoice_amount_czk'],r['payment_received_czk'],r['fx_settlement_diff_czk']),(D('90'),D('87.27'),D('-2.73')))
  self.assertEqual(r['payment_currency'],'EUR');self.assertFalse(r['payment_needs_review']);self.assertEqual(order,original)
 def test_czk_is_unchanged(self):
  o=self.order();o[F].update(payment_currency='CZK',payment_received_czk='90.00',fx_settlement_diff_czk='0.00')
  r=self.s(o);self.assertEqual(r['payment_received_czk'],D('90'));self.assertFalse(r['payment_needs_review'])
 def test_missing_czk_is_never_estimated(self):
  o=self.order();o[F].update(payment_received_czk=None,fx_settlement_diff_czk=None,evidence_kind='unavailable',verification_required=True)
  r=self.s(o);self.assertEqual(r['invoice_amount_czk'],D('90'));self.assertIsNone(r['payment_received_czk']);self.assertIsNone(r['fx_settlement_diff_czk']);self.assertTrue(r['payment_needs_review'])
 def test_old_api_of_contract_source_marked_for_review(self):
  r=self.s({'id':123,'total':'90'});self.assertTrue(r['payment_needs_review']);self.assertIsNone(r['payment_received_czk'])
 def test_generic_woocommerce_backwards_compatible(self):
  r=settlement({'id':123,'total':'90'},'https://other.example');self.assertFalse(r['payment_needs_review']);self.assertEqual(r['invoice_amount_czk'],D('90'))
 def test_payload_ignored_without_configured_field(self):
  r=settlement(self.order(),URL);self.assertFalse(r['payment_needs_review']);self.assertIsNone(r['payment_received_czk'])
 def test_configured_evidence_source(self):
  o=self.order();o[F]['evidence_source']='billing.example'
  self.assertIsNone(self.s(o)['payment_received_czk'])
  self.assertEqual(self.s(o,evidence_source='billing.example')['payment_received_czk'],D('87.27'))
  self.assertIsNone(self.s(self.order(),url='')['payment_received_czk'],'bez adresy a bez nastavení se důkaz nepřijme')
 def test_bad_evidence_is_rejected(self):
  changes=[{'schema_version':2},{'order_id':456},{'evidence_source':'other'},{'invoice_amount_czk':'89'},
           {'evidence_kind':'exchange_estimate'},{'payment_received_czk':'NaN'},{'payment_received_czk':'Infinity'},
           {'payment_received_czk':'87.271'},{'fx_settlement_diff_czk':'-2.70'},{'transaction_ids':[]},
           {'transaction_ids':['123','123']},{'transaction_ids':['not-a-bank-id']},{'payment_received_czk':'-1.00'}]
  for change in changes:
   with self.subTest(change=change):
    o=self.order();o[F].update(change);r=self.s(o)
    self.assertIsNone(r['payment_received_czk']);self.assertTrue(r['payment_needs_review'])
 def test_upstream_loss_preserves_previously_proven_cash(self):
  values=self.s({'id':123,'total':'90'})
  r=preserve_verified(values,{'payment_received_czk':D('87.27'),'payment_currency':'EUR'})
  self.assertEqual(r['payment_received_czk'],D('87.27'));self.assertEqual(r['fx_settlement_diff_czk'],D('-2.73'));self.assertTrue(r['payment_needs_review'])
 def test_unknown_original_currency_keeps_proven_cash_but_requires_review(self):
  o=self.order();o[F]['payment_currency']=None;r=self.s(o)
  self.assertEqual(r['payment_received_czk'],D('87.27'));self.assertTrue(r['payment_needs_review'])

if __name__=='__main__':unittest.main(verbosity=2)
