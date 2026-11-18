"""Address pagination fixtures never commit; --serve provides a browser target."""
import sys, unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch
from flask import template_rendered
from app import app
from osvc_app import db

class Connection:
 def __init__(self,real):self.real=real
 def cursor(self):return self.real.cursor()
 def commit(self):pass
 def rollback(self):pass
 def close(self):pass

@contextmanager
def fixture():
 with app.app_context():real=db.connection()
 with ExitStack() as stack:
  for target in ['osvc_app.db.connection','osvc_app.routes.connection','osvc_app.address_routes.connection']:stack.enter_context(patch(target,return_value=Connection(real)))
  try:
   with real.cursor() as cur:
    cur.executemany("INSERT INTO counterparties (name,role,source) VALUES (%s,%s,'manual')",[(f'TESTPAG{count} {role} {i:03}',role) for count in [99,100,101,200,201] for role in ['supplier','customer','fuel_station'] for i in range(count)])
   yield
  finally:real.rollback();real.close()

class AddressPaginationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.fx=fixture();cls.fx.__enter__()
 @classmethod
 def tearDownClass(cls):cls.fx.__exit__(None,None,None)
 def setUp(self):
  self.client=app.test_client()
  with self.client.session_transaction() as s:s['user']='osvc';s['local_auth']=1
 def get(self,url):
  contexts=[]
  def capture(sender,template,context,**kw):contexts.append(context)
  with template_rendered.connected_to(capture,app):response=self.client.get(url)
  self.assertEqual(response.status_code,200)
  return contexts[-1]
 def test_boundaries_all_roles_and_unique_rows(self):
  for count in [99,100,101,200,201]:
   for key,role in [('suppliers','supplier'),('customers','customer'),('stations','fuel_station')]:
    seen=[]
    for page in range(1,(count+99)//100+1):
     c=self.get(f'/address-book?q=TESTPAG{count}&{key}_page={page}')
     self.assertEqual(c['pagers'][key].total,count)
     self.assertEqual(c['pagers'][key].pages,(count+99)//100)
     self.assertEqual(len(c[key]),min(100,count-100*(page-1)))
     self.assertTrue(all(r['role']==role for r in c[key]))
     seen.extend(r['id'] for r in c[key])
    self.assertEqual(len(set(seen)),count)
 def test_independent_pages_and_legacy_url(self):
  for prefix in ['/address-book','/settings/address-book']:
   c=self.get(prefix+'?q=TESTPAG201&suppliers_page=2&customers_page=3&stations_page=1')
   self.assertEqual([c['pagers'][k].page for k in ['suppliers','customers','stations']],[2,3,1])
   self.assertEqual([len(c[k]) for k in ['suppliers','customers','stations']],[100,1,100])

if __name__=='__main__':
 if '--serve' in sys.argv:
  with fixture():app.run(host='0.0.0.0',port=8091,threaded=False,use_reloader=False)
 else:unittest.main(verbosity=2)
