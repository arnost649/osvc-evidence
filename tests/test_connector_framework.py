import json,stat
from pathlib import Path
from unittest.mock import patch
from test_invoice_sync import InvoiceTests,PDF
from app import app
from osvc_app import db,woocommerce as wc,income_sources as src
from osvc_app.connectors import secrets_for

class FrameworkTests(InvoiceTests):
 def setUp(self):
  super().setUp()
  self.config={'api_root':'wp-json/wc/v3','invoice_mode':'sftp_template','sftp_host':'archive.example.test','sftp_port':22,'sftp_user':'readonly','invoice_template':'/invoices/{order_id}.pdf'}
  root=Path(self.temp.name);(root/'password').write_text('fixture-password');(root/'password').chmod(0o600);(root/'known').write_text('fixture-host-key')
  secrets={name:{'consumer_key':name+'-key','consumer_secret':name+'-secret','sftp_password_file':str(root/'password'),'known_hosts':str(root/'known')} for name in ('first','second')}
  (root/'secrets.json').write_text(json.dumps(secrets));(root/'secrets.json').chmod(0o600)
  self.extra=patch.dict(app.config,{'INCOME_SOURCE_SECRETS_FILE':str(root/'secrets.json'),'DATA_STATE_DIR':self.temp.name});self.extra.start()
  self.ids=[db.execute("INSERT INTO income_sources (provider,name,url,active,import_documents,configuration,secret_profile) VALUES ('woocommerce',%s,%s,1,1,%s,%s)",(name,'https://'+name+'.example.test',json.dumps(self.config),name)) for name in ('first','second')]
  self.orders=[self.order(991501,new=False)]
  self.archive.files['/invoices/991501.pdf']=PDF
  self.calls=[]
  def api(endpoint,params=None,method='GET'):
   self.calls.append((wc._base_url(),wc.runtime_config('WC_CONSUMER_KEY'),endpoint,params,method))
   if method=='OPTIONS':return {'endpoints':[{'args':{'modified_after':{}}}]}
   return self.orders if endpoint=='orders' else self.orders[0]
  self.api=patch.object(wc,'api_request',side_effect=api);self.api.start()
  self.archive.stat=lambda path:type('Stat',(),{'st_mode':stat.S_IFDIR})()
 def tearDown(self):
  self.api.stop();self.extra.stop();super().tearDown()
 def test_two_webs_same_order_separate_auth_income_pdf(self):
  for ident in self.ids:
   p=src.provider(src.get_source(ident));self.assertTrue(p.get_status()['configured'])
   self.assertTrue(p.test_connection()['activation_ok'])
   self.assertEqual(src.synchronize(ident)['imported'],1)
   self.assertEqual(src.synchronize(ident)['imported'],0)
  rows=db.query('SELECT r.source_id,r.external_id,a.stored_filename FROM income_source_records r JOIN attachments a ON a.document_id=r.document_id WHERE r.source_id IN (%s,%s)',tuple(self.ids))
  self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['stored_filename'],rows[1]['stored_filename'])
  self.assertTrue(any(c[1]=='first-key' for c in self.calls));self.assertTrue(any(c[1]=='second-key' for c in self.calls))
  self.assertTrue(any(c[3] and c[3].get('modified_after') for c in self.calls))
  self.assertEqual({r['external_id'] for r in rows},{'991501'})
 def test_missing_secret_pdf_and_activation_rejected(self):
  ident=self.ids[0]
  db.execute("UPDATE income_sources SET secret_profile='missing',active=0 WHERE id=%s",(ident,))
  status=src.provider(src.get_source(ident)).get_status();self.assertFalse(status['configured'])
  with app.test_client() as c,patch.dict(app.config,{'WTF_CSRF_ENABLED':False}):
   with c.session_transaction() as s:s['user']='osvc';s['local_auth']=1
   r=c.post(f'/settings/income-sources/{ident}/activation',data={'active':'yes'});self.assertEqual(r.status_code,400)
  db.execute("UPDATE income_sources SET secret_profile='first',configuration=%s WHERE id=%s",(json.dumps({**self.config,'invoice_template':''}),ident))
  self.assertFalse(src.provider(src.get_source(ident)).get_status()['documents_configured'])
 def test_scoped_backfill_and_rotation(self):
  first,second=self.ids
  src.synchronize(first);src.synchronize(second)
  row=db.query('SELECT a.* FROM attachments a JOIN income_source_records r ON r.document_id=a.document_id WHERE r.source_id=%s',(first,),one=True)
  Path(self.temp.name,row['stored_filename']).unlink()
  src.synchronize(second);self.assertFalse(Path(self.temp.name,row['stored_filename']).exists())
  src.synchronize(first);self.assertTrue(Path(self.temp.name,row['stored_filename']).exists())
  p=src.provider(src.get_source(first));p.test_connection();self.assertTrue(src.provider(src.get_source(first)).get_status()['tested'])
  f=Path(self.temp.name,'secrets.json');data=json.loads(f.read_text());data['first']['consumer_secret']='rotated';f.write_text(json.dumps(data))
  self.assertFalse(src.provider(src.get_source(first)).get_status()['tested'])
 def test_empty_installation_ui_no_required_shop(self):
  db.execute('DELETE FROM income_source_records')
  db.execute('DELETE FROM income_sources')
  with patch.dict(app.config,{'WC_URL':None,'WC_CONSUMER_KEY':None,'WC_CONSUMER_SECRET':None,'INCOME_SOURCE_SECRETS_FILE':'/missing'}),app.test_client() as c:
   with c.session_transaction() as s:s['user']='osvc';s['local_auth']=1
   for path in ['/','/settings?tab=sources','/payments/income','/settings/income-sources/new']:
    self.assertEqual(c.get(path).status_code,200)
   self.assertIn('Zatím nemáte',c.get('/settings?tab=sources').text)
 def test_incomplete_draft_saved_not_activated(self):
  with app.test_client() as c,patch.dict(app.config,{'WTF_CSRF_ENABLED':False}):
   with c.session_transaction() as s:s['user']='osvc';s['local_auth']=1
   r=c.post('/settings/income-sources/add',data={'provider':'woocommerce','name':'Draft fixture','url':'https://shop.example.test'})
   self.assertEqual(r.status_code,302)
   source=db.query("SELECT * FROM income_sources WHERE name='Draft fixture'",one=True)
   self.assertFalse(source['active']);self.assertEqual(source['provider'],'woocommerce')

 def test_disabled_source_preserves_history_then_resumes(self):
  ident=self.ids[0];src.synchronize(ident)
  rows=db.query('SELECT * FROM income_source_records WHERE source_id=%s',(ident,))
  db.execute('UPDATE income_sources SET active=0 WHERE id=%s',(ident,))
  count=len(self.calls)
  with self.assertRaises(src.SourceError):src.synchronize(ident)
  self.assertEqual(count,len(self.calls));self.assertEqual(rows,db.query('SELECT * FROM income_source_records WHERE source_id=%s',(ident,)))
  db.execute('UPDATE income_sources SET active=1 WHERE id=%s',(ident,))
  self.assertEqual(src.synchronize(ident)['imported'],0)
  self.assertEqual(len(rows),len(db.query('SELECT * FROM income_source_records WHERE source_id=%s',(ident,))))
