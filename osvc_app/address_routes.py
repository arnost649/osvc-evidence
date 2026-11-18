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
  extra+=' AND (name LIKE %s OR ico LIKE %s OR street LIKE %s OR city LIKE %s OR postal_code LIKE %s OR phone LIKE %s OR email LIKE %s)'; term=f'%{search}%'; params += [term]*7
 fields='id,role,name,operator_name,ico,dic,street,city,postal_code,official_address,country_code,email,phone,note,verified_at,verification_source,deleted_at'
 groups={}; pagers={}
 for key,roles in [('suppliers',"('supplier','both')"),('customers',"('customer','both')"),('stations',"('fuel_station')")]:
  groups[key],pagers[key]=paginate(f"SELECT {fields} FROM counterparties WHERE source='manual' AND role IN {roles}{extra} ORDER BY name,id",tuple(params),page_parameter=key+'_page',fragment=key)
 # All active contacts for the live suggestions of „Hledat kontakt“ (filtered in the browser by the shared combobox, ui.js).
 contacts=query("SELECT id,role,name,operator_name,ico,city FROM counterparties WHERE source='manual' AND deleted_at IS NULL ORDER BY name,id")
 return render_template('address_book.html',**groups,pagers=pagers,search=search,contacts=contacts)


@bp.post('/settings/address-book')
@bp.post('/address-book')
@login_required
def create_address():
 name=request.form.get('name','').strip(); role=request.form.get('role','customer')
 if role not in ('supplier','customer','fuel_station'): role='customer'
 if not name: flash('Zadejte název.','error'); return redirect(url_for('main.address_book'))
 duplicate=None if role=='fuel_station' else query("SELECT id,role FROM counterparties WHERE source='manual' AND role<>'fuel_station' AND LOWER(TRIM(name))=LOWER(TRIM(%s)) AND deleted_at IS NULL ORDER BY id LIMIT 1",(name,),one=True)
 if duplicate:
  if duplicate['role'] not in (role,'both'):
   execute("UPDATE counterparties SET role='both' WHERE id=%s",(duplicate['id'],)); audit('counterparty',duplicate['id'],'update',duplicate,query('SELECT * FROM counterparties WHERE id=%s',(duplicate['id'],),one=True))
  flash('Tento subjekt už v adresáři existuje; použita byla stávající karta.','success'); return redirect(url_for('main.address_book'))
 values=(name,role,request.form.get('ico','').strip() or None,request.form.get('dic','').strip() or None,request.form.get('street','').strip() or None,request.form.get('city','').strip() or None,request.form.get('postal_code','').strip() or None,request.form.get('country_code','').strip() or None,request.form.get('email','').strip() or None,request.form.get('phone','').strip() or None,request.form.get('official_address','').strip() or None,request.form.get('note','').strip() or None)
 ident=execute('INSERT INTO counterparties (name,source,role,ico,dic,street,city,postal_code,country_code,email,phone,official_address,note) VALUES (%s,\'manual\',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',values); audit('counterparty',ident,'insert',None,query('SELECT * FROM counterparties WHERE id=%s',(ident,),one=True)); flash('Záznam byl přidán do adresáře.','success'); return redirect(url_for('main.address_book'))

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
 name=' '.join((request.form.get('name') or '').split())
 if not name or len(name)>200: flash('Zadejte platný název.','error'); return redirect(url_for('main.address_book'))
 roles=set(request.form.getlist('roles'))
 roles = {'fuel_station'} if item['role']=='fuel_station' else roles & {'supplier','customer'}
 if not roles: flash('Vyberte alespoň jednu roli.','error'); return redirect(url_for('main.address_book'))
 new_role='both' if len(roles)==2 else next(iter(roles))
 duplicate=None if item['role']=='fuel_station' else query("SELECT id FROM counterparties WHERE id<>%s AND source='manual' AND role<>'fuel_station' AND LOWER(name)=LOWER(%s) AND deleted_at IS NULL LIMIT 1",(ident,name),one=True)
 if duplicate: flash('Tento název už v dané části adresáře existuje.','error'); return redirect(url_for('main.address_book'))
 execute('UPDATE counterparties SET name=%s,role=%s,ico=%s,dic=%s,street=%s,city=%s,postal_code=%s,country_code=%s,email=%s,phone=%s,official_address=%s,note=%s WHERE id=%s',(name,new_role,request.form.get('ico','').strip() or None,request.form.get('dic','').strip() or None,request.form.get('street','').strip() or None,request.form.get('city','').strip() or None,request.form.get('postal_code','').strip() or None,request.form.get('country_code','').strip() or None,request.form.get('email','').strip() or None,request.form.get('phone','').strip() or None,request.form.get('official_address',item.get('official_address') or '').strip() or None,request.form.get('note','').strip() or None,ident)); audit('counterparty',ident,'update',item,query('SELECT * FROM counterparties WHERE id=%s',(ident,),one=True)); flash('Záznam uložen.','success'); return redirect(url_for('main.address_book'))

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
