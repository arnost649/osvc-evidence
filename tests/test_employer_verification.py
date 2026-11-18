import unittest
from datetime import datetime,timezone
from osvc_app.employer_verification import merge
class Employer(unittest.TestCase):
 def test_preserves_and_clears(self):
  old={'employer':'Vzorová firma s.r.o.','employer_ico':'00000019','employer_source':'ARES'}
  self.assertEqual(merge(old,{'employer':'Vzorová firma s.r.o.'})['employer_ico'],'00000019')
  self.assertNotIn('employer_ico',merge(old,{'employer':'Other','employer_ico':'forged'}))
 def test_server_candidate_only(self):
  c={'name':'Vzorová firma s.r.o.','ico':'00000019','at':datetime.now(timezone.utc).isoformat(),'token':'secret'}
  self.assertNotIn('employer_ico',merge({}, {'employer':c['name']},c,'wrong'))
  p=merge({}, {'employer':c['name'],'employment_periods':[{'from':'2020-11-01'}]},c,'secret')
  self.assertEqual(p['employer_source'],'ARES');self.assertEqual(p['employment_periods'],[{'from':'2020-11-01'}])
  c['at']='2000-01-01T00:00:00+00:00'
  self.assertNotIn('employer_ico',merge({}, {'employer':c['name']},c,'secret'))
if __name__=='__main__':unittest.main()
