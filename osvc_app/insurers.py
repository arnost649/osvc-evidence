"""Official institution directory; never a lookup of a person's insurance."""
import json,re
from datetime import date,datetime,timezone,timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request,urlopen
from flask import has_app_context
SOURCE='https://www.vzp.cz/poskytovatele/ciselniky/zdravotni-pojistovny'
SEED=Path(__file__).parent/'data'/'insurers.json'
ALIASES={'111':'VZP','201':'VoZP','205':'ČPZP','207':'OZP','209':'ZPŠ','211':'ZP MV ČR','213':'RBP'}
def path():
 from .backup import state_dir
 return state_dir()/'insurers.json'
def directory():
 p=path() if has_app_context() else SEED
 return json.loads((p if p.exists() else SEED).read_text(encoding='utf-8'))
def entries():return directory()['entries']
def lookup(code):return next((r for r in entries() if r['insurance_code']==str(code)),None)
def names():return {r['insurance_code']:r['name'] for r in entries() if r['active']}
class TableParser(HTMLParser):
 def __init__(self):super().__init__();self.rows=[];self.row=[];self.cell=None
 def handle_starttag(self,tag,attrs):
  if tag=='tr':self.row=[]
  if tag=='td':self.cell=[]
  if tag=='br' and self.cell is not None:self.cell.append(' ')
 def handle_data(self,data):
  if self.cell is not None:self.cell.append(data)
 def handle_endtag(self,tag):
  if tag=='td' and self.cell is not None:self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
  if tag=='tr' and self.row:self.rows.append(self.row)
def parse_registry(html):
 parser=TableParser();parser.feed(html);now=datetime.now(timezone.utc).isoformat();rows=[]
 for row in parser.rows:
  if len(row)==5 and re.fullmatch(r'\d{3}',row[0]) and re.fullmatch(r'\d{8}',row[2]):
   rows.append(dict(insurance_code=row[0],name=row[1],short_name=ALIASES.get(row[0],row[1]),ico=row[2],address=row[3],data_box=row[4],source_url=SOURCE,verified_at=now,active=True))
 if len(rows)<5 or len({r['insurance_code'] for r in rows})!=len(rows):raise ValueError('Oficiální číselník má neočekávaný formát; původní kopie zůstává zachována.')
 return {'source_url':SOURCE,'verified_at':now,'entries':rows}
def refresh():
 with urlopen(Request(SOURCE,headers={'User-Agent':'OSVC-local-directory/1.0'}),timeout=20) as response:
  data=response.read(2_000_001)
 if len(data)>2_000_000:raise ValueError('Číselník překročil povolenou velikost.')
 fresh=parse_registry(data.decode('utf-8'))
 active={r['insurance_code'] for r in fresh['entries']}
 fresh['entries'] += [dict(r,active=False) for r in entries() if r['insurance_code'] not in active]
 from .backup import write_atomic,json_bytes
 write_atomic(path(),json_bytes(fresh))
 return fresh
def hydrate(p):
 """Read adapter: canonical code plus old calculation aliases, no database writes."""
 code=str(p.get('insurance_code') or p.get('insurer_code') or '')
 row=lookup(code)
 p['insurance_code']=code;p['insurer_code']=code
 if row:p['insurer']=row['name']
 p['verified_registry']=bool(row and row['active'])
 if 'user_confirmed_insurer' not in p:
  source=p.get('sources',{}).get('insurer',{})
  p['user_confirmed_insurer']=bool(code and (source.get('source') in ('user_confirmed','manual_override') or p.get('insurer_source')=='user_confirmed')) if isinstance(source,dict) else False
 return p
def validate_periods(year,periods):
 from .year_periods import resolve_year_period
 if not isinstance(periods,list) or not 1<=len(periods)<=12:raise ValueError('Doplňte období zdravotního pojištění.')
 resolved=[]
 for p in periods:
  if not isinstance(p,dict):raise ValueError('Neplatné období pojištění.')
  row=lookup(p.get('insurance_code',''))
  if not row or not row['active']:raise ValueError('Neplatná nebo neznámá zdravotní pojišťovna.')
  span=resolve_year_period(year,p.get('from'),p.get('to'))
  a,b=span['effective_from'],span['effective_to']
  if a is None or b is None or a>b:raise ValueError('Neplatné období pojištění.')
  resolved.append((a,b,p))
 resolved.sort(key=lambda x:x[0]);expected=date(year,1,1)
 for a,b,p in resolved:
  if a!=expected:raise ValueError('Období pojištění se překrývají nebo mezi nimi chybí pokrytí.')
  expected=b+timedelta(days=1)
 if expected!=date(year+1,1,1):raise ValueError('Období pojištění musí pokrýt celý zvolený rok.')
 return [{k:p.get(k,'') for k in ('from','to','insurance_code')} for a,b,p in resolved]

def canonicalize(p):
 """Lossless schema adapter; institution names live only in the directory."""
 p=dict(p);hydrate(p)
 if p['verified_registry']:
  row=lookup(p['insurance_code']);p['insurance_registry_source']=row['source_url'];p['insurance_verified_at']=row['verified_at']
  p.pop('insurer',None);p.pop('insurer_code',None)
 return p

def description(p):
 def title(code):
  row=lookup(code)
  return (row['name']+' · '+code) if row else code
 if p.get('health_changed')=='yes' and p.get('insurance_periods'):
  return '; '.join(title(r['insurance_code'])+' ('+(r.get('from') or 'začátek roku')+' – '+(r.get('to') or 'konec roku')+')' for r in p['insurance_periods'])
 return title(p.get('insurance_code') or p.get('insurer_code') or '')
