import json
from datetime import date,datetime,timezone
from . import cas
from flask import Blueprint,request,render_template,redirect,url_for,flash,session,jsonify,send_file,abort
from .routes import login_required
from . import profile,annual,profile_presentation,employer_verification,insurers
from .ares import AresUnavailable
from . import profile_registry,profile_periods
import secrets,tempfile
from pathlib import Path
import time
bp=Blueprint('annual',__name__)

def year_arg():
 try:year=int(request.values.get('year',cas.today().year))
 except ValueError:abort(400)
 if not 2000<=year<=2100:abort(400)
 return year

def context(year):
 identity,p,ir,yr,report=annual.year_report(year)
 opts={**profile.OPTIONS,'expense_rate':{k:v['label'] for k,v in (profile.rules(year) or {}).get('expense_rates',{}).items()},'reason':(profile.rules(year) or {}).get('secondary_reasons',{'employment':'Zaměstnání','other':'Jiný důvod'})}
 return dict(profile_identity=identity,year_profile=p,profile_ir=ir,profile_yr=yr,profile_year=year,profile_report=report,profile_fields=profile.FIELDS,profile_options=opts,profile_months=profile.MONTHS,profile_identity_fields=profile.IDENTITY,profile_pobyt_fields=profile.POBYT,profile_help=profile.MONTH_HELP,profile_vehicles=profile.vehicles(),profile_insurers=insurers.names(),insurer_directory=insurers.entries(),profile_view=profile_presentation.build(identity,p,report,profile.vehicles()))

@bp.post('/settings/profile')
@login_required
def save_profile():
 year=year_arg();identity,old,_,_=profile.load(year)
 try:
  new,p=profile.parse(request.form,year,identity)
  profile_presentation.preserve_sources(old,p)
  employer_verification.merge(old,p,session.get("employer_verified"),request.form.get("employer_verification"))
  profile.zachovej_odhad_zaloh(old,p)
  verified=registry_candidate()
  if request.form.get('ares_applied')=='yes' and not verified:raise ValueError('Návrh registrů vypršel. Načtěte jej znovu; ostatní údaje zůstaly ve formuláři.')
  if verified and request.form.get('ares_applied')=='yes' and new.get('ico')==verified['data'].get('ico'):
   new['registry']=verified
   if all(new.get(k)==verified['data'].get(k,'') for k in profile.IDENTITY):new['ares']={'verified_at':verified['at'],'source':'ARES / ROS / RŽP','ico':new['ico']}
  profile.save(year,new,p,int(request.form.get('identity_revision','-1')),int(request.form.get('year_revision','-1')))
  if old.get('vehicles')!=p.get('vehicles'):flash(f'Evidence jízd a PHM zůstala zachována. Pro daňový výpočet roku {year} bude použit zvolený režim.','info')
  flash('Profil OSVČ byl uložen.','success')
 except ValueError as exc:
  flash(str(exc),'error')
  # Preserve submitted values rather than discarding a partly completed profile.
  ctx=context(year);ctx['profile_error']=str(exc);ctx['submitted']=request.form
  return render_template('profile_retry.html',**ctx),400
 section=request.form.get('profile_section','overview')
 if section not in ('overview','business','employment','social','health','tax','vehicle','advanced'):section='overview'
 return redirect(url_for('main.settings',year=year)+'#profile-'+section)

@bp.post('/settings/profile/ares')
@login_required
def verify_profile():
 ico=request.form.get('ico','')
 if not ico.isdigit() or len(ico)!=8:return jsonify(error='Zadejte osmimístné IČO.'),400
 candidate=profile_registry.lookup(ico)
 if not candidate['data'].get('name'):
  return jsonify(error='Identifikaci se nepodařilo načíst. Uložené údaje zůstaly zachovány.',statuses=candidate['statuses']),503
 token=secrets.token_hex(24);path=Path(tempfile.gettempdir())/('osvc-registry-'+token+'.json')
 # Session stores only a random reference, never a bulky public registry response.
 path.write_text(json.dumps(candidate,ensure_ascii=False),encoding='utf-8');path.chmod(0o600)
 old=session.pop('profile_registry_token',None)
 if old and len(old)==48 and all(c in '0123456789abcdef' for c in old):(Path(tempfile.gettempdir())/('osvc-registry-'+old+'.json')).unlink(missing_ok=True)
 session['profile_registry_token']=token
 return jsonify(candidate)

def registry_candidate():
 token=session.get('profile_registry_token','')
 if len(token)!=48 or any(c not in '0123456789abcdef' for c in token):return None
 path=Path(tempfile.gettempdir())/('osvc-registry-'+token+'.json')
 try:
  if time.time()-path.stat().st_mtime>3600:path.unlink(missing_ok=True);return None
  return json.loads(path.read_text(encoding='utf-8'))
 except (OSError,ValueError):return None

@bp.post('/settings/profile/preview')
@login_required
def preview_profile():
 year=year_arg();identity,old,_,_=profile.load(year)
 try:
  new,p=profile.parse(request.form,year,identity)
  profile_presentation.preserve_sources(old,p)
  employer_verification.merge(old,p,session.get("employer_verified"),request.form.get("employer_verification"))
  profile.zachovej_odhad_zaloh(old,p)
  report=annual.build(year,new,p,annual.evidence(year))
  view=profile_presentation.build(new,p,report,profile.vehicles())
  return jsonify(months=p['months'],missing=profile_periods.source_missing(p),view=view,overview_html=render_template('_profile_overview.html',profile_view=view))
 except ValueError as exc:return jsonify(error=str(exc)),400

def roky_prehledu():
 """Roky, pro které jsou nějaká data (platby, jízdy, PHM, uložený roční profil), sestupně."""
 from .db import roky_zaznamu
 roky=roky_zaznamu([('payments','payment_date','deleted_at IS NULL',()),('trips','trip_date','deleted_at IS NULL',()),
                    ('fuel_purchases','purchase_date','deleted_at IS NULL',()),('osvc_year_profiles','tax_year','1=1',())])
 return [y for y in roky if 2000<=y<=2100]

@bp.get('/annual')
@login_required
def overview():
 years=roky_prehledu()
 if request.values.get('year'):year=year_arg()
 else:year=cas.today().year if cas.today().year in years or not years else years[0]   # bez zvoleného roku: letošní, nemá-li data, poslední rok s daty
 if year not in years:years=sorted(set(years)|{year},reverse=True)   # zvolený rok (odkaz) musí být v nabídce; bez dat vůbec = jen letošní
 ctx=context(year)
 from .annual_podklad import podklad   # 1.0.3: stejný podklad k opsání jako PDF
 from . import urady   # úřady, formuláře a termíny podle adresy z Profilu OSVČ (ARES jen poprvé, pak uloženo)
 return render_template('annual.html',display=annual.display,profile_years=years,podklad=podklad(ctx['profile_report']),urady=urady.karty(ctx['profile_identity'],ctx['year_profile'],year),**ctx)

@bp.get('/annual/pdf')
@login_required
def pdf():
 from .annual_pdf import generate
 year=year_arg();report=context(year)['profile_report']
 return send_file(generate(report),mimetype='application/pdf',as_attachment=True,download_name=f'osvc-podklady-{year}.pdf')

@bp.post('/settings/profile/employer/search')
@login_required
def employer_search():
 from .ares import lookup_by_name
 name=' '.join(request.form.get('name','').split())[:200]
 if len(name)<2:return jsonify(error='Zadejte zaměstnavatele.'),400
 try:results=lookup_by_name(name,limit=100)
 except AresUnavailable:return jsonify(error='ARES není dostupný. Zkuste ověření znovu.'),503
 results.sort(key=lambda x:(x['name'].casefold()!=name.casefold(),x['name']))
 session['employer_candidates']=[x['ico'] for x in results]
 return jsonify(results=results)

@bp.post('/settings/profile/employer/verify')
@login_required
def employer_verify():
 from .ares import lookup_by_ico
 from .db import query
 ico=request.form.get('ico','')
 if ico not in session.get('employer_candidates',[]):return jsonify(error='Nejdříve vyhledejte a vyberte subjekt.'),400
 try:company=lookup_by_ico(ico)
 except AresUnavailable:return jsonify(error='ARES není dostupný. Zkuste ověření znovu.'),503
 if not company:return jsonify(error='Subjekt nebyl nalezen.'),404
 contacts=query('SELECT id FROM counterparties WHERE ico=%s ORDER BY id LIMIT 1',(ico,))
 candidate={'name':company['name'],'ico':company['ico'],'at':datetime.now(timezone.utc).isoformat(),'token':secrets.token_hex(24),'counterparty_id':contacts[0]['id'] if contacts else None}
 session['employer_verified']=candidate
 return jsonify(candidate)

@bp.post('/settings/profile/insurers/refresh')
@login_required
def refresh_insurers():
 from . import insurers
 try:return jsonify(insurers.refresh())
 except Exception:return jsonify(error='Číselník se nepodařilo aktualizovat. Lokální kopie zůstala zachována.'),502
