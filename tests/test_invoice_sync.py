"""Invoice integration tests: real local SQL (osvc_test), rolled back; fake read-only SFTP.
Cesty archivu jsou v testovací konfiguraci; synchronizace běží se zdrojem (g.income_source)."""
import errno,hashlib,io,stat,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import contextmanager
from urllib.error import HTTPError
from app import app
from osvc_app import db,woocommerce as wc

PDF=b'%PDF-1.4\n'+b' '*1100+b'\n%%EOF\n'
class Connection:
 def __init__(self,real):self.real=real
 def cursor(self):return self.real.cursor()
 def commit(self):pass
 def rollback(self):pass
 def close(self):pass
class Archive:
 def __init__(self):self.files={};self.reads=0
 def lstat(self,path):
  if path not in self.files:raise FileNotFoundError(errno.ENOENT,'absent')
  return SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_size=len(self.files[path]))
 def open(self,path,mode):self.reads+=1;return io.BytesIO(self.files[path])
 @contextmanager
 def session(self):yield self
class InvoiceTests(unittest.TestCase):
 def setUp(self):
  self.ctx=app.app_context();self.ctx.push();self.real=db.connection();self.temp=tempfile.TemporaryDirectory();self.archive=Archive()
  self.patches=[patch('osvc_app.db.connection',return_value=Connection(self.real)),patch('osvc_app.woocommerce._invoice_sftp',self.archive.session),patch.dict(app.config,{'UPLOAD_FOLDER':self.temp.name}),patch('osvc_app.connectors.secrets_for',return_value={})]
  for p in self.patches:p.start()
  # synchronizace běží jen se zdrojem (jako ostrá) – skutečný zdroj z osvc_test, archivní cesty jen pro test; vše se vrací rollbackem.
  sid=db.query('SELECT id FROM income_sources ORDER BY id LIMIT 1',one=True)['id']
  from flask import g;from datetime import date
  g.income_source={'id':sid,'name':'test','sync_from':date(2026,1,1),'import_documents':True,'configuration':{'private_dir':'/archiv','legacy_dir':'/wpo','invoice_mode':'sftp_archive','invoice_meta_key':'_shop_invoice_pdf_path'}}
 def tearDown(self):
  self.real.rollback();self.real.close()
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup();self.ctx.pop()
 def order(self,ident=990001,new=False):
  return {'id':ident,'number':str(ident),'status':'completed','date_paid':'2026-09-20T10:00:00','total':'100.00','billing':{'first_name':'TEST invoice'},'line_items':[{'name':'TEST item','quantity':1,'total':'100.00'}],'meta_data':[{'key':'_shop_invoice_pdf_path','value':f'invoice-{ident}-abcdef.pdf'}] if new else []}
 def put(self,order,legacy=False,data=PDF):
  path=wc._invoice_sources(order)[0 if not legacy else -1];self.archive.files[path]=data;return path
 def doc(self,order):
  from flask import g
  return db.query("SELECT * FROM documents WHERE source_ref=%s",(f"source:{g.income_source['id']}:order:{order['id']}",),one=True)
 def test_new_existing_retry_and_idempotence(self):
  o=self.order(new=True);self.put(o);r=wc.sync_orders([o]);self.assertEqual(r['pdf_added'],1);doc=self.doc(o);a=db.query('SELECT * FROM attachments WHERE document_id=%s',(doc['id'],));self.assertEqual(len(a),1)
  reads=self.archive.reads;wc.sync_orders([o]);self.assertEqual(self.archive.reads,reads);self.assertEqual(len(list(Path(self.temp.name).glob('*.pdf'))),1)
  self.assertEqual(db.query('SELECT COUNT(*) n FROM payments WHERE document_id=%s',(doc['id'],),one=True)['n'],1)
  Path(self.temp.name,a[0]['stored_filename']).unlink();self.assertEqual(wc.sync_orders([o])['pdf_added'],1)
  repaired=db.query('SELECT * FROM attachments WHERE document_id=%s',(doc['id'],));self.assertEqual(len(repaired),1);self.assertEqual(repaired[0]['id'],a[0]['id']);self.assertTrue(wc._document_has_invoice(doc['id']))
 def test_missing_then_legacy_backfill_preserves_payment(self):
  o=self.order();wc.sync_orders([o]);doc=self.doc(o);self.assertFalse(wc._document_has_invoice(doc['id']))
  before=db.query('SELECT * FROM payments WHERE document_id=%s',(doc['id'],));self.put(o,legacy=True)
  statuses=wc.backfill_invoices([o]);self.assertIn({'document_id':doc['id'],'order_id':str(o['id']),'status':'added'},statuses)
  self.assertEqual(before,db.query('SELECT * FROM payments WHERE document_id=%s',(doc['id'],)))
  self.assertTrue(wc._document_has_invoice(doc['id']))
 def test_html_and_truncated_pdf_rejected_then_retry(self):
  o=self.order(new=True)
  for data in [b'<html>login'+b' '*1500,PDF[:-8]]:
   self.put(o,data=data);r=wc.sync_orders([o]);self.assertEqual(r['pdf_errors'],1);self.assertTrue(r['warnings']);self.assertEqual(list(Path(self.temp.name).glob('*.pdf')),[])
  self.put(o);self.assertEqual(wc.sync_orders([o])['pdf_added'],1)
 def test_http_failure_is_reported_without_secret_and_retried(self):
  o=self.order(new=True)
  with patch('osvc_app.woocommerce._download_archived_invoice',side_effect=HTTPError('https://example.test/file?token=SECRET',404,'missing',{},None)),self.assertLogs(app.logger,level='WARNING') as logs:
   r=wc.sync_orders([o])
  self.assertEqual(r['pdf_errors'],1);self.assertIsNotNone(self.doc(o));self.assertIn('404',' '.join(logs.output));self.assertNotIn('SECRET',' '.join(logs.output))
  self.put(o);self.assertEqual(wc.sync_orders([o])['pdf_added'],1)
 def test_access_denied_and_unsafe_metadata(self):
  o=self.order(new=True)
  with patch.object(self.archive,'lstat',side_effect=PermissionError(errno.EACCES,'denied')):
   self.assertEqual(wc.sync_orders([o])['pdf_errors'],1)
  o['meta_data'][0]['value']='../../secret.pdf';self.assertEqual(wc.sync_orders([o])['pdf_errors'],1)
 def test_hash_mismatch_repaired_without_overwriting_unrelated_file(self):
  o=self.order();self.put(o);wc.sync_orders([o]);doc=self.doc(o);a=db.query('SELECT * FROM attachments WHERE document_id=%s',(doc['id'],),one=True)
  path=Path(self.temp.name,a['stored_filename']);path.write_bytes(b'not a PDF')
  self.assertEqual(wc.sync_orders([o])['pdf_added'],1);self.assertEqual(path.read_bytes(),b'not a PDF');self.assertTrue(wc._document_has_invoice(doc['id']))

if __name__=='__main__':unittest.main(verbosity=2)
