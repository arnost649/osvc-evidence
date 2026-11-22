"""Interval facts are authoritative; monthly rows are a reproducible compatibility projection."""
from calendar import monthrange
from copy import deepcopy
from datetime import date,timedelta
import json
from .year_periods import resolve_year_period

from .insurers import names,hydrate
INSURERS=names() # compatibility for older integrations; UI reads the current directory

MONTH_KEYS=('activity','employment','social','reason','minimum','health_reason','health_employment')

def interval(raw,year):
 resolved=resolve_year_period(year,raw.get('from'),raw.get('to'))
 return resolved['effective_from'],resolved['effective_to']

def prazdne(item):
 """Období bez data Od i Do – neukládá se a nepočítá (dřív by znamenalo celý rok)."""
 return not ((item or {}).get('from') or (item or {}).get('to'))

def platna(periods):
 """Období s aspoň jedním datem (prázdná se ignorují i u starších uložených dat)."""
 return [x for x in (periods or []) if not prazdne(x)]

def zacatek(periods):
 """Začátek nejdřívějšího platného období: ISO datum, '' = od začátku roku (Od prázdné), None = žádné období."""
 platne=platna(periods)
 if not platne:return None
 return min((x.get('from') or '') for x in platne)

def overlap(a,b):return max(a[0],b[0])<=min(a[1],b[1])

def covers(periods,first,last):
 cursor=first
 for start,end in sorted(periods):
  if end<cursor:continue
  if start>cursor:return False
  if end>=last:return True
  cursor=end+timedelta(days=1)
 return False

def project(year,p):
 p=deepcopy(p)
 if p.get('profile_version')!=2:return p
 for key in ('expense_adjustment','base_adjustment'):
  if p.get(key) in ('',None):p[key]='0'
 if not p.get('social_voluntary'):p['social_voluntary']='no'
 hydrate(p)
 # prázdné období (bez Od i Do) se nepočítá – bez platného období je údaj chybějící, ne „celý rok“
 business=[interval(x,year) for x in platna(p.get('business_periods'))] if p.get('business_status')=='yes' else []
 jobs=[(interval(x,year),x) for x in platna(p.get('employment_periods'))] if p.get('employment_status')=='yes' else []
 rows=[]
 for m in range(1,13):
  first,last=date(year,m,1),date(year,m,monthrange(year,m)[1]);window=(first,last)
  active=[(max(a,first),min(b,last)) for a,b in business if overlap((a,b),window)]
  present=[(i,j) for i,j in jobs if overlap(i,window)]
  insured=[(i,j) for i,j in present if j.get('insured')=='yes' and any(overlap(i,a) for a in active)]
  uncertain=any(j.get('insured') not in ('yes','no') and any(overlap(i,a) for a in active) for i,j in present)
  employed=('insured' if any(j.get('insured')=='yes' for i,j in present) else 'uninsured') if present else ('no' if p.get('employment_status')=='no' or (p.get('employment_status')=='yes' and jobs) else '')
  row={'month':m,'activity':('yes' if active else 'no') if business or p.get('business_status')=='no' else '', 'employment':employed,'social':'','reason':'','minimum':'','health_reason':'','health_employment':'no'}
  if active and (p.get('employment_status')=='no' or (p.get('employment_status')=='yes' and jobs)):
   if insured:row.update(social='secondary',reason='employment')
   elif not uncertain:row['social']='main'
  # Health tests whole calendar coverage independently from social overlap.
  eligible=[i for i,j in present if j.get('health_conditions')=='yes']
  unknown=[i for i,j in present if j.get('health_conditions') not in ('yes','no')]
  if active and (p.get('employment_status')=='no' or (p.get('employment_status')=='yes' and jobs)):
   if covers(eligible,first,last):row.update(minimum='auto',health_reason='employment',health_employment='yes')
   elif not covers(eligible+unknown,first,last):row['minimum']='yes'
  if p.get('overrides_enabled'):row.update({k:v for k,v in p.get('month_overrides',{}).get(str(m),{}).items() if k in MONTH_KEYS and v})
  rows.append(row)
 p['months']=rows
 periods=platna(p.get('business_periods'))
 p['start']=zacatek(periods) or '';p['end']=max((x.get('to','') for x in periods),default='') if periods and all(x.get('to') for x in periods) else ''
 emp=platna(p.get('employment_periods')) if p.get('employment_status')=='yes' else []
 p['employment_from']=min(((x.get('from') or '') for x in emp),default='');p['employment_to']=max((x.get('to','') for x in emp),default='') if emp and all(x.get('to') for x in emp) else ''
 return p

def prepare(year,p):
 """Read-only adapter. Legacy manual rows stay explicit until user releases them."""
 p=deepcopy(p)
 if p.get('profile_version')==2:return project(year,p)
 p['profile_version']=2
 p['business_periods']=[{'from':p['start'],'to':p.get('end','')}] if p.get('start') else []
 p['business_status']='yes' if p['business_periods'] else ''
 p['employment_periods']=[{'from':p['employment_from'],'to':p.get('employment_to',''),'insured':'','health_conditions':''}] if p.get('employment_from') else []
 p['employment_status']='yes' if p['employment_periods'] else ('no' if all(m.get('employment')=='no' for m in p['months']) else '')
 p['month_overrides']={str(m['month']):{k:m[k] for k in MONTH_KEYS if m.get(k)} for m in p['months'] if any(m.get(k) for k in MONTH_KEYS)}
 p['overrides_enabled']=bool(p['month_overrides']);p['legacy_overrides']=p['overrides_enabled']
 return project(year,p)

def parse_periods(form,kind,year):
 try:items=json.loads(form.get(kind+'_periods','[]'))
 except (ValueError,TypeError):raise ValueError('Neplatná období.')
 if not isinstance(items,list) or len(items)>40:raise ValueError('Neplatný počet období (nejvýše 40).')
 result=[]
 for item in items:
  if not isinstance(item,dict):raise ValueError('Neplatné období.')
  if prazdne(item):
   if kind=='employment' and any(item.get(k) for k in ('insured','health_conditions')):raise ValueError('Zaměstnání: doplňte datum Od nebo Do, nebo období odeberte.')
   continue   # prázdné období se neukládá (nepočítá se jako celý rok)
  try:a,b=interval(item,year)
  except (ValueError,KeyError,TypeError):raise ValueError('Doplňte platné datum začátku období.')
  row={'from':item.get('from') or '', 'to':item.get('to') or ''}
  if kind=='employment':
   for key in ('insured','health_conditions'):
    value=item.get(key,'')
    if value not in ('','yes','no'):raise ValueError('Neplatné potvrzení zaměstnání.')
    row[key]=value
  result.append(row)
 return sorted(result,key=lambda x:x['from'])

def source_missing(p):
 missing={k:[] for k in ('business','employment','social','health')}
 if p.get('business_status') not in ('yes','no'):missing['business'].append('Doplňte období podnikání nebo potvrďte rok bez činnosti.')
 elif p.get('business_status')=='yes' and not platna(p.get('business_periods')):missing['business'].append('Doplňte období podnikání (datum Od nebo Do).')
 if p.get('employment_status') not in ('yes','no'):missing['employment'].append('Uveďte, zda jste byl/a zaměstnán/a.')
 elif p.get('employment_status')=='yes' and not platna(p.get('employment_periods')):missing['employment'].append('Doplňte období zaměstnání (datum Od nebo Do).')
 if any(m.get('activity')=='yes' and not m.get('social') for m in p['months']) and not missing['business'] and not missing['employment']:missing['social'].append('Potvrďte účast zaměstnání na pojištění pro vedlejší SVČ.')
 if any(m.get('activity')=='yes' and not m.get('minimum') for m in p['months']) and not missing['business'] and not missing['employment']:missing['health'].append('Potvrďte podmínky zdravotního pojištění v období zaměstnání.')
 return missing
