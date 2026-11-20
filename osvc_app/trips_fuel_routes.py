"""Jízdy a PHM (/trips, /fuel, výpočet nákladu cesty, ověření benzinky).
Stránky jsou na blueprintu 'main' z routes.py, takže URL a názvy endpointů (url_for('main.…')) zůstávají."""
from datetime import date
from decimal import Decimal
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.datastructures import FileStorage
from . import cas
from .ares import AresUnavailable, verify_supplier
from .db import execute, query, rok
from .forms import FuelForm, TripForm
from .pagination import paginate
from .routes import bp, km_celkem, attachment_file, audit, current_attachment, login_required, receipt_document, set_trip_fuel_choices, statutory_fuel_label, trip_calculation, trip_fuel_label, trip_fuels_for_picker, trip_interval_conflict, trip_rate, trip_snapshot_calculation, val, vehicles


def simple_crud(kind,formcls,table,datefield):
 ident=request.view_args.get('ident'); form=formcls()
 vehicles(form)
 if len(form.vehicle_id.choices)==2 and not ident: form.vehicle_id.data=form.vehicle_id.choices[1][0]
 existing=query(f'SELECT * FROM {table} WHERE id=%s',(ident,),True) if ident else None
 if ident and not existing: abort(404)
 if existing and existing.get('system_type')=='income_connector':abort(409,description='Příjem spravuje jeho externí zdroj.')
 if request.method=='GET' and existing: form.process(data=existing)
 vehicle_id=form.vehicle_id.data
 trip_date=form.trip_date.data or cas.today()
 trip_end_date=form.trip_end_date.data or trip_date
 set_trip_fuel_choices(form,vehicle_id,trip_date,trip_end_date,existing.get('fuel_purchase_id') if existing else None)
 valid_fuel_ids={choice[0] for choice in form.fuel_purchase_id.choices}
 if form.fuel_purchase_id.data not in valid_fuel_ids:
  form.fuel_purchase_id.data=0
  if request.method=='POST': form.fuel_purchase_id.raw_data=['0']
 if form.validate_on_submit():
  end_date=form.trip_end_date.data or form.trip_date.data
  if end_date<form.trip_date.data:
   form.trip_end_date.errors.append('Datum ukončení nesmí být před datem začátku.')
   y=request.args.get('year',str(cas.today().year)); rows,pager=paginate(f"SELECT x.*,v.name vehicle FROM {table} x JOIN vehicles v ON v.id=x.vehicle_id WHERE x.deleted_at IS NULL AND x.{datefield}>=%s AND x.{datefield}<%s ORDER BY x.{datefield} DESC,x.id DESC",rok(y)); total=km_celkem(*rok(y))
   from .db import roky_zaznamu
   years=roky_zaznamu([(table,datefield,'deleted_at IS NULL',())],(cas.today().year,y))
   return render_template('records.html',years=years,form=form,rows=rows,pager=pager,kind=kind,year=y,total=total,editing=bool(ident),draft_key=f'trip-{ident}' if ident else 'trip-new',trip_cost_ready=True,initial_cost=None,vehicle_needs_consumption=False,selected_vehicle_id=form.vehicle_id.data)
  conflict=trip_interval_conflict(form.trip_date.data,end_date,ident)
  if conflict:
   flash(conflict,'error')
   target=url_for('main.trips',ident=ident) if ident else url_for('main.trips')
   return redirect(target)
  form.trip_end_date.data=end_date
  fields=['trip_date','trip_end_date','vehicle_id','origin','destination','purpose','distance_km','note']
  values=[val(getattr(form,f).data) for f in fields]
  distance_index=6
  calculation=trip_calculation(form.vehicle_id.data,form.trip_date.data,values[distance_index],form.fuel_purchase_id.data or 0,end_date)
  fields += ['fuel_purchase_id','fuel_price_source','travel_rate_id','calculation_consumption_l_100km','calculation_base_rate_per_km','calculation_fuel_price_per_liter','base_compensation','fuel_compensation','travel_cost_total']
  if calculation.get('total') is not None:
   values += [calculation['fuel_purchase_id'],calculation['fuel_price_source'],calculation['rate_id'],calculation['consumption'],calculation['base_rate'],calculation['fuel_price'],calculation['base'],calculation['fuel'],calculation['total']]
  else: values += [val(form.fuel_purchase_id.data),None,None,None,None,None,None,None,None]
  draft_key=f'trip-{ident}' if ident else 'trip-new'
  if ident:
   old=existing; execute(f"UPDATE {table} SET "+','.join(f'{f}=%s' for f in fields)+' WHERE id=%s',tuple(values+[ident])); audit('trip',ident,'update',old,query(f'SELECT * FROM {table} WHERE id=%s',(ident,),one=True))
  else:
   ident=execute(f"INSERT INTO {table} ("+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(values)); audit('trip',ident,'insert',new=query(f'SELECT * FROM {table} WHERE id=%s',(ident,),one=True))
  flash('Jízda uložena.','success'); return redirect(url_for('main.trips',draft_saved=draft_key))
 y=request.args.get('year',str(cas.today().year)); rows,pager=paginate(f"SELECT x.*,v.name vehicle FROM {table} x JOIN vehicles v ON v.id=x.vehicle_id WHERE x.deleted_at IS NULL AND x.{datefield}>=%s AND x.{datefield}<%s ORDER BY x.{datefield} DESC,x.id DESC",rok(y)); total=km_celkem(*rok(y)) if kind=='trip' else None
 if kind=='trip':
  for row in rows:
   calculated=trip_snapshot_calculation(row)
   if calculated.get('total') is not None: row['travel_cost_total']=calculated['total']
 initial_cost=None
 if existing:
  current=trip_snapshot_calculation(existing)
  if current.get('total') is not None: initial_cost={'calculation_consumption_l_100km':current['consumption'],'calculation_base_rate_per_km':current['base_rate'],'calculation_fuel_price_per_liter':current['fuel_price'],'base_compensation':current['base'],'fuel_compensation':current['fuel'],'travel_cost_total':current['total']}
 selected_vehicle_id=existing.get('vehicle_id') if existing else form.vehicle_id.data
 selected_vehicle=query('SELECT id,normalized_consumption_l_100km FROM vehicles WHERE id=%s',(selected_vehicle_id,),one=True) if selected_vehicle_id else None
 from .db import roky_zaznamu
 return render_template('records.html',years=roky_zaznamu([('trips','trip_date','deleted_at IS NULL',())],(cas.today().year,y)),form=form,rows=rows,pager=pager,kind=kind,year=y,total=total,editing=bool(ident),draft_key=f'trip-{ident}' if ident else 'trip-new',trip_cost_ready=True,initial_cost=initial_cost,vehicle_needs_consumption=bool(selected_vehicle and selected_vehicle['normalized_consumption_l_100km'] is None),selected_vehicle_id=selected_vehicle_id,trip_has_snapshot=bool(existing and initial_cost and current.get('snapshot')))

@bp.get('/trips/cost-preview')
@login_required
def trip_cost_preview():
 vehicle_id=request.args.get('vehicle_id',type=int); trip_date=request.args.get('trip_date'); trip_end_date=request.args.get('trip_end_date') or trip_date; distance=request.args.get('distance_km'); fuel_id=request.args.get('fuel_purchase_id',0,type=int)
 if not vehicle_id or not trip_date:
  return jsonify({'ready':True,'message':'','fuels':[]})
 try: trip_date=date.fromisoformat(trip_date); trip_end_date=date.fromisoformat(trip_end_date)
 except ValueError: return jsonify({'ready':True,'message':'Zadejte platné datum.','fuels':[]})
 if trip_end_date<trip_date: return jsonify({'ready':True,'message':'Datum ukončení nesmí být před datem začátku.','fuels':[]})
 rate=trip_rate(vehicle_id,trip_date)
 fuels=[{'id':f['id'],'label':trip_fuel_label(f)} for f in trip_fuels_for_picker(vehicle_id,trip_end_date,fuel_id)]
 result=trip_calculation(vehicle_id,trip_date,distance,fuel_id,trip_end_date)
 payload={k:(str(v) if isinstance(v,Decimal) else v) for k,v in result.items()}
 payload['fuels']=fuels
 payload['statutory_label']=statutory_fuel_label(rate,trip_date)
 return jsonify(payload)

def fuel_counterparty_choices(form):
 form.counterparty_options=query("SELECT id,name,operator_name,ico FROM counterparties WHERE source='manual' AND role='fuel_station' AND deleted_at IS NULL ORDER BY name")

def resolve_fuel_counterparty(name, selected_id):
 name=' '.join((name or '').split())
 if not name or len(name)>200: raise ValueError('Zadejte název čerpací stanice.')
 selected=query("SELECT id,name FROM counterparties WHERE id=%s AND source='manual' AND role='fuel_station' AND deleted_at IS NULL",(int(selected_id),),one=True) if str(selected_id or '').isdigit() else None
 return selected['id'] if selected and selected['name'].casefold()==name.casefold() else None

def linked_fuel_payment(fuel):
 return query("SELECT * FROM payments WHERE fuel_purchase_id=%s AND direction='expense' ORDER BY id LIMIT 1",(fuel['id'],),one=True)

def sync_fuel_payment(fuel, method=None, creating=False):
 payment=linked_fuel_payment(fuel)
 category=payment.get('category_id') if payment else None  # preserve legacy metadata
 description=f"PHM – {fuel.get('station_name') or fuel.get('station') or 'čerpací stanice'}"
 args=(fuel['document_id'], fuel.get('event_id'), fuel.get('counterparty_id'), category, fuel['purchase_date'], 'expense', (payment.get('method') if payment else None), fuel['total_amount'], description, fuel.get('note'))
 if payment:
  old=payment
  execute('UPDATE payments SET fuel_purchase_id=%s,document_id=%s,event_id=%s,counterparty_id=%s,category_id=%s,payment_date=%s,direction=%s,method=%s,amount=%s,description=%s,note=%s,deleted_at=NULL WHERE id=%s',(fuel['id'],)+args+(payment['id'],))
  new=query('SELECT * FROM payments WHERE id=%s',(payment['id'],),one=True)
  if old != new: audit('payment',payment['id'],'update',old,new)
  return payment['id']
 fields='fuel_purchase_id,system_type,document_id,event_id,counterparty_id,category_id,payment_date,direction,method,amount,description,note'
 values=(fuel['id'],'fuel')+args
 ident=execute(f'INSERT INTO payments ({fields}) VALUES ({",".join(["%s"]*len(values))})',values)
 audit('payment',ident,'insert',new=query('SELECT * FROM payments WHERE id=%s',(ident,),one=True))
 return ident

@bp.route('/fuel',methods=['GET','POST'])
@bp.route('/fuel/<int:ident>/edit',methods=['GET','POST'])
@login_required
def fuels(ident=None):
 form=FuelForm(); vehicles(form)
 fuel_counterparty_choices(form)
 if len(form.vehicle_id.choices)==2 and not ident: form.vehicle_id.data=form.vehicle_id.choices[1][0]
 fuel=query('SELECT f.*,c.name counterparty_name FROM fuel_purchases f LEFT JOIN counterparties c ON c.id=f.counterparty_id WHERE f.id=%s',(ident,),one=True) if ident else None
 if ident and not fuel: abort(404)
 if request.method=='GET' and fuel:
  form.process(data=fuel); form.counterparty_name.data=fuel.get('station_name') or fuel.get('counterparty_name') or fuel.get('station') or ''; form.counterparty_id.data=str(fuel.get('counterparty_id') or '')
 valid=form.validate_on_submit()
 if valid:
  try:
   counterparty_id=resolve_fuel_counterparty(form.counterparty_name.data,form.counterparty_id.data)
   if fuel and form.counterparty_name.data == (fuel.get('station_name') or fuel.get('counterparty_name') or fuel.get('station') or ''):
    counterparty_id=fuel.get('counterparty_id')
  except ValueError as exc:
   flash(str(exc),'error'); return redirect(request.url)
  document_id=fuel.get('document_id') if fuel else None
  if isinstance(form.upload.data, FileStorage) and form.upload.data.filename:
   try:
    if document_id: attachment_file(document_id,form.upload.data)
    else: document_id=receipt_document(form.upload.data,form.purchase_date.data,form.total_amount.data,form.note.data)
   except ValueError as exc: flash(str(exc),'error'); return redirect(request.url)
  station=fuel.get('station') if fuel else None
  station_name=' '.join(form.counterparty_name.data.split())
  fields=['vehicle_id','counterparty_id','event_id','document_id','purchase_date','liters','price_per_liter','total_amount','station','station_name','note']
  event_id=fuel.get('event_id') if fuel else None
  liters=form.liters.data
  if fuel and fuel.get('liters') is not None and fuel.get('price_per_liter')==form.price_per_liter.data and fuel.get('total_amount')==form.total_amount.data: liters=fuel['liters']   # uložené litry beze změny ceny neměnit
  values=[form.vehicle_id.data,counterparty_id,event_id,document_id,form.purchase_date.data,liters,form.price_per_liter.data,form.total_amount.data,station,station_name,(fuel.get('note') if fuel else val(form.note.data))]
  draft_key=f'fuel-{ident}' if ident else 'fuel-new'
  if ident:
   old=fuel; execute('UPDATE fuel_purchases SET '+','.join(f'{f}=%s' for f in fields)+' WHERE id=%s',tuple(values+[ident])); fuel=query('SELECT * FROM fuel_purchases WHERE id=%s',(ident,),one=True); audit('fuel_purchase',ident,'update',old,fuel)
  else:
   ident=execute('INSERT INTO fuel_purchases ('+','.join(fields)+') VALUES ('+','.join(['%s']*len(fields))+')',tuple(values)); fuel=query('SELECT * FROM fuel_purchases WHERE id=%s',(ident,),one=True); audit('fuel_purchase',ident,'insert',new=fuel)
  sync_fuel_payment(fuel)
  flash('PHM uloženo a výdaj aktualizován.','success'); return redirect(url_for('main.fuels',draft_saved=draft_key))
 y=request.args.get('year',str(cas.today().year)); rows,pager=paginate("SELECT f.*,v.name vehicle,c.name counterparty_name,(SELECT a.id FROM attachments a WHERE a.document_id=f.document_id AND a.deleted_at IS NULL ORDER BY a.id DESC LIMIT 1) attachment_id,(SELECT a.mime_type FROM attachments a WHERE a.document_id=f.document_id AND a.deleted_at IS NULL ORDER BY a.id DESC LIMIT 1) attachment_mime FROM fuel_purchases f JOIN vehicles v ON v.id=f.vehicle_id LEFT JOIN counterparties c ON c.id=f.counterparty_id WHERE f.deleted_at IS NULL AND f.purchase_date>=%s AND f.purchase_date<%s ORDER BY f.purchase_date DESC,f.id DESC",rok(y))
 from .db import roky_zaznamu
 from decimal import Decimal   # sčítá se v Pythonu (SQLite: SUM nad převáděným sloupcem by vrátil haléře)
 soucet=sum((Decimal(r['total_amount']) for r in query("SELECT total_amount FROM fuel_purchases WHERE deleted_at IS NULL AND purchase_date>=%s AND purchase_date<%s",rok(y)) if r['total_amount'] is not None),Decimal(0))
 return render_template('records.html',soucet=soucet,years=roky_zaznamu([('fuel_purchases','purchase_date','deleted_at IS NULL',())],(cas.today().year,y)),form=form,rows=rows,pager=pager,kind='fuel',year=y,total=None,editing=bool(ident),draft_key=f'fuel-{ident}' if ident else 'fuel-new',current_attachment=current_attachment(fuel['document_id']) if fuel else None)

@bp.route('/trips',methods=['GET','POST'])
@bp.route('/trips/<int:ident>/edit',methods=['GET','POST'])
@login_required
def trips(ident=None): return simple_crud('trip',TripForm,'trips','trip_date')
@bp.post('/<kind>/<int:ident>/cancel')
@login_required
def cancel_record(kind,ident):
 table={'trip':'trips','fuel':'fuel_purchases'}.get(kind)
 if not table: abort(404)
 if kind=='fuel':
  fuel=query('SELECT * FROM fuel_purchases WHERE id=%s',(ident,),one=True); payment=linked_fuel_payment(fuel) if fuel else None
  execute('UPDATE fuel_purchases SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL',(ident,)); audit('fuel_purchase',ident,'cancel',fuel,query('SELECT * FROM fuel_purchases WHERE id=%s',(ident,),one=True))
  if payment and payment['deleted_at'] is None:
   execute('UPDATE payments SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL',(payment['id'],)); audit('payment',payment['id'],'cancel',payment,query('SELECT * FROM payments WHERE id=%s',(payment['id'],),one=True))
 else:
  old=query(f'SELECT * FROM {table} WHERE id=%s',(ident,),one=True); execute(f'UPDATE {table} SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL',(ident,)); audit(kind,ident,'cancel',old,query(f'SELECT * FROM {table} WHERE id=%s',(ident,),one=True))
 flash('Záznam zrušen.','success'); return redirect(url_for('main.'+('trips' if kind=='trip' else 'fuels')))

@bp.post('/fuel/<int:ident>/restore')
@login_required
def restore_fuel(ident):
 fuel=query('SELECT * FROM fuel_purchases WHERE id=%s',(ident,),one=True)
 if not fuel: abort(404)
 execute('UPDATE fuel_purchases SET deleted_at=NULL WHERE id=%s',(ident,)); audit('fuel_purchase',ident,'restore',fuel,query('SELECT * FROM fuel_purchases WHERE id=%s',(ident,),one=True))
 payment=linked_fuel_payment(fuel)
 if payment:
  execute('UPDATE payments SET deleted_at=NULL WHERE id=%s',(payment['id'],)); audit('payment',payment['id'],'restore',payment,query('SELECT * FROM payments WHERE id=%s',(payment['id'],),one=True))
 return redirect(url_for('main.fuels'))
def operator_candidates_message(count):
 # Czech agreement: 1 možný provozovatel, 2–4 možní provozovatelé, 5+ možných provozovatelů.
 if count==1:return 'Nalezen 1 možný provozovatel'
 if 2<=count<=4:return f'Nalezeni {count} možní provozovatelé'
 return f'Nalezeno {count} možných provozovatelů'

@bp.post('/fuel/verify')
@login_required
def verify_fuel():
 name=' '.join(request.form.get('counterparty_name','').split())
 if not name or len(name)>200:return jsonify(status='warning',message='Zadejte název benzinky.',candidates=[]),400
 # Local identity takes precedence over external name search.
 matches=query("SELECT id,name,operator_name,ico,dic,verified_at FROM counterparties WHERE source='manual' AND role='fuel_station' AND deleted_at IS NULL AND LOWER(name)=LOWER(%s) ORDER BY id",(name,))
 selected=request.form.get('counterparty_id','')
 station=next((row for row in matches if str(row['id'])==selected),None) or (matches[0] if len(matches)==1 else None)
 if station and station.get('operator_name') and station.get('ico'):
  return jsonify(status='success',message='Ověřeno: '+station['operator_name'],station_id=station['id'],candidates=[])
 if station and not station.get('ico'):
  return jsonify(status='warning',message='Benzinka je v adresáři; provozovatel zatím není ověřen.',station_id=station['id'],candidates=[])
 try:
  candidates,_=verify_supplier(station or {'name':name,'ico':None})
  if station and station.get('ico') and len(candidates)==1 and candidates[0]['ico']==station['ico']:
   return jsonify(status='success',message='Ověřeno: '+candidates[0]['name'],station_id=station['id'],candidates=[])
  return jsonify(status='warning',message=(operator_candidates_message(len(candidates)) if candidates else 'Stanice není dosud v adresáři. Provozovatele se nepodařilo jednoznačně ověřit.'),candidates=candidates)
 except AresUnavailable:
  return jsonify(status='danger',message='Registr není dostupný. Název benzinky lze uložit bez ověření.',candidates=[])
