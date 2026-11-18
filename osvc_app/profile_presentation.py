"""Read-only presentation of existing profile facts and calculation dependencies."""
from copy import deepcopy
from datetime import date,datetime,timezone
from . import profile
from .year_periods import year_period_text

TITLES={'identity':'Identifikační údaje','business':'Podnikání','employment':'Zaměstnání','social':'ČSSZ','health':'Zdravotní pojištění','tax':'Daňové nastavení','vehicles':'Vozidla a doprava'}
SOURCE_LABELS={'registry':'Registr','internal':'Evidence','derived':'Vypočteno','user_confirmed':'Potvrzeno','imported':'Import','imported_cssz':'Import ČSSZ','manual_override':'Ruční korekce'}

def source(p,key,default='user_confirmed'):
 entry=p.get('sources',{}).get(key,{})
 kind=entry.get('source',default)
 label=SOURCE_LABELS.get(kind,'Zdroj vyžaduje kontrolu')
 if kind=='imported' and entry.get('provider')=='cssz':label='Import ČSSZ'
 return {'source':kind,'label':label,'provider':entry.get('provider')}

def path_value(p,key):
 for part in key.split('.'):
  if not isinstance(p,dict):return None
  p=p.get(part)
 return p

def preserve_sources(old,new):
 """Keep import attribution until its actual fact changes; never accept browser source claims."""
 result=deepcopy(old.get('sources',{}));now=datetime.now(timezone.utc).isoformat()
 keys=['employer','insurer','insurer_code','insurance_code','insurance_periods','user_confirmed_insurer','business_periods','employment_periods','employment_status','business_status','expense_method','expense_rate','social_paid','health_paid','tax_review','month_overrides']
 keys += ['vehicles.'+str(k)+'.'+field for k in new.get('vehicles',{}) for field in ('vehicle_method','actual_basis','private','eligible','from','to')]
 for key in keys:
  value=path_value(new,key)
  if value!=path_value(old,key) and value not in (None,'',[],{}):
   result[key]={'source':'manual_override' if key=='month_overrides' else 'user_confirmed','confirmed_at':now}
  elif value in (None,'',[],{}):result.pop(key,None)
 new['sources']=result
 return new

def short_date(value):
 try:d=date.fromisoformat(value);return f'{d.day}. {d.month}. {d.year}'
 except (ValueError,TypeError):return '—'

def period_text(periods):
 return ' · '.join((short_date(p.get('from')) if p.get('from') else 'začátek roku')+' – '+(short_date(p['to']) if p.get('to') else 'konec roku / trvá') for p in periods) or 'Období neuvedeno'

def build(identity,p,report,vehicles):
 year=report['year']
 from .profile_status import evaluate
 completeness=report.get('profile_status') or evaluate(p,report['missing'],report['sections'])
 missing=completeness['missing']
 rows=p.get('months',[]);active=[m for m in rows if m.get('activity')=='yes'];n=len(active)
 known_activity=all(m.get('activity') in ('yes','no') for m in rows) and len(rows)==12
 social_values={m.get('social') for m in active};social='Vedlejší' if social_values=={'secondary'} else 'Hlavní' if social_values=={'main'} else 'Hlavní i vedlejší' if social_values=={'main','secondary'} else 'Bez činnosti' if known_activity and not n else '—'
 reason='zaměstnání' if active and all(m.get('reason')=='employment' for m in active if m.get('social')=='secondary') and 'secondary' in social_values else ''
 def item(label,value,state='known',src='derived',detail='',target='business'):
  info=source(p,src) if src not in SOURCE_LABELS else {'source':src,'label':SOURCE_LABELS[src]}
  return {'label':label,'value':value or '—','state':state,'source':info['source'],'hint':info['label']+(' · '+detail if detail else ''),'target':target}
 business_state='missing' if missing['business'] else 'known'
 social_fact_state='missing' if any(not m.get('social') for m in active) or not known_activity else 'review' if len(social_values)>1 or any(m.get('reason') not in ('','employment',None) for m in active) else 'known'
 employer=p.get('employer') or ('Zaměstnání' if p.get('employment_status')=='yes' else 'Bez zaměstnání' if p.get('employment_status')=='no' else '—')
 if p.get('employer_ico'):employer+=' · IČO '+p['employer_ico']
 insurer='VZP' if p.get('insurer_code')=='111' else p.get('insurer') or '—'
 method=profile.OPTIONS['expense_method'].get(p.get('expense_method'),'—')
 modes={'actual':'Skutečné náklady','flat':'Paušální výdaj na dopravu','none':'Daňově neuplatňováno'}
 vehicle_text=' · '.join(v['name']+' – '+(profile.OPTIONS['actual_basis'].get(p.get('vehicles',{}).get(str(v['id']),{}).get('actual_basis'),'Skutečné náklady / cestovní náhrady') if p.get('vehicles',{}).get(str(v['id']),{}).get('vehicle_method')=='actual' else modes.get(p.get('vehicles',{}).get(str(v['id']),{}).get('vehicle_method'),'—')) for v in vehicles) or 'Bez vozidla'
 reg=identity.get('registry',{});registered=bool(reg.get('data')) and all(identity.get(k)==reg['data'].get(k) for k in ('ico','name'))
 identification=(identity.get('name') or '—')+(' · IČO '+identity['ico'] if identity.get('ico') else '')
 quick=[item('Identifikace',identification,'missing' if missing['identity'] else 'known','registry' if registered else 'user_confirmed',reg.get('sources',{}).get('name','ARES') if registered else '',target='identity'),
  item('OSVČ',social,social_fact_state,target='social'),
  item('Aktivní od',short_date(p.get('start')) if p.get('start') else 'Začátek roku' if p.get('business_status')=='yes' else '—',business_state if p.get('business_status')!='no' else 'known','business_periods',period_text(p.get('business_periods',[]))),
  item('Aktivita',str(n)+(' měsíc' if n==1 else ' měsíce' if 2<=n<=4 else ' měsíců') if known_activity else '—',business_state,'derived'),
  item('Zaměstnání',employer,'missing' if missing['employment'] else 'known','employer',('Firma: ARES · '+p.get('employer_verified_at','')[:10]+'; ' if p.get('employer_source')=='ARES' else '')+'Pracovní poměr: '+source(p,'employment_periods')['label']+' · '+period_text(p.get('employment_periods',[])),target='employment'),
  item('ČSSZ',social+(' · '+reason if reason else ''),social_fact_state,'derived',target='social'),
  item('Zdravotní',insurer,'known' if p.get('verified_registry') and p.get('user_confirmed_insurer') else 'missing','insurer',target='health'),
  item('Daňové výdaje',method,'known' if p.get('expense_method') and (p.get('expense_method')!='percentage' or p.get('expense_rate')) else 'missing','expense_method',target='tax'),
  item('Vozidlo',vehicle_text,'missing' if missing['vehicles'] else 'known','internal','Režim: '+', '.join(source(p,'vehicles.'+str(v['id'])+'.vehicle_method')['label'] for v in vehicles),target='vehicles')]
 from .insurers import lookup
 institution=lookup(p.get('insurance_code') or p.get('insurer_code'))
 if institution:
  insurer=institution['short_name']+' · '+institution['insurance_code']
  for item_row in quick:
   if item_row['label']=='Zdravotní':
    item_row['value']=insurer;item_row['hint']=institution['name']+' · IČO '+institution['ico']+' · oficiální číselník'
 briefs={'identity':identification,'business':('Aktivní od '+(short_date(p.get('start')) if p.get('start') else 'začátku roku')+' · '+str(n)+(' měsíc' if n==1 else ' měsíce' if 2<=n<=4 else ' měsíců')) if known_activity and n else 'Bez činnosti' if known_activity else 'Období neuvedeno','employment':employer+' · '+(year_period_text(year,p.get('employment_periods') or [{}]) if p.get('employment_status')=='yes' else 'Bez zaměstnání' if p.get('employment_status')=='no' else 'Období neuvedeno'),'social':social+(' · '+reason if reason else ''),'health':insurer,'tax':method,'vehicles':vehicle_text}
 cards={}
 for key,title in TITLES.items():
  section_status=completeness['sections'][key]
  cards[key]={'title':title,'summary':briefs[key],**section_status,'open':bool(missing[key])}
 for row in quick:
  section_status=completeness['sections'][row['target']]
  row['state']=section_status['state']
  if section_status['reason']:row['hint']+=' · '+section_status['reason']
 issues=[{'key':key,'title':TITLES[key],'items':list(dict.fromkeys(items))} for key,items in missing.items() if items]
 count=sum(len(s['items']) for s in issues)
 return {'quick':quick,'cards':cards,'issues':issues,'missing_count':count,'profile_state':completeness['state'],'profile_status_reason':completeness['reason']}
