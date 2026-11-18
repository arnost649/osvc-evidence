import unittest
from unittest.mock import patch
from osvc_app.profile_registry import lookup,permission_periods
from osvc_app.ares import AresUnavailable

class RegistryTests(unittest.TestCase):
 def request(self,path,*a,**kw):
  if path.startswith('/ciselniky'):return {'ciselniky':[]}
  if path=='/ekonomicke-subjekty/12345678':return {'ico':'12345678','obchodniJmeno':'Test','sidlo':{'nazevObce':'Obec'},'pravniForma':'101','datumVzniku':'2000-01-01','czNace':['01']}
  if path=='/ekonomicke-subjekty-ros/12345678':return {'icoId':'12345678','zaznamy':[{'datumVzniku':'2001-01-01','pravniFormaRos':{'hodnota':'101'},'statutarniOrgany':[{'osoba':'DO NOT RETAIN'}]}]}
  return {'icoId':'12345678','zaznamy':[{'primarniZaznam':True,'ico':'12345678','dic':'CZ12345678','osobaPodnikatel':{'rodneCislo':'DO NOT RETAIN'},'zivnosti':[{'datumVzniku':'2026-01-01','predmetPodnikani':'Test činnost','oboryCinnosti':[{'oborNazev':'Test obor'}],'preruseniZivnosti':[{'platnostOd':'2026-03-16','platnostDo':'2026-08-31'}]}]}]}
 def test_sources_and_minimization(self):
  with patch('osvc_app.profile_registry._request',side_effect=self.request):r=lookup('12345678')
  self.assertEqual(r['sources']['name'],'ARES');self.assertEqual(r['sources']['dic'],'RŽP');self.assertNotIn('DO NOT RETAIN',str(r));self.assertTrue(any(x['value']=='Test obor' for x in r['metadata']))
  self.assertEqual(r['suggested_periods'],[{'from':'2026-01-01','to':'2026-03-15'},{'from':'2026-09-01','to':''}])
 def test_one_source_failure_preserves_rest(self):
  def request(path,*a,**kw):
   if 'subjekty-ros' in path:raise AresUnavailable('offline')
   return self.request(path,*a,**kw)
  with patch('osvc_app.profile_registry._request',side_effect=request):r=lookup('12345678')
  self.assertEqual(r['data']['name'],'Test');self.assertEqual(r['statuses'][1]['state'],'error');self.assertEqual(r['data']['dic'],'CZ12345678')
 def test_multiple_licenses_union(self):
  r=permission_periods([{'datumVzniku':'2026-01-01','preruseniZivnosti':[{'platnostOd':'2026-03-01','platnostDo':'2026-08-31'}]},{'datumVzniku':'2026-02-01','datumZaniku':'2026-09-01'}])
  self.assertEqual(r,[{'from':'2026-01-01','to':''}])
 def test_unknown_history_no_guess(self):self.assertEqual(permission_periods([{'predmetPodnikani':'No date'}]),[])
if __name__=='__main__':unittest.main(verbosity=2)
