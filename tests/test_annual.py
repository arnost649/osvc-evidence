import copy,unittest
from unittest.mock import patch
from decimal import Decimal as D
from osvc_app import annual,profile

class AnnualTests(unittest.TestCase):
 def setUp(self):
  self.identity=dict(ico='00000019',name='TEST',number='1',city='Praha',zip='10000',country='Česká republika')
  self.p=dict(months=[dict(month=m,activity='yes',employment='insured',social='secondary',reason='employment',minimum='auto',health_employment='yes') for m in range(1,13)],vehicles={},social_paid='0',health_paid='0',social_case='standard',social_voluntary='no',insurer='TEST',insurer_code='111',health_from='2026-01-01',health_to='2026-12-31',health_case='standard',expense_method='actual',expense_adjustment='0',base_adjustment='0',tax_case='standard',tax_review='yes')
  self.ev=dict(income=D(200000),ordinary=D(50000),vehicles={},issues=[],counts={})
 def build(self,year=2026):
  with patch('osvc_app.profile.vehicles',return_value=[]):return annual.build(year,self.identity,self.p,self.ev)
 def field(self,r,section,key):return next(f for s in r['sections'] if s['key']==section for f in s['fields'] if f['field_key']==key)
 def test_standard_secondary(self):
  r=self.build();self.assertEqual(self.field(r,'social','premium')['value'],D(24090));self.assertEqual(self.field(r,'health','premium')['value'],D(10125));self.assertEqual(self.field(r,'social','balance')['status'],'known')
 def test_threshold_reduction_exact(self):
  for m in self.p['months'][:8]:m['activity']='no'
  self.ev['ordinary']=D(0);self.ev['income']=D(39168)
  self.assertEqual(self.field(self.build(),'social','premium')['value'],D(0))
  self.ev['income']=D(39169);self.assertGreater(self.field(self.build(),'social','premium')['value'],0)
 def test_health_independent(self):
  first=self.build()
  for m in self.p['months']:m['minimum']='yes'
  r=self.build();self.assertEqual(self.field(r,'health','premium')['value'],D(39664));self.assertEqual(self.field(first,'social','premium')['value'],self.field(r,'social','premium')['value'])
 def test_main_2026_updated_minimum(self):
  for m in self.p['months']:m['social']='main'
  r=self.build();self.assertEqual(self.field(r,'social','assessment')['value'],D(17139)*12)
 def test_reduced_main_requires_start_in_three_year_window(self):
  for m in self.p['months']:m['social']='main'
  self.p['social_case']='new20';self.assertIsNone(self.field(self.build(),'social','assessment')['value'])
  self.p['start']='2025-09-01';self.assertEqual(self.field(self.build(),'social','assessment')['value'],D(12242)*12)
  self.p['start']='2022-01-01';self.assertEqual(self.field(self.build(),'social','assessment')['status'],'missing')
 def test_missing_is_not_zero(self):
  self.p['social_paid']='';r=self.build();self.assertIsNone(self.field(r,'social','paid')['value']);self.assertIn('Zaplacené zálohy ČSSZ',r['missing']['social'])
 def test_missing_paid_does_not_block_premium(self):
  self.p['social_paid']='';self.p['health_paid']='';r=self.build()
  self.assertEqual(self.field(r,'social','premium')['status'],'known');self.assertEqual(self.field(r,'health','premium')['status'],'known')
  self.assertEqual(self.field(r,'social','balance')['status'],'missing')
 def test_unknown_expenses_need_item_classification(self):
  self.ev.update(unknown_expenses=D(10000),unknown_ids=[6]);r=self.build()
  self.assertEqual(self.field(r,'tax','base')['status'],'missing')
  self.p['unknown_expenses']='include';self.assertIsNone(self.field(self.build(),'tax','expenses')['value'])
  self.p['unknown_expenses']='exclude';self.assertIsNone(self.field(self.build(),'tax','expenses')['value'])
 def test_future_rules_not_inherited(self):
  r=self.build(2027);self.assertIsNone(r['rules']);self.assertIsNone(self.field(r,'social','premium')['value']);self.assertTrue(r['reviews'])
 def test_mixed_activity_not_false_certainty(self):
  self.p['months'][0]['social']='main';r=self.build();self.assertEqual(self.field(r,'social','premium')['status'],'review');self.assertIsNone(self.field(r,'social','premium')['value'])
 def test_percentage_does_not_add_vehicle(self):
  self.p.update(expense_method='percentage',expense_rate='trade');r=self.build();self.assertEqual(self.field(r,'tax','expenses')['value'],D(120000))
 def test_vehicle_sources_not_double_counted(self):
  self.p['vehicles']={'1':{'vehicle_method':'actual','actual_basis':'travel'}};self.ev['vehicles']={'1':{'travel':D(8000),'fuel':D(4000),'missing':False}}
  with patch('osvc_app.profile.vehicles',return_value=[{'id':1,'name':'TEST'}]):r=annual.build(2026,self.identity,self.p,self.ev)
  self.assertEqual(self.field(r,'tax','expenses')['value'],D(58000))
 def test_flat_transport_and_no_row_numbers(self):
  self.p['vehicles']={'1':{'vehicle_method':'flat','from':1,'to':12,'private':'yes','eligible':'yes'}};self.ev['vehicles']={'1':{'travel':D(8000),'fuel':D(4000),'missing':False}}
  with patch('osvc_app.profile.vehicles',return_value=[{'id':1,'name':'TEST'}]):r=annual.build(2026,self.identity,self.p,self.ev)
  self.assertEqual(self.field(r,'tax','expenses')['value'],D(98000));self.assertTrue(all(f['row_number'] is None and 'Zdroj:' in f['tooltip'] and 'Kam patří:' in f['tooltip'] for s in r['sections'] for f in s['fields']))
if __name__=='__main__':unittest.main(verbosity=2)
