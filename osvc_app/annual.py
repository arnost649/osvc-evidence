"""Yearly working papers. Unsupported legal cases never get a known status."""
from decimal import Decimal,ROUND_CEILING,ROUND_HALF_UP
from datetime import date
from . import cas
from . import profile,insurers
from .year_periods import resolve_year_period,vehicle_year_period
from .db import query, rok
D=lambda x:Decimal(str(x))
PRAVIDLA_CHYBI='Pravidla pro rok {} zatím nejsou – nainstalujte novou verzi aplikace.'   # pravidla roku chodí s aktualizacemi
ODHAD_ZALOH='Odhad: {} Kč měsíčně × {} měs. Upřesněte skutečný úhrn podle {}.'
def odhad_zaloh(p,n):
 """Roční úhrn záloh z měsíční částky z průvodce (social/health_advance_month), když skutečný úhrn není zadán. Upraví p."""
 poznamky={}
 for key,kde in (('social','ePortálu ČSSZ'),('health','přehledu plateb u pojišťovny')):
  mesic=p.get(key+'_advance_month')
  if p.get(key+'_paid') in ('',None) and mesic not in ('',None):
   try:p[key+'_paid']=str(money(D(mesic)*n));poznamky[key]=ODHAD_ZALOH.format(str(mesic).replace('.',','),n,kde)
   except Exception:pass
 return poznamky
def money(x):return D(x).quantize(D('.01'),rounding=ROUND_HALF_UP)
def hodnota(x):return D(x['hodnota'] if isinstance(x,dict) else x)
def datum_cz(t):
 d=date.fromisoformat(t);return f'{d.day}. {d.month}. {d.year}'
def kc(x):
 t=f'{money(x):,.2f}'.replace(',',' ').replace('.',',')
 return (t[:-3] if t.endswith(',00') else t)+' Kč'
def nova_zaloha(key,year,base,n,p,main=0,secondary=0,health_min=0):
 """Nová měsíční záloha placená v roce year+1 po podání přehledu za rok year (1.0.3), jen podle tax_rules/zalohy-<year+1>.json.
 Vrátí (částka nebo None, poznámka). Podporované případy: ČSSZ jen hlavní nebo jen vedlejší SVČ; ZP minimum ve všech aktivních měsících."""
 z=profile.zalohy(year+1)
 if not z:return None,f'stanoví se podle pravidel {year+1}'
 if base is None or not n:return None,'chybí podklady pro výpočet'
 pm=hodnota(z['prumerna_mzda'])
 if key=='social':
  s=z['social']
  if main and not secondary:
   new20=p.get('social_case')=='new20'
   if new20:
    try:new20=date.fromisoformat(str(p.get('start'))[:10]).year>=year+1-2
    except ValueError:return None,'ověřte u ČSSZ (snížené minimum pro začínající – chybí datum zahájení)'
   minimum=ceil(pm*hodnota(s['new_main_min_ratio' if new20 else 'main_min_ratio']))
  elif secondary and not main:minimum=ceil(pm*hodnota(s['secondary_min_ratio']))
  else:return None,'ověřte u ČSSZ (kombinace hlavní a vedlejší SVČ)'
  mesic=max(ceil(max(D(0),base)*hodnota(s['base_ratio'])/n),minimum)
  zaloha=ceil(mesic*hodnota(s['rate']))
  return zaloha,f"Od měsíce po podání přehledu za {year}: 29,2 % z měsíčního základu {kc(mesic)} (55 % průměrného měsíčního daňového základu, nejméně minimum {year+1} {kc(minimum)}). Zdroj: {s['base_ratio']['zdroj']}; průměrná mzda {kc(pm)} – {z['prumerna_mzda']['zdroj'].split(',')[0]} (vyhlášeno {datum_cz(z['prumerna_mzda']['vyhlaseno'])})."
 h=z['health']
 if health_min!=n:return None,'ověřte u pojišťovny (část roku bez povinného minima)'
 minimum=pm*hodnota(h['min_ratio'])
 mesic=max(max(D(0),base)*hodnota(h['base_ratio'])/n,minimum)
 zaloha=ceil(mesic*hodnota(h['rate']))
 return zaloha,f"Za měsíc podání přehledu za {year} a dál: 13,5 % z měsíčního základu {kc(mesic)} (50 % průměrného měsíčního daňového základu, nejméně minimum {year+1} {kc(minimum)}). Zdroj: {h['base_ratio']['zdroj']}; průměrná mzda {kc(pm)} – {z['prumerna_mzda']['zdroj'].split(',')[0]} (vyhlášeno {datum_cz(z['prumerna_mzda']['vyhlaseno'])})."
def ceil(x):return D(x).quantize(D('1'),rounding=ROUND_CEILING)
FORMS={'tax':('Finanční úřad','Přiznání DPFO → Příloha č. 1 – samostatná činnost (§ 7)'), 'social':('ČSSZ','Přehled o příjmech a výdajích OSVČ'),'health':('Zdravotní pojišťovna','Přehled o výši daňového základu OSVČ')}
LABELS={
 'income':('Příjmy z podnikání','Příjmy ze samostatné činnosti','Součet nevyřazených plateb příjmů za rok.','Příjmy'),
 'expenses':('Daňově uznatelné výdaje','Výdaje související se samostatnou činností','Výdaje podle potvrzených podílů jednotlivých záznamů a ročního režimu. PHM se nezapočítává znovu vedle náhrady paliva v Jízdách.','Výdaje, Jízdy, PHM a Profil OSVČ'),
 'result':('Výsledek podnikání','Rozdíl příjmů a výdajů','Příjmy minus zvolené daňové výdaje před úpravami základu.','Vypočteno'),
 'method':('Způsob uplatnění výdajů','Způsob uplatnění výdajů','Skutečné výdaje a procentní paušál jsou odlišné metody. Paušální daň není procentní výdajový paušál.','Profil OSVČ → Daňové nastavení'),
 'adjustment':('Úpravy základu daně','Úpravy podle § 5 a § 23','Ručně ověřené zvýšení nebo snížení výsledku nad rámec evidence. Nula je výslovné potvrzení bez úprav.','Profil OSVČ → Daňové nastavení'),
 'base':('Daňový základ OSVČ','Daňový základ ze samostatné činnosti','Výsledek samostatné činnosti po zadaných úpravách. Záporný výsledek se pro pojistné neuplatňuje jako záporný vyměřovací základ.','Vypočteno z příjmů, výdajů a úprav'),
 'months':('Měsíce podnikání','Počet měsíců výkonu SVČ','Počet měsíců, kdy byla vykonávána činnost. I část měsíce může být aktivním měsícem.','Profil OSVČ → Podnikání'),
 'main':('Měsíce hlavní SVČ','Měsíce hlavní samostatné výdělečné činnosti','Počet aktivních měsíců označených pro ČSSZ jako hlavní.','Profil OSVČ → ČSSZ'),
 'secondary':('Měsíce vedlejší SVČ','Měsíce vedlejší samostatné výdělečné činnosti','Počet aktivních měsíců vedlejší činnosti pro ČSSZ, například při pojištěném zaměstnání.','Profil OSVČ → ČSSZ'),
 'reason':('Důvod vedlejší SVČ','Důvod výkonu vedlejší SVČ','Zákonný důvod se dokládá ČSSZ; samotné zaměstnání bez účasti na pojištění nestačí.','Profil OSVČ → ČSSZ'),
 'paid':('Zaplacené zálohy','Úhrn zaplacených záloh na pojistné','Skutečně uhrazené zálohy přiřazené k roku. Porovnejte se stavem u příslušné instituce.','Profil OSVČ → příslušné pojištění'),
 'assessment':('Vyměřovací základ','Vyměřovací základ','Základ pro pojistné podle pravidel roku a potvrzených výjimek. ČSSZ a zdravotní pojištění používají odlišná pravidla.','Vypočteno z daňového základu a ročního profilu'),
 'premium':('Roční pojistné','Pojistné za kalendářní rok','Pojistné z vyměřovacího základu, zaokrouhlené na koruny nahoru.','Vypočteno'),
 'balance':('Doplatek / přeplatek','Doplatek nebo přeplatek pojistného','Roční pojistné minus zaplacené zálohy. Kladná částka je doplatek, záporná přeplatek.','Vypočteno'),
 'advance':('Orientační nová záloha','Nová měsíční záloha','Nová měsíční záloha po podání přehledu podle pravidel následujícího roku (zákon a nařízení vlády o průměrné mzdě). Platí při stejném režimu činnosti; jinou situaci ověřte u instituce.','Vypočteno podle pravidel následujícího roku'),
 'insurer':('Zdravotní pojišťovna','Zdravotní pojišťovna a kód','Pojišťovna, pro kterou je určen roční přehled. Změna pojišťovny během roku vyžaduje rozdělení údajů.','Profil OSVČ → Zdravotní pojištění'),
 'employment':('Souběh se zaměstnáním','Souběh samostatné činnosti a zaměstnání','Počet aktivních měsíců se zaměstnáním. Pro zdravotní výjimku nestačí samotný souběh ani vedlejší činnost ČSSZ.','Profil OSVČ → Zaměstnání'),
 'minimum':('Měsíce s povinným minimem','Počet měsíců s minimálním vyměřovacím základem','Počet aktivních měsíců s povinností minima. Výjimka ze zaměstnání vyžaduje celoměsíční souběh, hlavní zdroj v zaměstnání a odvod alespoň zaměstnaneckého minima.','Profil OSVČ → Zdravotní pojištění')}

def year_report(year):
 """Load the same yearly inputs for dashboard, annual view and PDF."""
 from .profile_periods import prepare
 identity,p,ir,yr=profile.load(year)
 p=prepare(year,p)
 return identity,p,ir,yr,build(year,identity,p,evidence(year))

def evidence(year):
 payments=query('SELECT p.* FROM payments p WHERE p.deleted_at IS NULL AND p.payment_date>=%s AND p.payment_date<%s',rok(year))
 trips=query('SELECT * FROM trips WHERE deleted_at IS NULL AND trip_date>=%s AND trip_date<%s',rok(year))
 fuels=query('SELECT * FROM fuel_purchases WHERE deleted_at IS NULL AND purchase_date>=%s AND purchase_date<%s',rok(year))
 from .routes import trip_snapshot_calculation
 from . import moduly
 # Vypnutý modul s volbou „Nezapočítávat“: jeho záznamy zůstávají, jen se vynechají ze součtů (a spočítají do „Nezapočteno“).
 bez_dopravy=moduly.vyrazeno('doprava');bez_webu=moduly.vyrazeno('externi_web')
 stazene={r['document_id'] for r in query('SELECT document_id FROM income_source_records WHERE document_id IS NOT NULL')} if bez_webu else set()
 nezapocteno={}
 if bez_dopravy:nezapocteno['doprava']={'jizdy':len(trips),'tankovani':len(fuels),'nahrady':D(0),'phm':D(0)}
 if bez_webu:nezapocteno['externi_web']={'prijmy':0,'castka':D(0)}
 by_vehicle={str(v['id']):{'travel':D(0),'fuel':D(0),'missing':False} for v in profile.vehicles()}
 issues=[];expense_issues=[]
 for t in trips:
  result=trip_snapshot_calculation(t)
  if bez_dopravy:
   nezapocteno['doprava']['nahrady']+=D(result.get('total') or 0);continue
  part=by_vehicle[str(t['vehicle_id'])]
  if result.get('total') is None:part['missing']=True
  else:part['travel']+=D(result['total'])
  if t.get('trip_end_date') and t['trip_end_date'].year!=year:part['cross_year']=True
 fuel_ids={f['id']:f for f in query('SELECT id,vehicle_id FROM fuel_purchases')}
 income=D(0);ordinary=D(0);unknown=D(0);unknown_ids=[];ordinary_total=D(0);excluded=D(0);pending=[]
 from .expense_tax import classification
 for p in payments:
  if p['direction']=='income' and p.get('document_id') in stazene:
   nezapocteno['externi_web']['prijmy']+=1
   if p['currency']=='CZK':nezapocteno['externi_web']['castka']+=p['amount']
   continue
  if bez_dopravy and p['direction']=='expense' and p['fuel_purchase_id']:
   if p['currency']=='CZK':nezapocteno['doprava']['phm']+=p['amount']
   continue
  if p['currency']!='CZK':
   (issues if p['direction']=='income' else expense_issues).append('Platba v cizí měně – chybí přepočet do Kč.');continue
  if p['direction']=='income':
   income+=p['amount']
   if p.get('payment_needs_review'):issues.append('Příjem #%s: připsaná částka / měna vyžaduje ověření; evidovaná částka není odhad kurzu.' % p['id'])
   continue
  if p['fuel_purchase_id']:
   f=fuel_ids.get(p['fuel_purchase_id'])
   if f:by_vehicle[str(f['vehicle_id'])]['fuel']+=p['amount']
   else:expense_issues.append('Výdaj PHM bez vazby na vozidlo.')
  else:
   ordinary_total+=p['amount'];tax=classification(p)
   if tax['ratio'] is None:
    unknown+=p['amount'];unknown_ids.append(p['id']);pending.append({'id':p['id'],'date':p['payment_date'],'description':p['description'],'amount':p['amount'],'reason':tax['reason']})
   else:
    accepted=money(p['amount']*tax['ratio']/100);ordinary+=accepted;excluded+=p['amount']-accepted

 return {'income':income,'ordinary_total':money(ordinary_total),'recorded_expenses':money(ordinary_total+sum((v['travel'] for v in by_vehicle.values()),D(0))),'excluded_expenses':money(excluded),'pending_expenses':pending,'ordinary':money(ordinary),'unknown_expenses':money(unknown),'unknown_ids':unknown_ids,'vehicles':by_vehicle,'issues':issues,'expense_issues':expense_issues,'counts':{'Příjmy':sum(p['direction']=='income' for p in payments),'Výdaje':sum(p['direction']=='expense' for p in payments),'Jízdy':len(trips),'PHM':len(fuels)},'bez_dopravy':bez_dopravy,'nezapocteno':nezapocteno}

def build(year,identity,p,ev):
 from .profile_periods import project,source_missing
 p=project(year,p)
 if p.get('profile_version')==2:
  for key in ('social_case','health_case','tax_case'):
   if not p.get(key):p[key]='standard'   # nevyplněno = běžný případ (zvláštní okolnosti uživatel volí výslovně)
 r=profile.rules(year);months=p['months'];active=[m for m in months if m.get('activity')=='yes'];n=len(active)
 odhady=odhad_zaloh(p,n)
 missing={k:[] for k in ['identity','business','employment','social','health','tax','vehicles']}
 def need(section,condition,label):
  if not condition:missing[section].append(label)
 for k in ['ico','name','number','city','zip','country']:need('identity',identity.get(k),profile.IDENTITY[k])
 need('business',all(m.get('activity') in ('yes','no') for m in months),'Aktivita ve všech 12 měsících')
 need('employment',all(m.get('employment') for m in months),'Zaměstnání ve všech 12 měsících')
 for key in ['social_paid','social_case']:need('social',p.get(key) not in ('',None),dict((x[0],x[1]) for x in profile.FIELDS['social'])[key])
 if p.get('social_case')=='new20':need('social',p.get('start') and 0<=year-date.fromisoformat(p['start']).year<=2,'Datum prvního zahájení v tomto nebo předchozích dvou letech')
 for m in active:
  need('social',m.get('social'),'Charakter ČSSZ: '+profile.MONTHS[m['month']-1])
  if m.get('social')=='secondary':
   need('social',m.get('reason'),'Důvod vedlejší SVČ: '+profile.MONTHS[m['month']-1])
   if m.get('reason')=='employment':need('social',m.get('employment')=='insured','Pojištěné zaměstnání: '+profile.MONTHS[m['month']-1])
 if any(m.get('social')=='secondary' for m in active):need('social',p.get('social_voluntary'),'Dobrovolná účast ČSSZ')
 for key in ['insurer','insurer_code','health_paid','health_case']:need('health',p.get(key) not in ('',None),dict((x[0],x[1]) for x in profile.FIELDS['health'])[key])
 health_min=0
 for m in active:
  mode=m.get('minimum');employed=m.get('employment') in ('insured','uninsured') and m.get('health_employment')=='yes'
  if mode=='yes':health_min+=1
  elif mode=='no' and m.get('health_reason')=='state':pass
  elif mode in ('no','auto') and employed and (mode=='auto' or m.get('health_reason')=='employment'):pass
  else:missing['health'].append('Minimum / výjimka: '+profile.MONTHS[m['month']-1])
 for key in ['expense_method','tax_case','base_adjustment']:need('tax',p.get(key) not in ('',None),dict((x[0],x[1]) for x in profile.FIELDS['tax'])[key])
 need('tax',p.get('tax_review')=='yes','Potvrďte kontrolu evidence a daňových korekcí')
 if p.get('expense_method')=='percentage':need('tax',p.get('expense_rate'),'Sazba procentního paušálu')
 else:
  need('tax',p.get('expense_adjustment') not in ('',None),'Korekce výdajů (nebo 0)')
  if ev.get('unknown_ids'):need('tax',False,f"Posoudit daňový podíl {len(ev['unknown_ids'])} výdajů")
 transport=D(0);comparisons=[];flat_count=0;private_count=0
 # vyřazená Doprava = ani jízdy a PHM, ani paušál dopravy; režim vozidel se pro výpočet nepoužije (nastavení zůstává)
 for v in ([] if ev.get('bez_dopravy') else profile.vehicles()):
  key=str(v['id']);setting=p['vehicles'].get(key,{});method=setting.get('vehicle_method');values=ev['vehicles'].get(key,{'travel':D(0),'fuel':D(0),'missing':False});selected=None;flat=None
  need('vehicles',method,'Daňový režim: '+v['name'])
  vehicle_period=vehicle_year_period(year,setting.get('from'),setting.get('to'))
  if r and setting.get('private'):
   flat=D(r['transport']['private_month' if setting['private']=='yes' else 'full_month'])*len(vehicle_period['months'])
  if method=='none':selected=D(0)
  elif method=='actual':
   basis=setting.get('actual_basis');need('vehicles',basis,'Zdroj skutečných nákladů: '+v['name'])
   if basis:selected=values[basis]
   if basis=='travel':
    need('vehicles',not values['missing'],'Chybějící výpočet Jízdy: '+v['name'])
    need('vehicles',not values.get('cross_year'),'Časové přiřazení jízdy přes více let: '+v['name'])
  elif method=='flat':
   flat_count+=1;private_count+=setting.get('private')=='yes'
   need('vehicles',flat is not None,'Období a soukromé použití: '+v['name']);need('vehicles',setting.get('eligible')=='yes','Podmínky paušálu dopravy: '+v['name'])
   need('vehicles',all(months[m-1].get('activity')=='yes' for m in vehicle_period['months']),'Paušál dopravy jen v aktivních měsících: '+v['name'])
   selected=flat
  if selected is not None:transport+=selected
  actual=values.get(setting.get('actual_basis'))
  comparisons.append({'name':v['name'],'method':profile.OPTIONS['actual_basis'].get(setting.get('actual_basis'),'Skutečné náklady / cestovní náhrady') if method=='actual' else profile.OPTIONS['vehicle_method'].get(method,'Chybí volba'),'travel':values['travel'],'fuel':values['fuel'],'flat':flat,'difference':actual-flat if actual is not None and flat is not None else None})
 if r:
  need('vehicles',flat_count<=r['transport']['max_vehicles'],'Nejvýše tři vozidla s paušálem dopravy')
  need('vehicles',private_count<=1,'Krácený paušál: ostatní paušální vozidla musí být výlučně podnikatelská')
 def amount(key):return D(p[key]) if p.get(key) not in (None,'') else None
 adjustment=amount('base_adjustment');cost=None
 if p.get('expense_method')=='actual' and not missing['vehicles'] and not ev.get('unknown_ids') and not ev.get('expense_issues') and amount('expense_adjustment') is not None:cost=ev['ordinary']+transport+amount('expense_adjustment')
 elif p.get('expense_method')=='percentage' and r and p.get('expense_rate') in r['expense_rates']:
  rate=r['expense_rates'][p['expense_rate']];cost=min(ev['income']*D(rate['rate']),D(rate['cap']))
 result=money(ev['income']-cost) if cost is not None else None
 base=result+adjustment if result is not None and adjustment is not None else None
 tax_status='known'
 reviews=list(ev['issues'])+(ev.get('expense_issues',[]) if p.get('expense_method')=='actual' else [])
 if not r:reviews.append(PRAVIDLA_CHYBI.format(year))
 if p.get('tax_case')!='standard':reviews.append('Profil OSVČ → Daňový režim: DPH / paušální daň / více sazeb / jiný režim. Použitelnost základu § 7 vyžaduje ověření tohoto režimu.')
 if p.get('tax_review')!='yes':reviews.append('V Profilu OSVČ není potvrzena kontrola evidence a daňových korekcí.')
 if not n and base is not None and base!=0:reviews.append('Nenulový daňový základ bez aktivních měsíců – ověřte přiřazení pojistného.')
 if cost is not None and cost<0:reviews.append('Korekce vedla k záporným výdajům.')
 if missing['tax'] or base is None:tax_status='missing'
 elif reviews:tax_status='review'
 # Each field inherits only its actual dependencies, not every annual review.
 income_state='review' if ev['issues'] else 'known'
 expense_reasons=list(ev.get('expense_issues',[])) if p.get('expense_method')=='actual' else []
 if p.get('tax_review')!='yes':expense_reasons.append('V Profilu OSVČ není potvrzena kontrola evidence a daňových korekcí.')
 if cost is not None and cost<0:expense_reasons.append('Korekce vedla k záporným výdajům.')
 expense_state='missing' if cost is None or p.get('tax_review')!='yes' else 'review' if expense_reasons else 'known'
 result_state='missing' if result is None or expense_state=='missing' else 'review' if income_state=='review' or expense_state=='review' else 'known'
 # Completeness of the §7 arithmetic is distinct from legal applicability.
 # Keep general tax applicability reviews separate from arithmetic completeness.
 base_state='missing' if base is None else result_state
 tax_reasons=list(reviews)
 known_months=not missing['business'];main=sum(m.get('social')=='main' for m in active);secondary=sum(m.get('social')=='secondary' for m in active)
 social_inputs=[x for x in missing['social'] if x!='Zaplacené zálohy ČSSZ']+missing['employment']
 social_months_ready=known_months and all(m.get('social') and (m.get('social')!='secondary' or m.get('reason')) for m in active)
 social_base=social_premium=None;social_state='missing' if social_inputs or not known_months or base_state=='missing' else 'review'
 social_threshold=D(r['social']['secondary_threshold'])-D(r['social']['threshold_reduction_month'])*(12-n) if r else None
 no_social_participation=bool(r and base_state=='known' and known_months and social_months_ready and not social_inputs and n>0 and main==0 and secondary==n and base<social_threshold and p.get('social_voluntary')=='no')
 if no_social_participation:social_base=D(0);social_premium=D(0);social_state='known'
 elif r and base_state=='known' and not social_inputs and known_months:
  supported=p.get('social_case') in ('standard','new20') and not(main and secondary) and all(m.get('reason')=='employment' for m in active if m.get('social')=='secondary')
  if supported:
   sr=r['social'];profit=max(D(0),base)
   if n==0:social_base=D(0)
   elif main:
    minimum=D(sr['new_main_min_month'] if p['social_case']=='new20' else sr['main_min_month'])*n
    social_base=min(D(sr['max_base']),max(ceil(profit*D(sr['base_ratio'])),minimum))
   elif profit<D(sr['secondary_threshold'])-D(sr['threshold_reduction_month'])*(12-n) and p.get('social_voluntary')=='no':social_base=D(0)
   else:social_base=min(D(sr['max_base']),max(ceil(profit*D(sr['base_ratio'])),D(sr['secondary_min_month'])*n))
   social_premium=ceil(social_base*D(sr['rate']));social_state='known'
 health_inputs=[x for x in missing['health'] if x!='Zaplacené zálohy zdravotního pojištění']+missing['employment']
 health_base=health_premium=None;health_state='missing' if health_inputs or not known_months or base_state=='missing' else 'review'
 if r and base_state=='known' and not health_inputs and known_months and (p.get('health_case')=='standard' or (health_min==0 and base<=0)):
  health_period=resolve_year_period(year,p.get('health_from'),p.get('health_to'))
  covered=all(health_period['effective_from']<=date(year,m['month'],1)<=health_period['effective_to'] for m in active)
  if covered:
   hr=r['health'];health_base=max(max(D(hr.get('negative_base_floor',0)),base)*D(hr['base_ratio']),D(hr['min_month'])*health_min);health_premium=ceil(health_base*D(hr['rate']));health_state='known'
 expense_note=(f"{len(ev.get('unknown_ids',[]))} výdajů čeká na posouzení. Nelze dokončit daňový výsledek; otevřete Výdaje → Chybí posouzení." if p.get('expense_method')=='actual' and ev.get('unknown_ids') else '')
 today=cas.today()
 completed=sum(date(year,m['month'],1)<date(today.year,today.month,1) for m in active)
 current=sum(year==today.year and m['month']==today.month for m in active)
 future=n-completed-current
 period_note=(f'Roční rozsah podle uložených období: {n} měsíců; dokončené {completed}, probíhající {current}, předpokládané budoucí {future}. Budoucí měsíce zatím neproběhly.' if future or current else '')
 sections=[]
 def field(section,key,value,status='known',unit='Kč',note=''):
  human,official,meaning,source=LABELS[key];agency,form=FORMS[section]
  if section=='tax' and key=='base':human='Dílčí základ daně § 7';official='Dílčí základ daně (ztráta) ze samostatné činnosti'
  mapping=(r or {}).get('form_fields',{}).get(section+'.'+key,{})
  official=mapping.get('official_label',official);meaning=mapping.get('description',meaning);source=mapping.get('source_note',source)
  row=mapping.get('row_number') if (r or {}).get('form_rows_confirmed') else None
  destination=f'{agency} → {form} → {official}'+(f' → řádek {row}' if row is not None else '')
  return {'form_year':year,'form_type':section,'field_key':key,'official_label':official,'row_number':row,'source_note':source,'label':human,'value':value,'status':('missing' if value is None and status=='known' else status),'unit':unit,'tooltip':f'{meaning} Zdroj: {source}. Kam patří: {destination}. '+note,'destination':destination,'note':note}
 f=lambda key,value,status='known',unit='Kč',note='':field('tax',key,value,status,unit,note)
 sections.append({'key':'tax','title':FORMS['tax'][0],'form':FORMS['tax'][1],'fields':[f('income',ev['income'],'review' if ev['issues'] else 'known'),f('expenses',cost,expense_state,note=expense_note),f('result',result,result_state,note=expense_note),f('method',profile.OPTIONS['expense_method'].get(p.get('expense_method')),'known',''),f('adjustment',adjustment),f('base',base,base_state,note=expense_note)]})
 def advance_field(key,zero_advance,state,advance_note):
  if zero_advance:return field(key,'advance',D(0),'known',note=advance_note)
  if state!='known':return field(key,'advance',None,'info',note=advance_note)
  value,note=nova_zaloha(key,year,base,n,p,main,secondary,health_min)
  if value is None:return field(key,'advance',None,'info',note=note+'. '+advance_note)
  f=field(key,'advance',value,'known',note=note)
  f['tooltip']=f"{LABELS['advance'][2]} Kam patří: {f['destination']}. {note}"   # popis z pravidel roku (2026.json) platí pro neověřenou zálohu
  return f
 for key,assessment,premium,state in [('social',social_base,social_premium,social_state),('health',health_base,health_premium,health_state)]:
  paid=amount(key+'_paid');items=[field(key,'base',base,base_state,note=expense_note),field(key,'months',n if known_months else None,'known','měsíců',period_note)]
  if key=='social':items += [field(key,'main',main if social_months_ready else None,'known','měsíců'),field(key,'secondary',secondary if social_months_ready else None,'known','měsíců'),field(key,'reason',', '.join(sorted({(r or {}).get('secondary_reasons',{}).get(m.get('reason'),m.get('reason') or 'Chybí důvod') for m in active if m.get('social')=='secondary'})) or ('Nevztahuje se' if known_months and not secondary else None),'known','')]
  else:items += [field(key,'insurer',insurers.description(p) or None,'known',''),field(key,'employment',sum(m.get('employment') in ('insured','uninsured') for m in active) if not missing['employment'] and known_months else None,'known','měsíců'),field(key,'minimum',health_min if not health_inputs and known_months else None,'known','měsíců')]
  if key=='social' and not social_months_ready:
   items[-1]=field(key,'reason',None,'missing','')
  zero_advance=(key=='social' and no_social_participation) or (key=='health' and state=='known' and n>0 and health_min==0 and all(m.get('health_employment')=='yes' for m in active))
  advance_note=(f'Při pokračování vedlejší SVČ bez dobrovolné účasti po podání přehledu: záloha 0 Kč. Změna na hlavní činnost nebo dobrovolné přihlášení v roce {year+1} vyžaduje nové posouzení.' if key=='social' else f'Při pokračování celoměsíčního zaměstnání jako hlavního zdroje a splnění zaměstnaneckého minima se zálohy neplatí. Změna okolností v roce {year+1} vyžaduje nové posouzení.') if zero_advance else f'Pro zálohu roku {year+1} je nutné ověřit další trvání činnosti, její pojistný režim a pravidla tohoto roku. Nejde o průměr letošního pojistného.'
  if key=='social' and no_social_participation:
   items[0]['tooltip']+=f' Rozhodná částka pro {n} měsíců: {social_threshold} Kč; povinná účast nevzniká a dobrovolná účast není zvolena.'
  items += [field(key,'paid',paid,note='Potvrďte skutečný roční úhrn v Profilu OSVČ; nula není předpokládána.' if paid is None else odhady.get(key,'')),field(key,'assessment',assessment,state),field(key,'premium',premium,state),field(key,'balance',premium-paid if premium is not None and paid is not None else None,'missing' if paid is None else state,note='Chybí potvrzený úhrn zaplacených záloh.' if paid is None else ''),advance_field(key,zero_advance,state,advance_note)]
  items[-1]['label']='Orientační záloha při stejném režimu'

  sections.append({'key':key,'title':FORMS[key][0],'form':FORMS[key][1],'fields':items})
 if p.get('profile_version')==2:
  sources=source_missing(p)
  if missing['identity']:missing['identity']=['Zadejte IČO a načtěte identifikaci z registrů.' if not identity.get('ico') else 'Doplňte identifikaci načtením registrů nebo ruční opravou chybějících údajů.']
  for key in ('business','employment'):missing[key]=sources[key]
  missing['social']=[x for x in missing['social'] if not x.startswith(('Charakter ČSSZ:','Důvod vedlejší SVČ:','Pojištěné zaměstnání:'))]+sources['social']
  missing['health']=[x for x in missing['health'] if not x.startswith('Minimum / výjimka:') and x not in ('Kód pojišťovny','Pojištění od','Pojištění do')]+sources['health']
  if p.get('overrides_enabled'):
   if any(m.get('activity')=='yes' and m.get('social')=='secondary' and (not m.get('reason') or (m.get('reason')=='employment' and m.get('employment')!='insured')) for m in months):missing['social'].append('Zkontrolujte vzájemný soulad ručních korekcí ČSSZ.')
   if any(m.get('activity')=='yes' and m.get('minimum') in ('no','auto') and not (m.get('minimum')=='no' and m.get('health_reason')=='state') and not (m.get('health_employment')=='yes' and m.get('employment') in ('insured','uninsured') and (m.get('minimum')=='auto' or m.get('health_reason')=='employment')) for m in months):missing['health'].append('Zkontrolujte podklady ruční výjimky ze zdravotního minima.')
  if not p.get('insurer_code') and 'Zdravotní pojišťovna' not in missing['health']:missing['health'].append('Zvolte zdravotní pojišťovnu.')
  if p.get('health_changed')=='yes':reviews.append('Změna pojišťovny během roku vyžaduje rozdělení přehledů a kontrolu.')
  for key in missing:missing[key]=list(dict.fromkeys(x.rstrip('.') for x in missing[key]))
 for section in sections:
  for item in section['fields']:
   key=item['field_key'];state=item['status'];reasons=[]
   if state=='review':
    if section['key']=='tax':
     reasons=ev['issues'] if key=='income' else expense_reasons if key=='expenses' else list(ev['issues'])+expense_reasons if key in ('result','base') else tax_reasons
    elif key=='base':reasons=list(ev['issues'])+expense_reasons
    elif key=='advance':reasons=[item['note']]
    else:
     reasons=list(ev['issues'])+expense_reasons if base_state=='review' else []
     if section['key']=='social':
      if main and secondary:reasons.append('Kombinace hlavní a vedlejší SVČ vyžaduje individuální výpočet.')
      if p.get('social_case') not in ('standard','new20'):reasons.append('Profil ČSSZ obsahuje zvláštní pojistné okolnosti.')
      if any(m.get('reason') not in ('employment',None,'') for m in active if m.get('social')=='secondary'):reasons.append('Důvod vedlejší SVČ není podporován automatickým výpočtem.')
     else:
      period=resolve_year_period(year,p.get('health_from'),p.get('health_to'))
      if any(not(period['effective_from']<=date(year,m['month'],1)<=period['effective_to']) for m in active):reasons.append('Období zdravotního pojištění nepokrývá všechny aktivní měsíce.')
      if p.get('health_case')!='standard' or p.get('health_changed')=='yes':reasons.append('Změna pojišťovny nebo zvláštní zdravotní režim vyžaduje samostatnou kontrolu.')
    if not r:reasons.append(PRAVIDLA_CHYBI.format(year))
   elif state=='missing':
    reasons=[item['note']] if item['note'] else (missing['tax']+missing['vehicles'] if section['key'] in ('social','health') and key in ('base','assessment','premium','balance') and base_state=='missing' else missing.get(section['key'],[]))
    if not reasons:reasons=['Chybí vstup pro položku '+item['label']+'.']
   item['status_reason']=' '.join(dict.fromkeys(x for x in reasons if x))
  section['status']='missing' if any(f['status']=='missing' for f in section['fields']) else 'review' if any(f['status']=='review' for f in section['fields']) else 'known'
  section['status_reason']=' '.join(dict.fromkeys(f['status_reason'] for f in section['fields'] if f['status']==section['status'] and f['status_reason']))
 for section in sections:
  section['missing']=[f['label'] for f in section['fields'] if f['status']=='missing'];section['review']=[f['label'] for f in section['fields'] if f['status']=='review']
 from .profile_status import evaluate
 completeness=evaluate(p,missing,sections)
 missing=completeness['missing']
 return {'profile_status':completeness,'year':year,'identity':identity,'profile':p,'rules':r,'sections':sections,'missing':missing,'reviews':reviews,'counts':ev['counts'],'vehicles':comparisons,'expense_summary':{'recorded':ev.get('recorded_expenses'),'ordinary_total':ev.get('ordinary_total'),'confirmed':money(ev['ordinary']+transport) if not missing['vehicles'] else None,'excluded':ev.get('excluded_expenses',D(0)),'pending':ev.get('unknown_expenses',D(0)),'pending_count':len(ev.get('unknown_ids',[])),'items':ev.get('pending_expenses',[]),'travel':money(sum((v['travel'] for v in ev['vehicles'].values()),D(0))),'fuel':money(sum((v['fuel'] for v in ev['vehicles'].values()),D(0)))},'social_threshold':social_threshold,'period_note':period_note,'period_counts':{'completed':completed,'current':current,'future':future},'nezapocteno':moduly_nezapocteno(ev),'snapshot_version':1}

def moduly_nezapocteno(ev):
 from .moduly import nezapocteno_text
 return nezapocteno_text(ev.get('nezapocteno') or {})

def display(f):
 if f['value'] is None:return '—'
 if f['unit']=='Kč':return f"{D(f['value']):,.2f}".replace(',',' ').replace('.',',')+' Kč'
 return str(f['value'])+(' '+f['unit'] if f['unit'] else '')
