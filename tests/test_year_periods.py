import unittest,copy,json
from datetime import date
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
from osvc_app.year_periods import resolve_year_period,year_period_text,vehicle_year_period
from osvc_app.profile_periods import project,parse_periods,source_missing
from osvc_app import profile
class YearPeriods(unittest.TestCase):
 def test_boundaries(self):
  for year in (2026,2027):
   for start,end,months in [(None,None,list(range(1,13))), (f'{year}-09-01',None,list(range(9,13))), (None,f'{year}-03-31',[1,2,3]), (f'{year}-03-01',f'{year}-10-31',list(range(3,11))),('2020-11-01',None,list(range(1,13)))]:
    with self.subTest(year=year,start=start,end=end):
     r=resolve_year_period(year,start,end);self.assertEqual(r['months'],months);self.assertEqual(r['full_year'],len(months)==12)
 def test_outside_invalid_and_leap(self):
  self.assertEqual(resolve_year_period(2026,'2027-01-01',None)['months'],[])
  self.assertEqual(resolve_year_period(2026,None,'2025-12-31')['months'],[])
  with self.assertRaises(ValueError):resolve_year_period(2026,'2026-10-01','2026-02-01')
  self.assertEqual(resolve_year_period(2024,'2024-02-29','2024-02-29')['months'],[2])
 def test_parse_no_fake_dates(self):
  for row in ({'from':None,'to':None},{'from':'','to':'2026-03-31'},{'from':'2020-11-01','to':''}):
   result=parse_periods(MultiDict({'employment_periods':json.dumps([row])}),'employment',2026)[0]
   self.assertEqual(result['from'],row['from'] or '');self.assertEqual(result['to'],row['to'] or '')
 def test_derivation_and_history(self):
  p={'profile_version':2,'business_status':'yes','business_periods':[{'from':'2026-09-07','to':''}],'employment_status':'yes','employment_periods':[{'from':'','to':'','insured':'yes','health_conditions':'yes'}]}
  for start in ('','2020-11-01'):
   p['employment_periods'][0]['from']=start;before=copy.deepcopy(p);r=project(2026,p)
   self.assertEqual(p,before);self.assertEqual(r['employment_periods'],p['employment_periods'])
   self.assertEqual([x['social'] for x in r['months'][8:]],['secondary']*4)
   self.assertEqual([x['minimum'] for x in r['months'][8:]],['auto']*4)
   self.assertFalse(any(source_missing(r).values()))
   self.assertEqual(year_period_text(2026,p['employment_periods']),'Celý rok')
 def test_vehicle(self):self.assertEqual(vehicle_year_period(2026,None,None)['months'],list(range(1,13)))
 def test_health_does_not_persist_defaults(self):
  with patch('osvc_app.profile.vehicles',return_value=[]):
   _,p=profile.parse(MultiDict({'profile_version':'2','insurer_code':'111','employment_status':'yes','employment_periods':'[{"from":"","to":"","insured":"yes","health_conditions":"yes"}]'}),2026,{})
  self.assertEqual(p['health_from'],'');self.assertEqual(p['health_to'],'');self.assertEqual(p['employment_from'],'')
if __name__=='__main__':unittest.main()
