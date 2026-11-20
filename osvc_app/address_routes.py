"""Adresář (dodavatelé, odběratelé, benzinky; ověření v ARES).
Stránky jsou na blueprintu 'main' z routes.py, takže URL a názvy endpointů (url_for('main.…')) zůstávají."""
from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError
from .ares import AresUnavailable, identifiers_from_text, lookup_by_ico, text_from_attachment, verify_supplier
from .db import connection, execute, query
from .pagination import paginate
from .routes import bp, audit, cursor_audit, login_required, supplier_attachment


@bp.get('/settings/address-book')
@bp.get('/address-book')
@login_required
def address_book():
 search=' '.join(request.args.get('q','').split())[:200]
 extra=' AND deleted_at IS NULL'
 params=[]
 if search:
  extra+=' AND (name LIKE %s OR ico LIKE %s OR dic LIKE %s OR street LIKE %s OR city LIKE %s OR postal_code LIKE %s)'; term=f'%{search}%'; params += [term]*6
 fields='id,role,name,operator_name,ico,dic,street,city,postal_code,official_address,country_code,verified_at,verification_source,deleted_at'   # e-mail, telefon a poznámka se nezobrazují (v DB zůstávají)
 groups={}; pagers={}
 for key,roles in [('suppliers',"('supplier','both')"),('customers',"('customer','both')"),('stations',"('fuel_station')")]:
  groups[key],pagers[key]=paginate(f"SELECT {fields} FROM counterparties WHERE source='manual' AND role IN {roles}{extra} ORDER BY name,id",tuple(params),page_parameter=key+'_page',fragment=key)
 # All active contacts for the live suggestions of „Hledat kontakt“ (filtered in the browser by the shared combobox, ui.js).
 contacts=query("SELECT id,role,name,operator_name,ico,city FROM counterparties WHERE source='manual' AND deleted_at IS NULL ORDER BY name,id")
 return render_template('address_book.html',**groups,pagers=pagers,search=search,contacts=contacts)


def ares_contact(ico):
 """Veřejné údaje z ARES pro formulář kontaktu (název, IČO, DIČ, adresa po polích). None = IČO v ARES není."""
 v=lookup_by_ico(ico)
 if not v: return None
 street=' '.join(x for x in [(v.get('street') or v.get('part') or (v.get('city') if v.get('number') else '')), v.get('number')] if x)
 return {'name':v['name'],'ico':v['ico'],'dic':v.get('dic') or '','street':street,'city':v.get('city') or '','postal_code':v.get('zip') or '',
         'country_code':(v.get('country_code') or 'CZ')[:2].upper(),'address':v.get('address') or ''}


@bp.get('/address-book/ares/<ico>')
@login_required
def address_ares(ico):
 digits=''.join(ch for ch in ico if ch.isdigit())
 if len(digits)!=8: return jsonify(ok=False,message='IČO má 8 číslic.'),400
 try: data=ares_contact(digits)
 except AresUnavailable: return jsonify(ok=False,message='ARES teď nejde načíst – zkuste to za chvíli.'),503
 if not data: return jsonify(ok=False,message='IČO v ARES nenalezeno.'),404
 return jsonify(ok=True,contact=data)


def save_contact(item=None):
 """Uloží nový kontakt nebo úpravu z formuláře adresáře. Adresář drží jen veřejné údaje (název, IČO, DIČ, adresa);
 e-mail, telefon a poznámka se neměnívají. ares=fresh → údaje se znovu načtou z ARES a zapíšou jako ověřené,
 ares=keep → ověřené údaje zůstanou, jak jsou; jinak ruční údaje (bez ověření). Vrací (ok, zpráva, id)."""
 f=request.form
 station=(item['role']=='fuel_station') if item else ('fuel_station' in f.getlist('roles') or f.get('role')=='fuel_station')
 if station: role='fuel_station'
 else:
  roles=set(f.getlist('roles')) or ({f.get('role')} if f.get('role') else set())
  roles&={'supplier','customer'}
  if not roles: return False,'Vyberte aspoň jednu roli (Dodavatel nebo Odběratel).',None
  role='both' if len(roles)==2 else next(iter(roles))
 clean=lambda k,n: ' '.join((f.get(k) or '').split())[:n] or None
 ico=''.join(ch for ch in (f.get('ico') or '') if ch.isdigit()) or None
 if ico and len(ico)!=8: return False,'IČO má 8 číslic.',None
 vals={'name':clean('name',200),'dic':clean('dic',30),'street':clean('street',200),'city':clean('city',120),'postal_code':clean('postal_code',20),
       'country_code':(clean('country_code',2) or 'CZ').upper(),'official_address':item.get('official_address') if item else None,
       'operator_name':item.get('operator_name') if item else None}
 verified=False; keep=False
 state=f.get('ares','')
 if state=='fresh' and ico:
  try: data=ares_contact(ico)
  except AresUnavailable: return False,'ARES teď nejde načíst – zkuste uložit znovu za chvíli.',None
  if not data: return False,'IČO v ARES nenalezeno.',None
  if station: vals.update(dic=data['dic'] or None,operator_name=data['name'],official_address=data['address'] or None)
  else: vals.update({k:(data[k] or None) for k in ('name','dic','street','city','postal_code')},country_code=data['country_code'] or 'CZ',official_address=data['address'] or None)
  verified=True
 elif state=='keep' and item and item.get('verified_at') and ico==(item.get('ico') or None):
  keep=True
  if not station: vals.update({k:item.get(k) for k in ('name','dic','street','city','postal_code')},country_code=item.get('country_code') or 'CZ')
  else: vals['dic']=item.get('dic')
 if not vals['name']: return False,'Zadejte název nebo jméno.',None
 if not station:
  dup=query("SELECT id,name,role FROM counterparties WHERE source='manual' AND role<>'fuel_station' AND deleted_at IS NULL AND id<>%s AND (LOWER(name)=LOWER(%s)"+(" OR ico=%s" if ico else "")+") ORDER BY id LIMIT 1",
            (item['id'] if item else 0,vals['name'])+((ico,) if ico else ()),one=True)
  if dup and not item:
   if dup['role'] not in (role,'both'):
    old=query('SELECT * FROM counterparties WHERE id=%s',(dup['id'],),one=True); execute("UPDATE counterparties SET role='both' WHERE id=%s",(dup['id'],)); audit('counterparty',dup['id'],'update',old,query('SELECT * FROM counterparties WHERE id=%s',(dup['id'],),one=True))
   return True,f"{dup['name']} už v adresáři je; použita byla stávající karta.",dup['id']
  if dup: return False,f"Kontakt se stejným názvem nebo IČO už v adresáři je ({dup['name']}).",None
 cols=['name','role','ico','dic','street','city','postal_code','country_code','official_address','operator_name']
 row=[vals['name'],role,ico,vals['dic'],vals['street'],vals['city'],vals['postal_code'],vals['country_code'],vals['official_address'],vals['operator_name']]
 ver_sql=",verified_at=CURRENT_TIMESTAMP,verification_source='ares'" if verified else ("" if keep else ",verified_at=NULL,verification_source=NULL")
 if item:
  execute('UPDATE counterparties SET '+','.join(c+'=%s' for c in cols)+ver_sql+' WHERE id=%s',tuple(row)+(item['id'],))
  audit('counterparty',item['id'],'update',item,query('SELECT * FROM counterparties WHERE id=%s',(item['id'],),one=True)); return True,'Kontakt uložen.',item['id']
 ident=execute('INSERT INTO counterparties ('+','.join(cols)+",source) VALUES ("+','.join(['%s']*len(cols))+",'manual')",tuple(row))
 if verified: execute("UPDATE counterparties SET verified_at=CURRENT_TIMESTAMP,verification_source='ares' WHERE id=%s",(ident,))
 audit('counterparty',ident,'insert',None,query('SELECT * FROM counterparties WHERE id=%s',(ident,),one=True)); return True,'Kontakt byl přidán do adresáře.',ident


def _section(role):
 return 'stations' if role=='fuel_station' else ('customers' if role=='customer' else 'suppliers')


@bp.post('/settings/address-book')
@bp.post('/address-book')
@login_required
def create_address():
 ok,message,ident=save_contact()
 flash(message,'success' if ok else 'error')
 role=query('SELECT role FROM counterparties WHERE id=%s',(ident,),one=True)['role'] if ident else (request.form.getlist('roles') or [request.form.get('role','supplier')])[0]
 return redirect(url_for('main.address_book')+'#'+_section(role))


@bp.get('/address-book/<int:ident>/verify')
@bp.get('/settings/suppliers/<int:ident>/verify')
@login_required
def verify_supplier_view(ident):
 supplier=query("SELECT id,name,ico,dic,official_address FROM counterparties WHERE id=%s AND source='manual' AND deleted_at IS NULL",(ident,),one=True)
 if not supplier: abort(404)
 attachment=supplier_attachment(ident)
 try:
  results,source=verify_supplier(supplier,attachment,current_app.config['UPLOAD_FOLDER'])
  return jsonify(ok=bool(results),supplier={'id':supplier['id'],'name':supplier['name'],'ico':supplier['ico']},results=results,source=source,attachment={'id':attachment['id'],'name':attachment['original_filename'],'mime':attachment['mime_type'],'url':url_for('main.attachment_view',ident=attachment['id'])} if attachment else None,message=None if results else 'Dodavatele se nepodařilo automaticky ověřit.')
 except AresUnavailable:
  return jsonify(ok=False,supplier={'id':supplier['id'],'name':supplier['name'],'ico':supplier['ico']},results=[],attachment={'id':attachment['id'],'name':attachment['original_filename'],'mime':attachment['mime_type'],'url':url_for('main.attachment_view',ident=attachment['id'])} if attachment else None,message='Dodavatele se nepodařilo automaticky ověřit.')

@bp.get('/settings/suppliers/verify-name')
@login_required
def verify_supplier_name():
 name=' '.join(request.args.get('name','').split())
 selected=request.args.get('id','')
 supplier=None; attachment=None
 if selected.isdigit():
  supplier=query("SELECT id,name,ico,dic,official_address FROM counterparties WHERE id=%s AND source='manual' AND role IN ('supplier','both') AND deleted_at IS NULL",(int(selected),),one=True)
  if supplier and supplier['name'].casefold()!=name.casefold(): supplier=None
 if not supplier:
  if not name or len(name)>200: return jsonify(ok=False,message='Nejdříve zadejte dodavatele.'),400
  supplier={'id':None,'name':name,'ico':None,'dic':None,'official_address':None}
 else: attachment=supplier_attachment(supplier['id'])
 try:
  results,source=verify_supplier(supplier,attachment,current_app.config['UPLOAD_FOLDER'])
  return jsonify(ok=bool(results),supplier={'id':supplier['id'],'name':supplier['name'],'ico':supplier['ico']},results=results,source=source,attachment={'id':attachment['id'],'name':attachment['original_filename'],'mime':attachment['mime_type'],'url':url_for('main.attachment_view',ident=attachment['id'])} if attachment else None,message=None if results else 'Dodavatele se nepodařilo automaticky ověřit.')
 except AresUnavailable:
  return jsonify(ok=False,supplier={'id':supplier['id'],'name':supplier['name'],'ico':supplier['ico']},results=[],attachment={'id':attachment['id'],'name':attachment['original_filename'],'mime':attachment['mime_type'],'url':url_for('main.attachment_view',ident=attachment['id'])} if attachment else None,message='Dodavatele se nepodařilo automaticky ověřit.')

@bp.post('/settings/suppliers/verify-name/apply')
@login_required
def apply_supplier_name_verification():
 try: validate_csrf(request.form.get('csrf_token'))
 except ValidationError: abort(400)
 # role: supplier (default, payment forms), customer or fuel_station (Adresář → Hledat kontakt → ARES).
 target=request.form.get('role','supplier')
 if target not in ('supplier','customer','fuel_station'): return jsonify(ok=False,message='Neznámá sekce adresáře.'),400
 ico=''.join(ch for ch in request.form.get('ico','') if ch.isdigit())
 if len(ico)!=8: return jsonify(ok=False,message='Vyberte platný výsledek ARES.'),400
 try: verified=lookup_by_ico(ico)
 except AresUnavailable: return jsonify(ok=False,message='Dodavatele se nepodařilo automaticky ověřit.'),503
 if not verified: return jsonify(ok=False,message='Dodavatele se nepodařilo automaticky ověřit.'),404
 conn=connection()
 try:
  with conn.cursor() as cur:
   if target=='fuel_station':
    # A station is its own record (operator = legal subject); the same operator may run several stations.
    cur.execute("SELECT * FROM counterparties WHERE source='manual' AND role='fuel_station' AND ico=%s AND LOWER(name)=LOWER(%s) AND deleted_at IS NULL ORDER BY id LIMIT 1",(verified['ico'],verified['name'])); updated=cur.fetchone()
    if updated:
     conn.rollback(); return jsonify(ok=True,message='Benzinka už v adresáři je.',role=target,supplier={'id':updated['id'],'name':updated['name'],'ico':updated['ico']})
    cur.execute("INSERT INTO counterparties (name,operator_name,source,role,ico,dic,official_address,verified_at,verification_source) VALUES (%s,%s,'manual','fuel_station',%s,%s,%s,CURRENT_TIMESTAMP,'ares')",(verified['name'],verified['name'],verified['ico'],verified['dic'] or None,verified['address'] or None)); ident=cur.lastrowid
    cur.execute('SELECT * FROM counterparties WHERE id=%s',(ident,)); updated=cur.fetchone(); cursor_audit(cur,'counterparty',ident,'insert',new=updated)
    conn.commit()
    return jsonify(ok=True,message='Benzinka byla přidána do adresáře.',role=target,supplier={'id':updated['id'],'name':updated['name'],'ico':updated['ico']})
   cur.execute("SELECT * FROM counterparties WHERE source='manual' AND role<>'fuel_station' AND ico=%s AND deleted_at IS NULL ORDER BY id LIMIT 1 FOR UPDATE",(verified['ico'],)); supplier=cur.fetchone()
   if supplier:
    role='both' if supplier['role'] not in (target,'both') else supplier['role']
    cur.execute('UPDATE counterparties SET name=%s,role=%s,ico=%s,dic=%s,official_address=%s,verified_at=CURRENT_TIMESTAMP,verification_source=%s WHERE id=%s',(verified['name'],role,verified['ico'],verified['dic'] or None,verified['address'] or None,'ares',supplier['id']))
    cur.execute('SELECT * FROM counterparties WHERE id=%s',(supplier['id'],)); updated=cur.fetchone(); cursor_audit(cur,'counterparty',supplier['id'],'update',supplier,updated)
   else:
    cur.execute("INSERT INTO counterparties (name,source,role,ico,dic,official_address,verified_at,verification_source) VALUES (%s,'manual',%s,%s,%s,%s,CURRENT_TIMESTAMP,'ares')",(verified['name'],target,verified['ico'],verified['dic'] or None,verified['address'] or None)); ident=cur.lastrowid
    cur.execute('SELECT * FROM counterparties WHERE id=%s',(ident,)); updated=cur.fetchone(); cursor_audit(cur,'counterparty',ident,'insert',new=updated)
  conn.commit()
 except Exception:
  conn.rollback(); raise
 finally: conn.close()
 return jsonify(ok=True,message='Ověřené údaje byly použity.',role=target,supplier={'id':updated['id'],'name':updated['name'],'ico':updated['ico']})

@bp.post('/address-book/<int:ident>/verify/apply')
@bp.post('/settings/suppliers/<int:ident>/verify/apply')
@login_required
def apply_supplier_verification(ident):
 ico=''.join(ch for ch in request.form.get('ico','') if ch.isdigit())
 if len(ico)!=8: return jsonify(ok=False,message='Vyberte platný výsledek ARES.'),400
 try: verified=lookup_by_ico(ico)
 except AresUnavailable: return jsonify(ok=False,message='Dodavatele se nepodařilo automaticky ověřit.'),503
 if not verified: return jsonify(ok=False,message='Dodavatele se nepodařilo automaticky ověřit.'),404
 conn=connection()
 try:
  with conn.cursor() as cur:
   cur.execute("SELECT * FROM counterparties WHERE id=%s AND source='manual' AND deleted_at IS NULL FOR UPDATE",(ident,)); old=cur.fetchone()
   if not old: abort(404)
   if old['role']=='fuel_station':
    cur.execute('UPDATE counterparties SET operator_name=%s,ico=%s,dic=%s,official_address=%s,verified_at=CURRENT_TIMESTAMP,verification_source=%s WHERE id=%s',(verified['name'],verified['ico'],verified['dic'] or None,verified['address'] or None,'ares',ident))
    cur.execute('SELECT * FROM counterparties WHERE id=%s',(ident,)); updated=cur.fetchone()
    cursor_audit(cur,'counterparty',ident,'update',old,updated)
    conn.commit()
    return jsonify(ok=True,message='Právní subjekt ověřen. Název a adresa provozovny zůstaly zachovány.',supplier={'id':ident,'name':old['name'],'ico':verified['ico']})
   cur.execute("SELECT * FROM counterparties WHERE id<>%s AND source='manual' AND role<>'fuel_station' AND deleted_at IS NULL AND ico=%s ORDER BY id LIMIT 1 FOR UPDATE",(ident,verified['ico'])); canonical=cur.fetchone()
   if canonical:
    canonical_role='both' if canonical['role'] != old['role'] else canonical['role']
    cur.execute('UPDATE counterparties SET name=%s,role=%s,ico=%s,dic=%s,official_address=%s,verified_at=CURRENT_TIMESTAMP,verification_source=%s WHERE id=%s',(verified['name'],canonical_role,verified['ico'],verified['dic'] or None,verified['address'] or None,'ares',canonical['id']))
    cur.execute('UPDATE fuel_purchases SET counterparty_id=%s WHERE counterparty_id=%s',(canonical['id'],ident))
    cur.execute('UPDATE payments SET counterparty_id=%s WHERE counterparty_id=%s',(canonical['id'],ident))
    cur.execute('UPDATE documents SET counterparty_id=%s WHERE counterparty_id=%s',(canonical['id'],ident))
    cur.execute('UPDATE counterparties SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s',(ident,))
    cur.execute('SELECT * FROM counterparties WHERE id=%s',(canonical['id'],)); updated=cur.fetchone(); cursor_audit(cur,'counterparty',canonical['id'],'update',canonical,updated); cursor_audit(cur,'counterparty',ident,'merge',old,{'canonical_id':canonical['id']})
    conn.commit(); return jsonify(ok=True,message='Ověřené údaje byly sloučeny se stávajícím dodavatelem.',supplier={'id':updated['id'],'name':updated['name'],'ico':updated['ico']})
   cur.execute("SELECT id FROM counterparties WHERE id<>%s AND source='manual' AND role<>'fuel_station' AND deleted_at IS NULL AND LOWER(name)=LOWER(%s) LIMIT 1",(ident,verified['name']))
   if cur.fetchone():
    conn.rollback(); return jsonify(ok=False,message='Ověřený název už používá jiný dodavatel v adresáři.'),409
   attachment=supplier_attachment(ident); source='ares'
   if attachment:
    found=identifiers_from_text(text_from_attachment(attachment,current_app.config['UPLOAD_FOLDER']))
    if found and found['ico']==verified['ico']: source='document+ares'
   cur.execute('UPDATE counterparties SET name=%s,ico=%s,dic=%s,official_address=%s,verified_at=CURRENT_TIMESTAMP,verification_source=%s WHERE id=%s',(verified['name'],verified['ico'],verified['dic'] or None,verified['address'] or None,source,ident))
   cur.execute('SELECT * FROM counterparties WHERE id=%s',(ident,)); updated=cur.fetchone(); cursor_audit(cur,'counterparty',ident,'update',old,updated)
  conn.commit()
 except Exception:
  conn.rollback(); raise
 finally: conn.close()
 return jsonify(ok=True,message='Ověřené údaje byly použity.',supplier={'id':ident,'name':verified['name'],'ico':verified['ico']})

@bp.post('/settings/address-book/<int:ident>')
@bp.post('/address-book/<int:ident>')
@login_required
def edit_address(ident):
 validate_csrf(request.form.get('csrf_token'))
 item=query("SELECT * FROM counterparties WHERE id=%s AND source='manual' AND deleted_at IS NULL",(ident,),one=True)
 if not item: abort(404)
 ok,message,_=save_contact(item)
 flash(message,'success' if ok else 'error')
 return redirect(url_for('main.address_book')+'#'+_section(item['role']))

@bp.post('/address-book/<int:ident>/deactivate')
@login_required
def deactivate_address(ident):
 item=query("SELECT * FROM counterparties WHERE id=%s AND source='manual' AND deleted_at IS NULL",(ident,),one=True)
 if not item: abort(404)
 execute('UPDATE counterparties SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s AND deleted_at IS NULL',(ident,)); audit('counterparty',ident,'cancel',item,query('SELECT * FROM counterparties WHERE id=%s',(ident,),one=True)); flash('Kontakt byl deaktivován.','success'); return redirect(url_for('main.address_book',status='all'))

@bp.post('/address-book/<int:ident>/restore')
@login_required
def restore_address(ident):
 item=query("SELECT * FROM counterparties WHERE id=%s AND source='manual' AND deleted_at IS NOT NULL",(ident,),one=True)
 if not item: abort(404)
 execute('UPDATE counterparties SET deleted_at=NULL WHERE id=%s',(ident,)); audit('counterparty',ident,'restore',item,query('SELECT * FROM counterparties WHERE id=%s',(ident,),one=True)); flash('Kontakt byl znovu aktivován.','success'); return redirect(url_for('main.address_book',status='all'))
