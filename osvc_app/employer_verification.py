"""Company provenance is independent of the employment relationship."""
from datetime import datetime,timezone
FIELDS=('employer_ico','employer_verified_at','employer_source','employer_counterparty_id')
def merge(old,new,candidate=None,token=None):
 # Browser claims about ICO/provenance are never accepted.
 for key in FIELDS:new.pop(key,None)
 if new.get('employer')==old.get('employer'):
  for key in FIELDS:
   if key in old:new[key]=old[key]
 if candidate and token==candidate.get('token') and new.get('employer')==candidate.get('name'):
  age=(datetime.now(timezone.utc)-datetime.fromisoformat(candidate['at'])).total_seconds()
  if 0<=age<3600:
   new.update(employer_ico=candidate['ico'],employer_verified_at=candidate['at'],employer_source='ARES',employer_counterparty_id=candidate.get('counterparty_id'))
   new.setdefault('sources',{})['employer']={'source':'registry','provider':'ARES','verified_at':candidate['at']}
 return new
