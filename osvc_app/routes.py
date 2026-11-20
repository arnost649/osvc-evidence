from . import system_types
from .forms import ManualExpenseForm
from . import expense_tax
from .pagination import paginate
import os, uuid, hashlib, json, subprocess
from datetime import date, datetime, timedelta
from . import cas
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from pathlib import Path
from flask import Blueprint, render_template, redirect, url_for, flash, session, request, abort, current_app, send_from_directory, jsonify
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError
from werkzeug.utils import secure_filename
from .db import query, execute, connection, rok
from .forms import PaymentForm, DocumentForm, TripForm, FuelForm
from .income_sources import source_ready as wc_configured, source_ready as wc_sync_ready, default_source, last_sync, synchronize, SourceError
from .ares import AresUnavailable, identifiers_from_text, lookup_by_ico, text_from_attachment, verify_supplier
from werkzeug.datastructures import FileStorage

bp=Blueprint('main',__name__)
ALLOWED={'application/pdf','image/jpeg','image/png'}
TRIP_FUELS_SQL="SELECT f.id,f.purchase_date,COALESCE(f.station_name,f.station) station,f.price_per_liter,f.total_amount FROM fuel_purchases f JOIN vehicles fv ON fv.id=f.vehicle_id JOIN vehicles tv ON tv.id=%s WHERE f.vehicle_id=%s AND fv.fuel_type=tv.fuel_type AND f.purchase_date<=%s AND f.deleted_at IS NULL ORDER BY f.purchase_date DESC,f.id DESC"

def login_required(f):
 @wraps(f)
 def wrapped(*a,**k):
  from . import ucet
  u=ucet.aktualni()   # účet v aplikaci (I2); změna hesla zvýší verzi → starší přihlášení neplatí
  if session.get('local_auth') != 1 or not u or session.get('user') != u['username'] or ('auth' in session and session['auth'] != u['auth_version']):
   session.clear(); return redirect(url_for('main.login'))
  return f(*a,**k)
 return wrapped
def val(v): return v if v not in ('',None,0) else None
def choices(form, field, sql, params=()): getattr(form,field).choices=[(0,'— nevybráno —')]+[(r['id'],r['name']) for r in query(sql,params)]
def docs_choices(form): getattr(form,'document_id').choices=[(0,'— nevybráno —')]+[(r['id'],r['number'] if r['number'] is not None else f"#{r['id']}") for r in query("SELECT id,number FROM documents WHERE deleted_at IS NULL ORDER BY issue_date DESC")]
def vehicles(form): getattr(form,'vehicle_id').choices=[(0,'— nevybráno —')]+[(r['id'],r['name']+(f" ({r['registration_plate']})" if r['registration_plate'] is not None else '')) for r in query("SELECT id,name,registration_plate FROM vehicles WHERE deleted_at IS NULL AND active=1")]
# Kontrola chybějících sloupců: osvc_app/schema.py (jednou při startu, jen do logu).
def event_choices(form):
 form.event_id.choices=[('', '— bez akce —')]
 form.event_id.choices += [(r['id'],f"{r['event_date'].strftime('%d.%m.%Y')} – {r['name']}") for r in query("SELECT id,event_date,name FROM business_events WHERE deleted_at IS NULL ORDER BY event_date DESC,name")]
def event_id_value(value): return val(value)
def payment_choices(form,direction):
 role='supplier' if direction=='expense' else 'customer'
 form.counterparty_options=query("SELECT id,name FROM counterparties WHERE source='manual' AND role IN (%s,'both') AND deleted_at IS NULL ORDER BY name",(role,))
 if hasattr(form,'document_id'): docs_choices(form)
 if hasattr(form,'event_id'): event_choices(form)
def audit(entity,ident,action,old=None,new=None):
 execute('INSERT INTO audit_log (entity_type,entity_id,action,old_data,new_data) VALUES (%s,%s,%s,%s,%s)',(entity,ident,action,json.dumps(old,default=str) if old is not None else None,json.dumps(new,default=str) if new is not None else None))


def calculate_trip_cost(distance, consumption, base_rate, statutory_fuel_price, receipt_fuel_price=None):
 try:
  km=Decimal(str(distance)); used_consumption=Decimal(str(consumption)); per_km=Decimal(str(base_rate)); statutory=Decimal(str(statutory_fuel_price))
  receipt=Decimal(str(receipt_fuel_price)) if receipt_fuel_price is not None else None
 except (InvalidOperation, TypeError, ValueError): return None
 # A selected receipt is a price source, not a ceiling and not a consumable
 # allocation.  It may therefore be reused by any eligible trip.
 used_price=receipt if receipt is not None else statutory
 money=Decimal('0.01')
 base=(km*per_km).quantize(money,rounding=ROUND_HALF_UP)
 fuel=(km*used_consumption/Decimal('100')*used_price).quantize(money,rounding=ROUND_HALF_UP)
 return {'consumption':used_consumption,'base_rate':per_km,'fuel_price':used_price,'base':base,'fuel':fuel,'total':base+fuel}

def trip_rate(vehicle_id, trip_date):
 return query("SELECT r.* FROM travel_rates r JOIN vehicles v ON v.id=%s WHERE r.deleted_at IS NULL AND r.vehicle_type='passenger_car' AND r.fuel_type=v.fuel_type AND %s BETWEEN r.valid_from AND r.valid_to ORDER BY r.valid_from DESC,r.id DESC LIMIT 1",(vehicle_id,trip_date),one=True)

def trip_fuels(vehicle_id, trip_date):
 return query(TRIP_FUELS_SQL,(vehicle_id,vehicle_id,trip_date))

def trip_fuels_for_picker(vehicle_id, trip_date, selected_fuel_id=None):
 fuels=trip_fuels(vehicle_id,trip_date)
 if not selected_fuel_id: return fuels[:1]
 selected=[fuel for fuel in fuels if int(fuel['id']) == int(selected_fuel_id)]
 latest=fuels[:1]
 return selected + [fuel for fuel in latest if not selected or fuel['id'] != selected[0]['id']]

def _as_date(value):
 if isinstance(value,date): return value
 return date.fromisoformat(str(value)[:10])

def trip_interval_conflict(start, end, exclude_id=None):
 """Return the first exclusive-day collision, or None.

 A trip's endpoints remain shareable; only interior days of multi-day
 trips are exclusive.  This is intentionally checked server-side.
 """
 start=_as_date(start); end=_as_date(end or start)
 rows=query("SELECT id,trip_date,trip_end_date,origin,destination FROM trips WHERE deleted_at IS NULL" )
 new_interior=(start + timedelta(days=1), end - timedelta(days=1)) if start < end else None
 for row in rows:
  if exclude_id is not None and int(row['id']) == int(exclude_id): continue
  other_start=_as_date(row['trip_date']); other_end=_as_date(row['trip_end_date'] or row['trip_date'])
  other_interior=(other_start + timedelta(days=1), other_end - timedelta(days=1)) if other_start < other_end else None
  conflict_day=None
  if new_interior and new_interior[0] <= new_interior[1]:
   lo=max(new_interior[0],other_start); hi=min(new_interior[1],other_end)
   if lo <= hi: conflict_day=lo
  if conflict_day is None and other_interior and other_interior[0] <= other_interior[1]:
   lo=max(start,other_interior[0]); hi=min(end,other_interior[1])
   if lo <= hi: conflict_day=lo
  if conflict_day:
   route=f"{row['origin']} → {row['destination']}"
   span=f"{cas.datum(other_start)}–{cas.datum(other_end)}"
   return f"Cestu nelze uložit. Datum {cas.datum(conflict_day)} je uvnitř již evidované vícedenní cesty {route} ({span})."
 return None

def trip_fuel_label(fuel):
 amount=f"{fuel['total_amount']:,.2f}".replace(',', ' ').replace('.', ',')
 return f"{fuel['purchase_date'].strftime('%d.%m.%Y')} · {fuel['station'] or system_types.labels()['fuel']} · {amount} Kč"

def statutory_fuel_label(rate, trip_date):
 if not rate: return 'Vyhlášková cena'
 price=f"{float(rate['average_fuel_price_per_liter']):.2f}".replace('.',',')
 return f"Vyhlášková cena {trip_date.year} · {price} Kč/l"

def set_trip_fuel_choices(form, vehicle_id=None, trip_date=None, trip_end_date=None, selected_fuel_id=None):
 form.fuel_purchase_id.choices=[(0,'Bez dokladu – vyhláška')]
 if not vehicle_id or not trip_date: return
 rate=trip_rate(vehicle_id,trip_date)
 form.fuel_purchase_id.choices[0]=(0,'Bez dokladu – vyhláška')
 for fuel in trip_fuels_for_picker(vehicle_id,trip_end_date or trip_date,selected_fuel_id):
  form.fuel_purchase_id.choices.append((fuel['id'],trip_fuel_label(fuel)))

def trip_calculation(vehicle_id, trip_date, distance, fuel_purchase_id=0, trip_end_date=None):
 vehicle=query('SELECT id,normalized_consumption_l_100km FROM vehicles WHERE id=%s AND deleted_at IS NULL',(vehicle_id,),one=True)
 if not vehicle: return {'ready':True,'message':'Vyberte vozidlo.'}
 if vehicle['normalized_consumption_l_100km'] is None: return {'ready':True,'message':'Nejdříve doplňte normovanou spotřebu vozidla.','needs_consumption':True,'vehicle_id':vehicle['id']}
 rate=trip_rate(vehicle_id,trip_date)
 if not rate: return {'ready':True,'message':'Pro datum jízdy a palivo není nastavena sazba.'}
 fuel=None
 if fuel_purchase_id:
  fuel=query('SELECT f.id,f.price_per_liter FROM fuel_purchases f JOIN vehicles fv ON fv.id=f.vehicle_id JOIN vehicles tv ON tv.id=%s WHERE f.id=%s AND f.vehicle_id=%s AND fv.fuel_type=tv.fuel_type AND f.purchase_date<=%s AND f.deleted_at IS NULL',(vehicle_id,fuel_purchase_id,vehicle_id,trip_end_date or trip_date),one=True)
  if not fuel: return {'ready':True,'message':'Vybrané tankování nepatří k vozidlu.'}
 result=calculate_trip_cost(distance,vehicle['normalized_consumption_l_100km'],rate['base_rate_per_km'],rate['average_fuel_price_per_liter'],fuel['price_per_liter'] if fuel else None)
 if not result: return {'ready':True,'message':'Zadejte počet kilometrů.'}
 return {'ready':True,'message':None,'rate_id':rate['id'],'fuel_purchase_id':fuel['id'] if fuel else None,'fuel_price_source':'receipt' if fuel else 'statutory',**result}

def trip_snapshot_calculation(trip):
 """Return the immutable stored result, or calculate legacy rows once for display."""
 fields=('calculation_consumption_l_100km','calculation_base_rate_per_km','calculation_fuel_price_per_liter','base_compensation','fuel_compensation','travel_cost_total')
 if all(trip.get(field) is not None for field in fields):
  return {'ready':True,'message':None,'rate_id':trip.get('travel_rate_id'),'fuel_purchase_id':trip.get('fuel_purchase_id'),'fuel_price_source':trip.get('fuel_price_source') or ('receipt' if trip.get('fuel_purchase_id') else 'statutory'),'consumption':trip['calculation_consumption_l_100km'],'base_rate':trip['calculation_base_rate_per_km'],'fuel_price':trip['calculation_fuel_price_per_liter'],'base':trip['base_compensation'],'fuel':trip['fuel_compensation'],'total':trip['travel_cost_total'],'snapshot':True}
 return trip_calculation(trip['vehicle_id'],trip['trip_date'],trip['distance_km'],trip.get('fuel_purchase_id') or 0,trip.get('trip_end_date') or trip['trip_date'])

TRIP_EXPENSES_SQL="SELECT t.id,t.trip_date,t.trip_end_date,t.origin,t.destination,t.purpose,t.distance_km,t.vehicle_id,t.fuel_purchase_id,v.normalized_consumption_l_100km,r.id rate_id,r.base_rate_per_km,r.average_fuel_price_per_liter,f.price_per_liter receipt_price FROM trips t JOIN vehicles v ON v.id=t.vehicle_id LEFT JOIN travel_rates r ON r.id=(SELECT rr.id FROM travel_rates rr WHERE rr.deleted_at IS NULL AND rr.vehicle_type='passenger_car' AND rr.fuel_type=v.fuel_type AND t.trip_date BETWEEN rr.valid_from AND rr.valid_to ORDER BY rr.valid_from DESC,rr.id DESC LIMIT 1) LEFT JOIN fuel_purchases f ON f.id=t.fuel_purchase_id AND f.vehicle_id=t.vehicle_id AND f.purchase_date<=t.trip_end_date AND f.deleted_at IS NULL WHERE t.deleted_at IS NULL AND t.trip_date>=%s AND t.trip_date<%s"

def km_celkem(od,do):
 """Součet km jízd v rozsahu dat (od včetně, do bez). Sčítá Python s Decimal – v SQLite jsou km uložené jako celé desetiny."""
 return sum((r['distance_km'] for r in query("SELECT distance_km FROM trips WHERE deleted_at IS NULL AND trip_date>=%s AND trip_date<%s",(od,do))),Decimal('0.0'))

def item_descriptions(rows):
 """Popisy položek dokladu spojené „ · “ (podle id) do row['item_descriptions'] – dřív GROUP_CONCAT v SQL, teď v Pythonu (MySQL i SQLite)."""
 ids=sorted({r['document_id'] for r in rows if r.get('document_id')})
 texts={}
 if ids:
  for i in query('SELECT document_id,description FROM document_items WHERE deleted_at IS NULL AND document_id IN ('+','.join(['%s']*len(ids))+') ORDER BY id',tuple(ids)):
   if i['description'] is not None:texts.setdefault(i['document_id'],[]).append(i['description'])
 for r in rows:
  r['item_descriptions']=' · '.join(texts[r['document_id']]) if r.get('document_id') in texts else None
 return rows

def derived_trip_expenses(year, ids=None):
 if ids is not None and not ids: return []
 sql=TRIP_EXPENSES_SQL
 params=rok(year)
 if ids is not None:
  sql+=" AND t.id IN ("+",".join(["%s"]*len(ids))+")"; params+=tuple(ids)
 rows=query(sql+" ORDER BY t.trip_date DESC,t.id DESC",params)
 result=[]
 for row in rows:
  cost=calculate_trip_cost(row['distance_km'],row['normalized_consumption_l_100km'],row['base_rate_per_km'],row['average_fuel_price_per_liter'],row['receipt_price'])
  if not cost: continue
  result.append({'id':row['id'],'payment_date':row['trip_date'],'counterparty_name':None,'system_type':'trip','description':f"{row['origin']} → {row['destination']} · {row['purpose']}",'amount':cost['total'],'method':None,'attachment_id':None,'source_kind':'trip'})
 return result

def receipt_document(upload, issue_date, amount, note=None):
 if not upload or not upload.filename: return None
 if upload.mimetype not in ALLOWED: raise ValueError('Povolený je pouze PDF, JPG nebo PNG.')
 ext=Path(secure_filename(upload.filename)).suffix.lower()
 if ext not in {'.pdf','.jpg','.jpeg','.png'}: raise ValueError('Neplatná přípona souboru.')
 ident=execute("INSERT INTO documents (document_type,issue_date,gross_total,source,note) VALUES ('receipt',%s,%s,'manual',%s)",(issue_date,amount,note))
 attachment_file(ident,upload)
 audit('document',ident,'insert',new=query('SELECT * FROM documents WHERE id=%s',(ident,),one=True))
 return ident

def attachment_file(document_id, upload):
 if not upload or not upload.filename: return None
 if upload.mimetype not in ALLOWED: raise ValueError('Povolený je pouze PDF, JPG nebo PNG.')
 ext=Path(secure_filename(upload.filename)).suffix.lower()
 if ext not in {'.pdf','.jpg','.jpeg','.png'}: raise ValueError('Neplatná přípona souboru.')
 target=Path(current_app.config['UPLOAD_FOLDER'])/f'{uuid.uuid4().hex}{ext}'; upload.save(target)
 digest=hashlib.sha256(target.read_bytes()).hexdigest()
 duplicate=query('SELECT id FROM attachments WHERE document_id=%s AND sha256=%s AND deleted_at IS NULL LIMIT 1',(document_id,digest),one=True)
 if duplicate:
  target.unlink(missing_ok=True); return duplicate['id']
 attachment=execute('INSERT INTO attachments (document_id,original_filename,stored_filename,mime_type,sha256) VALUES (%s,%s,%s,%s,%s)',(document_id,secure_filename(upload.filename),target.name,upload.mimetype,digest))
 audit('attachment',attachment,'insert',new={'document_id':document_id,'stored_filename':target.name})
 return attachment

def current_attachment(document_id):
 if not document_id: return None
 return query('SELECT id,document_id,original_filename,stored_filename,mime_type FROM attachments WHERE document_id=%s AND deleted_at IS NULL ORDER BY id DESC LIMIT 1',(document_id,),one=True)

def supplier_attachment(counterparty_id):
 return query("SELECT a.id,a.document_id,a.original_filename,a.stored_filename,a.mime_type FROM payments p JOIN attachments a ON a.document_id=p.document_id AND a.deleted_at IS NULL WHERE p.counterparty_id=%s AND p.direction='expense' AND p.deleted_at IS NULL ORDER BY p.payment_date DESC,p.id DESC,a.id DESC LIMIT 1",(counterparty_id,),one=True)

def stage_payment_upload(upload):
 if not isinstance(upload,FileStorage) or not upload.filename: return None
 original=secure_filename(upload.filename)
 ext=Path(original).suffix.lower()
 allowed_ext={'.pdf':'application/pdf','.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png'}
 if ext not in allowed_ext: raise ValueError('Povolený je pouze PDF, JPG nebo PNG.')
 target=Path(current_app.config['UPLOAD_FOLDER'])/f'{uuid.uuid4().hex}{ext}'
 try:
  upload.save(target)
  head=target.read_bytes()[:12]
  detected='application/pdf' if head.startswith(b'%PDF') else ('image/jpeg' if head.startswith(b'\xff\xd8\xff') else ('image/png' if head.startswith(b'\x89PNG\r\n\x1a\n') else None))
  if detected != allowed_ext[ext]: raise ValueError('Obsah souboru neodpovídá typu PDF/JPG/PNG.')
  return {'path':target,'stored_filename':target.name,'original_filename':original,'mime_type':detected,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
 except Exception:
  target.unlink(missing_ok=True)
  raise

def cursor_audit(cur,entity,ident,action,old=None,new=None):
 cur.execute('INSERT INTO audit_log (entity_type,entity_id,action,old_data,new_data) VALUES (%s,%s,%s,%s,%s)',(entity,ident,action,json.dumps(old,default=str) if old is not None else None,json.dumps(new,default=str) if new is not None else None))

def persist_manual_payment(cur,form,direction,ident,staged):
 old=None
 if ident:
  cur.execute('SELECT * FROM payments WHERE id=%s AND direction=%s FOR UPDATE',(ident,direction)); old=cur.fetchone()
  if not old: raise ValueError('Platba nebyla nalezena.')
 if direction=='expense':
  tax_ratio=expense_tax.resolve_submission({'tax_mode':form.tax_mode.data,'tax_pct':form.tax_pct.data or ''})
  stored_tax_mode='category' if old and old.get('tax_mode')=='category' and old.get('tax_deductible_pct')==tax_ratio else 'custom'   # vede se jen procento (tax_deductible_pct, 2 des. místa); 100 % a 50 % jsou jen rychlá volba
 role='supplier' if direction=='expense' else 'customer'; name=' '.join((form.counterparty_name.data or '').split())
 if not name: raise ValueError('Vyplňte dodavatele.' if role=='supplier' else 'Vyplňte odběratele.')
 cp=int(form.counterparty_id.data) if str(form.counterparty_id.data or '').isdigit() else None
 if cp:
  cur.execute("SELECT id,name FROM counterparties WHERE id=%s AND source='manual' AND role IN (%s,'both') AND deleted_at IS NULL FOR UPDATE",(cp,role)); selected=cur.fetchone()
  if not selected or selected['name'].casefold()!=name.casefold(): cp=None
 if not cp:
  cur.execute("SELECT id,role FROM counterparties WHERE source='manual' AND role<>'fuel_station' AND LOWER(name)=LOWER(%s) AND deleted_at IS NULL ORDER BY id LIMIT 1 FOR UPDATE",(name,)); duplicate=cur.fetchone()
  if duplicate and duplicate['role'] not in (role,'both'):
   cur.execute("UPDATE counterparties SET role='both' WHERE id=%s",(duplicate['id'],))
  if duplicate: cp=duplicate['id']
  else:
   cur.execute("INSERT INTO counterparties (name,source,role) VALUES (%s,'manual',%s)",(name,role)); cp=cur.lastrowid
   cursor_audit(cur,'counterparty',cp,'insert',new={'name':name,'source':'manual','role':role})
 doc_id=old.get('document_id') if old else None
 attachment_id=None; old_files=[]
 if staged:
  if not doc_id:
   cur.execute("INSERT INTO documents (document_type,counterparty_id,issue_date,gross_total,source,note) VALUES ('receipt',%s,%s,%s,'manual',%s)",(cp,form.payment_date.data,form.amount.data,val(form.note.data)))
   doc_id=cur.lastrowid
   cursor_audit(cur,'document',doc_id,'insert',new={'document_type':'receipt','counterparty_id':cp,'issue_date':form.payment_date.data,'gross_total':form.amount.data,'source':'manual','note':val(form.note.data)})
  else:
   cur.execute('SELECT id FROM documents WHERE id=%s FOR UPDATE',(doc_id,))
   if not cur.fetchone(): raise ValueError('Navázaný doklad nebyl nalezen.')
  cur.execute('SELECT * FROM attachments WHERE document_id=%s AND deleted_at IS NULL ORDER BY id DESC FOR UPDATE',(doc_id,)); attachments=cur.fetchall()
  if attachments:
   current=attachments[0]; attachment_id=current['id']; old_files.append(current['stored_filename'])
   cur.execute('UPDATE attachments SET original_filename=%s,stored_filename=%s,mime_type=%s,sha256=%s,deleted_at=NULL WHERE id=%s',(staged['original_filename'],staged['stored_filename'],staged['mime_type'],staged['sha256'],attachment_id))
   cursor_audit(cur,'attachment',attachment_id,'update',current,{'document_id':doc_id,'original_filename':staged['original_filename'],'stored_filename':staged['stored_filename'],'mime_type':staged['mime_type'],'sha256':staged['sha256'],'deleted_at':None})
   for extra in attachments[1:]:
    old_files.append(extra['stored_filename']); cur.execute('UPDATE attachments SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s',(extra['id'],)); cursor_audit(cur,'attachment',extra['id'],'cancel',extra,{'deleted_at':'CURRENT_TIMESTAMP'})
  else:
   cur.execute('INSERT INTO attachments (document_id,original_filename,stored_filename,mime_type,sha256) VALUES (%s,%s,%s,%s,%s)',(doc_id,staged['original_filename'],staged['stored_filename'],staged['mime_type'],staged['sha256'])); attachment_id=cur.lastrowid
   cursor_audit(cur,'attachment',attachment_id,'insert',new={'document_id':doc_id,'original_filename':staged['original_filename'],'stored_filename':staged['stored_filename'],'mime_type':staged['mime_type'],'sha256':staged['sha256']})
 event_id=old.get('event_id') if old else None
 values=(doc_id,event_id,cp,old.get('category_id') if old else None,form.payment_date.data,direction,(old.get('method') if old else None),form.amount.data,val(form.description.data),(old.get('note') if old and 'note' not in request.form else val(form.note.data)))
 if ident:
  cur.execute('UPDATE payments SET document_id=%s,event_id=%s,counterparty_id=%s,category_id=%s,payment_date=%s,direction=%s,method=%s,amount=%s,description=%s,note=%s WHERE id=%s',values+(ident,))
 else:
  cur.execute('INSERT INTO payments (document_id,event_id,counterparty_id,category_id,payment_date,direction,method,amount,description,note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',values); ident=cur.lastrowid
 if not old:cur.execute('UPDATE payments SET system_type=%s WHERE id=%s',(direction,ident))
 if direction=='expense':
  cur.execute('UPDATE payments SET tax_mode=%s,tax_deductible_pct=%s WHERE id=%s',(stored_tax_mode,tax_ratio,ident))
 cur.execute('SELECT * FROM payments WHERE id=%s',(ident,));cursor_audit(cur,'payment',ident,'update' if old else 'insert',old,cur.fetchone())
 if staged:
  cur.execute('SELECT p.document_id,d.id document_exists,a.id attachment_id,a.stored_filename FROM payments p JOIN documents d ON d.id=p.document_id JOIN attachments a ON a.document_id=d.id AND a.deleted_at IS NULL WHERE p.id=%s AND a.id=%s',(ident,attachment_id)); invariant=cur.fetchone()
  if not invariant or invariant['stored_filename']!=staged['stored_filename'] or not staged['path'].is_file(): raise RuntimeError('Doklad se nepodařilo bezpečně uložit.')
 return {'payment_id':ident,'document_id':doc_id,'attachment_id':attachment_id,'old_files':old_files}

def save_manual_payment(form,direction,ident=None):
 staged=stage_payment_upload(form.upload.data)
 conn=connection()
 try:
  with conn.cursor() as cur: result=persist_manual_payment(cur,form,direction,ident,staged)
  conn.commit()
 except Exception:
  conn.rollback()
  if staged: staged['path'].unlink(missing_ok=True)
  raise
 finally: conn.close()
 if staged:
  folder=Path(current_app.config['UPLOAD_FOLDER']).resolve()
  for filename in result['old_files']:
   safe=secure_filename(filename)
   if safe and safe==filename:
    path=(folder/safe).resolve()
    if path.parent==folder and path!=staged['path'].resolve(): path.unlink(missing_ok=True)
 return result

@bp.route('/')
@login_required
def dashboard():
 y=cas.today().year; start=f'{y}-01-01'; end=f'{y+1}-01-01'
 from .annual import year_report
 *_,report=year_report(y)
 tax_fields={f['field_key']:f for section in report['sections'] if section['key']=='tax' for f in section['fields']}
 income=tax_fields['income']['value'];expense=tax_fields['expenses']['value'];balance=tax_fields['result']['value']
 # Bez daňového výsledku (chybí nastavení) ukáže Přehled předběžné součty evidence (nová instalace 0,00 Kč) a výzvy s odkazem.
 predbezne=expense is None
 if predbezne:
  expense=(report.get('expense_summary') or {}).get('recorded') or Decimal(0);balance=(income or Decimal(0))-expense
 vyzvy=dashboard_prompts(report,y)
 total_km=km_celkem(start,end)
 recent=[]
 names=system_types.labels()   # štítky i náhradní popisy jen z Nastavení → Názvy typů
 from . import moduly
 # Posledních 5 položek: záznamy vypnutého modulu se neukazují vůbec (bez ohledu na volbu výpočtů), místo nich další položky.
 doprava=moduly.zapnuto('doprava');bez_stazenych=moduly.skryt_platby_sql()
 for row in query("SELECT p.id,p.system_type,p.payment_date,p.direction,p.description,p.amount,d.source document_source,s.id income_source_id,s.name income_source_name,(SELECT a.id FROM attachments a WHERE a.document_id=p.document_id AND a.deleted_at IS NULL ORDER BY a.id DESC LIMIT 1) attachment_id FROM payments p LEFT JOIN documents d ON d.id=p.document_id LEFT JOIN income_source_records r ON r.document_id=p.document_id LEFT JOIN income_sources s ON s.id=r.source_id WHERE p.deleted_at IS NULL AND p.fuel_purchase_id IS NULL"+bez_stazenych+" ORDER BY p.payment_date DESC,p.id DESC LIMIT 20"):
  kind=system_types.payment_kind(row)
  if row['direction']=='income' and (row.get('income_source_id') or row.get('document_source') not in (None,'manual')):kind='income_connector'
  source_label=row.get('income_source_name') if row['direction']=='income' and kind=='income_connector' else None
  recent.append({'sort_date':row['payment_date'],'id':row['id'],'date':row['payment_date'],'kind':kind,'source_label':source_label,'description':row['description'] or names.get(kind,names[row['direction']]),'metric_kind':'amount','metric':row['amount'],'href':('/payments/income/%s' if row['direction']=='income' else '/payments/expense/%s') % row['id']})
  # importovaný příjem nejde ručně upravit → klik otevře jeho PDF (když je), podle typu, ne podle názvu zdroje.
  if kind=='income_connector':recent[-1]['href']='/attachments/%s/view' % row['attachment_id'] if row.get('attachment_id') else None
 for row in ([] if not doprava else query("SELECT f.id,f.purchase_date,f.station,f.total_amount FROM fuel_purchases f WHERE f.deleted_at IS NULL ORDER BY f.purchase_date DESC,f.id DESC LIMIT 20")):
  recent.append({'sort_date':row['purchase_date'],'id':row['id'],'date':row['purchase_date'],'kind':'fuel','description':row['station'] or names['fuel'],'metric_kind':'amount','metric':row['total_amount'],'href':'/fuel/%s/edit' % row['id']})
 for row in ([] if not doprava else query("SELECT t.id,t.trip_date,t.trip_end_date,t.origin,t.destination,t.distance_km FROM trips t WHERE t.deleted_at IS NULL ORDER BY t.trip_date DESC,t.id DESC LIMIT 20")):
  recent.append({'sort_date':row['trip_date'],'id':row['id'],'date':row['trip_date'],'kind':'trip','description':'%s – %s' % (row['origin'],row['destination']),'metric_kind':'km','metric':row['distance_km'],'href':'/trips/%s/edit' % row['id']})
 # názvy typů z Nastavení platí i pro ruční příjem ; importovaný příjem ukazuje název zdroje.
 for item in recent:item['kind_label']=item.get('source_label') or names[item['kind']]
 recent=sorted(recent,key=lambda item:(str(item['sort_date']),item['id']),reverse=True)[:5]
 return render_template('dashboard.html',year=y,predbezne=predbezne,vyzvy=vyzvy,nezapocteno=report.get('nezapocteno'),income=income,expense=expense,balance=balance,total_km=total_km,recent_items=recent,wc_sync_ready=wc_sync_ready())

PROFIL_ODKAZY={'identity':'overview','business':'business','employment':'employment','social':'social','health':'health','tax':'tax','vehicles':'vehicle'}
PROFIL_NAZVY={'identity':'Identifikace','business':'Podnikání','employment':'Zaměstnání','social':'ČSSZ','health':'Zdravotní pojištění','tax':'Daně','vehicles':'Vozidla'}
def dashboard_prompts(report,year):
 """Srozumitelné výzvy pro Přehled: co chybí a odkaz přímo na příslušnou část Profilu OSVČ (nejvýš 4)."""
 from .annual import PRAVIDLA_CHYBI
 vyzvy=[] if report.get('rules') or 'rules' not in report else [{'text':PRAVIDLA_CHYBI.format(year),'odkaz':None}]
 for key,items in (report.get('missing') or {}).items():
  for item in items:
   vyzvy.append({'text':PROFIL_NAZVY.get(key,key)+': '+item.rstrip('.'),'odkaz':url_for('main.settings')+'#profile-'+PROFIL_ODKAZY.get(key,'overview')})
 return vyzvy[:4]

@bp.route('/payments/<direction>',methods=['GET','POST'])
@bp.route('/payments/<direction>/<int:ident>',methods=['GET','POST'])
@login_required
def payments(direction,ident=None):
 if direction not in ('income','expense'): abort(404)
 if request.method=='GET' and 'tax_status' in request.args:
  return redirect(url_for('main.payments',direction=direction,ident=ident,year=request.args.get('year')))
 form=ManualExpenseForm() if direction=='expense' else PaymentForm()
 form.counterparty_name.label.text=('Odběratel' if direction=='income' else 'Dodavatel')
 form.description.label.text='Popis'
 form.upload.label.text='Doklad (PDF/JPG/PNG)'
 form.payment_date.label.text=('Datum přijetí' if direction=='income' else 'Datum')
 payment_choices(form,direction)
 existing=query('SELECT p.*, d.number, c.name counterparty_name FROM payments p LEFT JOIN documents d ON d.id=p.document_id LEFT JOIN counterparties c ON c.id=p.counterparty_id WHERE p.id=%s AND p.direction=%s',(ident,direction),True) if ident else None
 if ident and not existing: abort(404)
 if existing and existing.get('system_type')=='income_connector':abort(409,description='Příjem spravuje jeho externí zdroj.')
 if direction=='expense' and ident and existing and existing.get('fuel_purchase_id'): return redirect(url_for('main.fuels',ident=existing['fuel_purchase_id']))
 if request.method=='GET' and existing: form.process(data=existing); form.counterparty_name.data=existing.get('counterparty_name') or ''; form.counterparty_id.data=str(existing.get('counterparty_id') or '')
 if direction=='expense' and request.method=='GET' and existing:
  pct=existing.get('tax_deductible_pct')
  form.tax_mode.data='100' if pct is None or pct==100 else '50' if pct==50 else 'custom'   # nabídka 100 % / 50 % / Vlastní…; 0 % a ostatní = vlastní
  form.tax_pct.data=str(pct) if form.tax_mode.data=='custom' else ''
 if form.validate_on_submit():
  draft_key=f'{direction}-{ident}' if ident else direction
  try: result=save_manual_payment(form,direction,ident)
  except ValueError as exc:
   if direction=='expense': form.tax_mode.errors=list(form.tax_mode.errors)+[str(exc)]
   else: flash(str(exc),'error')
  except Exception: flash('Doklad ani změny se nepodařilo uložit. Zkuste to znovu.','error'); return redirect(request.url)
  else:
   ident=result['payment_id']; flash('Platba upravena.' if existing else 'Platba vytvořena.','success')
   return redirect(url_for('main.payments',direction=direction,year=form.payment_date.data.year,draft_saved=draft_key))
 year=request.args.get('year',str(cas.today().year)); attachment_select="(SELECT a.id FROM attachments a WHERE a.document_id=d.id AND a.deleted_at IS NULL ORDER BY a.id DESC LIMIT 1) attachment_id,(SELECT a.mime_type FROM attachments a WHERE a.document_id=d.id AND a.deleted_at IS NULL ORDER BY a.id DESC LIMIT 1) attachment_mime"; select=f"p.*,d.number,d.source,d.note,d.document_type,{attachment_select},c.name counterparty_name"
 joins=' LEFT JOIN counterparties c ON c.id=p.counterparty_id'
 payment_where="p.direction=%s AND p.deleted_at IS NULL AND p.payment_date>=%s AND p.payment_date<%s"
 if direction=='expense': payment_where+=" AND p.fuel_purchase_id IS NULL"
 from . import moduly
 payment_where+=moduly.skryt_platby_sql()   # vypnutý modul: jeho záznamy se v seznamu neukazují
 payment_sql=f"SELECT {select} FROM payments p LEFT JOIN documents d ON d.id=p.document_id{joins} WHERE {payment_where}"
 if direction=='income':
  rows,pager=paginate(payment_sql+" ORDER BY p.payment_date DESC,p.id DESC",(direction,*rok(year)),count_sql="SELECT COUNT(*) total FROM payments p WHERE "+payment_where)
  item_descriptions(rows)
  origins={r['document_id']:r for r in query('SELECT r.document_id,s.name,s.id FROM income_source_records r JOIN income_sources s ON s.id=r.source_id WHERE r.document_id IN ('+','.join(['%s']*len(rows))+')',tuple(r.get('document_id') for r in rows))} if rows else {}
  for row in rows:
   row['source_kind']='payment'
   origin=origins.get(row.get('document_id'))
   row['income_source_id']=origin['id'] if origin else None
   row['income_source_name']=origin['name'] if origin else system_types.labels()['income']
 else:
  tax_rows=expense_tax.rows(year)
  missing_ids=[r['id'] for r in tax_rows if r['tax']['state']=='pending']
  # Page the combined keys before loading details; preserve payment-first ties.
  eligible=TRIP_EXPENSES_SQL+" AND t.distance_km IS NOT NULL AND v.normalized_consumption_l_100km IS NOT NULL AND r.base_rate_per_km IS NOT NULL AND r.average_fuel_price_per_liter IS NOT NULL"
  key_sql="SELECT p.id,p.payment_date,0 source_rank FROM payments p WHERE "+payment_where
  key_args=(direction,*rok(year))
  if moduly.zapnuto('doprava'):key_sql+=" UNION ALL SELECT t.id,t.trip_date payment_date,1 source_rank FROM ("+eligible+") t";key_args+=rok(year)
  keys,pager=paginate("SELECT * FROM ("+key_sql+") k ORDER BY payment_date DESC,id DESC,source_rank ASC",key_args)
  payment_ids=[k['id'] for k in keys if k['source_rank']==0]
  trip_ids=[k['id'] for k in keys if k['source_rank']==1]
  rows=query(payment_sql+" AND p.id IN ("+','.join(['%s']*len(payment_ids))+")",(direction,*rok(year),*payment_ids)) if payment_ids else []
  item_descriptions(rows)
  for row in rows: row['source_kind']='payment';row['tax_missing']=row['id'] in missing_ids
  rows+=derived_trip_expenses(year,trip_ids)
  rows.sort(key=lambda row:(row['payment_date'],row['id']),reverse=True)
 # součet za vybraný rok – stejné záznamy jako seznam (výdaje: nákupy + jízdy, bez tankování)
 # sčítá se v Pythonu: v SQLite jsou částky celá čísla převedená na Decimal až podle typu sloupce (SUM by vrátil haléře)
 soucet=sum((Decimal(r['amount']) for r in query("SELECT p.amount FROM payments p WHERE "+payment_where,(direction,*rok(year))) if r['amount'] is not None),Decimal(0))
 if direction=='expense' and moduly.zapnuto('doprava'): soucet+=sum((Decimal(r['amount']) for r in derived_trip_expenses(year)),Decimal(0))
 from .db import roky_zaznamu
 zdroje=[('payments','payment_date','direction=%s AND deleted_at IS NULL',(direction,))]
 if direction=='expense' and moduly.zapnuto('doprava'): zdroje+=[('trips','trip_date','deleted_at IS NULL',()),('fuel_purchases','purchase_date','deleted_at IS NULL',())]
 years=roky_zaznamu(zdroje,(cas.today().year,year))
 return render_template('payments.html' if direction=='income' else 'payments_expense.html',soucet=soucet,years=years,form=form,rows=rows,pager=pager,type_labels=system_types.labels(),missing_count=len(missing_ids) if direction=='expense' else 0,existing=existing,direction=direction,year=year,editing=bool(ident),draft_key=f'{direction}-{ident}' if ident else direction,wc_configured=wc_configured(),wc_sync_ready=wc_sync_ready(),last_sync=last_sync(),current_attachment=current_attachment(existing.get('document_id')) if existing else None)

# Synchronizace zdroje příjmů: /settings/income-sources/<id>/sync.

@bp.route('/expense/new', methods=['GET','POST'])
@login_required
def new_expense():
 return payments('expense')
@bp.post('/payments/<direction>/<int:ident>/cancel')
@login_required
def cancel_payment(direction,ident):
 from . import moduly
 if not moduly.zapnuto('externi_web') and query('SELECT 1 FROM payments p JOIN income_source_records r ON r.document_id=p.document_id WHERE p.id=%s LIMIT 1',(ident,),True):
  flash('Stažený příjem jde smazat jen se zapnutým modulem Externí web (Nastavení → Moduly).','error'); return redirect(url_for('main.payments',direction=direction))
 if not moduly.zapnuto('doprava') and query('SELECT 1 FROM payments WHERE id=%s AND fuel_purchase_id IS NOT NULL',(ident,),True):
  flash('Tankování jde smazat jen se zapnutým modulem Doprava (Nastavení → Moduly).','error'); return redirect(url_for('main.payments',direction=direction))
 old=query('SELECT * FROM payments WHERE id=%s',(ident,),True); execute('UPDATE payments SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL',(ident,)); new=query('SELECT * FROM payments WHERE id=%s',(ident,),True); audit('payment',ident,'cancel',old,new); flash('Platba zrušena.','success'); return redirect(url_for('main.payments',direction=direction))


# Stránky jsou rozdělené po oblastech. Moduly níže registrují stránky na tentýž blueprint 'main' (url_for('main.…')). Import až na konci – moduly berou pomocné funkce odsud.
from . import events_routes  # noqa: E402,F401  Akce
from . import system_routes  # noqa: E402,F401  Přihlášení, odhlášení, napájení
from . import address_routes  # noqa: E402,F401  Adresář (dodavatelé, odběratelé, benzinky; ověření v ARES)
from . import settings_routes  # noqa: E402,F401  Nastavení (stránka, vozidla, názvy typů, vzhled)
from . import documents_routes  # noqa: E402,F401  Doklady a přílohy (/documents, /uploads, /attachments)
from . import trips_fuel_routes  # noqa: E402,F401  Jízdy a PHM (/trips, /fuel, výpočet nákladu cesty, ověření benzinky)
