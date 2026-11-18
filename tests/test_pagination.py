"""Real SQL fixtures stay in one rolled-back transaction; --serve is for browsers."""
import sys, unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch
from flask import template_rendered
from app import app
from osvc_app import db, routes
from osvc_app.pagination import Pagination

COUNTS={2041:99,2042:100,2043:101,2044:200,2045:201}
PATHS=['/payments/income','/payments/expense','/trips','/fuel']
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
    cur.execute('SELECT id,fuel_type FROM vehicles WHERE normalized_consumption_l_100km IS NOT NULL AND deleted_at IS NULL LIMIT 1');vehicle=cur.fetchone()
    cur.execute("INSERT INTO vehicles (name,fuel_type,active) VALUES ('TEST bez spotřeby',%s,1)",(vehicle['fuel_type'],));missing=cur.lastrowid
    cur.execute("INSERT INTO travel_rates (valid_from,valid_to,vehicle_type,fuel_type,base_rate_per_km,average_fuel_price_per_liter) VALUES ('2041-01-01','2045-12-31','passenger_car',%s,5,40)",(vehicle['fuel_type'],))
    for year,n in COUNTS.items():
     day=f'{year}-01-15'
     cur.executemany("INSERT INTO payments (payment_date,direction,amount,description) VALUES (%s,'income',10,%s)",[(day,f'TEST příjem {i}') for i in range(n)])
     cur.executemany("INSERT INTO payments (payment_date,direction,amount,description) VALUES (%s,'expense',20,%s)",[(day,f'TEST výdaj {i}') for i in range(n-n//2)])
     cur.executemany("INSERT INTO trips (vehicle_id,trip_date,trip_end_date,origin,destination,purpose,distance_km) VALUES (%s,%s,%s,'TEST Start','TEST Cíl',%s,10)",[(vehicle['id'] if i<n//2 else missing,day,day,f'TEST jízda {i}') for i in range(n)])
     cur.executemany("INSERT INTO fuel_purchases (vehicle_id,purchase_date,liters,price_per_liter,total_amount,station_name) VALUES (%s,%s,10,40,400,%s)",[(vehicle['id'],day,f'TEST stanice {i}') for i in range(n)])
    cur.executemany("INSERT INTO business_events (event_date,name) VALUES ('2045-01-15',%s)",[(f'TEST akce {i}',) for i in range(201)])
    cur.executemany("INSERT INTO documents (document_type,issue_date,gross_total,source) VALUES ('receipt','2045-01-15',10,'manual')",[() for _ in range(201)])
   yield
  finally:real.rollback();real.close()

class PaginationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.fixture=fixture();cls.fixture.__enter__()
 @classmethod
 def tearDownClass(cls):cls.fixture.__exit__(None,None,None)
 def setUp(self):
  self.client=app.test_client()
  with self.client.session_transaction() as s:s['user']='osvc';s['local_auth']=1
 def get(self,url):
  contexts=[]
  def capture(sender,template,context,**kw):contexts.append(context)
  with template_rendered.connected_to(capture,app):response=self.client.get(url)
  self.assertEqual(response.status_code,200)
  return response,contexts[-1]
 def test_boundaries_and_all_rows(self):
  for path in PATHS:
   for year,n in COUNTS.items():
    seen=[]
    for page in range(1,(n+99)//100+1):
     response,c=self.get(f'{path}?year={year}&page={page}')
     self.assertEqual(c['pager'].total,n,(path,year));self.assertEqual(c['pager'].pages,(n+99)//100)
     self.assertEqual(len(c['rows']),min(100,n-(page-1)*100))
     self.assertEqual(response.text.count('class="pagination pagination-'),2 if n>100 else 0)
     seen.extend((r.get('source_kind',''),r['id']) for r in c['rows'])
    self.assertEqual(len(set(seen)),n,(path,year,'duplicates or omissions'))
 def test_expenses_keep_existing_calculation(self):
  with app.app_context():expected={r['id']:r['amount'] for r in routes.derived_trip_expenses(2045)}
  actual={}
  for page in [1,2,3]:
   _,c=self.get(f'/payments/expense?year=2045&page={page}')
   actual.update({r['id']:r['amount'] for r in c['rows'] if r['source_kind']=='trip'})
  self.assertEqual(actual,expected)
 def test_invalid_pages_and_other_lists(self):
  for page,want in [('bogus',1),('-4',1),('0',1),('9999',3)]:
   _,c=self.get('/fuel?year=2045&page='+page);self.assertEqual(c['pager'].page,want)
  _,c=self.get('/fuel?year=2040&page=2');self.assertEqual(c['pager'].total,0);self.assertEqual(c['pager'].page,1)
  for path,key in [('/documents','rows'),('/events','events')]:
   _,c=self.get(path+'?page=2');self.assertEqual(len(c[key]),100);self.assertGreater(c['pager'].total,200)
 def test_links_and_ellipsis(self):
  with app.test_request_context('/payments/income?year=2045&tag=a&tag=b&page=6'):
   request_endpoint=app.url_map.bind('').match('/payments/income')
   from flask import request
   request.url_rule=next(r for r in app.url_map.iter_rules() if r.rule=='/payments/<direction>');request.view_args={'direction':'income'}
   pager=Pagination(1201,6)
   self.assertEqual(pager.numbers,[1,None,5,6,7,None,13])
   self.assertIn('year=2045&tag=a&tag=b&page=7',pager.url(7))

if __name__=='__main__':
 if '--serve' in sys.argv:
  with fixture():app.run(host='0.0.0.0',port=8091,threaded=False,use_reloader=False)
 else:unittest.main(verbosity=2)
