"""Kontrola struktury DB.

Jednou při startu se zkontroluje, že sloupce a tabulky, na které kód spoléhá, opravdu existují; co chybí, jde do logu (nic se nemění).
"""
import logging
from .db import query

log = logging.getLogger('osvc.schema')
if not log.handlers:
    _h = logging.StreamHandler(); _h.setFormatter(logging.Formatter('%(name)s: %(message)s'))
    log.addHandler(_h); log.setLevel(logging.INFO); log.propagate = False

REQUIRED = {
    'business_events': ('id', 'event_date', 'name'),
    'payments': ('counterparty_id', 'event_id', 'fuel_purchase_id', 'system_type'),
    'fuel_purchases': ('counterparty_id', 'event_id'),
    'trips': ('event_id', 'fuel_purchase_id', 'travel_rate_id', 'travel_cost_total'),
    'vehicles': ('normalized_consumption_l_100km',),
    'travel_rates': ('id',),
}


def missing():
    """Seznam „tabulka.sloupec“, které v DB chybí (prázdný = vše v pořádku)."""
    from .db import engine
    if engine() == 'sqlite':
        have = {(t, r['name']) for t in REQUIRED for r in query(f'SELECT name FROM pragma_table_info(%s)', (t,))}
        return [f'{t}.{c}' for t, cols in REQUIRED.items() for c in cols if (t, c) not in have]
    rows = query("SELECT TABLE_NAME t, COLUMN_NAME c FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ("
                 + ','.join(['%s'] * len(REQUIRED)) + ")", tuple(REQUIRED))
    have = {(r['t'], r['c']) for r in rows}
    return [f'{t}.{c}' for t, cols in REQUIRED.items() for c in cols if (t, c) not in have]


def check_at_start(app):
    try:
        with app.app_context():
            gone = missing()
    except Exception as exc:  # DB nedostupná při startu – aplikace má běžet dál, jen to zapíše
        log.warning('kontrolu struktury nešlo provést: %s', type(exc).__name__); return None
    if gone: log.warning('v databázi chybí: %s – některé stránky nebudou fungovat, napiš správci', ', '.join(gone))
    else: log.info('struktura DB v pořádku (%d tabulek)', len(REQUIRED))
    return gone
