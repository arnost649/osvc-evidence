"""Průvodce prvním spuštěním (kroky I3, A2) – samostatná instalace (Windows, Linux).

- Dokud v aplikaci není přihlašovací účet, každá adresa vede sem a průvodce nejde přeskočit. Na serveru majitele účet je.
- Strana 1 (/pruvodce): vše, co Profil OSVČ a Roční přehled potřebují k „zelené“ – podnikatel (IČO + ARES), přihlášení,
  podnikání v roce, zaměstnání (zaměstnavatel přes ARES), vedlejší činnost z jiného důvodu, první zahájení, zdravotní pojišťovna,
  zálohy (měsíčně / neplatím), způsob výdajů, daňový režim, potvrzení evidence (nikdy předem), moduly. Uloží se najednou
  v jedné transakci; profil roku jde přes profile.parse (stejná pravidla jako formulář Profilu); účet vzniká jako poslední.
  Moduly se zapíšou až po úspěšném uložení databáze.
- Strana 2 (/pruvodce/dalsi, už přihlášený): Doprava = první vozidlo + režim uplatnění; Externí web = vysvětlení a odkaz na
  průvodce zdroje příjmů. Bez modulů se přeskočí. Všechno jde později změnit v Nastavení.
"""
import json
import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.datastructures import MultiDict
from . import cas, moduly, profile, ucet
from .db import connection

bp = Blueprint('pruvodce', __name__)
ADRESA = '/pruvodce'
VYCHOZI_STAT = 'Česká republika'
SAZBY_POPIS = {'craft': 'řemeslné živnosti a zemědělství', 'trade': 'ostatní živnosti (obchod, služby)', 'other': 'ostatní samostatná činnost (např. autor, poradce)',
               'rent': 'nájem obchodního majetku'}
VEDLEJSI_JINE = {'pension': 'pobírám starobní nebo invalidní důchod', 'study': 'studuji (nezaopatřené dítě)', 'parental': 'mám rodičovský příspěvek / mateřskou',
                 'care': 'pečuji o osobu závislou na péči'}


def hotovo():
    """True, když už průvodce proběhl (je účet). Výsledek se pamatuje v procesu – účet nemizí."""
    if current_app.config.get('_OSVC_INSTALACE_HOTOVA'): return True
    if ucet.aktualni() is None: return False
    current_app.config['_OSVC_INSTALACE_HOTOVA'] = True
    return True


def brana():
    """before_request: bez účtu vede každá stránka do průvodce (kromě statických souborů a průvodce samotného)."""
    if request.endpoint == 'static' or (request.blueprint == 'pruvodce'): return None
    try:
        if hotovo(): return None
    except Exception as exc:   # nedostupná databáze nesmí na serveru otevřít průvodce
        current_app.logger.warning('průvodce: stav instalace nejde zjistit (%s)', type(exc).__name__)
        return None
    if request.method != 'GET' or request.path.startswith('/api/'):
        return jsonify(error='Nejdřív dokončete průvodce prvním spuštěním.'), 409
    return redirect(url_for('pruvodce.formular'))


def _text(form, klic, nejvic=200):
    return ' '.join((form.get(klic) or '').split())[:nejvic]


def _datum(form, klic, rok, popis):
    hodnota = (form.get(klic) or '').strip()
    if not hodnota: return None
    try: d = date.fromisoformat(hodnota)
    except ValueError: raise ValueError(f'{popis}: neplatné datum.')
    if d.year != rok: raise ValueError(f'{popis}: zadejte datum v roce {rok}.')
    return d


def _castka(form, klic, popis):
    raw = (form.get(klic) or '').replace(' ', '').replace(' ', '').replace(',', '.')
    try: d = Decimal(raw)
    except InvalidOperation: raise ValueError(f'{popis}: zadejte částku v Kč.')
    if not d.is_finite() or d < 0 or d > 1_000_000 or d != d.quantize(Decimal('0.01')): raise ValueError(f'{popis}: neplatná částka.')
    return d


def _volba(form, klic, povolene, popis):
    hodnota = form.get(klic) or ''
    if hodnota not in povolene: raise ValueError(popis)
    return hodnota


def rok_pruvodce():
    return cas.today().year


def identita(form):
    ico = re.sub(r'\s', '', form.get('ico') or '')
    if not re.fullmatch(r'\d{8}', ico): raise ValueError('IČO musí mít přesně 8 číslic.')
    ident = {'ico': ico, 'name': _text(form, 'name'), 'dic': _text(form, 'dic', 20).upper(), 'street': _text(form, 'street'),
             'number': _text(form, 'number', 20), 'city': _text(form, 'city'), 'zip': re.sub(r'\s', '', form.get('zip') or '')[:10],
             'country': _text(form, 'country', 60) or VYCHOZI_STAT}
    if not ident['name']: raise ValueError('Vyplňte jméno nebo obchodní název.')
    if not ident['number'] or not ident['city'] or not ident['zip']: raise ValueError('Vyplňte adresu: číslo domu, obec a PSČ.')
    if ident['country'] == VYCHOZI_STAT and not re.fullmatch(r'\d{5}', ident['zip']): raise ValueError('PSČ musí mít 5 číslic.')
    if ident['dic'] and not re.fullmatch(r'[A-Z]{2}\d{8,10}', ident['dic']): raise ValueError('DIČ zadejte ve tvaru CZ12345678, nebo ho nechte prázdné.')
    ident['pobyt_jinde'], ident['pobyt'] = profile.parse_pobyt(form, '')   # trvalý pobyt jinde (určuje FÚ a OSSZ)
    return ident


def profil_roku(form, rok, pravidla):
    """Odpovědi strany 1 → formulář Profilu OSVČ (verze 2) pro profile.parse + doplňky (měsíční zálohy, vedlejší z jiného důvodu)."""
    f = MultiDict({'profile_version': '2', 'insurer_directory_ui': '1', 'paid_confirmation_ui': '1', 'health_changed': 'no', 'social_voluntary': 'no',
                   'business_status': 'yes', 'health_case': 'standard'})
    od = _datum(form, 'podnikani_od', rok, 'Od kdy podnikáte') or date(rok, 1, 1)
    do = _datum(form, 'podnikani_do', rok, 'Konec podnikání') if form.get('podnikani_konec') == 'ano' else None
    if do and do < od: raise ValueError('Konec podnikání nesmí být před jeho začátkem.')
    f['business_periods'] = json.dumps([{'from': od.isoformat(), 'to': do.isoformat() if do else ''}])
    zam = _volba(form, 'zamestnani', ('ano', 'ne'), 'Odpovězte, zda máte vedle podnikání zaměstnání.')
    f['employment_status'] = 'yes' if zam == 'ano' else 'no'
    if zam == 'ano':
        zod = _datum(form, 'zamestnani_od', rok, 'Zaměstnání od') or date(rok, 1, 1)
        zdo = _datum(form, 'zamestnani_do', rok, 'Zaměstnání do')
        if zdo and zdo < zod: raise ValueError('Konec zaměstnání nesmí být před jeho začátkem.')
        pojisteni = _volba(form, 'zamestnani_socialni', ('yes', 'no'), 'Odpovězte, zda vám zaměstnavatel platí sociální pojištění.')
        zdravotni = _volba(form, 'zamestnani_zdravotni', ('yes', 'no'), 'Odpovězte na otázku o zdravotním pojištění ze zaměstnání.')
        f['employment_periods'] = json.dumps([{'from': zod.isoformat(), 'to': zdo.isoformat() if zdo else '', 'insured': pojisteni, 'health_conditions': zdravotni}])
        f['employer'] = _text(form, 'zamestnavatel')
        f['employer_verification'] = form.get('zamestnavatel_token', '')
    else:
        f['employment_periods'] = '[]'
    jine = form.get('vedlejsi_jine') or ''
    if jine and jine not in VEDLEJSI_JINE: raise ValueError('Neplatný důvod vedlejší činnosti.')
    f['social_case'] = 'new20' if _volba(form, 'prvni_zahajeni', ('ano', 'ne'), 'Odpovězte, zda je to vaše první podnikání za posledních 20 let.') == 'ano' else 'standard'
    kod = form.get('pojistovna') or ''
    from . import insurers
    radek = insurers.lookup(kod) if kod else None
    if not radek or not radek['active']: raise ValueError('Vyberte svou zdravotní pojišťovnu.')
    f['insurance_code'] = kod; f['user_confirmed_insurer'] = 'yes'   # výběr v průvodci = potvrzení
    mesicne = {}
    for klic, popis in (('social', 'Zálohy na sociální pojištění (ČSSZ)'), ('health', 'Zálohy na zdravotní pojištění')):
        volba = _volba(form, f'{klic}_zalohy', ('plati', 'neplati'), f'{popis}: vyberte „platím“ nebo „neplatím“.')
        if volba == 'neplati':
            f[f'{klic}_paid'] = '0'; f[f'{klic}_paid_confirmed'] = 'yes'
        else:
            castka = _castka(form, f'{klic}_mesicne', popis)
            if castka <= 0: raise ValueError(f'{popis}: zadejte měsíční částku, nebo zvolte „neplatím“.')
            f[f'{klic}_paid'] = ''; mesicne[klic] = str(castka)
    metoda = _volba(form, 'vydaje', ('actual', 'percentage'), 'Vyberte, jak uplatníte výdaje.')
    f['expense_method'] = metoda
    if metoda == 'percentage':
        f['expense_rate'] = _volba(form, 'pausal', tuple((pravidla or {}).get('expense_rates', {})), 'Vyberte výši výdajového paušálu.')
    f['tax_case'] = _volba(form, 'dane_rezim', ('standard', 'other'), 'Vyberte daňový režim.')
    f['tax_review'] = 'yes' if form.get('potvrzeni') == 'ano' else 'no'
    return f, mesicne, jine


def zkontroluj(form):
    """Celá strana 1 → (identita, profil roku, moduly). Chyba = ValueError s českou zprávou."""
    rok = rok_pruvodce(); pravidla = profile.rules(rok)
    ident = identita(form)
    ucet.kontrola_jmena(form.get('username'))
    ucet.kontrola_hesla(form.get('password'), form.get('password2'))
    f, mesicne, jine = profil_roku(form, rok, pravidla)
    for k, v in ident.items(): f['identity_' + k] = v
    nova_identita, data = profile.parse(f, rok, {})
    from . import employer_verification, profile_periods
    employer_verification.merge({}, data, session.get('pruvodce_zamestnavatel'), f.get('employer_verification'))
    if f.get('employer') and not data.get('employer_ico'):
        raise ValueError('Zaměstnavatele vyberte z výsledků hledání v ARES (nebo pole nechte prázdné).')
    for klic, castka in mesicne.items(): data[f'{klic}_advance_month'] = castka
    if jine:   # vedlejší činnost z jiného důvodu než zaměstnání → ruční korekce měsíců (výpočet pak k ruční kontrole)
        data['overrides_enabled'] = True; data['vedlejsi_duvod'] = jine
        data['month_overrides'] = {str(m): {'social': 'secondary', 'reason': 'other'} for m in range(1, 13)}
        data = profile_periods.project(rok, data)
    nova_identita['ares'] = _ares_overeni(nova_identita)
    zapnute = {k: form.get('modul_' + k) == '1' for k in moduly.MODULY}
    return rok, nova_identita, data, zapnute


def _ares_overeni(ident):
    """Značka ověření v ARES – jen když se uložené údaje shodují s tím, co ARES v tomto průvodci vrátil."""
    navrh = session.get('pruvodce_ares')
    if navrh and all(ident.get(k, '') == navrh['data'].get(k, '') for k in ('ico', 'name', 'street', 'number', 'city', 'zip')):
        return {'verified_at': navrh['at'], 'source': 'ARES', 'ico': ident['ico']}
    return None


def uloz(form):
    rok, ident, data, zapnute = zkontroluj(form)
    c = connection()
    try:
        c.begin()
        with c.cursor() as cur:
            for tabulka, klic, hodnota, obsah in (('osvc_profile', 'id', 1, ident), ('osvc_year_profiles', 'tax_year', rok, data)):
                cur.execute(f'SELECT revision FROM {tabulka} WHERE {klic}=%s', (hodnota,))
                text = json.dumps(obsah, ensure_ascii=False)
                if cur.fetchone(): cur.execute(f'UPDATE {tabulka} SET data=%s, revision=revision+1 WHERE {klic}=%s', (text, hodnota))
                else: cur.execute(f'INSERT INTO {tabulka} ({klic}, data) VALUES (%s,%s)', (hodnota, text))
            u = ucet.zaloz(cur, form.get('username'), form.get('password'), form.get('password2'))   # poslední: tím je instalace hotová
        c.commit()
    except Exception:
        c.rollback(); raise
    finally:
        c.close()
    for klic, zap in zapnute.items(): moduly.uloz(klic, zapnuto=zap)   # až po uložení databáze
    session.pop('pruvodce_ares', None); session.pop('pruvodce_zamestnavatel', None)
    current_app.config['_OSVC_INSTALACE_HOTOVA'] = True
    current_app.logger.info('průvodce prvním spuštěním: strana 1 hotová')
    return u, zapnute


def kontext(f):
    from . import insurers
    rok = rok_pruvodce(); pravidla = profile.rules(rok)
    sazby = [(k, v['label'], SAZBY_POPIS.get(k, '')) for k, v in (pravidla or {}).get('expense_rates', {}).items()]
    pojistovny = sorted((r for r in insurers.entries() if r['active']), key=lambda r: r['insurance_code'])
    from .annual import PRAVIDLA_CHYBI
    return dict(f=f, rok=rok, sazby=sazby, pojistovny=pojistovny, moduly_info=moduly.MODULY, vedlejsi_jine=VEDLEJSI_JINE,
                pravidla_chybi=None if pravidla else PRAVIDLA_CHYBI.format(rok))


VYCHOZI = {'country': VYCHOZI_STAT, 'modul_doprava': '1', 'zamestnani_socialni': 'yes', 'zamestnani_zdravotni': 'no', 'dane_rezim': 'standard',
           'podnikani_konec': 'ne', 'vedlejsi_jine': ''}   # první podnikání bez předvyplnění (předvyplní jen ARES)


@bp.route(ADRESA, methods=['GET', 'POST'])
def formular():
    if hotovo():
        if request.method == 'POST': flash('Průvodce už je dokončený – aplikace je připravená.', 'info')   # Zpět a znovu odeslat
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        try:
            u, zapnute = uloz(request.form)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('pruvodce.html', **kontext(request.form)), 400
        session.clear()
        session['user'] = u['username']; session['auth'] = u['auth_version']; session['local_auth'] = 1
        from .obnova import zobraz_kod   # záchranný kód pro zapomenuté heslo se ukáže jednou, pak průvodce pokračuje
        if any(zapnute.values()): return zobraz_kod(u['kod'], url_for('pruvodce.dalsi'))
        flash('Hotovo. Aplikace je připravená – vše můžete kdykoli změnit v Nastavení.', 'success')
        return zobraz_kod(u['kod'], url_for('main.dashboard'))
    f = dict(VYCHOZI, podnikani_od=f'{rok_pruvodce()}-01-01')
    return render_template('pruvodce.html', **kontext(f))


@bp.post(ADRESA + '/ares')
def ares():
    """Doplnění jména a adresy podle IČO. Nedostupný ARES není chyba průvodce – údaje jdou zadat ručně."""
    if hotovo(): return jsonify(error='Průvodce už proběhl.'), 409
    from .ares import AresUnavailable, lookup_by_ico
    ico = re.sub(r'\s', '', request.form.get('ico') or '')
    if not re.fullmatch(r'\d{8}', ico): return jsonify(error='Zadejte osmimístné IČO.'), 400
    try: subjekt = lookup_by_ico(ico)
    except AresUnavailable: return jsonify(error='ARES teď neodpovídá. Údaje vyplňte ručně, nebo to zkuste později.'), 503
    if not subjekt: return jsonify(error='Subjekt s tímto IČO v ARES není. Zkontrolujte IČO, nebo údaje vyplňte ručně.'), 404
    data = {k: subjekt.get(k, '') for k in ('ico', 'name', 'dic', 'street', 'number', 'city', 'zip', 'country')}
    data['zip'] = re.sub(r'\s', '', data['zip'])
    session['pruvodce_ares'] = {'at': cas.utc_now_naive().replace(microsecond=0).isoformat() + 'Z', 'data': data}
    return jsonify({**data, **vznik_podnikani(subjekt.get('vznik'))})


def vznik_podnikani(vznik, rok=None):
    """Datum vzniku IČO z ARES → předvyplnění „Od kdy letos podnikáte“ a zda se ptát na první podnikání (vznik v posledních 2 letech)."""
    rok = rok or rok_pruvodce()
    try: d = date.fromisoformat(vznik or '')
    except ValueError: return {'vznik': '', 'podnikani_od': '', 'ptat_prvni': None}
    return {'vznik': d.isoformat(), 'vznik_text': f'{d.month}/{d.year}', 'podnikani_od': d.isoformat() if d.year == rok else f'{rok}-01-01',
            'ptat_prvni': d.year >= rok - 2}


@bp.post(ADRESA + '/zamestnavatel')
def zamestnavatel():
    """Zaměstnavatel z ARES: hledat=název → seznam; ico=… → ověřený výběr (token pro uložení, platí hodinu)."""
    if hotovo(): return jsonify(error='Průvodce už proběhl.'), 409
    from .ares import AresUnavailable, lookup_by_ico, lookup_by_name
    try:
        if request.form.get('ico'):
            ico = request.form['ico']
            if ico not in session.get('pruvodce_zamestnavatele', []): return jsonify(error='Nejdřív zaměstnavatele vyhledejte.'), 400
            firma = lookup_by_ico(ico)
            if not firma: return jsonify(error='Subjekt nebyl nalezen.'), 404
            vyber = {'name': firma['name'], 'ico': firma['ico'], 'at': datetime.now(timezone.utc).isoformat(), 'token': secrets.token_hex(24), 'counterparty_id': None}
            session['pruvodce_zamestnavatel'] = vyber
            return jsonify(name=vyber['name'], ico=vyber['ico'], token=vyber['token'])
        nazev = ' '.join((request.form.get('hledat') or '').split())[:200]
        if len(nazev) < 2: return jsonify(error='Zadejte aspoň 2 znaky názvu zaměstnavatele.'), 400
        vysledky = lookup_by_name(nazev, limit=20)
    except AresUnavailable:
        return jsonify(error='ARES teď neodpovídá. Zaměstnavatele můžete doplnit později v Profilu OSVČ.'), 503
    session['pruvodce_zamestnavatele'] = [x['ico'] for x in vysledky]
    return jsonify(vysledky=[{'name': x['name'], 'ico': x['ico'], 'city': x.get('city', '')} for x in vysledky])


# ---- strana 2 (už přihlášený) ----
REZIMY = {'actual': 'Podle knihy jízd (cestovní náhrady)', 'fuel': 'Skutečně zaplacené PHM', 'flat': 'Paušální výdaj na dopravu', 'none': 'Neuplatňovat'}


def uloz_vozidlo(form, rok):
    nazev = _text(form, 'vozidlo_nazev')
    if not nazev: return None
    spz = _text(form, 'vozidlo_spz', 20).upper() or None; palivo = _text(form, 'vozidlo_palivo', 50) or None
    raw = (form.get('vozidlo_spotreba') or '').strip().replace(',', '.'); spotreba = None
    if raw:
        try: spotreba = Decimal(raw)
        except InvalidOperation: raise ValueError('Spotřebu vozidla zadejte jako číslo (l/100 km).')
        if not spotreba.is_finite() or not 0 < spotreba <= 100: raise ValueError('Spotřeba vozidla musí být větší než 0 a nejvýše 100 l/100 km.')
        spotreba = spotreba.quantize(Decimal('0.001'))
    identity, data, ir, yr = profile.load(rok)
    pausal_procenty = data.get('expense_method') == 'percentage'
    rezim = 'none' if pausal_procenty else _volba(form, 'vozidlo_rezim', tuple(REZIMY), 'Vyberte, jak vozidlo uplatníte.')
    nastaveni = {'vehicle_method': 'actual' if rezim in ('actual', 'fuel') else rezim, 'actual_basis': 'fuel' if rezim == 'fuel' else 'travel',
                 'private': '', 'eligible': '', 'from': None, 'to': None}
    if rezim == 'flat':
        nastaveni['private'] = _volba(form, 'vozidlo_soukrome', ('yes', 'no'), 'Odpovězte, zda vozidlo používáte i soukromě.')
        nastaveni['eligible'] = 'yes' if form.get('vozidlo_podminky') == 'ano' else ''
    from .db import execute
    ident = execute('INSERT INTO vehicles (name,registration_plate,fuel_type,normalized_consumption_l_100km,active) VALUES (%s,%s,%s,%s,1)', (nazev, spz, palivo, spotreba))
    data.setdefault('vehicles', {})[str(ident)] = nastaveni
    profile.save(rok, identity, data, ir, yr)
    return ident


@bp.route(ADRESA + '/dalsi', methods=['GET', 'POST'])
def dalsi():
    if not hotovo(): return redirect(url_for('pruvodce.formular'))
    from .routes import login_required
    return login_required(_dalsi)()


def _dalsi():
    rok = rok_pruvodce(); zap = moduly.zapnute()
    if not any(zap.values()): return redirect(url_for('main.dashboard'))
    _, data, _, _ = profile.load(rok)
    kontext2 = dict(zapnute=zap, rezimy=REZIMY, pausal_procenty=data.get('expense_method') == 'percentage')
    if request.method == 'POST':
        try:
            if zap['doprava']: uloz_vozidlo(request.form, rok)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('pruvodce2.html', f=request.form, **kontext2), 400
        flash('Hotovo. Aplikace je připravená – vše můžete kdykoli změnit v Nastavení.', 'success')
        if zap['externi_web'] and request.form.get('dalsi') == 'zdroj': return redirect('/settings/income-sources/new')
        return redirect(url_for('main.dashboard'))
    return render_template('pruvodce2.html', f={'vozidlo_rezim': 'actual'}, **kontext2)
