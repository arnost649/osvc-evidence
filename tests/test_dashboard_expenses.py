"""Read-only 2026 regression; alternative evidence is simulated only in memory."""
import unittest
from copy import deepcopy
from decimal import Decimal as D
from unittest.mock import patch
from flask import template_rendered
from app import app
from osvc_app import annual,expense_tax
from osvc_app.annual_routes import context
from osvc_app.db import query
class DashboardExpenses(unittest.TestCase):
 def setUp(self):
  self.ctx=app.test_request_context();self.ctx.push()
  self.client=app.test_client()
  with self.client.session_transaction() as s:s['user']='osvc';s['local_auth']=1
 def tearDown(self):self.ctx.pop()
 def dashboard(self):
  values={}
  def capture(sender,template,context,**kw):values.update(context)
  with template_rendered.connected_to(capture,app):
   r=self.client.get('/');self.assertEqual(r.status_code,200)
  return values,r.text
 def tax(self,r):return {f['field_key']:f['value'] for s in r['sections'] if s['key']=='tax' for f in s['fields']}
 def test_real_2026_same_source(self):
  report=context(2026)['profile_report'];v=self.tax(report)
  with patch('osvc_app.annual.year_report',return_value=(None,None,None,None,report)):
   values,html=self.dashboard()
  for key,field,expected in [('income','income','3040'),('expense','expenses','15664.83'),('balance','result','-12624.83')]:
   self.assertEqual(values[key],v[field]);self.assertEqual(values[key],D(expected))
  self.assertIn('dashboard-expenses',html)
 def test_purchase_shares(self):
  rows=expense_tax.rows(2026)
  card=next(r for r in rows if r['amount']==D('10000'))
  self.assertEqual(expense_tax.classification(card)['ratio'],D(50))
  self.assertEqual(annual.money(card['amount']*card['tax_deductible_pct']/100),D(5000))
  other=[r for r in rows if r['id']!=card['id']]
  self.assertTrue(all(expense_tax.classification(r)['ratio']==100 for r in other))
  self.assertEqual(sum(r['amount'] for r in other),D(9606))
 def test_fuel_excluded_under_travel_mode(self):
  identity,p,_,_,report=annual.year_report(2026);ev=annual.evidence(2026)
  self.assertEqual(report['expense_summary']['travel'],D('1058.83'))
  self.assertEqual(report['expense_summary']['fuel'],D('2459.50'))
  changed=deepcopy(ev)
  for v in changed['vehicles'].values():v['fuel']+=D(10000)
  self.assertEqual(self.tax(annual.build(2026,identity,p,changed))['expenses'],self.tax(report)['expenses'])
 def test_unresolved_does_not_become_zero_or_raw_total(self):
  identity,p,_,_,_=annual.year_report(2026);ev=annual.evidence(2026)
  ev['unknown_ids']=[-1]
  report=annual.build(2026,identity,p,ev)
  with patch('osvc_app.annual.year_report',return_value=(identity,p,None,None,report)):
   values,html=self.dashboard()
  self.assertIsNone(values['expense']);self.assertIsNone(values['balance']);self.assertIn('nelze dokončit',html)
