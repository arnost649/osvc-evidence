"""Moduly, které jde v Nastavení zapnout a vypnout.

Zapnutí/vypnutí nikdy nemění ani nemaže data – tabulky existují vždy, volba je jen v souboru instance/moduly.json
(vedle appearance.json, bez tajemství; součást ZIP zálohy). Chybějící soubor = oba moduly zapnuté a započítané.
  zapnuto    – modul je vidět (menu, Přehled, formuláře); adresy vypnutého modulu přesměrují na Přehled
  zapocitat  – existující záznamy vypnutého modulu se počítají do součtů a Ročního přehledu; vyřazené z výpočtů jsou jen
               u vypnutého modulu se zapocitat=False (zapnutí modulu volbu vrátí na „započítat“)
"""
import json
import os
import tempfile
from . import zamky
from pathlib import Path
from flask import current_app

MODULY = {
    'doprava': {'nazev': 'Doprava', 'popis': 'Jízdy, PHM a vozidla.'},
    'externi_web': {'nazev': 'Externí web', 'popis': 'Zdroje příjmů a jejich synchronizace (e-shop na WordPressu/WooCommerce).'},
}
VYCHOZI = {'zapnuto': True, 'zapocitat': True}
# Stránky modulu (i formuláře a pomocné adresy pod nimi). Vypnutý modul je přesměruje na Přehled s hláškou.
ADRESY = {
    'doprava': ('/trips', '/fuel', '/settings/vehicles'),
    'externi_web': ('/settings/income-sources',),
}


def cesta():
    if current_app.config.get('MODULY_SETTINGS_FILE'):
        return Path(current_app.config['MODULY_SETTINGS_FILE'])
    return Path(current_app.config.get('DATA_STATE_DIR', Path(current_app.root_path).parent / 'instance')) / 'moduly.json'


def platna_data(value):
    """Ověří obsah souboru (i ze ZIP zálohy): jen známé moduly a logické hodnoty. Vyhodí ValueError."""
    if not isinstance(value, dict) or not set(value) <= set(MODULY):
        raise ValueError('Neplatné nastavení modulů.')
    for item in value.values():
        if not isinstance(item, dict) or not set(item) <= set(VYCHOZI) or any(type(v) is not bool for v in item.values()):
            raise ValueError('Neplatné nastavení modulů.')
    return value


def stav():
    """{klíč: {'zapnuto': bool, 'zapocitat': bool}} pro všechny moduly; poškozený nebo chybějící soubor = výchozí stav."""
    try:
        data = platna_data(json.loads(cesta().read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        data = {}
    return {k: {**VYCHOZI, **data.get(k, {})} for k in MODULY}


def zapnuto(klic):
    return stav()[klic]['zapnuto']


def vyrazeno(klic):
    """Záznamy modulu se nezapočítávají do výpočtů (jen u vypnutého modulu s volbou „Nezapočítávat“)."""
    s = stav()[klic]
    return not s['zapnuto'] and not s['zapocitat']


def zapnute():
    """{klíč: bool} pro šablony (moduly_zapnute.doprava …)."""
    return {k: v['zapnuto'] for k, v in stav().items()}


def modul_adresy(path):
    """Klíč modulu, kterému adresa patří (přesně, nebo podstránka za „/“), jinak None."""
    for klic, prefixy in ADRESY.items():
        if any(path == p or path.startswith(p + '/') for p in prefixy):
            return klic
    return None


def uloz(klic, zapnuto=None, zapocitat=None):
    if klic not in MODULY:
        raise KeyError(klic)
    data = stav()
    if zapnuto is not None: data[klic]['zapnuto'] = bool(zapnuto)
    if zapnuto: data[klic]['zapocitat'] = True   # zapnutý modul se vždy počítá celý
    if zapocitat is not None: data[klic]['zapocitat'] = bool(zapocitat)
    path = cesta(); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.moduly-', dir=path.parent)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data, out, ensure_ascii=False); out.flush(); os.fsync(out.fileno())
        zamky.nahrad(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
    return data[klic]


def pocty():
    """Kolik záznamů modul obsahuje (jen čtení; smazané záznamy se nepočítají)."""
    from .db import query
    one = lambda sql: int(query(sql, one=True)['n'])
    return {
        'doprava': {
            'jizdy': one('SELECT COUNT(*) n FROM trips WHERE deleted_at IS NULL'),
            'tankovani': one('SELECT COUNT(*) n FROM fuel_purchases WHERE deleted_at IS NULL'),
            'vozidla': one('SELECT COUNT(*) n FROM vehicles WHERE deleted_at IS NULL'),
        },
        'externi_web': {
            'zdroje': one('SELECT COUNT(*) n FROM income_sources'),
            'prijmy': one("SELECT COUNT(DISTINCT p.id) n FROM payments p JOIN income_source_records r ON r.document_id=p.document_id "
                          "WHERE p.direction='income' AND p.deleted_at IS NULL"),
        },
    }


def sklonuj(n, jedna, dve, pet):
    return f'{n} {jedna if n == 1 else dve if 2 <= n <= 4 else pet}'


def obsah_text(klic, p):
    """Lidský popis obsahu modulu, např. „42 jízd, 18 tankování, 1 vozidlo“; prázdný modul = „zatím nic“."""
    if klic == 'doprava':
        casti = [sklonuj(p['jizdy'], 'jízda', 'jízdy', 'jízd'), sklonuj(p['tankovani'], 'tankování', 'tankování', 'tankování'),
                 sklonuj(p['vozidla'], 'vozidlo', 'vozidla', 'vozidel')]
    else:
        casti = [sklonuj(p['zdroje'], 'zdroj', 'zdroje', 'zdrojů'), sklonuj(p['prijmy'], 'stažený příjem', 'stažené příjmy', 'stažených příjmů')]
    return ', '.join(casti) if any(p.values()) else 'zatím nic'


# Seznamy (Přehled, Příjmy, Výdaje, Doklady, Akce): záznamy vypnutého modulu se neukazují vůbec, bez ohledu na volbu výpočtů.
# Součty řídí jen volba „zapocitat“ (annual.evidence), ne to, co je vidět.
STAZENY_DOKLAD = "(SELECT document_id FROM income_source_records WHERE document_id IS NOT NULL)"


def skryt_platby_sql(p='p'):
    """Podmínka „AND …“ pro seznam plateb: bez stažených příjmů (vypnutý Externí web) a PHM (vypnutá Doprava); jinak ''."""
    casti = []
    if not zapnuto('externi_web'):
        casti.append(f" AND NOT ({p}.direction='income' AND ({p}.system_type='income_connector' OR {p}.document_id IN {STAZENY_DOKLAD}"
                     f" OR {p}.document_id IN (SELECT id FROM documents WHERE source<>'manual')))")
    if not zapnuto('doprava'):
        casti.append(f" AND {p}.fuel_purchase_id IS NULL")
    return ''.join(casti)


def skryt_doklady_sql(d='d'):
    """Podmínka „AND …“ pro seznam dokladů: bez stažených faktur a dokladů k tankování vypnutých modulů; jinak ''."""
    casti = []
    if not zapnuto('externi_web'):
        casti.append(f" AND {d}.source='manual' AND {d}.id NOT IN {STAZENY_DOKLAD}")
    if not zapnuto('doprava'):
        casti.append(f" AND {d}.id NOT IN (SELECT document_id FROM payments WHERE fuel_purchase_id IS NOT NULL AND document_id IS NOT NULL)")
    return ''.join(casti)


def kc(x):
    return f"{x:,.2f}".replace(',', '\u00a0').replace('.', ',') + '\u00a0Kč'   # pevné mezery – částka se nezalomí


def nezapocteno_text(n):
    """Krátký popis vyřazených záznamů pro Přehled, Roční přehled a PDF; nic vyřazeno = ''."""
    casti = []
    if n.get('doprava'):
        d = n['doprava']; co = [sklonuj(d['jizdy'], 'jízda', 'jízdy', 'jízd'), sklonuj(d['tankovani'], 'tankování', 'tankování', 'tankování')]
        castky = [f"náhrady {kc(d['nahrady'])}" if d['nahrady'] else '', f"PHM {kc(d['phm'])}" if d['phm'] else '']
        castky = ', '.join(x for x in castky if x)
        casti.append(f"{' a '.join(co)}{f' ({castky})' if castky else ''} – modul Doprava")
    if n.get('externi_web'):
        e = n['externi_web']
        casti.append(f"{sklonuj(e['prijmy'], 'stažený příjem', 'stažené příjmy', 'stažených příjmů')} za {kc(e['castka'])} – modul Externí web")
    return '; '.join(casti)
