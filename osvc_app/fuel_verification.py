"""Read-only fuel checks. Receipt text can later be supplied by an OCR adapter."""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


def number(value):
 try:
  result=Decimal(str(value or '').replace(' ','').replace('\u00a0','').replace(',','.'))
  return result if result.is_finite() and 0<result<=Decimal('1000000000') else None
 except InvalidOperation: return None


def parse_receipt_text(text):
 """Only explicit, unambiguous labelled values; never infer an operator from a brand."""
 found={}
 patterns={
  'ico':r'(?im)^\s*I[ČC]O\s*:?\s*(\d{8})\b',
  'dic':r'(?im)^\s*DI[ČC]\s*:?\s*([A-Z]{2}\d{8,10})\b',
  'name':r'(?im)^\s*(?:Provozovatel|Dodavatel)\s*:\s*([^\n]{3,200})$',
  'date':r'(?im)^\s*(?:Datum|Datum prodeje)\s*:?\s*(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})',
  'liters':r'(?im)^\s*(?:Litry|Množství(?:\s*\(l\))?)\s*:?\s*(\d+(?:[.,]\d{1,3})?)\s*(?:l)?\s*$',
  'price_per_liter':r'(?im)^\s*(?:Cena\s*/\s*l|Cena za litr)\s*:?\s*(\d+(?:[.,]\d{1,3})?)\s*(?:Kč(?:/l)?)?\s*$',
  'total_amount':r'(?im)^\s*(?:Celkem|Celkem k úhradě)\s*:?\s*([\d ]+(?:[.,]\d{2})?)\s*(?:Kč|CZK)?\s*$'
 }
 for key,pattern in patterns.items():
  values=set(re.findall(pattern,text or ''))
  if len(values)!=1: continue
  value=values.pop().strip()
  if key=='date':
   try:value=datetime.strptime(value.replace(' ',''),'%d.%m.%Y').date().isoformat()
   except ValueError:continue
  elif key in ('liters','price_per_liter','total_amount'):
   value=number(value)
   if value is None:continue
   value=str(value)
  found[key]=value
 return found


def verify_values(data, station, text='', receipt_present=False):
 checks=[]
 def add(ok,message):checks.append({'status':'success' if ok else 'warning','message':message})
 add(bool(station),'Vybraná benzinka je v adresáři.' if station else 'Vyberte benzinku z adresáře.')
 tolerance=Decimal('1.00') if data.get('method')=='cash' else Decimal('0.10')
 recognized=parse_receipt_text(text)
 if receipt_present:
  if not text: add(False,'Doklad nelze textově přečíst. Údaje z účtenky nebyly ověřeny; zkontrolujte je ručně.')
  else:
   for key,label,tol in [('total_amount','Částka',tolerance),('liters','Litry',Decimal('.01')),('price_per_liter','Cena/l',Decimal('.01'))]:
    value=recognized.get(key); entered=number(data.get(key))
    if value and entered is not None:
     match=abs(Decimal(value)-entered)<=tol;add(match,label+(' odpovídá dokladu.' if match else ' se liší od dokladu.'))
    else:add(False,label+' se z dokladu nepodařilo jednoznačně ověřit.')
   match=recognized.get('date')==data.get('purchase_date')
   add(bool(match),'Datum odpovídá dokladu.' if match else 'Datum na dokladu chybí nebo se liší.')
   ico=recognized.get('ico')
   match=bool(ico and station and station.get('ico')==ico)
   add(match,'IČO provozovatele odpovídá dokladu.' if match else 'Provozovatele se nepodařilo potvrdit podle IČO.')
   if recognized.get('dic') and station and station.get('dic'):
    match=recognized['dic']==station['dic'];add(match,'DIČ odpovídá dokladu.' if match else 'DIČ se liší od dokladu.')
 return {'checks':checks,'recognized':recognized,'ok':all(c['status']=='success' for c in checks)}
