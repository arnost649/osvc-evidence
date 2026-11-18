"""Insurance regressions: isolated input objects, no accounting writes."""
import unittest
from copy import deepcopy
from datetime import date
from unittest.mock import patch
class September2026(date):
 @classmethod
 def today(cls):return cls(2026,9,27)
from test_annual import AnnualTests

class Insurance2026(unittest.TestCase):
 build=AnnualTests.build
 field=AnnualTests.field
 def setUp(self):
  AnnualTests.setUp(self)
  clock=patch('osvc_app.annual.date',September2026);clock.start();self.addCleanup(clock.stop)
  # „dnes“ bere annual z osvc_app.cas (české datum)
  czclock=patch('osvc_app.cas.today',return_value=September2026.today());czclock.start();self.addCleanup(czclock.stop)
  self.p.update(profile_version=2,business_status='yes',business_periods=[{'from':'2026-09-07','to':''}],employment_status='yes',employment_periods=[{'from':'2020-11-01','to':'','insured':'yes','health_conditions':'yes'}],social_case='other',health_case='other',tax_case='other')
  self.ev.update(income=self.money('3040'),ordinary=self.money('15664.83'))
 def money(self,v):return __import__('decimal').Decimal(v)
 # Inherit the fixture helpers, not the different baseline scenarios.
 def test_scenario(self):
  before=deepcopy(self.p);r=self.build();self.assertEqual(self.p,before)
  self.assertEqual(r['social_threshold'],39169)
  for section in ('social','health'):
   for key,expected in [('base',self.money('-12624.83')),('months',4),('assessment',0),('premium',0),('paid',0),('balance',0),('advance',0)]:
    f=self.field(r,section,key);self.assertEqual(f['value'],expected,(section,key));self.assertEqual(f['status'],'known',(section,key,f))
   self.assertEqual(next(s for s in r['sections'] if s['key']==section)['status'],'known')
  for section,key,value in [('social','main',0),('social','secondary',4),('health','employment',4),('health','minimum',0)]:self.assertEqual(self.field(r,section,key)['value'],value)
  self.assertEqual(r['period_counts'],{'completed':0,'current':1,'future':3})
 def test_actual_advances_required(self):
  self.p.update(social_paid='',health_paid='');r=self.build()
  for s in ('social','health'):
   self.assertEqual(self.field(r,s,'premium')['value'],0);self.assertEqual(self.field(r,s,'premium')['status'],'known')
   self.assertEqual(self.field(r,s,'paid')['status'],'missing');self.assertEqual(self.field(r,s,'balance')['status'],'missing')
 def test_overpayments(self):
  self.p.update(social_paid='500',health_paid='700');r=self.build()
  for s,v in [('social',-500),('health',-700)]:self.assertEqual(self.field(r,s,'balance')['value'],v)
 def test_health_no_and_unknown(self):
  self.p['health_case']='standard'
  for choice,minimum,state in [('no',4,'known'),('',None,'missing')]:
   self.p['employment_periods'][0]['health_conditions']=choice;r=self.build()
   self.assertEqual(self.field(r,'health','minimum')['value'],minimum);self.assertEqual(self.field(r,'health','premium')['status'],state)
   self.assertEqual(self.field(r,'social','premium')['value'],0)
 def test_partial_month_not_exempt(self):
  self.p['health_case']='standard';self.p['employment_periods'][0]['from']='2026-09-07'
  self.assertEqual(self.field(self.build(),'health','minimum')['value'],1)
 def test_voluntary_not_zero(self):
  self.p.update(social_case='standard',social_voluntary='yes');self.assertGreater(self.field(self.build(),'social','premium')['value'],0)
 def test_threshold_boundary(self):
  self.p['social_case']='standard'
  for profit in (39168,39169):
   self.ev['income']=self.ev['ordinary']+profit
   self.assertEqual(self.field(self.build(),'social','premium')['value']==0,profit<39169)
 def test_incomplete_base_propagates(self):
  self.ev.update(unknown_ids=[1],unknown_expenses=self.money(100))
  for s in ('social','health'):
   for k in ('base','assessment','premium'):self.assertNotEqual(self.field(self.build(),s,k)['status'],'known')
if __name__=='__main__':unittest.main()
