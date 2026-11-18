"""Batch label saves: isolated in-memory connection, no accounting writes."""
import unittest
from unittest.mock import patch
from app import app
from osvc_app import settings_routes as routes,system_types  # kód Nastavení je v settings_routes

class MemoryConnection:
 def __init__(self):
  self.rows={k:v[0] for k,v in system_types.TYPES.items()};self.original=self.rows.copy();self.updates=[];self.committed=False;self.rolled_back=False
 def cursor(self):return self
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def execute(self,sql,args):
  if sql.startswith('SELECT'):self.key=args[0]
  elif sql.startswith('UPDATE system_types SET display_label='):
   name,key=args;self.rows[key]=name;self.updates.append(key)
  else:raise AssertionError(sql)
 def fetchone(self):return {'type_key':self.key,'display_label':self.rows[self.key]}
 def commit(self):self.committed=True
 def rollback(self):self.rows=self.original.copy();self.rolled_back=True
 def close(self):pass

class BatchLabelsTests(unittest.TestCase):
 def setUp(self):self.conn=MemoryConnection();self.data={'label_'+k:v for k,v in self.conn.rows.items()}
 def submit(self):
  with app.test_request_context('/settings/system-types',method='POST',data=self.data),patch.object(routes,'connection',return_value=self.conn),patch.object(routes,'cursor_audit') as audit:
   result=routes.update_system_types.__wrapped__()
   return result,audit.call_count
 def test_batch_only_changed_labels(self):
  self.data.update(label_trip='Cestovní náhrady',label_income='Tržba',type_key='evil')
  result,n=self.submit();self.assertEqual(result.status_code,302);self.assertEqual(n,2);self.assertEqual(self.conn.updates,['income','trip']);self.assertTrue(self.conn.committed);self.assertEqual(set(self.conn.rows),set(system_types.TYPES))
 def test_noop(self):
  _,n=self.submit();self.assertEqual(n,0);self.assertEqual(self.conn.updates,[])
 def test_invalid_batch_never_partially_saved(self):
  for invalid in ['', 'x'*101]:
   self.data.update(label_income='Changed',label_trip=invalid);self.submit();self.assertEqual(self.conn.updates,[]);self.assertFalse(self.conn.committed)
 def test_missing_label(self):
  del self.data['label_fuel'];self.submit();self.assertFalse(self.conn.committed)
 def test_failure_rolls_back_batch(self):
  self.data.update(label_income='Changed',label_trip='Changed')
  with app.test_request_context('/settings/system-types',method='POST',data=self.data),patch.object(routes,'connection',return_value=self.conn),patch.object(routes,'cursor_audit',side_effect=RuntimeError('test')):
   with self.assertRaises(RuntimeError):routes.update_system_types.__wrapped__()
  self.assertTrue(self.conn.rolled_back);self.assertEqual(self.conn.rows,self.conn.original)
if __name__=='__main__':unittest.main()
