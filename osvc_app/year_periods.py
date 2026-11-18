"""Resolve YEAR_SCOPE_PERIOD boundaries without inventing REAL_EVENT_DATE values."""
from datetime import date
from calendar import monthrange

def resolve_year_period(year,from_date=None,to_date=None):
 first,last=date(year,1,1),date(year,12,31)
 start=date.fromisoformat(from_date) if from_date else first
 end=date.fromisoformat(to_date) if to_date else last
 # Explicit historical dates can lie outside this year; that means no overlap.
 if from_date and to_date and start>end:raise ValueError('Konec období nesmí předcházet začátku.')
 if not 1900<=start.year<=2100 or not 1900<=end.year<=2100:raise ValueError('Neplatný rok období.')
 start,end=max(first,start),min(last,end)
 months=[m for m in range(1,13) if start<=date(year,m,monthrange(year,m)[1]) and end>=date(year,m,1)] if start<=end else []
 return {'effective_from':start,'effective_to':end,'full_year':start==first and end==last,'months':months}

def vehicle_year_period(year,start=None,end=None):
 return resolve_year_period(year,f'{year}-{int(start):02d}-01' if start else None,f'{year}-{int(end):02d}-{monthrange(year,int(end))[1]}' if end else None)

def year_period_text(year,periods):
 intervals=sorted((resolve_year_period(year,p.get('from'),p.get('to')) for p in periods),key=lambda p:p['effective_from'])
 cursor=date(year,1,1)
 from datetime import timedelta
 for p in intervals:
  a,b=p['effective_from'],p['effective_to']
  if a>cursor:break
  if b>=date(year,12,31):return 'Celý rok'
  if b>=cursor:cursor=b+timedelta(days=1)
 def fmt(d):return f'{d.day}. {d.month}. {d.year}'
 return ' · '.join(fmt(p['effective_from'])+' – '+fmt(p['effective_to']) for p in intervals if p['months']) or 'Mimo zvolený rok'
