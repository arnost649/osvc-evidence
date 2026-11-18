"""Connector instances and explicit configuration/readiness workflow."""
import json,re,time,logging
from datetime import date
from flask import Blueprint,request,redirect,flash,jsonify,render_template,current_app
from .routes import login_required
from .db import query,execute
from .income_sources import sources,provider,get_source,synchronize,source_lock,SourceError,PROVIDERS,PROVIDER_LABELS
from .connectors import MANIFESTS,unpack,signature,scheduler_status,access_changes,access_signature,diagnostics_current,store_failed_diagnostic

bp=Blueprint('income_sources',__name__)
# Výsledek každého ověření připojení do logu služby (journalctl -u osvc-evidence) – bez adres a přístupových údajů.
log=logging.getLogger('osvc.zdroje')
if not log.handlers:
 _h=logging.StreamHandler();_h.setFormatter(logging.Formatter('%(name)s: %(message)s'));log.addHandler(_h);log.setLevel(logging.INFO);log.propagate=False
def enrich(row):
 row=dict(row);row['configuration']=unpack(row.get('configuration'));row['diagnostics']=unpack(row.get('diagnostics'))
 row['sync_state']=unpack(row.get('sync_state'));row['status']=provider(row).get_status();row['manifest']=MANIFESTS[row['provider']]
 row['stats']=query('SELECT COUNT(DISTINCT r.id) incomes,COUNT(DISTINCT a.id) documents FROM income_source_records r LEFT JOIN attachments a ON a.document_id=r.document_id AND a.deleted_at IS NULL WHERE r.source_id=%s',(row['id'],),one=True)
 return row
def settings_context():
 return {'income_sources':[enrich(r) for r in sources()],'available_source_types':PROVIDER_LABELS,'income_scheduler':scheduler_status()}

NEW_SOURCE={'id':0,'name':'','url':'','provider':'woocommerce','configuration':{'api_root':'wp-json/wc/v3','invoice_mode':'sftp_template'},
 'import_documents':False,'automatic_sync':False,'active':False,'secret_profile':'','sync_from':None}
def new_page(source,status=200):
 """Přidání zdroje na jedné stránce (1g). Při chybě se formulář vrátí s vyplněnými hodnotami."""
 source={**source,'manifest':MANIFESTS['woocommerce'],'status':{'checks':[]}}
 return render_template('income_source_wizard.html',source=source,manifest=source['manifest'],providers=PROVIDER_LABELS,
  income_scheduler=scheduler_status(),admin_open=True),status

@bp.get('/settings/income-sources/new')
@login_required
def new():
 return new_page(NEW_SOURCE)

def submitted(existing=None):
 old=existing or {};f=request.form;c=unpack(old.get('configuration'))
 name=f.get('name','').strip();url=f.get('url','').strip().rstrip('/')
 if not name or len(name)>160:raise SourceError('Vyplňte název zdroje.')
 if len(url)>500:raise SourceError('Adresa je příliš dlouhá.')
 # Incomplete drafts are allowed; unsafe URLs are never accepted.
 from urllib.parse import urlsplit
 u=urlsplit(url)
 if url and (u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment):raise SourceError('Použijte HTTPS URL bez přihlašovacích údajů a parametrů.')
 root=f.get('api_root','wp-json/wc/v3').strip('/')
 if not re.fullmatch(r'[A-Za-z0-9_/-]+',root) or '..' in root:raise SourceError('Neplatný API root.')
 profile=f.get('secret_profile','').strip()
 if profile and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',profile):raise SourceError('Profil přístupů může obsahovat písmena, čísla, pomlčku a podtržítko.')
 invoice_mode=f.get('invoice_mode','sftp_template')
 if invoice_mode not in MANIFESTS['woocommerce']['document_modes']:raise SourceError('Neplatný režim PDF.')
 port=int(f.get('sftp_port') or 22)
 if not 1<=port<=65535:raise SourceError('Neplatný SFTP port.')
 c.update(api_root=root,invoice_mode=invoice_mode,sftp_port=port)
 for key in ('sftp_host','sftp_user','private_dir','legacy_dir','invoice_template'):
  c[key]=f.get(key,'').strip()
  if len(c[key])>500 or '..' in c[key].split('/'):raise SourceError('Neplatná konfigurace archivu.')
 if c.get('invoice_template') and ('{order_id}' not in c['invoice_template'] or not c['invoice_template'].startswith('/')):raise SourceError('Šablona musí být absolutní cesta a obsahovat {order_id}.')
 return dict(name=name,url=url,secret_profile=profile,configuration=json.dumps(c,ensure_ascii=False),sync_from=date.fromisoformat(f['sync_from']) if f.get('sync_from') else None,
 automatic_sync='automatic_sync' in f,import_documents='import_documents' in f)

def persist(values,ident=None):
 if ident:execute('UPDATE income_sources SET '+','.join(k+'=%s' for k in values)+' WHERE id=%s',tuple(values.values())+(ident,));return ident
 return execute('INSERT INTO income_sources ('+','.join(values)+') VALUES ('+','.join(['%s']*len(values))+')',tuple(values.values()))

@bp.post('/settings/income-sources/add')
@login_required
def add():
 try:
  kind=request.form.get('provider')
  if kind not in PROVIDERS:raise SourceError('Konektor není implementovaný.')
  ident=persist(dict(provider=kind,active=False,**submitted()))
  return redirect('/settings?tab=sources&configure='+str(ident)+'&test=1')
 except ValueError as exc:
  f=request.form;flash(str(exc),'error')
  keys=('api_root','invoice_mode','sftp_host','sftp_port','sftp_user','invoice_template','private_dir','legacy_dir')
  return new_page({**NEW_SOURCE,'provider':f.get('provider','woocommerce'),'name':f.get('name',''),'url':f.get('url',''),'secret_profile':f.get('secret_profile',''),
   'sync_from':f.get('sync_from') or None,'import_documents':'import_documents' in f,'automatic_sync':'automatic_sync' in f,
   'configuration':{k:f.get(k,'') for k in keys}},400)

@bp.post('/settings/income-sources/<int:ident>')
@login_required
def save(ident):
 try:
  with source_lock(ident):
   old=get_source(ident);values=submitted(old);candidate={**old,**values}
   # only a change of connection settings (address, credentials, SFTP, paths, PDF mode) needs a new verification;
   # saving e.g. "Automatická synchronizace" keeps the source active and its diagnostics.
   changes=access_changes(old,candidate);was_active=bool(old.get('active'))
   if changes:values.update(active=False,diagnostics=None,sync_state=None,last_error=None)
   stale=False
   if not changes:
    d=unpack(old.get('diagnostics'))
    if d and diagnostics_current(old,d):
     d['signature']=access_signature(candidate);values['diagnostics']=json.dumps(d)
    elif d:stale=True  # e.g. password changed in the credentials file since the last verification
   persist(values,ident)
  if changes and (was_active or old.get('diagnostics')):
   flash('Konfigurace uložena. Změnilo se nastavení připojení ('+', '.join(changes)+'), proto je potřeba znovu ověřit připojení'
    +(' a zdroj znovu aktivovat – do té doby je vypnutý.' if was_active else '.'),'warning')
  elif stale:flash('Konfigurace uložena.'+(' Zdroj zůstává aktivní, ale' if was_active else '')+' poslední ověření připojení neodpovídá současným přístupovým údajům'
   +' (např. změněné heslo nebo klíče v souboru přístupů) – ověřte připojení.','warning')
  else:flash('Konfigurace uložena.'+(' Zdroj zůstává aktivní.' if was_active else ''),'success')
 except ValueError as exc:flash(str(exc),'error')
 return redirect('/settings?tab=sources&configure='+str(ident))

@bp.post('/settings/income-sources/<int:ident>/activation')
@login_required
def activation(ident):
 try:
  with source_lock(ident):
   s=get_source(ident)
   if request.form.get('active')=='yes':
    status=provider(s).get_status()
    if not status['configured'] or not status['tested']:raise SourceError('Doplňte požadovanou konfiguraci a úspěšně ověřte připojení.')
    active=True
   else:active=False
   execute('UPDATE income_sources SET active=%s WHERE id=%s',(active,ident))
  return jsonify(ok=True)
 except SourceError as exc:return jsonify(ok=False,message=str(exc)),400

@bp.post('/settings/income-sources/<int:ident>/sync')
@login_required
def sync(ident):
 try:
  summary=synchronize(ident)
  for warning in summary.get('warnings',[]):flash(warning,'warning')
  return jsonify(ok=True,summary=summary)
 except SourceError as exc:return jsonify(ok=False,message=str(exc)),400

@bp.post('/settings/income-sources/<int:ident>/test')
@login_required
def test(ident):
 # Every verification replaces the stored result (also when it cannot run) and reports via flash; the page reloads afterwards.
 started=time.monotonic()
 def done(result):log.info('ověření zdroje %s: %s (%.1f s)',ident,result,time.monotonic()-started)
 try:
  with source_lock(ident):
   s=get_source(ident);p=provider(s);status=p.get_status()
   if not status['configured']:
    missing=[c for c in status['checks'] if not c['ok']]
    store_failed_diagnostic(s,[{'key':c['key'],'label':c['label'],'state':'error','detail':c['detail']} for c in missing])
    message='Připojení nelze ověřit, chybí: '+', '.join(c['label'] for c in missing)+'.'
    done('nenastaveno ('+', '.join(c['key'] for c in missing)+')')
    flash(message,'error');return jsonify(ok=False,message=message),400
   diagnostic=p.test_connection()
   failed=[c for c in diagnostic['checks'] if c['state']=='error']
   done('chyba ('+', '.join(c['key'] for c in failed)+')' if failed else 'OK')
   if failed:flash('Ověření skončilo chybou: '+', '.join(c['label'] for c in failed)+'.','error')
   else:flash('Připojení ověřeno.','success')
   return jsonify(ok=True,diagnostic=diagnostic)
 except SourceError as exc:
  busy='probíhá' in str(exc)
  message='Ověření teď nejde spustit – právě běží synchronizace tohoto zdroje (obvykle trvá jen pár sekund). Zkuste to za chvíli znovu.' if busy else str(exc)
  done('neprovedeno – '+('běží synchronizace' if busy else 'odmítnuto'))
  flash(message,'error');return jsonify(ok=False,message=message),400
 except Exception as exc:
  done('neočekávaná chyba '+type(exc).__name__)
  message='Ověření se nepodařilo dokončit. Zkontrolujte připojení a serverové přístupy.'
  try:store_failed_diagnostic(get_source(ident),[{'key':'test','label':'Ověření připojení','state':'error','detail':'Ověření se nepodařilo dokončit ('+type(exc).__name__+').'}])
  except Exception:pass
  flash(message,'error');return jsonify(ok=False,message=message),400
