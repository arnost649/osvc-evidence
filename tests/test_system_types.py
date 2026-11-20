"""Refactor regression tests, exclusively on a disposable DB with SQL rollback."""
import unittest
from decimal import Decimal as D
from unittest.mock import patch
from app import app
from osvc_app import db,annual,expense_tax,system_types
from osvc_app.annual_routes import context
from osvc_app.routes import derived_trip_expenses
from osvc_app.trips_fuel_routes import sync_fuel_payment  # 3d6
from test_invoice_sync import Connection
class SystemTypeTests(unittest.TestCase):
 def setUp(self):
  assert app.config['DB_NAME']=='osvc_expense_test'
  self.ctx=app.test_request_context();self.ctx.push();self.real=db.connection()
  self.mock=patch('osvc_app.db.connection',return_value=Connection(self.real));self.mock.start()
  self.routes_mock=patch('osvc_app.routes.connection',return_value=Connection(self.real));self.routes_mock.start()
  self.settings_mock=patch('osvc_app.settings_routes.connection',return_value=Connection(self.real));self.settings_mock.start();self.addCleanup(self.settings_mock.stop)
  self.config=patch.dict(app.config,{'WTF_CSRF_ENABLED':False,'TESTING':True});self.config.start()
  self.client=app.test_client()
  with self.client.session_transaction() as s:s['user']='osvc';s['local_auth']=1
 def tearDown(self):
  self.real.rollback();self.real.close();self.mock.stop();self.routes_mock.stop();self.config.stop();self.ctx.pop()
 def data(self,**kw):return dict(payment_date='2026-09-27',counterparty_name='TEST system types',description='TEST category-free',amount='100',**kw)
 def post(self,direction='expense',**kw):return self.client.post('/payments/'+direction,data=self.data(**kw))
 def latest(self):return db.query("SELECT * FROM payments WHERE description='TEST category-free' ORDER BY id DESC LIMIT 1",one=True)
 def total(self):return context(2026)['profile_report']['sections'][0]['fields'][1]['value']
 def test_manual_income_no_category(self):
  self.assertEqual(self.post('income').status_code,302);p=self.latest();self.assertIsNone(p['category_id']);self.assertEqual(p['system_type'],'income')
 def test_tax_required_and_ratios(self):
  before=self.total()
  for mode,pct in [('',''),('category',''),('custom',''),('custom','NaN'),('custom','101'),('custom','-1')]:
   self.assertEqual(self.post(tax_mode=mode,tax_pct=pct).status_code,200);self.assertIsNone(self.latest())
  for mode,pct,delta in [('100','50',100),('0','50',0),('custom','33,30',D('33.30'))]:
   self.assertEqual(self.post(tax_mode=mode,tax_pct=pct).status_code,302)
   p=self.latest();self.assertEqual(p['system_type'],'expense');self.assertIsNone(p['category_id']);self.assertEqual(p['tax_deductible_pct'],delta)
   before+=delta;self.assertEqual(self.total(),before)
 def test_unresolved_history_no_default(self):
  db.execute('UPDATE payments SET tax_deductible_pct=NULL,tax_mode=NULL WHERE id=21')
  db.execute("UPDATE categories SET tax_deductible_pct=100,tax_default_mode='ratio'")
  row=db.query('SELECT * FROM payments WHERE id=21',one=True);self.assertEqual(expense_tax.classification(row)['state'],'pending')
  self.assertIsNone(self.total());html=self.client.get('/payments/expense/21').text
  self.assertIn('<option value="100" selected>100 %</option>',html);self.assertNotIn('name="category_id"',html)
 def test_legacy_snapshot_retained_edit(self):
  row=db.query("SELECT * FROM payments WHERE direction='expense' AND fuel_purchase_id IS NULL AND tax_deductible_pct IS NOT NULL ORDER BY id LIMIT 1",one=True)
  db.execute("UPDATE payments SET tax_mode='category' WHERE id=%s",(row['id'],));db.execute('UPDATE categories SET tax_deductible_pct=0')
  data=dict(payment_date=str(row['payment_date']),counterparty_name=db.query('SELECT name FROM counterparties WHERE id=%s',(row['counterparty_id'],),True)['name'],counterparty_id=row['counterparty_id'],description=row['description'],amount=str(row['amount']),tax_mode='custom',tax_pct=str(row['tax_deductible_pct']))
  self.assertEqual(self.client.post('/payments/expense/'+str(row['id']),data=data).status_code,302)
  after=db.query('SELECT * FROM payments WHERE id=%s',(row['id'],),True)
  for k in ['category_id','tax_deductible_pct','document_id','payment_date','amount']:self.assertEqual(row[k],after[k])
  self.assertEqual(after['tax_mode'],'category')
 def test_type_label_not_accounting(self):
  before=context(2026)['profile_report'];self.assertEqual(self.client.post('/settings/system-types/trip',data={'display_label':'Cestovní náhrady'}).status_code,302)
  after=context(2026)['profile_report'];self.assertEqual(before,after)
  self.assertTrue(all(r['system_type']=='trip' for r in derived_trip_expenses(2026)))
  self.assertIn('Cestovní náhrady',self.client.get('/payments/expense?year=2026').text)
  self.assertEqual(self.client.post('/settings/system-types/random',data={'display_label':'X'}).status_code,404)
  self.assertEqual(self.client.post('/settings/categories',data={'name':'X','type':'expense'}).status_code,410)
 def test_fuel_once_and_link(self):
  before=self.total();f=db.query('SELECT * FROM fuel_purchases WHERE deleted_at IS NULL LIMIT 1',one=True)
  payment=db.query('SELECT * FROM payments WHERE fuel_purchase_id=%s',(f['id'],),True)
  ident=sync_fuel_payment(f);self.assertEqual(ident,payment['id']);self.assertEqual(self.total(),before)
  self.assertEqual(db.query('SELECT system_type FROM payments WHERE id=%s',(ident,),True)['system_type'],'fuel')
  db.execute('UPDATE payments SET amount=amount+100 WHERE id=%s',(ident,));self.assertEqual(self.total(),before)
 def test_render_all_surfaces(self):
  for path in ['/','/payments/income','/payments/expense','/settings','/settings/income-sources/new','/annual?year=2026']:
   r=self.client.get(path);self.assertEqual(r.status_code,200,path)
  for path in ['/payments/income','/payments/expense','/settings/income-sources/new']:
   self.assertNotIn('name="category_id"',self.client.get(path).text)
 def test_connector_owned(self):
  row=db.query("SELECT id FROM payments WHERE system_type='income_connector' LIMIT 1",one=True)
  self.assertEqual(self.client.post('/payments/income/'+str(row['id']),data=self.data()).status_code,409)

 def test_fuel_does_not_claim_similar_manual_expense(self):
  from osvc_app.trips_fuel_routes import linked_fuel_payment
  with patch('osvc_app.trips_fuel_routes.query',return_value=None) as query:
   self.assertIsNone(linked_fuel_payment({'id':999,'station':'PHM','purchase_date':'2026-09-27','total_amount':100}))
   self.assertEqual(query.call_count,1);self.assertIn('fuel_purchase_id',query.call_args.args[0])
