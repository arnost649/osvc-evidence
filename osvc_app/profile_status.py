"""Annual profile completeness. Calculation applicability warnings remain in report.reviews."""
from copy import deepcopy


def evaluate(p, missing, sections):
    missing = deepcopy(missing)
    if p.get('tax_review') != 'yes':
        missing['tax'].append('Potvrďte kontrolu evidence a daňových korekcí')
    if p.get('insurance_code') and not p.get('user_confirmed_insurer'):
        missing['health'].append('Potvrďte svou zdravotní pojišťovnu')
    if p.get('insurance_code') and not p.get('verified_registry'):
        missing['health'].append('Vyberte platný kód zdravotní pojišťovny')
    if p.get('employer') and not p.get('employer_ico'):
        missing['employment'].append('Ověřte zaměstnavatele v Profilu OSVČ → Zaměstnání')
    result = {}
    for key, items in missing.items():
        items = list(dict.fromkeys(x.rstrip('.') for x in items))
        missing[key] = items
        state = 'missing' if items else 'known'
        reasons = items
        section = next((s for s in sections if s['key'] == key), None)
        if not items and section and section['status'] != 'known':
            state = section['status']
            reasons = [section['status_reason']]
        result[key] = {'state': state, 'missing': items, 'reason': '; '.join(reasons)}
    result['advanced'] = {'state': 'not_applicable', 'missing': [], 'reason': ''}
    state = 'missing' if any(s['state'] == 'missing' for s in result.values()) else 'review' if any(s['state'] == 'review' for s in result.values()) else 'known'
    return {'sections': result, 'missing': missing, 'state': state,
            'reason': '; '.join(s['reason'] for s in result.values() if s['reason'])}
