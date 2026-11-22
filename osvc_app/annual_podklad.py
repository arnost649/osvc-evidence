"""Roční přehled jako podklad k opsání do formulářů (1.0.3) – stejná data pro stránku i PDF (1 strana A4).

Nahoře rok, jméno, IČO, adresa jedním řádkem, období podnikání a zdravotní pojišťovna; pak tři krátké tabulky
„název řádku ve formuláři | hodnota“ (Finanční úřad, ČSSZ, zdravotní pojišťovna). Upozornění jen tehdy, když něco chybí
nebo je potřeba zkontrolovat, jednou větou. Výpočet se nemění – vše pochází z annual.build (report).
Podrobnosti (stav, kam patří, zdroj, rozpad výdajů, měsíční korekce) zůstávají jen na stránce pod rozbalením a v ikonce (i).
"""
from decimal import Decimal
from . import insurers, profile
from .year_periods import year_period_text

D = lambda x: Decimal(str(x))
FORMULARE = {'tax': ('Finanční úřad', 'Příloha č. 1 DPFO – příjmy ze samostatné činnosti (§ 7)'),
             'social': ('ČSSZ', 'Přehled o příjmech a výdajích OSVČ'),
             'health': ('Zdravotní pojišťovna', 'Přehled o výši daňového základu OSVČ')}
# (klíč pole v reportu, název řádku ve formuláři); sekce None = hodnota z daňové části
RADKY = {
    'tax': [('tax.income', 'Příjmy'), ('tax.expenses', 'Výdaje'), ('tax.method', 'Způsob uplatnění výdajů'),
            ('tax.result', 'Rozdíl mezi příjmy a výdaji'), ('tax.adjustment', 'Úpravy základu (§ 5, § 23)'),
            ('tax.base', 'Dílčí základ daně (ztráta) z § 7')],
    'social': [('tax.income', 'Příjmy ze samostatné činnosti'), ('tax.expenses', 'Výdaje'), ('social.base', 'Daňový základ (rozdíl příjmů a výdajů)'),
               ('social.months', 'Počet měsíců výkonu SVČ'), ('social.main', 'z toho hlavní SVČ'), ('social.secondary', 'z toho vedlejší SVČ'),
               ('social.reason', 'Důvod vedlejší SVČ'), ('social.paid', 'Zaplacené zálohy'), ('social.assessment', 'Vyměřovací základ'),
               ('social.premium', 'Pojistné'), ('social.balance', 'Doplatek / přeplatek'), ('social.advance', 'Nová měsíční záloha')],
    'health': [('tax.income', 'Příjmy ze samostatné činnosti'), ('tax.expenses', 'Výdaje'), ('health.base', 'Daňový základ (rozdíl příjmů a výdajů)'),
               ('health.months', 'Počet měsíců výkonu SVČ'), ('health.minimum', 'z toho měsíce s minimálním vyměřovacím základem'),
               ('health.paid', 'Zaplacené zálohy'), ('health.assessment', 'Vyměřovací základ'), ('health.premium', 'Pojistné'),
               ('health.balance', 'Doplatek / přeplatek'), ('health.advance', 'Nová měsíční záloha')],
}


def castka(value):
    return f"{D(value):,.2f}".replace(',', ' ').replace('.', ',') + ' Kč'


def adresa(identity):
    ulice = ' '.join(x for x in (identity.get('street') or identity.get('city') or '', identity.get('number') or '') if x).strip()
    obec = ' '.join(x for x in ((identity.get('zip') or '').replace(' ', ''), identity.get('city') or '') if x)
    if obec and len(obec) > 6 and obec[:5].isdigit(): obec = obec[:3] + ' ' + obec[3:]   # PSČ 110 00
    stat = identity.get('country') or ''
    return ', '.join(x for x in (ulice, obec, '' if stat in ('', 'Česká republika', 'CZ') else stat) if x) or None


def obdobi(year, p):
    if p.get('profile_version') == 2:
        if p.get('business_status') == 'yes':
            from .profile_periods import platna
            return year_period_text(year, platna(p.get('business_periods'))) if platna(p.get('business_periods')) else None
        if p.get('business_status') == 'no': return 'Celý rok bez činnosti'
        return None
    aktivni = [m['month'] for m in p.get('months', []) if m.get('activity') == 'yes']
    if not aktivni: return None
    return 'Celý rok' if len(aktivni) == 12 else f'{aktivni[0]}.–{aktivni[-1]}. měsíc ({len(aktivni)} měs.)'


def _hodnota(f, rok, report):
    """(text, stav) pro buňku tabulky; stav: ok / chybi / kontrola."""
    klic, value = f['field_key'], f['value']
    if klic == 'advance':
        if value is not None: return castka(value), 'ok'
        if not profile.zalohy(rok + 1): return f'stanoví se podle pravidel {rok + 1}', 'info'
        sekce = next(s for s in report['sections'] if any(x is f for x in s['fields']))
        if any(x['status'] == 'missing' for x in sekce['fields'] if x is not f) or (f.get('note') or '').startswith('chybí'): return 'chybí', 'chybi'
        return (f.get('note') or 'ověřte u instituce').split('. ')[0], 'info'
    if klic == 'method' and value:
        p = report['profile']
        if p.get('expense_method') == 'percentage':
            sazba = ((report.get('rules') or {}).get('expense_rates', {}).get(p.get('expense_rate')) or {}).get('label', '')
            if '–' in sazba: value = f'{value} ({sazba.rsplit("–", 1)[1].strip()})'
    if value is None or value == '': return 'chybí', 'chybi'
    if klic == 'balance':
        v = D(value)
        text = 'doplatek ' + castka(v) if v > 0 else 'přeplatek ' + castka(-v) if v < 0 else castka(0)
    elif f['unit'] == 'Kč': text = castka(value)
    elif f['unit'] == 'měsíců': text = str(value)
    else: text = str(value)
    return text, ('kontrola' if f['status'] == 'review' else 'ok')


SKUPINY = {'identity': 'identifikace', 'business': 'podnikání', 'employment': 'zaměstnání', 'social': 'ČSSZ', 'health': 'zdravotní pojištění',
           'tax': 'daně', 'vehicles': 'doprava'}


def upozorneni(report):
    """Jedna věta, jen když něco chybí nebo je potřeba zkontrolovat; jinak None."""
    missing = report.get('missing') or {}
    skupiny = [SKUPINY.get(k, k) for k, v in missing.items() if v]
    chybi_pole = any(f['status'] == 'missing' for s in report['sections'] for f in s['fields'])
    if skupiny or chybi_pole:
        kde = f' ({", ".join(skupiny)})' if skupiny else ''
        return f'Chybí údaje v Profilu OSVČ{kde} – doplňte je; hodnoty označené „chybí“ zatím nejdou opsat.'
    kontrola = list(dict.fromkeys(x.rstrip('.') for x in report.get('reviews') or []))
    kontrola += [f"{f['label']} ({FORMULARE[s['key']][0]})" for s in report['sections'] for f in s['fields'] if f['status'] == 'review' and f['field_key'] != 'advance']
    kontrola = list(dict.fromkeys(kontrola))
    if kontrola:
        return 'Zkontrolujte: ' + kontrola[0][:1].lower() + kontrola[0][1:] + (f' (a další: {len(kontrola) - 1})' if len(kontrola) > 1 else '') + '.'
    return None


def podklad(report):
    rok, identity, p = report['year'], report['identity'], report['profile']
    pole = {f"{s['key']}.{f['field_key']}": f for s in report['sections'] for f in s['fields']}
    tabulky = []
    for sekce, radky in RADKY.items():
        rows = []
        for klic, nazev in radky:
            f = pole.get(klic)
            if not f: continue
            k = f['field_key']
            if k in ('result', 'adjustment') and (pole['tax.adjustment']['value'] in (None, 0) or D(pole['tax.adjustment']['value']) == 0): continue   # bez úprav = základ
            if k == 'reason' and f['value'] == 'Nevztahuje se': continue
            text, stav = _hodnota(f, rok, report)
            rows.append({'nazev': nazev, 'hodnota': text, 'stav': stav, 'napoveda': f.get('tooltip', ''), 'klic': klic})
        tabulky.append({'klic': sekce, 'urad': FORMULARE[sekce][0], 'formular': FORMULARE[sekce][1], 'radky': rows})
    return {'rok': rok,
            'hlavicka': [('Jméno', identity.get('name') or None), ('IČO', identity.get('ico') or None), ('Adresa', adresa(identity)),
                         ('Období podnikání', obdobi(rok, p)), ('Zdravotní pojišťovna', insurers.description(p) or None)],
            'upozorneni': upozorneni(report), 'tabulky': tabulky,
            'pravidla': (report.get('rules') or {}).get('id'), 'zalohy': zdroje_zaloh(rok + 1)}


def zdroje_zaloh(rok):
    """Zdroje pravidel nové zálohy pro rok `rok`: [(co, zdroj, vyhlášeno)]; bez pravidel prázdné."""
    z = profile.zalohy(rok)
    if not z: return []
    def cz(t):
        try: y, m, d = (int(x) for x in t.split('-')); return f'{d}. {m}. {y}'
        except (ValueError, AttributeError): return t
    pm = z['prumerna_mzda']
    radky = [(f'Průměrná mzda {rok}: {castka(pm["hodnota"]).replace(",00", "")}', pm['zdroj'].split(',')[0], cz(pm['vyhlaseno']))]
    for sekce, nazev in (('social', 'ČSSZ'), ('health', 'Zdravotní pojištění')):
        for v in z[sekce].values():
            if isinstance(v, dict) and 'hodnota' in v and str(v.get('vyhlaseno', ''))[:1].isdigit():   # jen hodnoty vyhlášené s datem
                radky.append((nazev, v['zdroj'], cz(v['vyhlaseno'])))
    return radky
