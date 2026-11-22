"""Obnova zapomenutého hesla (1.0.3).

1. Záchranný kód – vzniká při nastavení nebo změně hesla (průvodce, Nastavení → Účet, obnova) a ukáže se jednou
   (/ucet/zachranny-kod: Vytisknout, Stáhnout jako .txt, „Kód jsem si uložil“). V databázi je jen jeho otisk.
   Přihlášení → „Zapomněl jsem heslo“ (/login/zapomenute-heslo): kód → nové jméno a heslo → nový kód.
   Chybné kódy: nejvýš POKUSU za OKNO sekund (pro celou aplikaci, v paměti procesu).
2. Nástroj „Obnovit heslo“ na počítači s aplikací (spoustec obnovit-heslo / python -m osvc_app.obnova_hesla) nastaví
   dočasné přihlášení osvc / osvc. To platí jen z tohoto počítače (adresa, ze které požadavek přišel, patří tomuto počítači)
   a hned vynutí změnu jména a hesla (/ucet/zmena-hesla) – jiná stránka se do té doby neotevře.
Data, doklady ani nastavení se při obnově nikdy nemění.
"""
import math
import socket
import threading
import time
from collections import deque
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from . import ucet
from .routes import login_required

bp = Blueprint('obnova', __name__)
POKUSU = 5
OKNO = 15 * 60
PLATNOST_OVERENI = 10 * 60   # ověřený kód → nové heslo do 10 minut
POVOLENE_PRI_ZMENE = {'obnova.zmena', 'main.logout', 'main.login', 'static'}


class Omezeni:
    """Nejvýš `pocet` chybných pokusů za `okno` sekund. Vlákna waitress sdílejí jednu instanci."""
    def __init__(self, pocet=POKUSU, okno=OKNO):
        self.pocet, self.okno, self.chyby, self.zamek = pocet, okno, deque(), threading.Lock()

    def _uklid(self, ted):
        while self.chyby and ted - self.chyby[0] >= self.okno: self.chyby.popleft()

    def zbyva_cekat(self):
        """0 = lze zkusit; jinak počet sekund do dalšího pokusu."""
        with self.zamek:
            ted = time.monotonic(); self._uklid(ted)
            return 0 if len(self.chyby) < self.pocet else max(1, math.ceil(self.chyby[0] + self.okno - ted))

    def chyba(self):
        with self.zamek:
            ted = time.monotonic(); self._uklid(ted); self.chyby.append(ted)
            return self.pocet - len(self.chyby)

    def vynuluj(self):
        with self.zamek: self.chyby.clear()


omezeni = Omezeni()


def je_mistni(adresa=None):
    """True, když požadavek přišel z tohoto počítače: 127.0.0.1/::1 nebo vlastní adresa počítače (k té jde socket přivázat).
    Aplikace nepřijímá X-Forwarded-For, adresa je skutečný protějšek spojení."""
    adresa = (adresa if adresa is not None else request.remote_addr) or ''
    if adresa.startswith('::ffff:'): adresa = adresa[7:]
    if adresa in ('127.0.0.1', '::1') or adresa.startswith('127.'): return True
    try:
        for rodina, typ, proto, _, sockaddr in socket.getaddrinfo(adresa, 0, type=socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST):
            with socket.socket(rodina, typ, proto) as s:
                s.bind(sockaddr)
                return True
    except (OSError, ValueError, UnicodeError):
        pass
    return False


def zobraz_kod(kod, dal):
    """Kód se ukáže jednou na /ucet/zachranny-kod (pak ze session zmizí); `dal` = kam pokračovat."""
    session['zachranny_kod'] = kod; session['zachranny_kod_dal'] = dal
    return redirect(url_for('obnova.kod'))


def prihlas(u):
    session.clear()
    session['user'] = u['username']; session['auth'] = u['auth_version']; session['local_auth'] = 1


def vynucena_zmena():
    """before_request: po dočasném přihlášení (nástroj Obnovit heslo) jen stránka změny jména a hesla; mimo tento počítač odhlásí."""
    if session.get('local_auth') != 1 or request.endpoint in ('static', None): return None
    try: u = ucet.ucet()
    except Exception: return None   # nedostupná databáze: rozhodne login_required
    if not u or not u.get('docasne') or session.get('user') != u['username']: return None
    if not je_mistni():
        session.clear()
        flash('Dočasné přihlášení funguje jen přímo na počítači, kde aplikace běží.', 'error')
        return redirect(url_for('main.login'))
    if request.endpoint in POVOLENE_PRI_ZMENE: return None
    if request.method != 'GET' or request.path.startswith('/api/'):
        return jsonify(error='Nejdřív si nastavte nové jméno a heslo.'), 409
    return redirect(url_for('obnova.zmena'))


def _cekani_text(sekund):
    minut = max(1, (sekund + 59) // 60)
    return f'Příliš mnoho chybných pokusů. Zkuste to znovu za {minut} {"minutu" if minut == 1 else "minuty" if minut < 5 else "minut"}.'


@bp.route('/login/zapomenute-heslo', methods=['GET', 'POST'])
def zapomenute():
    chyba = None
    if request.method == 'POST':
        cekat = omezeni.zbyva_cekat()
        if cekat:
            chyba = _cekani_text(cekat)
            current_app.logger.warning('obnova hesla: záchranný kód odmítnut – příliš mnoho pokusů (%s)', request.remote_addr)
        else:
            u = ucet.over_kod(request.form.get('kod', ''))
            if u:
                omezeni.vynuluj()
                session.clear()
                session['obnova_kodem'] = {'v': u['auth_version'], 't': time.time()}
                current_app.logger.info('obnova hesla: záchranný kód ověřen (%s)', request.remote_addr)
                return redirect(url_for('obnova.nove'))
            zbyva = omezeni.chyba()
            current_app.logger.warning('obnova hesla: chybný záchranný kód (%s, zbývá pokusů %s)', request.remote_addr, max(zbyva, 0))
            chyba = 'Záchranný kód nesouhlasí.' + (f' Zbývá pokusů: {zbyva}.' if zbyva > 0 else ' ' + _cekani_text(omezeni.zbyva_cekat()))
    return render_template('obnova_zapomenute.html', chyba=chyba, windows=current_app.config.get('OSVC_WINDOWS')), (400 if chyba else 200)


@bp.route('/login/nove-heslo', methods=['GET', 'POST'])
def nove():
    overeni = session.get('obnova_kodem') or {}
    u = ucet.ucet()
    if not u or overeni.get('v') != u['auth_version'] or time.time() - float(overeni.get('t') or 0) > PLATNOST_OVERENI:
        session.pop('obnova_kodem', None)
        flash('Ověření záchranným kódem vypršelo. Zadejte kód znovu.', 'error')
        return redirect(url_for('obnova.zapomenute'))
    chyba = None
    if request.method == 'POST':
        try:
            u, kod = ucet.nastav_nove(request.form.get('username'), request.form.get('password'), request.form.get('password2'), 'záchranný kód')
        except ValueError as exc:
            chyba = str(exc)
        else:
            prihlas(u)
            return zobraz_kod(kod, url_for('main.dashboard'))
    return render_template('obnova_heslo.html', rezim='kod', jmeno=request.form.get('username', u['username']), chyba=chyba), (400 if chyba else 200)


@bp.route('/ucet/zmena-hesla', methods=['GET', 'POST'])
@login_required
def zmena():
    """Vynucená změna po dočasném přihlášení osvc / osvc (jen z tohoto počítače – hlídá vynucena_zmena)."""
    u = ucet.ucet()
    if not u or not u.get('docasne'): return redirect(url_for('main.dashboard'))
    chyba = None
    if request.method == 'POST':
        try:
            u, kod = ucet.nastav_nove(request.form.get('username'), request.form.get('password'), request.form.get('password2'), 'po dočasném přihlášení')
        except ValueError as exc:
            chyba = str(exc)
        else:
            prihlas(u)
            return zobraz_kod(kod, url_for('main.dashboard'))
    return render_template('obnova_heslo.html', rezim='docasne', jmeno=request.form.get('username', ''), chyba=chyba), (400 if chyba else 200)


@bp.get('/ucet/zachranny-kod')
@login_required
def kod():
    kod = session.pop('zachranny_kod', None); dal = session.pop('zachranny_kod_dal', None) or url_for('main.dashboard')
    if not kod: return redirect(dal)
    from urllib.parse import parse_qsl, urlsplit
    cil = urlsplit(dal)   # formulář GET by parametry z action zahodil → skrytá pole
    u = ucet.ucet()
    odpoved = current_app.make_response(render_template('obnova_kod.html', kod=kod, dal_cesta=cil.path or '/', dal_parametry=parse_qsl(cil.query),
                                                        vytvoren=u.get('kod_vytvoren') if u else None))
    odpoved.headers['Cache-Control'] = 'no-store'   # tlačítko Zpět kód znovu neukáže
    return odpoved
