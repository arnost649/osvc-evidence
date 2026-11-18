import unittest
from copy import deepcopy
from app import app
from osvc_app import annual,profile,profile_presentation
from osvc_app.annual_routes import context
app.config['DB_NAME']='osvc_expense_test'
class CompletenessTests(unittest.TestCase):
 def setUp(self):
  self.ctx=app.test_request_context();self.ctx.push();self.c=context(2026);self.ev=annual.evidence(2026)
 def tearDown(self):self.ctx.pop()
 def view(self,p,ev=None,year=2026):
  r=annual.build(year,self.c['profile_identity'],p,ev or self.ev)
  return r,profile_presentation.build(self.c['profile_identity'],p,r,profile.vehicles())
 def assert_state(self,r,v,state):
  self.assertEqual(v['cards']['tax']['state'],state)
  self.assertEqual(next(x for x in v['quick'] if x['target']=='tax')['state'],state)
  self.assertEqual(v['profile_state'],state)
  self.assertEqual(r['profile_status']['state'],state)
 def test_current_and_legacy_warning(self):
  r,v=self.view(self.c['year_profile']);self.assert_state(r,v,'known')
  self.assertEqual(self.c['year_profile']['tax_review'],'yes');self.assertFalse(self.ev['unknown_ids'])
  self.assertTrue(r['reviews'])
  self.assertEqual([f['value'] for f in r['sections'][0]['fields']],[f['value'] for f in self.c['profile_report']['sections'][0]['fields']])
 def test_confirmation_missing_then_restored(self):
  p=deepcopy(self.c['year_profile'])
  for value in ['', 'no','yes']:
   p['tax_review']=value;r,v=self.view(p);self.assert_state(r,v,'known' if value=='yes' else 'missing')
   if value!='yes':self.assertIn('Potvrďte kontrolu',v['cards']['tax']['reason'])
 def test_unresolved_expense(self):
  ev=deepcopy(self.ev);ev['unknown_ids']=[-1];ev['unknown_expenses']=annual.D('100')
  r,v=self.view(self.c['year_profile'],ev);self.assert_state(r,v,'missing');self.assertIn('1 výdajů',v['cards']['tax']['reason'])
 def test_year_confirmation_not_inherited(self):
  c=context(2027);self.assertNotEqual(c['year_profile'].get('tax_review'),'yes');self.assertEqual(c['profile_view']['cards']['tax']['state'],'missing')
if __name__=='__main__':unittest.main()
