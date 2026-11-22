"""Permanent identity and explicitly entered yearly facts, separate from rules."""
import json,re
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
from .db import query,connection
from .db import IntegrityError

MONTHS=['Leden','Únor','Březen','Duben','Květen','Červen','Červenec','Srpen','Září','Říjen','Listopad','Prosinec']
IDENTITY={'ico':'IČO','name':'Jméno / obchodní jméno','dic':'DIČ','street':'Ulice','number':'Číslo domu','city':'Obec','zip':'PSČ','country':'Stát'}
POBYT={'street':'Ulice','number':'Číslo domu','city':'Obec','zip':'PSČ'}   # 1.0.3: trvalý pobyt jinde než adresa podnikání (určuje FÚ a OSSZ)

def parse_pobyt(form,prefix):
 """Zaškrtnutí „Trvalý pobyt je jinde než adresa podnikání“ + adresa. Vrátí (pobyt_jinde 'ano'/'', adresa dict nebo None). Chyba = ValueError."""
 if form.get(prefix+'pobyt_jinde')!='ano':return '',None
 adresa={k:' '.join((form.get(prefix+'pobyt_'+k) or '').split())[:200 if k!='zip' else 10] for k in POBYT}
 adresa['zip']=re.sub(r'\s','',adresa['zip'])
 if not adresa['number'] or not adresa['city'] or not adresa['zip']:raise ValueError('Vyplňte adresu trvalého pobytu: číslo domu, obec a PSČ.')
 if not re.fullmatch(r'\d{5}',adresa['zip']):raise ValueError('PSČ trvalého pobytu musí mít 5 číslic.')
 return 'ano',adresa
# key, human label, widget, help: one source for profile UI and documentation.
FIELDS={
 'business': [('start','Zahájení / obnovení','date','Datum je pomocné. Rozhodující jsou potvrzené měsíce aktivity níže; lze je předvyplnit tlačítkem z období.'),('end','Přerušení / ukončení','date','Poslední den činnosti v období. Při více přerušeních upravte jednotlivé měsíce; ovlivní přehledy obou pojištění.')],
 'employment':[('employment_from','Zaměstnání od','date','Období zaměstnání je pomocné; pro výpočty potvrďte po měsících účast na pojištění.'),('employment_to','Zaměstnání do','date','Konec období zaměstnání, pokud nastal. Prázdný konec znamená pokračující zaměstnání.'),('employer','Zaměstnavatel (volitelně)','text','Pouze identifikace zaměstnavatele pro vaši kontrolu. Mzdu zde neevidujeme.')],
 'social':[('social_paid','Zaplacené zálohy ČSSZ','money','Součet skutečně zaplacených záloh na důchodové pojištění OSVČ za tento rok, podle ePortálu ČSSZ. Použije se při ročním Přehledu OSVČ pro ČSSZ; nula znamená potvrzené nulové platby.'),('social_case','Okolnosti výpočtu ČSSZ','social_case','Běžný případ znamená bez důchodové slevy, celoměsíčních dávek, zahraničního pojištění a bez dosažení společného maxima se zaměstnáním. Jiný případ vyžaduje individuální výpočet. Snížené minimum platí pro první zahájení po 20 letech v roce zahájení a dalších dvou letech.'),('social_voluntary','Dobrovolná účast při vedlejší SVČ','yesno','Potvrďte, zda se hlásíte k důchodovému pojištění i pod rozhodnou částkou. Ovlivní roční pojistné ČSSZ.')],
 'health':[('insurer','Zdravotní pojišťovna','text','Název pojišťovny, pro kterou připravujeme Přehled o výši daňového základu OSVČ.'),('insurer_code','Kód pojišťovny','text','Třímístný kód vaší zdravotní pojišťovny. Systém jej neodvozuje z ČSSZ.'),('health_from','Pojištění od','date','Prázdné = od začátku zvoleného roku. Změna pojišťovny během aktivního podnikání vyžaduje rozdělení a individuální kontrolu.'),('health_to','Pojištění do','date','Konec období u uvedené pojišťovny. Prázdné = do konce zvoleného roku.'),('health_paid','Zaplacené zálohy zdravotního pojištění','money','Úhrn skutečně zaplacených záloh. Lze ověřit v Moje VZP. Potvrďte roční úhrn, včetně případné nuly.'),('health_case','Okolnosti zdravotního pojištění','health_case','Běžný případ: jedna pojišťovna a české pojištění po celou dobu činnosti, bez dalších zvláštních okolností. Jiný případ nepočítáme automaticky.')],
 'tax':[('unknown_expenses','Výdaje bez potvrzeného daňového podílu','unknown_expenses','U starších výdajů nemusí být určen daňový podíl. Výslovně potvrďte plné zahrnutí po kontrole, nebo je vylučte. Částečné krácení proveďte korekcí výdajů; nikdy se tiše nepovažují za uznatelné.'),('expense_method','Způsob uplatnění daňových výdajů','expense_method','Skutečné výdaje vycházejí z evidence a režimu vozidel. Procentní výdajový paušál vychází z příjmů a sazby pro daný rok; nepřičítají se k němu výdaje na vozidla. Nejde o paušální daň.'),('expense_rate','Druh činnosti pro procentní paušál','expense_rate','Sazba a limit podle zvoleného roku. Pokud máte více druhů činnosti s odlišnými sazbami, zvolte individuální kontrolu; nelze použít jednu sazbu na všechny příjmy.'),('tax_case','Daňový režim','tax_case','Běžná daňová evidence neplátce DPH po celý rok, jedné činnosti v Kč. Plátcovství DPH, paušální daň, souběh různých sazeb, účetnictví nebo zvláštní příjmy vyžadují individuální posouzení.'),('expense_adjustment','Korekce uznatelných výdajů (+/−)','signed','Ruční korekce evidence: např. vyloučení vlastního pojistného, soukromých výdajů, parkovného při paušálu dopravy nebo krácení ostatních nákladů. Zdroj: vaše kontrola. Pro Finanční úřad ovlivní výdaje; při procentním paušálu se nepoužije.'),('base_adjustment','Úpravy základu daně (+/−)','signed','Daňové úpravy nad rámec evidence, např. při změně režimu výdajů. Zdroj: vaše kontrola. Nula znamená, že jste ověřili, že žádné nejsou.'),('tax_review','Evidence a daňové korekce ověřeny','yesno','Potvrďte úplnost příjmů, daňové podíly výdajů, korekce a oprávněnost režimu dopravy. Tato kontrola je nutná, protože evidence sama nezná všechny daňové okolnosti.')]
}
OPTIONS={
 'unknown_expenses':{'include':'Po kontrole zahrnout; krácení zadám korekcí','exclude':'Daňově nezahrnovat'},
 'yesno':{'yes':'Ano','no':'Ne'},'social_case':{'standard':'Běžný případ – ověřeno','new20':'Snížené minimum při prvním zahájení po 20 letech','other':'Zvláštní okolnosti – kontrola'},'health_case':{'standard':'Běžný případ – ověřeno','other':'Zvláštní okolnosti / změna pojišťovny'},'expense_method':{'actual':'Skutečné výdaje','percentage':'Procentní výdajový paušál'},'tax_case':{'standard':'Daňová evidence neplátce DPH – jedna činnost','other':'DPH / paušální daň / více sazeb / jiný režim'},
 'activity':{'yes':'Aktivní','no':'Neaktivní'},'employment':{'no':'Bez zaměstnání','insured':'Zaměstnání s účastí na pojištění','uninsured':'Zaměstnání bez účasti na pojištění'},'social':{'main':'Hlavní','secondary':'Vedlejší'},'minimum':{'auto':'Automaticky','yes':'Minimum platí','no':'Výjimka z minima'},'health_reason':{'employment':'Zaměstnání – potvrzené podmínky','state':'Státní pojištěnec celý měsíc','other':'Jiná výjimka – kontrola'},'vehicle_method':{'actual':'Skutečné náklady / cestovní náhrady','flat':'Paušální výdaj na dopravu','none':'Neuplatňovat daňově'},'actual_basis':{'travel':'Cestovní náhrady z Jízd (včetně paliva)','fuel':'Skutečné platby PHM (bez náhrad z Jízd)'},'private':{'no':'Výlučně podnikání','yes':'I soukromé použití'}
}
MONTH_HELP={
 'activity':'Potvrďte každý měsíc i bez činnosti. Zdroj: roční profil. Počet aktivních měsíců se použije v přehledech ČSSZ a zdravotní pojišťovny.',
 'employment':'Zaměstnání se eviduje nezávisle na SVČ. Pro ČSSZ je rozhodující, zda zakládá účast na pojištění; mzdu nevyplňujete.',
 'social':'ČSSZ posuzuje hlavní či vedlejší SVČ v každém aktivním měsíci. Při vedlejší činnosti potvrďte důvod. Zdravotní režim se tím nenastavuje.',
 'health':'Minimum zdravotního pojištění se neposuzuje podle ČSSZ. U automatické výjimky zaměstnání potvrďte, že souběh trval celý měsíc, zaměstnání bylo hlavním zdrojem a pojistné z něj dosáhlo minima. Jinou neověřenou situaci označíme ke kontrole.',
 'vehicle':'Paušální výdaj na dopravu není procentní výdajový paušál. Jeden režim platí pro celé vozidlo a rok. Jízdy, PHM a účtenky se nemažou. U skutečných nákladů vyberte buď náhrady z Jízd, nebo platby PHM, aby se palivo nezapočetlo dvakrát.',
 'vehicle_eligible':'Pro paušál potvrďte celé způsobilé měsíce, vlastní či najaté vozidlo, splnění zákonných podmínek a nepřenechání jiné osobě. Nejvýše tři vozidla; ostatní náklady a parkovné zkontrolujte v daňových korekcích.'
}

def rules(year):
 p=Path(__file__).parent/'tax_rules'/f'{year}.json'
 return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None

def zalohy(year):
 """Parametry nové měsíční zálohy placené v roce `year` (tax_rules/zalohy-YYYY.json, jen z oficiálních zdrojů), jinak None."""
 p=Path(__file__).parent/'tax_rules'/f'zalohy-{year}.json'
 return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None

def load(year):
 permanent=query('SELECT * FROM osvc_profile WHERE id=1',one=True)
 annual=query('SELECT * FROM osvc_year_profiles WHERE tax_year=%s',(year,),one=True)
 identity=json.loads(permanent['data']) if permanent else {}
 data=json.loads(annual['data']) if annual else {}
 data.setdefault('months',[{'month':m} for m in range(1,13)]);data.setdefault('vehicles',{})
 from .profile_periods import project
 data=project(year,data)
 return identity,data,permanent['revision'] if permanent else 0,annual['revision'] if annual else 0

def vehicles():
 return query('SELECT id,name,registration_plate FROM vehicles ORDER BY name')

def _parse_legacy(form,year,old_identity):
 identity={k:form.get('identity_'+k,'').strip()[:200] for k in IDENTITY}
 if identity['ico'] and not re.fullmatch(r'\d{8}',identity['ico']):raise ValueError('IČO musí mít 8 číslic.')
 identity['ares']=old_identity.get('ares') if all(identity.get(k)==old_identity.get(k) for k in IDENTITY) else None
 identity['pobyt_jinde'],identity['pobyt']=parse_pobyt(form,'identity_')
 data={'months':[],'vehicles':{}}
 opts={**OPTIONS,'expense_rate':{k:v['label'] for k,v in (rules(year) or {}).get('expense_rates',{}).items()}}
 for fields in FIELDS.values():
  for key,label,kind,help in fields:
   value=form.get(key,'').strip()
   if len(value)>500:raise ValueError(label+': příliš dlouhá hodnota.')
   if kind in ('money','signed') and value:
    try:d=Decimal(value.replace(' ','').replace(',','.'))
    except InvalidOperation:raise ValueError(label+': zadejte číslo.')
    if not d.is_finite() or abs(d)>Decimal('100000000000') or (kind=='money' and d<0):raise ValueError(label+': neplatná částka.')
    if d!=d.quantize(Decimal('.01')):raise ValueError(label+': nejvýše dvě desetinná místa.')
    value=str(d)
   elif kind=='date' and value:
    try:dt=date.fromisoformat(value)
    except ValueError:raise ValueError(label+': neplatné datum.')
    if not 1900<=dt.year<=2100:raise ValueError(label+': nepodporovaný rok.')
    if key in ('health_from','health_to') and dt.year!=year:raise ValueError(label+': vymezte období pojištění ve zvoleném roce.')
   elif kind in opts and value and value not in opts[kind]:raise ValueError(label+': neplatná volba pro tento rok.')
   data[key]=value
 for start,end in [('start','end'),('employment_from','employment_to'),('health_from','health_to')]:
  if data[start] and data[end] and data[start]>data[end]:raise ValueError('Konec období nesmí předcházet začátku.')
 if data['insurer_code'] and not re.fullmatch(r'\d{3}',data['insurer_code']):raise ValueError('Kód zdravotní pojišťovny musí mít tři číslice.')
 secondary=(rules(year) or {}).get('secondary_reasons',{'employment':'Zaměstnání','other':'Jiný důvod'})
 for m in range(1,13):
  row={'month':m}
  for key,allowed in [('activity',OPTIONS['activity']),('employment',OPTIONS['employment']),('social',OPTIONS['social']),('reason',secondary),('minimum',OPTIONS['minimum']),('health_reason',OPTIONS['health_reason']),('health_employment',OPTIONS['yesno'])]:
   v=form.get(f'm{m}_{key}','')
   if v and v not in allowed:raise ValueError('Neplatná měsíční volba.')
   row[key]=v
  data['months'].append(row)
 for v in vehicles():
  ident=str(v['id']);row={}
  for key in ['vehicle_method','actual_basis','private','eligible']:
   value=form.get(f'v{ident}_{key}','');allowed=OPTIONS['yesno'] if key=='eligible' else OPTIONS[key]
   if value and value not in allowed:raise ValueError('Neplatný režim vozidla.')
   row[key]=value
  for key in ['from','to']:
   value=form.get(f'v{ident}_{key}','')
   if value and value not in [str(n) for n in range(1,13)]:raise ValueError('Měsíc vozidla musí být 1 až 12.')
   row[key]=int(value) if value else None
  if row['from'] and row['to'] and row['from']>row['to']:raise ValueError('Neplatné období vozidla.')
  data['vehicles'][ident]=row
 return identity,data

def zachovej_odhad_zaloh(old,new):
 """Měsíční zálohy z průvodce (odhad ročního úhrnu) zůstanou, dokud uživatel nezadá skutečný roční úhrn."""
 for key in ('social','health'):
  if old.get(key+'_advance_month') not in ('',None) and new.get(key+'_paid') in ('',None):new[key+'_advance_month']=old[key+'_advance_month']
 return new

def save(year,identity,data,identity_rev,annual_rev):
 data=dict(data)
 if data.get('insurance_code'):
  data.pop('insurer',None);data.pop('insurer_code',None)
 c=connection()
 try:
  c.begin()
  with c.cursor() as cur:
   for table,key,val,payload,rev in [('osvc_profile','id',1,identity,identity_rev),('osvc_year_profiles','tax_year',year,data,annual_rev)]:
    if rev:
     cur.execute(f'UPDATE {table} SET data=%s,revision=revision+1 WHERE {key}=%s AND revision=%s',(json.dumps(payload,ensure_ascii=False),val,rev))
     if cur.rowcount!=1:raise ValueError('Profil byl mezitím změněn. Obnovte stránku a zadejte změny znovu.')
    else:cur.execute(f'INSERT INTO {table} ({key},data) VALUES (%s,%s)',(val,json.dumps(payload,ensure_ascii=False)))
  c.commit()
 except IntegrityError as exc:
  c.rollback();raise ValueError('Profil byl mezitím založen. Obnovte stránku a zkontrolujte změny.') from exc
 except Exception:c.rollback();raise
 finally:c.close()


def parse(form,year,old_identity):
 if form.get('profile_version')!='2':return _parse_legacy(form,year,old_identity)
 from .profile_periods import parse_periods,project,INSURERS,MONTH_KEYS
 f=form.copy()
 # Compatibility fields remain internal. Posted technical months are only explicit overrides.
 for key in ('start','end','employment_from','employment_to'):f[key]=''
 for key in ('expense_adjustment','base_adjustment'):
  if not f.get(key):f[key]='0'
 from . import insurers
 code=f.get('insurance_code',f.get('insurer_code',''))
 if form.get('insurer_query','').strip() and not code:raise ValueError('Neplatná nebo neznámá zdravotní pojišťovna. Vyberte z nabídky.')
 row=insurers.lookup(code) if code else None
 if code and (not row or not row['active']):raise ValueError('Neplatná nebo neznámá zdravotní pojišťovna.')
 f['insurer_code']=code
 if row:f['insurer']=row['name']
 for key in ('social_case','health_case','tax_case'):
  if not f.get(key):f[key]='standard'   # běžný případ, dokud uživatel výslovně nezvolí zvláštní okolnosti (nezávisí na potvrzení kontroly)
 if not f.get('social_voluntary'):f['social_voluntary']='no'
 for v in vehicles():
  key='v'+str(v['id'])+'_actual_basis'
  if not f.get(key):f[key]='travel'
 identity,data=_parse_legacy(f,year,old_identity)
 if old_identity.get('registry') and identity.get('ico')==old_identity.get('ico'):identity['registry']=old_identity['registry']
 data['profile_version']=2
 for kind in ('business','employment'):
  status=form.get(kind+'_status','')
  if status not in ('','yes','no'):raise ValueError('Neplatný stav období.')
  data[kind+'_status']=status
  data[kind+'_periods']=parse_periods(form,kind,year)
 data['insurance_code']=code
 if form.get('insurer_directory_ui')=='1':
  data['user_confirmed_insurer']=form.get('user_confirmed_insurer')=='yes'
  if code and not data['user_confirmed_insurer']:raise ValueError('Potvrďte, že jste u vybrané pojišťovny pojištěn(a).')
 data['verified_registry']=bool(row and row['active'])
 data['health_changed']=form.get('health_changed','')
 if form.get('insurer_directory_ui')=='1':
  try:periods=json.loads(form.get('insurance_periods','[]'))
  except (TypeError,ValueError):raise ValueError('Neplatná období pojištění.')
  data['insurance_periods']=insurers.validate_periods(year,periods) if data['health_changed']=='yes' else []
 if data['health_changed']=='yes':data['health_case']='other'
 data['overrides_enabled']=form.get('overrides_enabled')=='yes'
 data['month_overrides']={str(m['month']):{k:m[k] for k in MONTH_KEYS if m.get(k)} for m in data['months'] if any(m.get(k) for k in MONTH_KEYS)}
 if form.get('paid_confirmation_ui')=='1':
  data['payment_confirmed']={}
  for key in ('social_paid','health_paid'):
   value=data.get(key)
   confirmed=value not in ('',None) and (Decimal(value)>0 or form.get(key+'_confirmed')=='yes')
   data['payment_confirmed'][key]=confirmed
   if not confirmed:data[key]=''
 data['payment_sources']={'social_paid':'manual','health_paid':'manual'}
 return identity,project(year,data)

