"""Nastavení (stránka, vozidla, názvy typů, vzhled).
Stránky jsou na blueprintu 'main' z routes.py, takže URL a názvy endpointů (url_for('main.…')) zůstávají."""
from decimal import Decimal, InvalidOperation
from flask import abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_wtf.csrf import validate_csrf
from . import system_types
from .db import connection, execute, query
from .routes import bp, audit, cursor_audit, login_required


@bp.route('/settings')
@login_required
def settings():
 from .annual_routes import context,year_arg
 from .income_source_routes import settings_context
 vehicle_columns='*'
 supplier_count=query("SELECT COUNT(*) AS total FROM counterparties WHERE source='manual' AND role IN ('supplier','both') AND deleted_at IS NULL",one=True)['total']
 customer_count=query("SELECT COUNT(*) AS total FROM counterparties WHERE source='manual' AND role IN ('customer','both') AND deleted_at IS NULL",one=True)['total']
 vehicles_rows=query(f'SELECT {vehicle_columns} FROM vehicles WHERE deleted_at IS NULL ORDER BY name')
 active_vehicle_count=sum(1 for row in vehicles_rows if row.get('active'))
 from . import moduly
 pocty=moduly.pocty()
 moduly_view=[{'klic':k,**info,**moduly.stav()[k],'obsah':moduly.obsah_text(k,pocty[k]),'ma_data':any(pocty[k].values())} for k,info in moduly.MODULY.items()]
 potvrdit=request.args.get('potvrdit') if request.args.get('potvrdit') in moduly.MODULY else None
 from .backup import last_restore_result
 from . import ucet as ucet_modul
 ucet_akt=ucet_modul.aktualni()
 ucet_db=query('SELECT password_changed_at FROM app_accounts WHERE id=%s',(ucet_akt['id'],),one=True) if ucet_akt and ucet_akt.get('id') else None
 sit_info=sit_prehled() if current_app.config.get('OSVC_SAMOSTATNA') else None
 return render_template('settings.html',sit_info=sit_info,ucet_jmeno=ucet_akt['username'] if ucet_akt else '',ucet_zmena=ucet_db['password_changed_at'] if ucet_db else None,moduly=moduly_view,potvrdit_modul=potvrdit,obnova=last_restore_result(),system_types=system_types.entries(),vehicles=vehicles_rows,active_vehicle_count=active_vehicle_count,supplier_count=supplier_count,customer_count=customer_count,**context(year_arg()),**settings_context())

@bp.post('/settings/vehicles')
@login_required
def create_vehicle():
 name=request.form.get('name','').strip(); plate=request.form.get('registration_plate','').strip() or None; fuel=request.form.get('fuel_type','').strip() or None; raw=request.form.get('normalized_consumption_l_100km','').strip().replace(',','.')
 if not name: flash('Zadejte název vozidla.','error'); return redirect(url_for('main.settings'))
 try: consumption=Decimal(raw) if raw else None
 except InvalidOperation: flash('Spotřebu zadejte jako číslo.','error'); return redirect(url_for('main.settings'))
 if consumption is not None and (consumption<=0 or consumption>100): flash('Spotřeba musí být větší než 0 a nejvýše 100 l/100 km.','error'); return redirect(url_for('main.settings'))
 ident=execute('INSERT INTO vehicles (name,registration_plate,fuel_type,normalized_consumption_l_100km,active) VALUES (%s,%s,%s,%s,1)',(name,plate,fuel,consumption)); audit('vehicle',ident,'insert',None,query('SELECT * FROM vehicles WHERE id=%s',(ident,),one=True)); flash('Vozidlo bylo přidáno.','success'); return redirect(url_for('main.settings'))

@bp.post('/settings/vehicles/<int:ident>')
@login_required
def update_vehicle(ident):
 old=query('SELECT * FROM vehicles WHERE id=%s AND deleted_at IS NULL',(ident,),one=True)
 if not old: abort(404)
 name=request.form.get('name','').strip(); plate=request.form.get('registration_plate','').strip() or None; fuel=request.form.get('fuel_type','').strip() or None; raw=request.form.get('normalized_consumption_l_100km','').strip().replace(',','.')
 try: consumption=Decimal(raw) if raw else None
 except InvalidOperation: flash('Spotřebu zadejte jako číslo.','error'); return redirect(url_for('main.settings'))
 active=1 if request.form.get('active')=='1' else 0
 if not name or (consumption is not None and (consumption<=0 or consumption>100)): flash('Zkontrolujte název a spotřebu vozidla.','error'); return redirect(url_for('main.settings'))
 execute('UPDATE vehicles SET name=%s,registration_plate=%s,fuel_type=%s,normalized_consumption_l_100km=%s,active=%s WHERE id=%s',(name,plate,fuel,consumption,active,ident)); audit('vehicle',ident,'update',old,query('SELECT * FROM vehicles WHERE id=%s',(ident,),one=True)); flash('Vozidlo bylo upraveno.','success'); return redirect(url_for('main.settings'))

@bp.post('/settings/system-types')
@login_required
def update_system_types():
 names={key:request.form.get('label_'+key,'').strip() for key in system_types.TYPES}
 if any(not name or len(name)>100 for name in names.values()):
  flash('Vyplňte všechny popisky (nejvýše 100 znaků).','error')
  return redirect('/settings#categories')
 return save_system_type_labels(names)

@bp.post('/settings/system-types/<key>')
@login_required
def update_system_type(key):
 if key not in system_types.TYPES:abort(404)
 name=request.form.get('display_label','').strip()
 if not name or len(name)>100:abort(400)
 return save_system_type_labels({key:name})

def save_system_type_labels(names):
 conn=connection()
 try:
  with conn.cursor() as cur:
   for key,name in names.items():
    cur.execute('SELECT * FROM system_types WHERE type_key=%s FOR UPDATE',(key,));old=cur.fetchone()
    if old['display_label']==name:continue
    cur.execute('UPDATE system_types SET display_label=%s WHERE type_key=%s',(name,key))
    cursor_audit(cur,'system_type',0,'update',old,{'type_key':key,'display_label':name})
  conn.commit()
 except Exception:conn.rollback();raise
 finally:conn.close()
 flash('Popisky uloženy.','success');return redirect('/settings#categories')

@bp.post('/settings/categories/<int:ident>')
@bp.post('/settings/categories')
@login_required
def legacy_categories(ident=None):
 abort(410,description='Uživatelské kategorie jsou archivní. Upravovat lze pouze popisky systémových typů.')

@bp.post('/settings/vehicles/<int:ident>/consumption')
@login_required
def vehicle_consumption(ident):
 validate_csrf(request.form.get('csrf_token'))
 old=query('SELECT * FROM vehicles WHERE id=%s AND deleted_at IS NULL',(ident,),one=True)
 if not old: abort(404)
 raw=(request.form.get('normalized_consumption_l_100km') or '').strip().replace(',','.')
 try: consumption=Decimal(raw) if raw else None
 except InvalidOperation: flash('Spotřebu zadejte jako číslo.','error'); return redirect(url_for('main.settings'))
 if consumption is not None and (consumption<=0 or consumption>100): flash('Spotřeba musí být větší než 0 a nejvýše 100 l/100 km.','error'); return redirect(url_for('main.settings'))
 execute('UPDATE vehicles SET normalized_consumption_l_100km=%s WHERE id=%s',(consumption,ident)); audit('vehicle',ident,'update',old,query('SELECT * FROM vehicles WHERE id=%s',(ident,),one=True))
 flash('Normovaná spotřeba uložena.','success'); return redirect(url_for('main.settings'))


@bp.post('/settings/appearance')
@login_required
def update_appearance():
 from .themes import THEME_IDS, save_theme
 payload=request.get_json(silent=True)
 value=payload.get('theme') if isinstance(payload,dict) else None
 if not isinstance(value,str) or value not in THEME_IDS:
  return jsonify(error='Neplatný barevný motiv.'),400
 try: save_theme(value)
 except OSError:
  current_app.logger.error('Appearance preference could not be saved.')
  return jsonify(error='Motiv se nepodařilo uložit. Zkuste to znovu.'),500
 return jsonify(theme=value)


def sit_prehled():
 """Síťový přístup pro Nastavení (jen samostatná instalace): volba, skutečný stav po startu, firewall, adresy."""
 from . import sit
 from .backup import state_dir
 inst=state_dir();port=current_app.config.get('OSVC_PORT');volba=sit.nacti(inst);st=sit.stav(inst)
 fw=sit._cti(inst/sit.SOUBOR).get('firewall') or ({'stav':'bez_zasahu','zprava':sit.linux_rada(port)} if volba['rezim']=='domaci' and not current_app.config.get('OSVC_WINDOWS') else {})
 v_siti=[x for x in st.get('naslouchani',[]) if not x.startswith('127.0.0.1:')]
 return {'volba':volba,'stav':st,'port':port,'firewall':fw,'lokalni_adresa':f'http://localhost:{port}/','sitove_adresy':[f'http://{x}/' for x in v_siti],
         'upozorneni':sit.UPOZORNENI,'windows':bool(current_app.config.get('OSVC_WINDOWS'))}

@bp.get('/settings/sit/adaptery')
@login_required
def sit_adaptery():
 if not current_app.config.get('OSVC_SAMOSTATNA'): abort(404)
 from . import sit
 return jsonify(adaptery=sit.adaptery())

@bp.post('/settings/sit')
@login_required
def update_sit():
 """Uložit síťový přístup → firewall (Windows přes UAC; Linux root jednotka podle sit.json) → restart aplikace."""
 if not current_app.config.get('OSVC_SAMOSTATNA'): abort(404)
 from . import sit
 from .backup import state_dir
 rezim=request.form.get('rezim');ip=request.form.get('ip','');port=current_app.config.get('OSVC_PORT')
 try:
  if rezim=='domaci':
   if request.form.get('potvrzeni')!='ano':raise ValueError('Pro zpřístupnění v síti potvrďte, že rozumíte rizikům.')
   if sit.platna_ip(ip) not in sit.adresy_pocitace():raise ValueError('Zvolená adresa na tomto počítači není. Vyberte adaptér ze seznamu.')
  data=sit.uloz(state_dir(),rezim,ip)
 except ValueError as exc:
  flash(str(exc),'error');return redirect(url_for('main.settings',tab='sit'))
 data['firewall']=sit.firewall(rezim,port);sit._zapis(state_dir()/sit.SOUBOR,data)
 current_app.logger.info('síťový přístup: %s %s, firewall %s',rezim,data['ip'],data['firewall']['stav'])
 restart=current_app.config.get('OSVC_RESTART')
 if restart:restart()
 nova=f"http://{data['ip']}:{port}/" if rezim=='domaci' else None
 return render_template('sit_restart.html',nova=nova,lokalni=f'http://localhost:{port}/',firewall=data['firewall'],restart=bool(restart))

@bp.post('/settings/aktualizace')
@login_required
def update_aktualizace():
 """V2: zapnutí/vypnutí upozornění na novou verzi (jen samostatná instalace)."""
 if not current_app.config.get('OSVC_SAMOSTATNA'): abort(404)
 from . import aktualizace
 zap=request.form.get('kontrolovat')=='1'; aktualizace.nastav(zap)
 flash('Upozornění na nové verze je zapnuté.' if zap else 'Upozornění na nové verze je vypnuté.','success')
 return redirect(url_for('main.settings')+'#aktualizace')

@bp.post('/settings/account')
@login_required
def update_account():
 """I2: změna přihlašovacího jména a/nebo hesla (vždy s ověřením současného hesla)."""
 from . import ucet
 try:
  u=ucet.zmen(request.form.get('current_password',''),request.form.get('username',''),request.form.get('new_password',''),request.form.get('new_password2',''))
 except ValueError as exc:
  flash(str(exc),'error'); return redirect(url_for('main.settings',tab='account'))
 session['user']=u['username']; session['auth']=u['auth_version']   # toto přihlášení platí dál
 flash('Přihlašovací údaje jsou uložené.','success')
 return redirect(url_for('main.settings',tab='account'))


@bp.post('/settings/modules/<klic>')
@login_required
def update_module(klic):
 """zapnutí/vypnutí modulu – jen volba v instance/moduly.json, data v DB se nemění."""
 from . import moduly
 if klic not in moduly.MODULY: abort(404)
 zapnuto=request.form.get('zapnuto');zapocitat=request.form.get('zapocitat')
 if zapnuto not in ('0','1',None) or zapocitat not in ('0','1',None) or (zapnuto is None and zapocitat is None):abort(400)
 nazev=moduly.MODULY[klic]['nazev'];zpet=redirect(url_for('main.settings',tab='modules'))
 if zapnuto is None and moduly.zapnuto(klic):
  flash(f'Modul {nazev} je zapnutý – jeho záznamy se počítají vždy.','info');return zpet
 # vypnutí modulu s daty: nejdřív otázka, co s existujícími záznamy ve výpočtech (Zrušit je výchozí)
 if zapnuto=='0' and zapocitat is None and moduly.zapnuto(klic) and any(moduly.pocty()[klic].values()):
  return redirect(url_for('main.settings',tab='modules',potvrdit=klic)+f'#modul-{klic}')
 try:
  if zapnuto is None:moduly.uloz(klic,zapocitat=zapocitat=='1')
  else:moduly.uloz(klic,zapnuto=zapnuto=='1',zapocitat=None if zapnuto=='1' or zapocitat is None else zapocitat=='1')
 except OSError:
  current_app.logger.error('Nastavení modulů nejde uložit.'); flash('Nastavení modulů se nepodařilo uložit.','error')
  return zpet
 s=moduly.stav()[klic]
 current_app.logger.info('modul %s: %s, %s',klic,'zapnut' if s['zapnuto'] else 'vypnut','započítán' if s['zapocitat'] else 'nezapočítán')
 if zapnuto=='1':flash(f'Modul {nazev} je zapnutý. Data zůstávají beze změny.','success')
 elif s['zapocitat']:flash(f"Modul {nazev} je {'vypnutý' if zapnuto else 'dál vypnutý'}. Existující záznamy se dál počítají do výpočtů. Data zůstávají beze změny.",'success')
 else:flash(f"Modul {nazev} je {'vypnutý' if zapnuto else 'dál vypnutý'}. Jeho záznamy se nezapočítávají do Přehledu ani Ročního přehledu. Data zůstávají beze změny.",'success')
 return zpet
