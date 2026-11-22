"""Příslušné úřady, formuláře a termíny ročních podání OSVČ (1.0.3) – pro stránku Roční přehled.

- Adresář úřadů: data/urady.json (finanční úřady podle kraje, OSSZ podle okresu, weby pojišťoven) – jen oficiální zdroje,
  ke každé části zdroj a datum ověření; ID datových schránek pojišťoven z číselníku VZP (insurers).
- Formuláře a termíny: data/podani-<rok>.json, dodávané s aktualizacemi aplikace po rocích. Rok bez souboru = „neověřeno“.
- Příslušnost obecně podle adresy z Profilu OSVČ: kraj a okres zjistí registr adres (ARES – standardizace adres, RÚIAN).
  Výsledek se uloží (stav aplikace, urady-adresa.json), další zobrazení už síť nepotřebuje. Praha se pozná i bez ARES.
  Bez ověřené adresy úřad „neurčen“ – nic se neodhaduje.
"""
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from flask import current_app

DATA = Path(__file__).parent / 'data'
TYDEN = ['po', 'út', 'st', 'čt', 'pá', 'so', 'ne']


def _json(nazev):
    p = DATA / nazev
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def adresar():
    return _json('urady.json')


def podani(rok):
    """Formuláře a termíny pro podání za rok `rok` (data/podani-<rok>.json), jinak None."""
    return _json(f'podani-{rok}.json')


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()).strip('-')


def datum_cz(iso, den=True):
    try: d = date.fromisoformat(str(iso)[:10])
    except ValueError: return str(iso)
    return f'{d.day}. {d.month}. {d.year}' + (f' ({TYDEN[d.weekday()]})' if den else '')


def _klic_adresy(identity):
    return ' | '.join((identity.get(k) or '').strip() for k in ('street', 'number', 'zip', 'city'))


def _cache_path():
    from .backup import state_dir
    return state_dir() / 'urady-adresa.json'


def _cache():
    try: return json.loads(_cache_path().read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def _uloz_cache(data):
    p = _cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8'); tmp.replace(p)
    except OSError:
        current_app.logger.warning('úřady: nejde uložit ověřenou adresu')


def _ares_okres(identity, timeout=4):
    """Kraj a okres adresy z registru adres (ARES). Vrátí (stav, dict|None); stav ok / nenalezeno / nedostupny."""
    from .ares import AresUnavailable, _request
    ulice, cislo, obec = (identity.get('street') or '').strip(), (identity.get('number') or '').strip(), (identity.get('city') or '').strip()
    psc = re.sub(r'\D', '', identity.get('zip') or '')
    dotazy = [f'{ulice} {cislo}, {obec}' if ulice else f'{obec} {cislo}', f'{ulice} {cislo}, {psc} {obec}' if ulice else f'{obec} {cislo}, {psc}']
    for text in dict.fromkeys(d.strip(' ,') for d in dotazy):
        try:
            data = _request('/standardizovane-adresy/vyhledat', {'textovaAdresa': text, 'typStandardizaceAdresy': 'VYHOVUJICI_ADRESY', 'start': 0, 'pocet': 20}, timeout=timeout)
        except AresUnavailable:
            return 'nedostupny', None
        nalezy = data.get('standardizovaneAdresy') or []
        if psc: nalezy = [a for a in nalezy if str(a.get('psc') or '') == psc]   # PSČ musí sedět (stejnojmenné obce)
        nalezy = [a for a in nalezy if (a.get('nazevObce') or '').casefold() == obec.casefold() or re.fullmatch(r'Praha(\s+\d+)?', obec)]
        kraje = {(a.get('nazevKraje'), a.get('nazevOkresu') or ('Hlavní město Praha' if a.get('nazevKraje') == 'Hlavní město Praha' else None)) for a in nalezy}
        if len(kraje) == 1:
            kraj, okres = kraje.pop()
            if kraj and okres:
                return 'ok', {'kraj': kraj, 'okres': okres, 'obec': nalezy[0].get('nazevObce') or obec, 'zdroj': 'ARES – standardizace adres (RÚIAN)', 'overeno': date.today().isoformat()}
    # záloha: okres patří obci – obec (přesný název) + PSČ, číslo domu jen zúží dotaz (ulice nemusí v registru sedět)
    cisla = list(dict.fromkeys(x for x in (re.match(r'\d+', cislo).group(0) if re.match(r'\d+', cislo) else None, '1') if x))
    for c in cisla:
        try:
            data = _request('/standardizovane-adresy/vyhledat', {'nazevObce': obec, 'cisloDomovni': int(c), 'typStandardizaceAdresy': 'VYHOVUJICI_ADRESY', 'start': 0, 'pocet': 200}, timeout=timeout)
        except AresUnavailable:
            return 'nedostupny', None
        nalezy = [a for a in data.get('standardizovaneAdresy') or [] if (a.get('nazevObce') or '').casefold() == obec.casefold()]
        if psc: nalezy = [a for a in nalezy if str(a.get('psc') or '') == psc]
        kraje = {(a.get('nazevKraje'), a.get('nazevOkresu')) for a in nalezy}
        if len(kraje) == 1:
            kraj, okres = kraje.pop()
            if kraj and okres:
                return 'ok', {'kraj': kraj, 'okres': okres, 'obec': obec, 'zdroj': 'ARES – standardizace adres (RÚIAN), podle obce a PSČ', 'overeno': date.today().isoformat()}
    return 'nenalezeno', None


def mista(identity, sit=True):
    """Kraj a okres adresy z Profilu OSVČ: uložený výsledek, Praha podle obce, jinak dotaz do ARES (sit=True).
    Nenalezenou adresu si pamatuje do konce dne (stránka nečeká na ARES při každém zobrazení)."""
    klic = _klic_adresy(identity)
    obec = (identity.get('city') or '').strip()
    if not obec: return None
    cache = _cache(); dnes = date.today().isoformat()
    ulozeno = cache.get(klic)
    if ulozeno and (ulozeno.get('kraj') or ulozeno.get('overeno') == dnes): return ulozeno if ulozeno.get('kraj') else None
    if re.fullmatch(r'Praha(\s+\d+)?', obec):
        stav, vysledek = 'ok', {'kraj': 'Hlavní město Praha', 'okres': 'Hlavní město Praha', 'obec': 'Praha', 'zdroj': 'obec Praha z Profilu OSVČ', 'overeno': dnes}
    elif sit and not current_app.config.get('TESTING'):
        stav, vysledek = _ares_okres(identity)
        current_app.logger.info('úřady: ověření adresy v ARES – %s%s', stav, f" (okres {vysledek['okres']})" if vysledek else '')
    else:
        return None
    if stav == 'ok': cache[klic] = vysledek; _uloz_cache(cache)
    elif stav == 'nenalezeno': cache[klic] = {'nenalezeno': True, 'overeno': dnes}; _uloz_cache(cache)
    return vysledek


def adresa_pro_urady(identity):
    """Adresa, podle které se určuje FÚ a OSSZ: trvalý pobyt, je-li jinde (Profil OSVČ), jinak adresa podnikání. (adresa, popis)"""
    pobyt = identity.get('pobyt') or {}
    if identity.get('pobyt_jinde') == 'ano' and pobyt.get('city'):
        return pobyt, 'adresy trvalého pobytu'
    return identity, 'adresy podnikání (trvalý pobyt je stejný)'


def prislusne(identity, p, sit=True):
    """Tři karty úřadů: {'tax'|'social'|'health': {'nazev','adresa','id_ds','web','zdroj','overeno','prislusnost'} nebo None + 'duvod'}."""
    a = adresar() or {}
    adresa, podle = adresa_pro_urady(identity)
    misto = mista(adresa, sit)
    vysledek = {'misto': misto, 'podle': podle}
    fu = (a.get('financni_urady') or {})
    if misto and misto['kraj'] in fu.get('urady', {}):
        u = fu['urady'][misto['kraj']]
        vysledek['tax'] = {**u, 'web': fu.get('web'), 'zdroj': fu.get('zdroj'), 'zdroj_url': fu.get('url'), 'overeno': fu.get('overeno'), 'prislusnost': fu.get('prislusnost')}
    else:
        vysledek['tax'] = None
    os_ = a.get('ossz') or {}
    klic = os_.get('okresy', {}).get(slug(misto['okres'])) if misto else None
    if klic and klic in os_.get('spravy', {}):
        vysledek['social'] = {**os_['spravy'][klic], 'zdroj': os_.get('zdroj'), 'zdroj_url': os_.get('url'), 'overeno': os_.get('overeno'), 'prislusnost': os_.get('prislusnost')}
    else:
        vysledek['social'] = None
    from . import insurers
    kod = str(p.get('insurance_code') or p.get('insurer_code') or '')
    zp = insurers.lookup(kod) if kod else None
    pz = a.get('pojistovny') or {}
    if zp:
        vysledek['health'] = {'nazev': zp['name'], 'kod': kod, 'adresa': zp.get('address'), 'id_ds': zp.get('data_box'), 'web': pz.get('web', {}).get(kod),
                              'zdroj': pz.get('zdroj_schranky'), 'zdroj_url': zp.get('source_url'), 'overeno': pz.get('overeno'),
                              'prislusnost': 'zdravotní pojišťovna z Profilu OSVČ'}
    else:
        vysledek['health'] = None
    return vysledek


def karty(identity, p, rok, sit=True):
    """Data pro stránku: úřady + formuláře a termíny roku (nebo „neověřeno“)."""
    u = prislusne(identity, p, sit)
    data = podani(rok)
    nazvy = {'tax': 'Finanční úřad', 'social': 'ČSSZ – správa sociálního zabezpečení', 'health': 'Zdravotní pojišťovna'}
    vystup = []
    for klic in ('tax', 'social', 'health'):
        r = (data or {}).get(klic) or {}
        formular = dict(r.get('formular') or {})
        if klic == 'health' and formular and u.get('health'):
            vlastni = (formular.get('url_pojistovna') or {}).get(u['health']['kod'])
            formular['url'] = vlastni or u['health'].get('web')
            if not vlastni: formular['stav'] = 'neověřeno'
        vystup.append({'klic': klic, 'nazev': nazvy[klic], 'urad': u.get(klic), 'formular': formular or None,
                       'terminy': [{**t, 'text': datum_cz(t['datum'])} for t in r.get('terminy', [])], 'doplatek': r.get('doplatek'),
                       'stav_terminu': r.get('stav_terminu'), 'overeno': (data or {}).get('overeno')})
    return {'misto': u.get('misto'), 'podle': u.get('podle'), 'karty': vystup, 'rok_podani': rok + 1, 'data_roku': bool(data)}
