import os
from pathlib import Path
from datetime import date, datetime
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

def create_app(test_config=None):
    load_dotenv(Path(__file__).parent.parent / '.env')
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        DB_HOST=os.environ.get('DB_HOST', 'localhost'), DB_PORT=int(os.environ.get('DB_PORT', 3306)),
        DB_USER=os.environ.get('DB_USER'), DB_PASSWORD=os.environ.get('DB_PASSWORD'), DB_NAME=os.environ.get('DB_NAME', 'osvc'),
        DB_ENGINE=os.environ.get('DB_ENGINE', 'mysql'), DB_PATH=os.environ.get('DB_PATH'),
        APP_USER=os.environ.get('APP_USER'), APP_PASSWORD_HASH=os.environ.get('APP_PASSWORD_HASH'),
        # nastavení konektoru je jen u zdroje příjmů (DB + soubor přístupů).
        WPO_INVOICE_MAX_BYTES=int(os.environ.get('WPO_INVOICE_MAX_BYTES', str(10 * 1024 * 1024))),
        UPLOAD_FOLDER=str(Path(__file__).parent.parent / 'uploads'), MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SYSTEM_SHUTDOWN_ENABLED=os.environ.get('SYSTEM_SHUTDOWN_ENABLED','true').lower() == 'true',
    )
    # jedno sdílené spojení do DB na požadavek; testy (TESTING / OSVC_TEST) ho mají vypnuté, protože podstrkují vlastní spojení.
    app.config['DB_SHARE_CONNECTION']=not (os.environ.get('OSVC_TEST') or (test_config or {}).get('TESTING'))
    # Testovací prostředí (tests/spust.sh) má vlastní složku stavu a dokladů; ostrá služba tyto proměnné nenastavuje.
    for key in ('DATA_STATE_DIR','UPLOAD_FOLDER','THEME_SETTINGS_FILE'):
        if os.environ.get(key): app.config[key]=os.environ[key]
    # Samostatná instalace (Windows/Linux, krok I1): soubor nastavení z OSVC_CONFIG – SQLite ve složce dat, tajný klíč ze souboru.
    if os.environ.get('OSVC_CONFIG') and not (test_config or {}).get('BEZ_OSVC_CONFIG'):
        from .instalace import nastaveni_aplikace
        app.config.update(nastaveni_aplikace(os.environ['OSVC_CONFIG']))
    if test_config: app.config.update(test_config)
    if not app.config['SECRET_KEY']: raise RuntimeError('SECRET_KEY chybí v .env')
    # Přihlášení je v aplikaci (I2): APP_USER/APP_PASSWORD_HASH z nastavení se při startu jednou převezmou do databáze.
    from .backup import init_gate
    init_gate(app)
    CSRFProtect(app)
    @app.template_filter('czk')
    def czk(value):
        if value is None: return '—'
        try: text=f'{float(value):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', ' ')
        except (TypeError,ValueError): text=str(value)
        return text + ' Kč'
    @app.template_filter('cz_decimal')
    def cz_decimal(value, decimals=2):
        if value is None: return '—'
        try:
            text=f'{float(value):,.{decimals}f}'.replace(',', 'X').replace('.', ',').replace('X', ' ')
            return text
        except (TypeError,ValueError): return str(value)
    @app.template_filter('cz_date')
    def cz_date(value):
        if not value: return '—'
        if isinstance(value, (date, datetime)): return value.strftime('%d.%m.%Y')
        try: return datetime.fromisoformat(str(value)[:10]).strftime('%d.%m.%Y')
        except ValueError: return str(value)
    @app.template_filter('cz_datetime')
    def cz_datetime(value):
        # uložené časy jsou UTC (i bez pásma) → zobrazit český čas; čisté datum beze změny.
        from . import cas
        if not value: return 'zatím neproběhla'
        parsed=cas.local(value)
        if parsed: return cas.datum(parsed, s_casem=True)
        try: return cas.datum(date.fromisoformat(str(value)[:10])) if len(str(value))<=10 else str(value)
        except ValueError: return str(value)
    @app.template_filter('local_date_iso')
    def local_date_iso(value):
        from . import cas
        parsed=cas.local(value)
        return parsed.date().isoformat() if parsed else str(value or '')[:10]
    @app.template_filter('liters')
    def liters(value): return (cz_decimal(value, 1) if value is not None else '—') + (' l' if value is not None else '')
    @app.template_filter('price_l')
    def price_l(value): return (cz_decimal(value, 2) if value is not None else '—') + (' Kč/l' if value is not None else '')
    @app.template_filter('km')
    def km(value): return (cz_decimal(value, 1) if value is not None else '—') + (' km' if value is not None else '')
    @app.template_filter('woo_status')
    def woo_status(value):
        mapping={'processing':'Vyřizuje se','completed':'Dokončeno','cancelled':'Zrušeno','refunded':'Refundováno'}
        text=str(value or '')
        marker='woo_status:'
        if marker in text: return mapping.get(text.split(marker,1)[1].split(';',1)[0].strip(), 'Evidováno')
        return 'Evidováno'
    from . import pruvodce   # I3: bez účtu (samostatná instalace) vede každá stránka do průvodce prvním spuštěním
    app.before_request(pruvodce.brana)
    app.register_blueprint(pruvodce.bp)
    from . import obnova   # 1.0.3: zapomenuté heslo (záchranný kód) a vynucená změna po dočasném přihlášení osvc / osvc
    app.before_request(obnova.vynucena_zmena)
    app.register_blueprint(obnova.bp)
    from flask_wtf.csrf import CSRFError
    @app.errorhandler(CSRFError)
    def csrf_chyba(exc):
        """Formulář ze staré stránky (např. Zpět po odeslání, vypršelé přihlášení): česky a zpět, ne „400 Bad Request“."""
        from flask import flash, jsonify, redirect, render_template_string, request
        app.logger.info('CSRF: %s (%s %s)', exc.description, request.method, request.path)
        if request.is_json or request.accept_mimetypes.best == 'application/json' or request.headers.get('X-CSRFToken') or request.path.endswith(('/ares', '/preview')):
            return jsonify(error='Stránka je zastaralá. Načtěte ji znovu (F5) a akci zopakujte.'), 400
        if request.blueprint == 'pruvodce':
            try: hotovo = pruvodce.hotovo()
            except Exception: hotovo = False
            if hotovo:   # Zpět a znovu odeslat po dokončeném průvodci
                flash('Průvodce už je dokončený – aplikace je připravená.', 'info'); return redirect('/')
        zpet = request.referrer if (request.referrer or '').startswith(request.host_url) else '/'
        return render_template_string("""{% extends 'base.html' %}{% block content %}<section class="login"><h1>Formulář je zastaralý</h1>
<p>Formulář pocházel ze starší stránky (třeba po tlačítku Zpět nebo po odhlášení), proto se nic neuložilo.</p>
<p><a class="button" href="{{ zpet }}">Zpět na stránku</a> a zadejte ho prosím znovu.</p></section>{% endblock %}""", zpet=zpet), 400
    from .routes import bp
    app.register_blueprint(bp)
    from .backup_routes import bp as backup_bp
    app.register_blueprint(backup_bp)
    from .annual_routes import bp as annual_bp
    app.register_blueprint(annual_bp)
    from .expense_tax_routes import bp as expense_tax_bp
    app.register_blueprint(expense_tax_bp)
    from .income_source_routes import bp as sources_bp
    app.register_blueprint(sources_bp)
    @app.context_processor
    def income_source_context():
        from .income_sources import default_source
        return {'primary_income_source': default_source()}
    from .income_sources import sync_block_reason
    # každý restart (nasazení) dá statickým souborům novou verzi ?v=…, prohlížeč tak nepoužije starý skript ani styly.
    asset_version=str(int(__import__('time').time()))
    @app.url_defaults
    def static_version(endpoint, values):
        if endpoint=='static' and 'v' not in values: values['v']=asset_version
    from .backup import server_backup_status
    app.jinja_env.globals['server_backup_status']=server_backup_status   # jen šablona Nastavení → Záloha
    app.jinja_env.globals['server_name']=__import__('socket').gethostname()   # varování u Napájení
    app.jinja_env.globals['income_sync_block']=sync_block_reason
    from . import aktualizace as _akt   # V2: lišta „nová verze“ a karta v Nastavení (jen samostatná instalace)
    app.jinja_env.globals['aktualizace_upozorneni']=_akt.upozorneni
    app.jinja_env.globals['aktualizace_prehled']=_akt.prehled
    app.jinja_env.globals['aktualizace_okno']=_akt.okno   # called only by templates with a Synchronize button
    # Přechod na SQLite (S3–S7): převod dat a srovnání. Spouští správce (skript S6), ne webová aplikace.
    import click as _click

    @app.cli.command('prevod-do-sqlite')
    @_click.argument('cil')
    def prevod_do_sqlite(cil):
        """MySQL (nastavená) → nový soubor SQLite CIL, pak srovnávací přehled. Kód 1 = rozdíly."""
        from . import prevod
        from .backup import data_lock
        with data_lock(exclusive=True):   # výhradně: během převodu nesmí běžet synchronizace ani obnova
            prevod.mysql_do_sqlite(cil, vypis=_click.echo)
            _, ok = prevod.porovnej_databaze(cil, vypis=_click.echo)
        raise SystemExit(0 if ok else 1)

    @app.cli.command('prevod-porovnej')
    @_click.argument('soubor')
    @_click.option('--vse', is_flag=True, help='vypsat i shodné řádky')
    def prevod_porovnej(soubor, vse):
        """Srovnávací přehled MySQL (nastavená) × soubor SQLite. Jen čte. Kód 1 = rozdíly."""
        from . import prevod
        _, ok = prevod.porovnej_databaze(soubor, vypis=_click.echo, jen_rozdily=not vse)
        raise SystemExit(0 if ok else 1)

    @app.cli.command('prevod-do-mysql')
    @_click.argument('zdroj')
    @_click.option('--nahradit-data-mysql', 'potvrzeno', is_flag=True, help='výslovné potvrzení: obsah tabulek OSVČ v MySQL se nahradí')
    def prevod_do_mysql(zdroj, potvrzeno):
        """Cesta zpět: soubor SQLite → MySQL (nastavená), obsah tabulek nahradí v jedné transakci, pak srovnání. Kód 1 = rozdíly."""
        from . import prevod
        from .backup import data_lock
        if not potvrzeno: raise SystemExit('Chybí --nahradit-data-mysql (obsah tabulek OSVČ v MySQL se nahradí daty ze SQLite).')
        with data_lock(exclusive=True):   # výhradně: během převodu nesmí běžet synchronizace ani obnova
            prevod.sqlite_do_mysql(zdroj, vypis=_click.echo)
            _, ok = prevod.porovnej_databaze(zdroj, vypis=_click.echo)
        raise SystemExit(0 if ok else 1)

    @app.cli.command('zaloha-db')
    @_click.argument('slozka')
    def zaloha_db_prikaz(slozka):
        """Noční záloha SQLite: konzistentní snímek + kontrola integrity + gzip do SLOZKA/osvc_<čas>.sqlite3.gz. Vypíše cestu."""
        from .zaloha_db import vytvor
        _click.echo(vytvor(slozka))

    @app.cli.command('sync-income-sources')
    def scheduled_income_sync():
        """Plánovaná synchronizace zdrojů příjmů (server: osvc-income-sync.timer; Windows: plánovač ve spouštěči)."""
        import click
        from .income_sources import planovana_synchronizace
        vysledek = planovana_synchronizace(lambda text, chyba=False: click.echo(text, err=chyba))
        if vysledek['chyb']: raise SystemExit(1)
    from . import moduly as _moduly
    @app.context_processor
    def moduly_context():
        return {'moduly_zapnute': _moduly.zapnute()}
    @app.before_request
    def vypnuty_modul():
        from flask import flash, redirect, request
        klic = _moduly.modul_adresy(request.path)
        if klic and not _moduly.zapnuto(klic):
            flash(f"Modul {_moduly.MODULY[klic]['nazev']} je vypnutý. Zapnete ho v Nastavení → Moduly.", 'info')
            return redirect('/')
    from .themes import THEMES, THEME_GROUPS, saved_theme
    @app.context_processor
    def appearance():
        return {"themes": THEMES, "theme_groups": THEME_GROUPS, "selected_theme": saved_theme()}
    @app.after_request
    def save_feedback(response):
        from flask import request, session
        if request.method=='POST' and request.form.get('_save_action')=='yes' and 300<=response.status_code<400:
            session['_flashes']=[('saved' if category=='success' else category, message) for category,message in session.get('_flashes',[])]
        return response
    from .db import close_shared
    app.teardown_appcontext(close_shared)
    if not app.config.get('TESTING'):
        from .struktura import pri_startu
        pri_startu(app)   # V1: starší databáze → snímek, úprava struktury, při chybě návrat a aplikace se nespustí
        from .schema import check_at_start
        check_at_start(app)   # jednou při startu, jen zápis do logu
        try:   # I2: přihlášení z nastavení serveru jednou do databáze (pak platí jen účet v aplikaci); v testech jen výslovně
            if os.environ.get('OSVC_TEST'): raise LookupError('testy')
            with app.app_context():
                from .ucet import prevezmi_z_nastaveni
                prevezmi_z_nastaveni()
        except LookupError: pass
        except Exception as exc:
            app.logger.warning('převzetí přihlášení do aplikace nešlo: %s', type(exc).__name__)
    return app
