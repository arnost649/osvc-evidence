"""Přihlašovací účet uložený v aplikaci (krok I2). Jeden účet v tabulce app_accounts; heslo jen jako otisk (werkzeug).

- Účet spravovaný aplikací = řádek s auth_version >= 2. Starší řádek (z doby Dockeru, auth_version 1) se ignoruje.
- Převzetí: když spravovaný účet není a v nastavení serveru je APP_USER + APP_PASSWORD_HASH, při startu se jednou převezmou
  do databáze (přihlášení se nezmění). Potom platí jen databáze – změna jména a hesla v Nastavení → Účet.
- Změna hesla zvýší auth_version → ostatní přihlášení (session s jinou verzí) se odhlásí.
- Obnova zapomenutého hesla (1.0.3) využívá sloupce app_accounts z doby Dockeru, bez úpravy struktury databáze. Platí jen
  hodnoty se značkou této verze – případné staré hodnoty z dřívější obnovy hesla e-mailem se nikdy nepoužijí:
    password_reset_token_hash     = 'zk1:' + otisk záchranného kódu (kód sám se nikde neukládá, ukáže se jednou),
    password_reset_requested_at   = kdy byl záchranný kód vytvořen (zobrazí se jen u platného kódu),
    email_verification_token_hash = 'osvc-docasne:' + čas, když nástroj „Obnovit heslo“ nastavil dočasné přihlášení osvc / osvc.
  Dočasné přihlášení platí jen z tohoto počítače a po přihlášení vynutí změnu jména a hesla (osvc_app/obnova.py).
"""
import re
import secrets
from flask import current_app, g, has_app_context
from werkzeug.security import check_password_hash, generate_password_hash
from . import cas
from .db import query, execute

SPRAVOVANY = 2
MIN_HESLO = 8
ABECEDA_KODU = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'   # bez 0/O, 1/I/L – dobře se čte z papíru
DOCASNE = 'osvc'   # dočasné jméno i heslo z nástroje „Obnovit heslo“
ZNACKA_KODU = 'zk1:'
ZNACKA_DOCASNE = 'osvc-docasne:'
SLOUPCE = ('id, username, password_hash, auth_version, password_reset_token_hash AS kod_ulozeny, password_reset_requested_at AS kod_vytvoren, '
           'email_verification_token_hash AS docasne_ulozene')


def _rozbal(radek):
    """Řádek z databáze → účet; kod_otisk a docasne jen se značkou 1.0.3 (staré hodnoty = None)."""
    if not radek: return None
    u = dict(radek)
    kod, docasne = u.pop('kod_ulozeny', None) or '', u.pop('docasne_ulozene', None) or ''
    u['kod_otisk'] = kod[len(ZNACKA_KODU):] if kod.startswith(ZNACKA_KODU) else None
    if not u['kod_otisk']: u['kod_vytvoren'] = None
    u['docasne'] = docasne[len(ZNACKA_DOCASNE):] or 'ano' if docasne.startswith(ZNACKA_DOCASNE) else None
    return u


def ucet():
    """Spravovaný účet {id, username, password_hash, auth_version}, nebo None. V rámci požadavku se načte jednou."""
    if has_app_context() and '_osvc_ucet' in g: return g._osvc_ucet
    u = _rozbal(query(f'SELECT {SLOUPCE} FROM app_accounts WHERE auth_version>=%s ORDER BY id LIMIT 1', (SPRAVOVANY,), one=True))
    if has_app_context(): g._osvc_ucet = u
    return u


def aktualni():
    """Účet pro přihlášení: spravovaný z databáze, jinak (před převzetím) z nastavení serveru; None = zatím žádný (průvodce I3)."""
    u = ucet()
    if u: return u
    c = current_app.config
    if c.get('APP_USER') and c.get('APP_PASSWORD_HASH'):
        return {'id': None, 'username': c['APP_USER'], 'password_hash': c['APP_PASSWORD_HASH'], 'auth_version': 0, 'kod_otisk': None, 'kod_vytvoren': None, 'docasne': None}
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
    kod = novy_kod()
    cur.execute('SELECT id FROM app_accounts WHERE id=1', ())
    if cur.fetchone():
        cur.execute('UPDATE app_accounts SET username=%s, password_hash=%s, auth_version=%s, password_changed_at=%s, password_reset_token_hash=%s, '
                    'password_reset_requested_at=%s, email_verification_token_hash=NULL WHERE id=1', (jmeno, otisk, SPRAVOVANY, ted, otisk_kodu(kod), ted))
    else:
        cur.execute('INSERT INTO app_accounts (id, username, password_hash, auth_version, password_changed_at, password_reset_token_hash, password_reset_requested_at) '
                    'VALUES (1,%s,%s,%s,%s,%s,%s)', (jmeno, otisk, SPRAVOVANY, ted, otisk_kodu(kod), ted))
    if has_app_context(): g.pop('_osvc_ucet', None)
    return {'username': jmeno, 'auth_version': SPRAVOVANY, 'kod': kod}


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
    """Změna jména a/nebo hesla (vždy s ověřením současného hesla). Vrátí (aktualizovaný účet, nový záchranný kód nebo None);
    nové heslo = nový záchranný kód. Chyba = ValueError."""
    u = aktualni()
    if not u or not check_password_hash(u['password_hash'], soucasne_heslo or ''): raise ValueError('Současné heslo nesouhlasí.')
    jmeno = kontrola_jmena(nove_jmeno)
    otisk = generate_password_hash(kontrola_hesla(nove_heslo, nove_heslo_znovu)) if (nove_heslo or nove_heslo_znovu) else u['password_hash']
    if not ucet(): prevezmi_z_nastaveni()
    u = ucet()
    if u is None: raise ValueError('Účet nejde uložit.')
    kod = None
    if otisk != u['password_hash']:   # nové heslo → vyšší verze = ostatní přihlášení se odhlásí; nový záchranný kód
        kod = novy_kod(); ted = cas.utc_now_naive().replace(microsecond=0)
        execute('UPDATE app_accounts SET username=%s, password_hash=%s, auth_version=%s, password_changed_at=%s, password_reset_token_hash=%s, '
                'password_reset_requested_at=%s, email_verification_token_hash=NULL WHERE id=%s',
                (jmeno, otisk, u['auth_version'] + 1, ted, otisk_kodu(kod), ted, u['id']))
    else:
        execute('UPDATE app_accounts SET username=%s WHERE id=%s', (jmeno, u['id']))
    g.pop('_osvc_ucet', None)
    current_app.logger.info('účet: změna %s', 'jména a hesla' if otisk != u['password_hash'] and jmeno != u['username'] else 'hesla' if otisk != u['password_hash'] else 'jména')
    return ucet(), kod


# --- obnova zapomenutého hesla (1.0.3) ---

def novy_kod():
    """Záchranný kód 3×4 znaky, např. K7QF-M2XD-9RTB (31^12 ≈ 2^59 možností)."""
    return '-'.join(''.join(secrets.choice(ABECEDA_KODU) for _ in range(4)) for _ in range(3))


def normalizuj_kod(text):
    """Zadaný kód bez mezer a pomlček, velkými písmeny (na malých písmenech nezáleží)."""
    return re.sub(r'[^A-Z0-9]', '', (text or '').upper())


def otisk_kodu(kod):
    return ZNACKA_KODU + generate_password_hash(normalizuj_kod(kod))


def over_kod(kod):
    """Účet, když záchranný kód sedí; jinak None."""
    u = ucet(); kod = normalizuj_kod(kod)
    if u and u.get('kod_otisk') and len(kod) == 12 and check_password_hash(u['kod_otisk'], kod): return u
    return None


def novy_zachranny_kod(soucasne_heslo):
    """Nový záchranný kód z Nastavení → Účet (ověří současné heslo). Starý kód tím přestane platit. Vrátí kód."""
    u = aktualni()
    if not u or not check_password_hash(u['password_hash'], soucasne_heslo or ''): raise ValueError('Současné heslo nesouhlasí.')
    if not ucet(): prevezmi_z_nastaveni()
    u = ucet()
    if u is None: raise ValueError('Účet nejde uložit.')
    kod = novy_kod()
    execute('UPDATE app_accounts SET password_reset_token_hash=%s, password_reset_requested_at=%s WHERE id=%s',
            (otisk_kodu(kod), cas.utc_now_naive().replace(microsecond=0), u['id']))
    g.pop('_osvc_ucet', None)
    current_app.logger.info('účet: nový záchranný kód')
    return kod


def nastav_nove(jmeno, heslo, znovu, duvod):
    """Nové jméno a heslo bez současného hesla – po ověření záchranným kódem nebo po dočasném přihlášení (vynucená změna).
    Odhlásí všechna zařízení (vyšší auth_version), zruší dočasné přihlášení, vytvoří nový záchranný kód. Vrátí (účet, kód)."""
    jmeno = kontrola_jmena(jmeno); heslo = kontrola_hesla(heslo, znovu)
    u = ucet()
    if u is None: raise ValueError('Účet nejde uložit.')
    if u.get('docasne') and jmeno.casefold() == DOCASNE: raise ValueError(f'Zvolte jiné uživatelské jméno než dočasné „{DOCASNE}“.')
    kod = novy_kod(); ted = cas.utc_now_naive().replace(microsecond=0)
    execute('UPDATE app_accounts SET username=%s, password_hash=%s, auth_version=%s, password_changed_at=%s, password_reset_token_hash=%s, '
            'password_reset_requested_at=%s, email_verification_token_hash=NULL WHERE id=%s',
            (jmeno, generate_password_hash(heslo), u['auth_version'] + 1, ted, otisk_kodu(kod), ted, u['id']))
    g.pop('_osvc_ucet', None)
    current_app.logger.info('účet: nové jméno a heslo (%s), všechna zařízení odhlášena, nový záchranný kód', duvod)
    return ucet(), kod


def docasne_prihlaseni():
    """Nástroj „Obnovit heslo“ na počítači s aplikací: přihlášení osvc / osvc (platí jen z tohoto počítače), všechna zařízení
    se odhlásí. Data, doklady ani nastavení se nemění. Bez účtu (průvodce ještě neproběhl) = ValueError."""
    if not ucet(): prevezmi_z_nastaveni()
    u = ucet()
    if u is None: raise ValueError('Aplikace zatím nemá přihlašovací účet. Otevřete ji v prohlížeči a dokončete průvodce prvním spuštěním.')
    execute('UPDATE app_accounts SET username=%s, password_hash=%s, auth_version=%s, email_verification_token_hash=%s WHERE id=%s',
            (DOCASNE, generate_password_hash(DOCASNE), u['auth_version'] + 1, ZNACKA_DOCASNE + cas.utc_now_naive().replace(microsecond=0).isoformat(), u['id']))
    if has_app_context(): g.pop('_osvc_ucet', None)
    current_app.logger.warning('účet: nástroj Obnovit heslo nastavil dočasné přihlášení %s / %s (jen z tohoto počítače), všechna zařízení odhlášena', DOCASNE, DOCASNE)
    return ucet()
