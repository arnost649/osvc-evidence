"""Connector manifests, isolated credentials and WooCommerce diagnostics."""
import hashlib,json,os,re,stat
from pathlib import Path
from datetime import datetime,timezone,timedelta
from contextlib import contextmanager
from urllib.parse import urlsplit
from flask import current_app,g
from .income_sources import IncomeSourceProvider,SourceError
from .db import query,execute

MANIFESTS={'woocommerce':{
 'id':'woocommerce','name':'WooCommerce',
 'configuration':[
  {'key':'url','label':'HTTPS adresa webu','kind':'required','section':'connection'},
  {'key':'api_root','label':'API root','kind':'derived','default':'wp-json/wc/v3','section':'connection'},
  {'key':'secret_profile','label':'Profil serverových přístupů','kind':'required','section':'authentication'},
  {'key':'consumer_key','label':'Consumer Key','kind':'required secret','section':'authentication'},
  {'key':'consumer_secret','label':'Consumer Secret','kind':'required secret','section':'authentication'},
  {'key':'sync_from','label':'Importovat od','kind':'optional','section':'synchronization'},
  {'key':'invoice_mode','label':'Způsob získání PDF','kind':'required if documents','section':'documents'},
  {'key':'sftp_host','label':'SFTP host','kind':'required if documents','section':'documents'},
  {'key':'sftp_user','label':'SFTP uživatel','kind':'required if documents','section':'documents'},
  {'key':'sftp_port','label':'SFTP port','kind':'derived','default':22,'section':'documents'},
  {'key':'sftp_password_file','label':'Soubor s heslem SFTP','kind':'required secret if documents','section':'documents'},
  {'key':'known_hosts','label':'Soubor ověřených host keys','kind':'required if documents','section':'documents'},
  {'key':'invoice_template','label':'Absolutní šablona s {order_id}','kind':'required if sftp_template','section':'documents'},
  {'key':'private_dir','label':'Privátní archiv','kind':'required if sftp_archive','section':'documents'},
  {'key':'legacy_dir','label':'Historický archiv','kind':'required if sftp_archive','section':'documents'},
 ],
 'mapping':[
  ('Datum příjmu','date_paid – datum zaplacení'),
  ('Zákazník','billing.first_name + billing.last_name'),
  ('Externí ID','order.id – v rámci tohoto zdroje'),
  ('Popis','line_items[].name; číslo objednávky zůstává v popisu platby'),
  ('Částka','order.total – celkem potvrzené objednávky, CZK'),
  ('Doklad','Existující PDF v nakonfigurovaném archivu'),
  ('Zdroj','Název této instance')],
 'capabilities':{'orders':'Objednávky','customers':'Zákazníci','items':'Položky objednávek','amounts':'Částky',
                 'invoices':'PDF faktury','historical_backfill':'Historický backfill','incremental_sync':'Inkrementální synchronizace',
                 'refunds':'Úplné refundace / zrušení','credit_notes':'Dobropisy'},
 'document_modes':{'sftp_archive':'SFTP archiv (metadata + historické WPO PDF)','sftp_template':'SFTP podle šablony názvu'},
}}

def unpack(value):
 return json.loads(value) if isinstance(value,str) else value or {}

# Fields that decide whether a verified connection is still valid. Saving anything else (automatic sync, import date,
# category, name) keeps the source active and its diagnostics. Values are normalised so that e.g. 1 from MySQL and True from the form match.
ACCESS_FIELDS=(('url','adresa webu'),('api_root','API root'),('secret_profile','profil přístupů'),('credentials','přístupové údaje (klíče nebo heslo)'),
 ('import_documents','import PDF dokladů'),('invoice_mode','způsob získání PDF'),('sftp_host','SFTP host'),('sftp_port','SFTP port'),('sftp_user','SFTP uživatel'),
 ('sftp_password_file','soubor s heslem SFTP'),('known_hosts','soubor ověřených host keys'),('invoice_template','šablona cesty PDF'),('private_dir','privátní archiv'),('legacy_dir','historický archiv'))
def access_values(source):
 c=unpack(source.get('configuration'));text=lambda v:str(v or '').strip()
 try:port=int(c.get('sftp_port') or 22)
 except (TypeError,ValueError):port=text(c.get('sftp_port'))
 values={'url':text(source.get('url')).rstrip('/'),'api_root':text(c.get('api_root') or 'wp-json/wc/v3').strip('/'),'secret_profile':text(source.get('secret_profile')),
  'credentials':hashlib.sha256(json.dumps(secrets_for(source),sort_keys=True).encode()).hexdigest(),'import_documents':bool(source.get('import_documents')),'sftp_port':port}
 for key in ('invoice_mode','sftp_host','sftp_user','sftp_password_file','known_hosts','invoice_template','private_dir','legacy_dir'):values[key]=text(c.get(key))
 if not values['import_documents']:
  # Without document import the archive settings are not used, so editing them does not need a new verification.
  for key in ('invoice_mode','sftp_host','sftp_port','sftp_user','sftp_password_file','known_hosts','invoice_template','private_dir','legacy_dir'):values[key]=None
 return values
def access_signature(source):
 return 'a1:'+hashlib.sha256(json.dumps(access_values(source),default=str,sort_keys=True).encode()).hexdigest()
def access_changes(old,new):
 a,b=access_values(old),access_values(new)
 if a['import_documents'] and not b['import_documents']:
  # Switching document import off needs no new verification (the verified API stays valid); archive fields are then unused.
  a={k:(None if k not in ('url','api_root','secret_profile','credentials') else v) for k,v in a.items()};b={**b,'import_documents':None}
 elif not a['import_documents'] and b['import_documents']:
  return [label for key,label in ACCESS_FIELDS if key in ('import_documents',) or (key in ('url','api_root','secret_profile','credentials') and a[key]!=b[key])]
 return [label for key,label in ACCESS_FIELDS if a[key]!=b[key]]
def diagnostics_current(source,diagnostics=None):
 """Diagnostics belong to the current access settings (new access signature, or the older full signature saved before 2026-11-13)."""
 d=unpack(source.get('diagnostics')) if diagnostics is None else diagnostics
 return bool(d.get('signature')) and d.get('signature') in (access_signature(source),signature(source))

def store_failed_diagnostic(source,checks):
 """Verification that could not run (missing settings, unexpected error) still replaces the old result, so the page never shows stale ✓.
 Capabilities of the API are kept: they steer incremental sync and do not depend on this failure."""
 previous=unpack(source.get('diagnostics'))
 diagnostic={'at':datetime.now(timezone.utc).isoformat(),'signature':access_signature(source),'checks':checks,
             'capabilities':previous.get('capabilities',{}),'activation_ok':False}
 execute('UPDATE income_sources SET diagnostics=%s WHERE id=%s',(json.dumps(diagnostic),source['id']))
 return diagnostic

ADMIN=' (doplní správce serveru)'
def secrets_status(source):
 """(profile values, problem) – problem is a Czech reason without any secret value, None when the profile is usable."""
 path=current_app.config.get('INCOME_SOURCE_SECRETS_FILE') or os.environ.get('INCOME_SOURCE_SECRETS_FILE')
 if not path:return {},'Aplikace nemá nastavený soubor přístupů (INCOME_SOURCE_SECRETS_FILE v app.env)'+ADMIN+'.'
 file=Path(path)
 try:mode=stat.S_IMODE(file.stat().st_mode)
 except OSError:return {},f'Soubor přístupů {path} neexistuje nebo ho aplikace nevidí'+ADMIN+'.'
 if mode&0o077:return {},f'Soubor přístupů {path} smí číst jen aplikace (práva 600, nyní {mode:o})'+ADMIN+'.'
 try:data=json.loads(file.read_text(encoding='utf-8'))
 except OSError:return {},f'Soubor přístupů {path} nejde přečíst'+ADMIN+'.'
 except ValueError:return {},f'Soubor přístupů {path} není platný JSON'+ADMIN+'.'
 profile=source.get('secret_profile') or ''
 if not profile:return {},'Není vyplněný profil serverových přístupů.'
 result=data.get(profile) if isinstance(data,dict) else None
 if not isinstance(result,dict):return {},f'Profil „{profile}“ v souboru přístupů není'+ADMIN+'.'
 missing=[k for k in ('consumer_key','consumer_secret') if not result.get(k)]
 if missing:return result,f'V profilu „{profile}“ chybí '+' a '.join(missing)+ADMIN+'.'
 return result,None

def secrets_for(source):
 return secrets_status(source)[0]

def secret_file_problem(path,label,private=False):
 """Reason why a file named in the credentials profile (SFTP password, known_hosts) is not usable, or None."""
 if not path:return f'V profilu přístupů chybí {label}'+ADMIN+'.'
 hint=' – služba nevidí do /home, soubor patří do konfigurační složky služby' if str(path).startswith('/home/') else ''
 try:info=Path(path).stat()
 except OSError:return f'{label.capitalize()} ({path}) neexistuje nebo ho aplikace nevidí{hint}'+ADMIN+'.'
 if not stat.S_ISREG(info.st_mode):return f'{label.capitalize()} ({path}) není soubor'+ADMIN+'.'
 # Windows práva 600 nezná (soubor je v profilu uživatele)
 if private and os.name!='nt' and stat.S_IMODE(info.st_mode)!=0o600:return f'{label.capitalize()} ({path}) musí mít práva 600'+ADMIN+'.'
 return None

SCHEDULER_FILE='income-sync-last.json'   # zapisuje `flask sync-income-sources` (systemd timer) po každém běhu
SCHEDULER_STALE=timedelta(minutes=35)      # timer běží každých 15 min; dva vynechané běhy = neběží
def scheduler_status():
 """Stav plánovače podle jeho skutečného posledního běhu.
 state: 'ok' (běžel nedávno), 'waiting' (nastavený, ještě neběžel – např. hned po nasazení), 'stale' (dlouho neběžel), 'missing'.
 INCOME_SYNC_SCHEDULER v app.env je už jen nápověda pro instalaci bez proběhlého běhu."""
 from .backup import state_dir
 now=datetime.now(timezone.utc)
 next_slot=now.replace(second=0,microsecond=0)+timedelta(minutes=15-now.minute%15)
 configured=(current_app.config.get('INCOME_SYNC_SCHEDULER') or os.environ.get('INCOME_SYNC_SCHEDULER')) in ('systemd-15min','spoustec-15min')
 try:last=json.loads((state_dir()/SCHEDULER_FILE).read_text(encoding='utf-8'))
 except (OSError,ValueError):last={}
 at=None
 try:at=datetime.fromisoformat(last['at'])
 except (KeyError,TypeError,ValueError):last={}
 state='ok' if at and now-at<=SCHEDULER_STALE else 'stale' if at else 'waiting' if configured else 'missing'
 return {'enabled':state in ('ok','waiting'),'state':state,'last_at':last.get('at'),'last_ok':last.get('ok'),
         'sources':last.get('sources',{}),'next':next_slot.isoformat() if state in ('ok','waiting') else None}
def record_scheduler_run(results):
 """Výsledek jednoho běhu plánovače: {id zdroje: {'state': ok|error|skipped, 'message': …}} – bez adres a přístupů."""
 from .backup import state_dir,write_atomic
 data={'at':datetime.now(timezone.utc).isoformat(),'ok':not any(r['state']=='error' for r in results.values()),'sources':{str(k):v for k,v in results.items()}}
 write_atomic(state_dir()/SCHEDULER_FILE,json.dumps(data,ensure_ascii=False).encode())
 return data

def signature(source):
 values={k:source.get(k) for k in ('url','configuration','secret_profile','sync_from','category_id','import_documents')}
 # Detect credential rotation without persisting or exposing credential values.
 values['configuration']=unpack(values.get('configuration'))
 values['credentials_digest']=hashlib.sha256(json.dumps(secrets_for(source),sort_keys=True).encode()).hexdigest()
 return hashlib.sha256(json.dumps(values,default=str,sort_keys=True).encode()).hexdigest()

class WooCommerceProvider(IncomeSourceProvider):
 manifest=MANIFESTS['woocommerce']
 @property
 def configuration(self):return unpack(self.source.get('configuration'))
 @contextmanager
 def runtime(self):
  previous=getattr(g,'income_source',None);g.income_source=self.source
  try:yield
  finally:g.income_source=previous
 def validate_config(self):
  s=self.source;c=self.configuration;secret,secret_problem=secrets_status(s);checks=[]
  def add(key,label,ok,detail='',problem=''):checks.append({'key':key,'label':label,'ok':bool(ok),'detail':detail if ok else (problem or detail)})
  u=urlsplit(s.get('url') or '')
  url_ok=u.scheme=='https' and u.hostname and not (u.username or u.password or u.query or u.fragment)
  add('connection','Připojení',url_ok and re.fullmatch(r'[A-Za-z0-9_/-]+',c.get('api_root','wp-json/wc/v3')),'HTTPS URL; odvozený API root',
      'Doplňte adresu webu (https://…).' if not s.get('url') else 'Adresa webu musí začínat https:// a nesmí obsahovat jméno, heslo ani parametry.' if not url_ok else 'Neplatný API root.')
  add('authentication','Autentizace',not secret_problem,'Server secret: Consumer Key + Consumer Secret',secret_problem)
  add('mapping','Mapování příjmů',True,'Potvrzená objednávka → příjem v CZK; typ income_connector')
  problems=[]
  if s['import_documents']:
   if c.get('invoice_mode') not in self.manifest['document_modes']:problems.append('Vyberte způsob získání PDF.')
   if not (c.get('sftp_host') and c.get('sftp_user')):problems.append('Doplňte SFTP host a uživatele.')
   if secret_problem and not secret:problems.append('Nejdřív je potřeba vyřešit soubor přístupů (viz Autentizace).')
   else:
    for key,label,private in (('sftp_password_file','soubor s heslem SFTP',True),('known_hosts','soubor ověřených host keys (known_hosts)',False)):
     problem=secret_file_problem(secret.get(key),label,private)
     if problem:problems.append(problem)
   if c.get('invoice_mode')=='sftp_archive':
    if not (c.get('private_dir') and c.get('legacy_dir')):problems.append('Doplňte privátní a historický archiv PDF.')
   elif not ('{order_id}' in c.get('invoice_template','') and c.get('invoice_template','').startswith('/')):problems.append('Doplňte šablonu cesty PDF (absolutní cesta s {order_id}).')
  add('documents','Doklady',not problems,'SFTP připojení, ověřený host key a archivní cesty' if s['import_documents'] else 'Import dokladů vypnutý',' '.join(problems))
  # stav plánovače ruční synchronizaci ani aktivaci neblokuje – karta ho ukazuje zvlášť (automatic_summary).
  add('synchronization','Synchronizace',True,'Ručně kdykoli; automaticky každých 15 minut, když běží plánovač')
  return checks
 def get_status(self):
  checks=self.validate_config();ready=all(c['ok'] for c in checks);d=unpack(self.source.get('diagnostics'))
  current=diagnostics_current(self.source,d)
  tested=current and d.get('activation_ok',False)
  state='AKTIVNÍ' if ready and self.source['active'] else 'PŘIPRAVENO' if ready else 'ROZPRACOVÁNO' if self.source.get('url') else 'NEKONFIGUROVÁNO'
  from .income_sources import sync_error,sync_warnings
  error=sync_error(self.source)
  if error or (current and any(x['state']=='error' for x in d.get('checks',[]))):state='CHYBA'
  return {'error':error,'warnings':sync_warnings(self.source),'configured':ready,'documents_configured':next(x['ok'] for x in checks if x['key']=='documents'),'checks':checks,'state':state,'tested':tested,'diagnostics_current':current}
 def fetch_income(self,**kwargs):
  from . import woocommerce as wc
  with self.runtime():return [wc.normalize_income(order) for order in wc.fetch_orders(**kwargs)]
 def fetch_document(self,order):
  from . import woocommerce as wc
  with self.runtime():return wc._download_archived_invoice(order['id'],order)
 def discover_capabilities(self):
  d=unpack(self.source.get('diagnostics'))
  return d.get('capabilities',{})
 def test_connection(self):
  from . import woocommerce as wc
  checks=[];caps={k:None for k in self.manifest['capabilities']}
  caps['credit_notes']=False
  def result(key,label,state,detail=''):
   checks.append({'key':key,'label':label,'state':state,'detail':detail})
  orders=[];detail=None;api=False;archive=False
  with self.runtime(),wc.invoice_sftp_session():
   try:
    orders=wc.fetch_orders(test_only=True)
    api=True
    for key,label in [('server','Server dostupný'),('auth','API autentizace'),('orders','Načtení objednávek')]:result(key,label,'ok')
    caps['orders']=True
   except Exception as exc:
    result('api','Server / API autentizace','error','Připojení odmítnuto nebo API není dostupné ('+str(getattr(exc,'code',type(exc).__name__))+').')
   if api:
    try:
     options=wc.api_request('orders',method='OPTIONS')
     incremental=any('modified_after' in e.get('args',{}) for e in options.get('endpoints',[]))
     caps['incremental_sync']=incremental
     result('incremental','Inkrementální synchronizace','ok' if incremental else 'review','Podporovaný filtr změn' if incremental else 'API nepotvrdilo filtr změn; bude použito plné načtení.')
    except Exception: caps['incremental_sync']=False;result('incremental','Inkrementální synchronizace','review','API nepotvrdilo filtr změn.')
   if orders:
    try:
     detail=wc.fetch_order(orders[0]['id']);result('detail','Detail objednávky','ok')
     for key,label,value in [('customers','Zákazník',detail.get('billing')),('items','Položky',detail.get('line_items')),('amounts','Částka',detail.get('total'))]:
      caps[key]=bool(value);result(key,label,'ok' if value else 'review','Údaj není v testované objednávce.' if not value else '')
     caps['refunds']='refunds' in detail
    except Exception:result('detail','Detail objednávky','error','Detail nelze načíst.')
   elif api:result('sample','Ukázková objednávka','review','Zdroj je prázdný; zákazníka, položky a PDF zatím nelze ověřit.')
   if self.source['import_documents']:
    try:
     with wc._invoice_sftp() as sftp:
      c=self.configuration
      paths=[c.get('private_dir'),c.get('legacy_dir')] if c.get('invoice_mode')=='sftp_archive' else [str(Path(c.get('invoice_template','')).parent)]
      for path in paths:sftp.stat(path)
     archive=True;result('archive','Přístup do archivu','ok');caps['historical_backfill']=True
    except Exception:result('archive','Přístup do archivu','error','Zkontrolujte SFTP přístup, host key a cesty.')
    if archive and detail:
     try:self.fetch_document(detail);result('pdf','Skutečná PDF faktura','ok');caps['invoices']=True
     except wc.InvoicePdfUnavailable as exc:
      if exc.status==2:result('pdf','Skutečná PDF faktura','review','Testovaná objednávka nemá uloženou fakturu.')
      else:result('pdf','Skutečná PDF faktura','error','Soubor nelze bezpečně načíst jako PDF.')
   else:
    caps['invoices']=False;caps['historical_backfill']=False;result('pdf','PDF faktury','off','Import vypnutý')
  diagnostic={'at':datetime.now(timezone.utc).isoformat(),'signature':access_signature(self.source),'checks':checks,'capabilities':caps,
              'activation_ok':api and (not self.source['import_documents'] or archive) and not any(c['state']=='error' for c in checks)}
  execute('UPDATE income_sources SET diagnostics=%s WHERE id=%s',(json.dumps(diagnostic),self.source['id']))
  return diagnostic
 def sync(self,automatic=False):
  from . import woocommerce as wc
  state=unpack(self.source.get('sync_state'));started=datetime.now(timezone.utc)
  incremental=self.discover_capabilities().get('incremental_sync') is True
  cursor=state.get('cursor') if incremental else None
  with self.runtime(),wc.invoice_sftp_session():
   orders=wc.fetch_orders(modified_after=cursor)
   summary=wc.sync_orders(orders)
   if self.source['import_documents']:
    # Missing local PDFs are repaired independently, using individual historical orders.
    # automatický běh se na chybějící fakturu ptá e-shopu nejvýš 1× denně;
    # ruční Synchronizovat zkouší vždy. Kontrola lokálních PDF je v jednom průchodu (cache v invoice_sftp_session).
    in_batch={str(o['id']) for o in orders};today=datetime.now(timezone.utc).date().isoformat()
    retried=state.get('pdf_retry') or {};retry={}
    for doc in wc.source_documents():
     if wc._document_has_invoice(doc['id']) or str(doc['external_id']) in in_batch:continue
     key=str(doc['id'])
     if automatic and retried.get(key)==today:retry[key]=today;continue
     retry[key]=today
     try:order=wc.fetch_order(doc['external_id']);status=wc._sync_invoice_for_document(doc['id'],order)
     except Exception:status='error'
     if status=='added':summary['pdf_added']+=1;retry.pop(key,None)
     if status=='error':summary['pdf_errors']+=1
    state['pdf_retry']=retry
    missing=[str(d['number']) for d in wc.source_documents() if not wc._document_has_invoice(d['id'])]
    summary['pdf_missing_orders']=missing;summary['pdf_missing']=len(missing)
  if summary['pdf_errors'] and not summary['warnings']:summary['warnings'].append('Některé doklady se nepodařilo doplnit; další synchronizace pokus zopakuje.')
  state.update(last_successful_sync=started.isoformat(),cursor=(started-timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%S') if incremental else None)
  execute('UPDATE income_sources SET sync_state=%s WHERE id=%s',(json.dumps(state),self.source['id']))
  return summary
