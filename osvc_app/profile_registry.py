"""Public identity lookup using the existing official ARES transport only.
No private person/representative/contact data from ROS/RŽP is retained.
"""
from datetime import date,datetime,timezone,timedelta
from . import cas
from functools import lru_cache
from urllib.error import HTTPError
from .ares import _request,_subject,AresUnavailable

@lru_cache(maxsize=24)
def dictionary(code,source,day):
 data=_request('/ciselniky-nazevniky/vyhledat',{'kodCiselniku':code,'zdrojCiselniku':source,'start':0,'pocet':10})
 result={}
 for book in data.get('ciselniky',[]):
  for item in book.get('polozkyCiselniku',[]):
   if item.get('platnostDo') and item['platnostDo']<day:continue
   if item.get('platnostOd') and item['platnostOd']>day:continue
   names=item.get('nazev',[])
   name=next((n.get('nazev') for n in names if n.get('kodJazyka') in ('cs','cz','ces')),None)
   if not name and len(names)==1:name=names[0].get('nazev')
   if name:result[str(item['kod'])]=name
 return result

def named(value,code,source):
 if value is None or value=='':return ''
 value=str(value)
 try:name=dictionary(code,source,cas.today().isoformat()).get(value)
 except AresUnavailable:name=None
 return (name+' ('+value+')') if name else ('Kód '+value)

def lookup(ico):
 statuses=[];sources={};data={};metadata=[];licenses=[]
 def add(label,value,source):
  if value not in ('',None,[],{}):metadata.append({'label':label,'value':str(value),'source':source})
 for title,path in [('ARES','ekonomicke-subjekty'),('ROS','ekonomicke-subjekty-ros'),('RŽP','ekonomicke-subjekty-rzp')]:
  try:raw=_request('/'+path+'/'+ico)
  except AresUnavailable as exc:
   absent=isinstance(exc.__cause__,HTTPError) and exc.__cause__.code==404
   statuses.append({'source':title,'state':'missing' if absent else 'error','message':'Veřejný záznam nenalezen' if absent else 'Zdroj nyní není dostupný'})
   continue
  if str(raw.get('ico',raw.get('icoId','')))!=ico:
   statuses.append({'source':title,'state':'error','message':'Nesouhlasí IČO odpovědi'});continue
  records=[raw] if title=='ARES' else raw.get('zaznamy',[])
  statuses.append({'source':title,'state':'ok' if records else 'missing','message':'Veřejné údaje načteny' if records else 'Veřejný záznam nenalezen'})
  primary=next((r for r in records if r.get('primarniZaznam')),records[0] if len(records)==1 else {})
  if title=='ARES':primary=raw
  if primary and title!='ROS':
   subject=_subject(primary)
   for key,value in subject.items():
    if value and key!='address' and not data.get(key):data[key]=value;sources[key]=title
  if title=='ARES':
   add('Právní forma',named(raw.get('pravniForma'),'PravniForma','res'),title)
   add('Finanční úřad',named(raw.get('financniUrad'),'FinancniUrad','ufo'),title)
   add('Vznik ekonomického subjektu',raw.get('datumVzniku'),title)
   add('Zánik ekonomického subjektu',raw.get('datumZaniku'),title)
   for key,caption,book in [('czNace','CZ-NACE 2025','CzNace'),('czNace2008','CZ-NACE 2008','CzNace2008')]:
    add(caption,'; '.join(named(x,book,'res') for x in raw.get(key,[])),title)
  elif title=='ROS':
   for record in records:
    add('Vznik subjektu dle ROS',record.get('datumVzniku'),title)
    add('Zánik subjektu dle ROS',record.get('datumZaniku'),title)
    # ROS supplies legal/registration status, not a promise that a trade is active.
    legal=record.get('pravniFormaRos') or {}
    if isinstance(legal,dict):
     for k,v in legal.items():
      if k in ('kod','hodnota'):add('Právní forma ROS',named(v,'PravniFormaRos','ros'),title)
  else:
   for record in records:
    state=record.get('zivnostiStav') or {}
    labels={'pocetAktivnich':'Aktivní oprávnění','pocetPrerusenych':'Přerušená oprávnění','pocetPozastavenych':'Pozastavená oprávnění','pocetZaniklych':'Zaniklá oprávnění'}
    for key,label in labels.items():add(label,state.get(key),title)
    for trade in record.get('zivnosti',[]):
     item={k:trade.get(k) for k in ('predmetPodnikani','datumVzniku','datumZaniku','platnostDo','preruseniZivnosti','pozastaveniZivnosti','oboryCinnosti') if trade.get(k)}
     licenses.append(item)
     add('Předmět podnikání',trade.get('predmetPodnikani'),title)
     add('Vznik oprávnění',trade.get('datumVzniku'),title)
     add('Zánik oprávnění',trade.get('datumZaniku'),title)
     add('Platnost oprávnění do',trade.get('platnostDo'),title)
     for key,label in [('preruseniZivnosti','Přerušení oprávnění'),('pozastaveniZivnosti','Pozastavení oprávnění')]:
      for event in trade.get(key,[]):add(label,(event.get('platnostOd') or '?')+' – '+(event.get('platnostDo') or 'dosud'),title)
     for branch in trade.get('oboryCinnosti',[]):
      # Public business descriptions only; do not persist involved persons.
      add('Obor činnosti',branch.get('oborNazev'),title)
 if not data.get('ico'):data['ico']=ico
 return {'data':data,'sources':sources,'metadata':metadata,'licenses':licenses,'suggested_periods':permission_periods(licenses),'statuses':statuses,'at':datetime.now(timezone.utc).isoformat()}


def permission_periods(licenses):
 """A proposal of license validity, NEVER automatically treated as actual SVČ."""
 if not licenses:return []
 spans=[];maximum=date(2100,12,31)
 try:
  for license in licenses:
   start=date.fromisoformat(license['datumVzniku'])
   ends=[date.fromisoformat(license[k]) for k in ('datumZaniku','platnostDo') if license.get(k)]
   parts=[(start,min(ends) if ends else maximum)]
   for event in license.get('preruseniZivnosti',[])+license.get('pozastaveniZivnosti',[]):
    a=date.fromisoformat(event['platnostOd']);b=date.fromisoformat(event['platnostDo']) if event.get('platnostDo') else maximum
    if a>b:return []
    rest=[]
    for x,y in parts:
     if b<x or a>y:rest.append((x,y));continue
     if x<a:rest.append((x,a-timedelta(days=1)))
     if b<y:rest.append((b+timedelta(days=1),y))
    parts=rest
   spans.extend((a,b) for a,b in parts if a<=b)
 except (KeyError,ValueError,TypeError):return []
 merged=[]
 for a,b in sorted(spans):
  if merged and (a-merged[-1][1]).days<=1:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
  else:merged.append((a,b))
 return [{'from':a.isoformat(),'to':b.isoformat() if b!=maximum else ''} for a,b in merged][:40]
