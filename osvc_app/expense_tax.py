"""One classification rule shared by annual totals and expense review UI."""
from decimal import Decimal, InvalidOperation
from .db import query, rok

def classification(row):
    value=row.get('tax_deductible_pct')
    source='Potvrzený podíl výdaje' if value is not None else 'Neurčeno'
    if value is None:return {'ratio':None,'source':source,'state':'pending','reason':'Daňové uplatnění výdaje dosud nebylo potvrzeno.'}
    try:ratio=Decimal(str(value))
    except InvalidOperation:ratio=Decimal('NaN')
    if not ratio.is_finite() or not 0<=ratio<=100:return {'ratio':None,'source':source,'state':'pending','reason':'Neplatný daňový podíl – vyžaduje opravu.'}
    return {'ratio':ratio,'source':source,'state':'excluded' if ratio==0 else 'confirmed','reason':''}

def parse_ratio(form):
    mode=form.get('tax_mode')
    if mode in ('0','50','100'):return Decimal(mode)
    if mode!='custom':raise ValueError('Vyberte daňové uplatnění.')
    try:value=Decimal(form.get('tax_pct','').replace(',','.'))
    except InvalidOperation:raise ValueError('Zadejte daňový podíl 0 až 100 %.')
    if not value.is_finite() or not 0<=value<=100 or value!=value.quantize(Decimal('.01')):raise ValueError('Daňový podíl musí být 0 až 100 %, nejvýše na dvě desetinná místa.')
    return value

def rows(year):
    result=query("SELECT p.* FROM payments p WHERE p.direction='expense' AND p.deleted_at IS NULL AND p.fuel_purchase_id IS NULL AND p.payment_date>=%s AND p.payment_date<%s ORDER BY p.payment_date DESC,p.id DESC",(*rok(year),))
    for row in result:row['tax']=classification(row)
    return result


def resolve_submission(data):
    """Every manual expense supplies its own explicit tax treatment."""
    return parse_ratio(data)
