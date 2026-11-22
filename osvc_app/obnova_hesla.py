"""Nástroj „Obnovit heslo“ (1.0.3) – zapomenuté heslo přímo na počítači, kde aplikace běží.

    python -m osvc_app.obnova_hesla [--config SOUBOR] [--ano]

--config = samostatná instalace (Windows: zástupce „OSVČ evidence – obnovit heslo“, Linux .deb: sudo osvc-evidence obnovit-heslo);
bez něj nastavení z prostředí / .env (server). Nastaví dočasné přihlášení osvc / osvc, které platí jen z tohoto počítače
a po přihlášení vynutí změnu jména a hesla; všechna zařízení se odhlásí. Data, doklady ani nastavení se nemění.
Kódy: 0 hotovo · 1 zrušeno · 2 chyba.
"""
import argparse
import os
import sys

OTAZKA = ('Obnovit přihlášení do OSVČ evidence?\n\n'
          'Jméno i heslo se dočasně nastaví na osvc / osvc. Přihlásit se tak půjde jen na tomto počítači '
          'a aplikace hned vyžádá nové jméno a heslo. Všechna zařízení se odhlásí.\n\n'
          'Data, doklady ani nastavení se nemění.')
HOTOVO = ('Heslo bylo obnoveno, přihlaste se jako osvc / osvc na tomto počítači.\n\n'
          'Adresa: {adresa}\n'
          'Po přihlášení si nastavíte nové jméno a heslo a dostanete nový záchranný kód. Ostatní zařízení byla odhlášena.')
ZNACKA = 'OSVČ evidence – obnovit heslo'


def _okno():
    """Windows bez konzole (pythonw ze zástupce, sys.stdout je None): zprávy v okně. python.exe (i s přesměrovaným výstupem) píše text."""
    return os.name == 'nt' and sys.stdout is None


def zprava(text, chyba=False):
    if _okno():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, ZNACKA, 0x10 if chyba else 0x40); return
        except Exception: pass
    if sys.stderr is not None: print(text, file=sys.stderr if chyba else sys.stdout, flush=True)


def otazka(text):
    if _okno():
        try:
            import ctypes
            return ctypes.windll.user32.MessageBoxW(None, text, ZNACKA, 0x04 | 0x20 | 0x100) == 6   # Ano/Ne, otazník, výchozí Ne
        except Exception: return False
    if sys.stdin is None or not sys.stdin.isatty(): return False
    print(text, flush=True)
    try: return input('Pokračovat? [a/N] ').strip().lower() in ('a', 'ano', 'y', 'yes')
    except EOFError: return False


def priprav_aplikaci(config=None):
    """Flask aplikace pro zápis do databáze. --config = samostatná instalace (jako ZIP záloha při odinstalaci)."""
    adresa = None
    if config:
        from . import instalace
        from .spoustec import adresa as adresa_aplikace
        hodnoty = instalace.nacti(config)
        os.environ['OSVC_CONFIG'] = os.path.abspath(config)
        instalace.priprav(hodnoty)
        adresa = adresa_aplikace(hodnoty)
        import logging, logging.handlers   # záznam do stejného logu jako aplikace (DATA_DIR/logy/osvc.log)
        slozka = instalace.slozky(hodnoty)['logy']; slozka.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(slozka / 'osvc.log', encoding='utf-8'); h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        koren = logging.getLogger(); koren.addHandler(h); koren.setLevel(logging.INFO)
    import logging
    from . import create_app, schema
    schema.log.setLevel(logging.WARNING)   # „struktura DB v pořádku“ do výpisu nástroje nepatří
    app = create_app()
    if not config:   # server: záznam do systémového logu dělá obalový skript (logger); výpis v terminálu jen hláška nástroje
        from flask.logging import default_handler
        app.logger.removeHandler(default_handler); app.logger.addHandler(logging.NullHandler())
    return app, adresa


def obnov(config=None):
    """Nastaví dočasné přihlášení; vrátí adresu aplikace na tomto počítači (nebo None)."""
    app, adresa = priprav_aplikaci(config)
    with app.app_context():
        from . import ucet
        ucet.docasne_prihlaseni()
    return adresa or os.environ.get('OSVC_ADRESA') or 'http://localhost/'


def main(argv=None):
    p = argparse.ArgumentParser(prog='osvc-evidence obnovit-heslo', description='Zapomenuté heslo: dočasné přihlášení osvc / osvc jen na tomto počítači.')
    p.add_argument('--config', help='soubor nastavení samostatné instalace')
    p.add_argument('--ano', action='store_true', help='bez otázky (potvrzeno předem)')
    a = p.parse_args(argv)
    if not a.ano and not otazka(OTAZKA):
        zprava('Zrušeno, nic se nezměnilo.'); return 1
    try:
        adresa = obnov(a.config)
    except FileNotFoundError as exc:
        zprava(f'Heslo nejde obnovit: chybí soubor nastavení ({exc.filename}). Je aplikace na tomto počítači nainstalovaná?', chyba=True); return 2
    except ValueError as exc:
        zprava(f'Heslo nejde obnovit: {exc}', chyba=True); return 2
    except Exception as exc:
        zprava(f'Heslo nejde obnovit: {type(exc).__name__}: {exc}', chyba=True); return 2
    zprava(HOTOVO.format(adresa=adresa)); return 0


if __name__ == '__main__':
    sys.exit(main())
