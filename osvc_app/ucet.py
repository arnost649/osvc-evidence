"""Přihlašovací účet uložený v aplikaci (krok I2). Jeden účet v tabulce app_accounts; heslo jen jako otisk (werkzeug).

- Účet spravovaný aplikací = řádek s auth_version >= 2. Starší řádek (z doby Dockeru, auth_version 1) se ignoruje.
- Převzetí: když spravovaný účet není a v nastavení serveru je APP_USER + APP_PASSWORD_HASH, při startu se jednou převezmou
  do databáze (přihlášení se nezmění). Potom platí jen databáze – změna jména a hesla v Nastavení → Účet.
- Změna hesla zvýší auth_version → ostatní přihlášení (session s jinou verzí) se odhlásí.
"""
from flask import current_app, g, has_app_context
from werkzeug.security import check_password_hash, generate_password_hash
from . import cas
from .db import query, execute

SPRAVOVANY = 2
MIN_HESLO = 8


def ucet():
    """Spravovaný účet {id, username, password_hash, auth_version}, nebo None. V rámci požadavku se načte jednou."""
    if has_app_context() and '_osvc_ucet' in g: return g._osvc_ucet
    u = query('SELECT id, username, password_hash, auth_version FROM app_accounts WHERE auth_version>=%s ORDER BY id LIMIT 1', (SPRAVOVANY,), one=True)
    if has_app_context(): g._osvc_ucet = u
    return u


def aktualni():
    """Účet pro přihlášení: spravovaný z databáze, jinak (před převzetím) z nastavení serveru; None = zatím žádný (průvodce I3)."""
    u = ucet()
    if u: return u
    c = current_app.config
    if c.get('APP_USER') and c.get('APP_PASSWORD_HASH'):
        return {'id': None, 'username': c['APP_USER'], 'password_hash': c['APP_PASSWORD_HASH'], 'auth_version': 0}
    return None


def prevezmi_z_nastaveni():
    """Jednorázové převzetí APP_USER/APP_PASSWORD_HASH do databáze. Vrátí True, když převzal."""
    c = current_app.config
    if not (c.get('APP_USER') and c.get('APP_PASSWORD_HASH')) or ucet(): return False
    ted = cas.utc_now_naive().replace(microsecond=0)
    if query('SELECT id FROM app_accounts WHERE id=1', one=True):   # starý řádek z doby Dockeru se přepíše
        execute('UPDATE app_accounts SET username=%s, password_hash=%s, auth_version=%s, password_changed_at=%s WHERE id=1',
                (c['APP_USER'], c['APP_PASSWORD_HASH'], SPRAVOVANY, ted))
    else:
        execute('INSERT INTO app_accounts (id, username, password_hash, auth_version, password_changed_at) VALUES (1,%s,%s,%s,%s)',
                (c['APP_USER'], c['APP_PASSWORD_HASH'], SPRAVOVANY, ted))
    g.pop('_osvc_ucet', None)
    current_app.logger.info('účet: přihlášení převzato z nastavení serveru do aplikace')
    return True


def zaloz(cur, jmeno, heslo, znovu):
    """Založení účtu v průvodci prvním spuštěním (I3), v transakci průvodce (cur). Jen když žádný spravovaný účet není;
    chyba = ValueError. Starý řádek z doby Dockeru (id=1, auth_version 1) se přepíše."""
    jmeno = kontrola_jmena(jmeno); otisk = generate_password_hash(kontrola_hesla(heslo, znovu))
    cur.execute('SELECT id FROM app_accounts WHERE auth_version>=%s LIMIT 1', (SPRAVOVANY,))
    if cur.fetchone(): raise ValueError('Účet už existuje – průvodce už proběhl. Přihlaste se.')
    ted = cas.utc_now_naive().replace(microsecond=0)
    cur.execute('SELECT id FROM app_accounts WHERE id=1', ())
    if cur.fetchone():
        cur.execute('UPDATE app_accounts SET username=%s, password_hash=%s, auth_version=%s, password_changed_at=%s WHERE id=1', (jmeno, otisk, SPRAVOVANY, ted))
    else:
        cur.execute('INSERT INTO app_accounts (id, username, password_hash, auth_version, password_changed_at) VALUES (1,%s,%s,%s,%s)', (jmeno, otisk, SPRAVOVANY, ted))
    if has_app_context(): g.pop('_osvc_ucet', None)
    return {'username': jmeno, 'auth_version': SPRAVOVANY}


def overit(jmeno, heslo):
    """Účet, když jméno a heslo sedí; jinak None."""
    u = aktualni()
    if u and jmeno == u['username'] and heslo and check_password_hash(u['password_hash'], heslo): return u
    return None


def kontrola_jmena(jmeno):
    jmeno = (jmeno or '').strip()
    if not 3 <= len(jmeno) <= 50: raise ValueError('Uživatelské jméno musí mít 3 až 50 znaků.')
    if any(ch.isspace() for ch in jmeno): raise ValueError('Uživatelské jméno nesmí obsahovat mezery.')
    return jmeno


def kontrola_hesla(heslo, znovu):
    if len(heslo or '') < MIN_HESLO: raise ValueError(f'Heslo musí mít aspoň {MIN_HESLO} znaků.')
    if len(heslo) > 200: raise ValueError('Heslo je příliš dlouhé.')
    if heslo != znovu: raise ValueError('Nové heslo a jeho zopakování se liší.')
    return heslo


def zmen(soucasne_heslo, nove_jmeno, nove_heslo='', nove_heslo_znovu=''):
    """Změna jména a/nebo hesla (vždy s ověřením současného hesla). Vrátí aktualizovaný účet; chyba = ValueError."""
    u = aktualni()
    if not u or not check_password_hash(u['password_hash'], soucasne_heslo or ''): raise ValueError('Současné heslo nesouhlasí.')
    jmeno = kontrola_jmena(nove_jmeno)
    otisk = generate_password_hash(kontrola_hesla(nove_heslo, nove_heslo_znovu)) if (nove_heslo or nove_heslo_znovu) else u['password_hash']
    if not ucet(): prevezmi_z_nastaveni()
    u = ucet()
    if u is None: raise ValueError('Účet nejde uložit.')
    if otisk != u['password_hash']:   # nové heslo → vyšší verze = ostatní přihlášení se odhlásí
        execute('UPDATE app_accounts SET username=%s, password_hash=%s, auth_version=%s, password_changed_at=%s WHERE id=%s',
                (jmeno, otisk, u['auth_version'] + 1, cas.utc_now_naive().replace(microsecond=0), u['id']))
    else:
        execute('UPDATE app_accounts SET username=%s WHERE id=%s', (jmeno, u['id']))
    g.pop('_osvc_ucet', None)
    current_app.logger.info('účet: změna %s', 'jména a hesla' if otisk != u['password_hash'] and jmeno != u['username'] else 'hesla' if otisk != u['password_hash'] else 'jména')
    return ucet()
