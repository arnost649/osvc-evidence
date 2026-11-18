import unittest,copy,json
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
from osvc_app import profile,annual
from osvc_app.profile_periods import project,prepare,source_missing

class PeriodTests(unittest.TestCase):
 def setUp(self):
  self.p={'profile_version':2,'business_status':'yes','business_periods':[{'from':'2026-09-07','to':''}],'employment_status':'yes','employment_periods':[{'from':'2026-01-01','to':'','insured':'yes','health_conditions':'yes'}],'months':[],'vehicles':{}}
 def test_four_months(self):
  p=project(2026,self.p);self.assertEqual([m['activity'] for m in p['months']],['no']*8+['yes']*4)
  self.assertEqual([m['social'] for m in p['months'][8:]],['secondary']*4)
  self.assertEqual([m['minimum'] for m in p['months'][8:]],['auto']*4)
 def test_change_employment_reprojects(self):
  self.p['employment_periods'][0]['from']='2026-10-01';p=project(2026,self.p)
  self.assertEqual(p['months'][8]['social'],'main');self.assertEqual(p['months'][8]['minimum'],'yes');self.assertEqual(p['months'][9]['social'],'secondary')
 def test_partial_month_health_not_social(self):
  self.p['employment_periods'][0]['from']='2026-09-15';p=project(2026,self.p)
  self.assertEqual(p['months'][8]['social'],'secondary');self.assertEqual(p['months'][8]['minimum'],'yes')
 def test_no_actual_overlap(self):
  self.p['employment_periods'][0].update({'from':'2026-09-01','to':'2026-09-06'});p=project(2026,self.p)
  self.assertEqual(p['months'][8]['social'],'main')
 def test_multi_period_and_union(self):
  self.p['business_periods']=[{'from':'2026-01-01','to':'2026-03-15'},{'from':'2026-09-01','to':''}]
  self.p['employment_periods']=[{'from':'2026-09-01','to':'2026-09-15','insured':'yes','health_conditions':'yes'},{'from':'2026-09-16','to':'','insured':'yes','health_conditions':'yes'}]
  p=project(2026,self.p);self.assertEqual(sum(m['activity']=='yes' for m in p['months']),7);self.assertEqual(p['months'][8]['minimum'],'auto')
 def test_gap_not_full_month(self):
  self.p['employment_periods']=[{'from':'2026-09-01','to':'2026-09-14','insured':'yes','health_conditions':'yes'},{'from':'2026-09-16','to':'','insured':'yes','health_conditions':'yes'}]
  self.assertEqual(project(2026,self.p)['months'][8]['minimum'],'yes')
 def test_unknown_is_source_problem(self):
  self.p['employment_periods'][0]['insured']='';p=project(2026,self.p)
  self.assertEqual(len(source_missing(p)['social']),1);self.assertEqual(p['months'][8]['social'],'')
 def test_unknown_health_separate(self):
  self.p['employment_periods'][0]['health_conditions']='';p=project(2026,self.p)
  self.assertEqual(p['months'][8]['social'],'secondary');self.assertEqual(len(source_missing(p)['health']),1)
 def test_no_activity_and_no_job(self):
  self.p.update(business_status='no',employment_status='no');p=project(2026,self.p)
  self.assertTrue(all(m['activity']=='no' and m['employment']=='no' for m in p['months']))
 def test_legacy_preserved(self):
  old={'months':[{'month':m,'activity':'yes','social':'main','employment':'no','minimum':'yes'} for m in range(1,13)],'vehicles':{},'start':'2026-09-07'}
  v=prepare(2026,old);self.assertTrue(v['overrides_enabled']);self.assertTrue(all(m['activity']=='yes' for m in v['months']));self.assertNotIn('profile_version',old)
  v['overrides_enabled']=False;self.assertEqual(sum(m['activity']=='yes' for m in project(2026,v)['months']),4)
 def test_parser_server_derivation_and_insurer(self):
  f=MultiDict({'profile_version':'2','business_status':'yes','business_periods':json.dumps(self.p['business_periods']),'employment_status':'yes','employment_periods':json.dumps(self.p['employment_periods']),'insurer_code':'111','tax_review':'yes','m9_social':'main'})
  with patch('osvc_app.profile.vehicles',return_value=[]):i,p=profile.parse(f,2026,{})
  self.assertEqual(p['months'][8]['social'],'secondary');self.assertEqual(p['health_from'],'');self.assertIn('Všeobecná',p['insurer']);self.assertEqual(p['base_adjustment'],'0')
  f['overrides_enabled']='yes'
  with patch('osvc_app.profile.vehicles',return_value=[]):i,p=profile.parse(f,2026,{})
  self.assertEqual(p['months'][8]['social'],'main')
 def test_invalid_period_rejected(self):
  f=MultiDict({'profile_version':'2','business_periods':'[{"from":"2026-12-01","to":"2026-01-01"}]'})
  with patch('osvc_app.profile.vehicles',return_value=[]),self.assertRaises(ValueError):profile.parse(f,2026,{})
 def test_2027_independent_projection(self):
  self.p['business_periods'][0]['to']='2026-12-31';self.assertTrue(all(m['activity']=='no' for m in project(2027,self.p)['months']))

if __name__=='__main__':unittest.main(verbosity=2)
