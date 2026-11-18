"""Local SQL rollback fixtures; external API/SFTP replaced by deterministic receipts."""
import json
from pathlib import Path
from unittest.mock import patch
from test_invoice_sync import InvoiceTests
from osvc_app import db, income_sources as src, woocommerce as wc
from app import app

class SourceTests(InvoiceTests):
 def setUp(self):
  super().setUp()
  self.source=src.default_source()
  self.ident=self.source['id']
  self.extra=patch.dict(app.config,{'DATA_STATE_DIR':self.temp.name});self.extra.start()
  db.execute("UPDATE income_sources SET active=1,import_documents=1,automatic_sync=0,sync_from='2026-01-01' WHERE id=%s",(self.ident,))
 def tearDown(self):
  self.extra.stop();super().tearDown()
 def test_disabled_retry_identity_and_documents(self):
  o=self.order(new=True);self.put(o)
  with patch.object(wc,'fetch_orders',return_value=[o]) as fetch:
   db.execute('UPDATE income_sources SET active=0 WHERE id=%s',(self.ident,))
   with self.assertRaises(src.SourceError):src.synchronize(self.ident)
   fetch.assert_not_called()
   db.execute('UPDATE income_sources SET active=1 WHERE id=%s',(self.ident,))
   self.assertEqual(src.synchronize(self.ident)['pdf_added'],1)
   doc=self.doc(o);before=db.query('SELECT * FROM attachments WHERE document_id=%s',(doc['id'],))
   self.assertEqual(src.synchronize(self.ident)['pdf_added'],0)
   self.assertEqual(len(db.query('SELECT * FROM income_source_records WHERE source_id=%s AND external_id=%s',(self.ident,str(o['id'])))),1)
   db.execute('UPDATE income_sources SET import_documents=0 WHERE id=%s',(self.ident,))
   src.synchronize(self.ident)
   self.assertEqual(before,db.query('SELECT * FROM attachments WHERE document_id=%s',(doc['id'],)))
   Path(self.temp.name,before[0]['stored_filename']).unlink()
   self.assertEqual(src.synchronize(self.ident)['pdf_added'],0)
   db.execute('UPDATE income_sources SET import_documents=1 WHERE id=%s',(self.ident,))
   self.assertEqual(src.synchronize(self.ident)['pdf_added'],1)
   self.assertEqual(before,db.query('SELECT * FROM attachments WHERE document_id=%s',(doc['id'],)))
 def test_normalized_contract_and_settings(self):
  with src.provider(src.get_source(self.ident)).runtime():
   record=wc.normalize_income(self.order())
   self.assertEqual(record.source_id,self.ident);self.assertEqual(record.external_id,'990001')
   self.assertEqual(record.document.mime_type,'application/pdf')
  with app.test_client() as c,patch.dict(app.config,{'WTF_CSRF_ENABLED':False}):
   with c.session_transaction() as s:s['user']='osvc';s['local_auth']=1
   r=c.post(f'/settings/income-sources/{self.ident}',data={'name':'Test zdroj','url':'https://example.test','sync_from':'2026-01-01','active':'on'})
   self.assertEqual(r.status_code,302)
   stored=src.get_source(self.ident)
   self.assertFalse(stored['import_documents']);self.assertFalse(stored['automatic_sync'])
   self.assertEqual(stored['name'],'Test zdroj')
   c.post(f'/settings/income-sources/{self.ident}',data={'name':'bad','url':'https://user:password@example.test'})
   self.assertEqual(src.get_source(self.ident)['name'],'Test zdroj')
 def test_automatic_disabled_and_failure_redacted(self):
  with patch.object(wc,'fetch_orders',side_effect=RuntimeError('secret')) as fetch:
   with self.assertRaises(src.SourceError):src.synchronize(self.ident,automatic=True)
   fetch.assert_not_called()
   with self.assertRaises(src.SourceError) as error:src.synchronize(self.ident)
   self.assertNotIn('secret',str(error.exception))
   self.assertNotIn('secret',src.get_source(self.ident)['last_error'])
