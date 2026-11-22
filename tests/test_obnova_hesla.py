"""1.0.3 – obnova zapomenutého hesla: záchranný kód (jen otisk, ukáže se jednou), Zapomněl jsem heslo, omezení pokusů,
dočasné přihlášení osvc / osvc jen z tohoto počítače s vynucenou změnou, nástroj Obnovit heslo (spoustec obnovit-heslo).
Data se nikdy nemění. Pracuje s kopií SQLite od tests/spust.sh (DB_PATH)."""
import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from werkzeug.security import generate_password_hash
from osvc_app import create_app, db, obnova, ucet

TMP = tempfile.TemporaryDirectory()
import osvc_app
KOREN = Path(osvc_app.__file__).resolve().parent.parent   # testy běží přes stdin – __file__ nepomůže
MISTNI, CIZI = '127.0.0.1', '192.0.2.10'


def setUpModule():
    if os.environ.get('DB_ENGINE') != 'sqlite': raise unittest.SkipTest('jen pro SQLite (kopie vzoru)')


def spojeni(cesta):
    c = sqlite3.connect(str(cesta))
    c.create_collation('OSVC_CI', lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    return c


def token(k, url):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', k.get(url).get_data(as_text=True))
    return m.group(1) if m else ''


class Zaklad(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH'], 'MODULY_SETTINGS_FILE': TMP.name + '/m.json'})
        self.v(db.execute, "UPDATE app_accounts SET username='osvc', password_hash=%s, auth_version=1, password_reset_token_hash=NULL, password_reset_requested_at=NULL, "
               "password_reset_expires_at=NULL, email_verification_token_hash=NULL WHERE id=1", (generate_password_hash('x'),))
        self.v(ucet.prevezmi_z_nastaveni)   # spravovaný účet osvc / osvc (z nastavení testů)
        obnova.omezeni.vynuluj()

    def v(self, funkce, *argumenty):
        """Přímé volání v samostatném kontextu aplikace – požadavky testovacího klienta mají každý svůj (jako v prohlížeči)."""
        with self.app.app_context(): return funkce(*argumenty)

    def ucet(self): return self.v(ucet.ucet)

    def over(self, kod): return self.v(ucet.over_kod, kod)

    def klient(self, adresa=MISTNI):
        k = self.app.test_client(); k.environ_base['REMOTE_ADDR'] = adresa
        return k

    def prihlas(self, k, jmeno, heslo):
        return k.post('/login', data={'csrf_token': token(k, '/login'), 'username': jmeno, 'password': heslo})

    def otisk_dat(self):
        """Všechny tabulky kromě účtu a auditu – obnova hesla je nesmí změnit."""
        c = spojeni(os.environ['DB_PATH']); h = hashlib.sha256()
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('app_accounts','audit_log') AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            for r in c.execute(f'SELECT * FROM "{t}" ORDER BY 1'): h.update(repr(r).encode())
        c.close(); return h.hexdigest()

    def novy_kod_z_nastaveni(self, k, heslo):
        r = k.post('/settings/account/rescue-code', data={'csrf_token': token(k, '/settings'), 'rescue_current_password': heslo})
        self.assertEqual(r.headers.get('Location'), '/ucet/zachranny-kod', r.get_data(as_text=True)[-1500:])
        html = k.get('/ucet/zachranny-kod').get_data(as_text=True)
        return re.search(r'data-zachranny-kod>([A-Z0-9-]+)<', html).group(1), html


class ZachrannyKod(Zaklad):
    def test_kod_jen_otisk_ukaze_se_jednou(self):
        k = self.klient(); self.prihlas(k, 'osvc', 'osvc')
        self.assertIn('Zatím nemáte záchranný kód', k.get('/settings').get_data(as_text=True))
        r = k.post('/settings/account/rescue-code', data={'csrf_token': token(k, '/settings'), 'rescue_current_password': 'spatne'}, follow_redirects=True)
        self.assertIn('Současné heslo nesouhlasí', r.get_data(as_text=True)); self.assertIsNone(self.ucet()['kod_otisk'])
        kod, html = self.novy_kod_z_nastaveni(k, 'osvc')
        self.assertRegex(kod, r'^[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}$')
        for text in ('Vytisknout', 'Stáhnout jako .txt', 'Kód jsem si uložil', 'type="checkbox" required', 'name="tab" value="account"', 'obnova-kod.js'):
            self.assertIn(text, html, text)
        self.assertEqual(k.get('/ucet/zachranny-kod').status_code, 302, 'podruhé se kód neukáže')
        radek = spojeni(os.environ['DB_PATH']).execute('SELECT * FROM app_accounts WHERE id=1').fetchone()
        self.assertFalse(any(kod in str(x) or kod.replace('-', '') in str(x) for x in radek), 'kód v databázi jen jako otisk')
        self.assertIn('Vytvořen', k.get('/settings').get_data(as_text=True))
        self.assertTrue(self.over(kod.lower().replace('-', ' '))); self.assertFalse(self.over('AAAA-AAAA-AAAA'))
        kod2, _ = self.novy_kod_z_nastaveni(k, 'osvc')
        self.assertFalse(self.over(kod), 'nový kód nahradí starý'); self.assertTrue(self.over(kod2))

    def test_zmena_hesla_v_nastaveni_da_novy_kod(self):
        k = self.klient(); self.prihlas(k, 'osvc', 'osvc')
        kod, _ = self.novy_kod_z_nastaveni(k, 'osvc')
        r = k.post('/settings/account', data={'csrf_token': token(k, '/settings'), 'username': 'osvc', 'current_password': 'osvc', 'new_password': 'noveheslo1', 'new_password2': 'noveheslo1'})
        self.assertEqual(r.headers['Location'], '/ucet/zachranny-kod')
        novy = re.search(r'data-zachranny-kod>([A-Z0-9-]+)<', k.get('/ucet/zachranny-kod').get_data(as_text=True)).group(1)
        self.assertFalse(self.over(kod)); self.assertTrue(self.over(novy))
        r = k.post('/settings/account', data={'csrf_token': token(k, '/settings'), 'username': 'majitel', 'current_password': 'noveheslo1'})
        self.assertIn('tab=account', r.headers['Location'], 'změna jen jména kód nemění'); self.assertTrue(self.over(novy))

    def test_pruvodce_bez_kodu_na_prihlaseni(self):
        html = self.klient().get('/login').get_data(as_text=True)
        self.assertIn('href="/login/zapomenute-heslo"', html); self.assertIn('Zapomněl jsem heslo', html)


class Zapomenute(Zaklad):
    def test_kod_nove_jmeno_a_heslo_novy_kod(self):
        k = self.klient(); self.prihlas(k, 'osvc', 'osvc'); kod, _ = self.novy_kod_z_nastaveni(k, 'osvc')
        data_pred = self.otisk_dat()
        z = self.klient(CIZI)   # přes síť: záchranný kód funguje odkudkoli
        self.assertEqual(z.get('/login/nove-heslo').headers['Location'], '/login/zapomenute-heslo', 'bez ověření kódem nic')
        stranka = z.get('/login/zapomenute-heslo').get_data(as_text=True)
        self.assertIn('Nemáte záchranný kód?', stranka); self.assertIn('sudo osvc-evidence obnovit-heslo', stranka); self.assertNotIn('nabídka Start', stranka)
        self.app.config['OSVC_WINDOWS'] = True
        stranka = z.get('/login/zapomenute-heslo').get_data(as_text=True); self.app.config['OSVC_WINDOWS'] = False
        self.assertIn('OSVČ evidence – obnovit heslo', stranka); self.assertNotIn('sudo', stranka)
        r = z.post('/login/zapomenute-heslo', data={'csrf_token': token(z, '/login/zapomenute-heslo'), 'kod': 'AAAA-BBBB-CCCC'})
        self.assertEqual(r.status_code, 400); self.assertIn('Zbývá pokusů: 4', r.get_data(as_text=True))
        r = z.post('/login/zapomenute-heslo', data={'csrf_token': token(z, '/login/zapomenute-heslo'), 'kod': ' ' + kod.lower().replace('-', ' ') + ' '})
        self.assertEqual(r.headers['Location'], '/login/nove-heslo')
        html = z.get('/login/nove-heslo').get_data(as_text=True); self.assertIn('value="osvc"', html, 'předvyplněné současné jméno')
        t = token(z, '/login/nove-heslo')
        for data, hlaska in (({'username': 'jana', 'password': 'kratke', 'password2': 'kratke'}, 'aspoň 8 znaků'),
                             ({'username': 'jana', 'password': 'noveheslo1', 'password2': 'noveheslo2'}, 'se liší'),
                             ({'username': 'j', 'password': 'noveheslo1', 'password2': 'noveheslo1'}, '3 až 50 znaků')):
            r = z.post('/login/nove-heslo', data={'csrf_token': t, **data}); self.assertEqual(r.status_code, 400); self.assertIn(hlaska, r.get_data(as_text=True))
        r = z.post('/login/nove-heslo', data={'csrf_token': t, 'username': 'jana', 'password': 'noveheslo1', 'password2': 'noveheslo1'})
        self.assertEqual(r.headers['Location'], '/ucet/zachranny-kod')
        novy = re.search(r'data-zachranny-kod>([A-Z0-9-]+)<', z.get('/ucet/zachranny-kod').get_data(as_text=True)).group(1)
        self.assertNotEqual(novy, kod); self.assertFalse(self.over(kod), 'použitý kód přestal platit'); self.assertTrue(self.over(novy))
        self.assertEqual(z.get('/').status_code, 200, 'po obnově přihlášen')
        self.assertEqual(k.get('/settings').headers['Location'], '/login', 'ostatní zařízení odhlášena')
        self.assertEqual(self.prihlas(self.klient(), 'osvc', 'osvc').status_code, 200)
        self.assertEqual(self.prihlas(self.klient(), 'jana', 'noveheslo1').status_code, 302)
        self.assertEqual(z.get('/login/nove-heslo').headers['Location'], '/login/zapomenute-heslo', 'ověření platí jen jednou')
        self.assertEqual(self.otisk_dat(), data_pred, 'data se nezměnila')

    def test_omezeni_pokusu(self):
        k = self.klient(); self.prihlas(k, 'osvc', 'osvc'); kod, _ = self.novy_kod_z_nastaveni(k, 'osvc')
        z = self.klient(CIZI); t = token(z, '/login/zapomenute-heslo')
        ted = [1000.0]
        with mock.patch('osvc_app.obnova.time.monotonic', side_effect=lambda: ted[0]):
            for i in range(5):
                r = z.post('/login/zapomenute-heslo', data={'csrf_token': t, 'kod': f'AAAA-AAAA-AAA{i + 2}'}); self.assertEqual(r.status_code, 400)
            self.assertIn('Příliš mnoho chybných pokusů', r.get_data(as_text=True))
            r = z.post('/login/zapomenute-heslo', data={'csrf_token': t, 'kod': kod})
            self.assertEqual(r.status_code, 400, 'ani správný kód během blokace'); self.assertIn('za 15 minut', r.get_data(as_text=True))
            r = self.klient('192.0.2.77').post('/login/zapomenute-heslo', data={'csrf_token': t, 'kod': kod})
            self.assertEqual(r.status_code, 400, 'blokace platí pro celou aplikaci, ne jen jednu adresu')
            ted[0] += 14 * 60
            self.assertIn('za 1 minutu', z.post('/login/zapomenute-heslo', data={'csrf_token': t, 'kod': kod}).get_data(as_text=True))
            ted[0] += 61
            r = z.post('/login/zapomenute-heslo', data={'csrf_token': t, 'kod': kod}); self.assertEqual(r.headers['Location'], '/login/nove-heslo', 'po 15 minutách znovu')


class DocasnePrihlaseni(Zaklad):
    def test_jen_z_tohoto_pocitace_a_vynucena_zmena(self):
        jinde = self.klient('192.0.2.50'); self.prihlas(jinde, 'osvc', 'osvc'); self.assertEqual(jinde.get('/').status_code, 200)
        data_pred = self.otisk_dat(); verze = self.ucet()['auth_version']
        self.v(ucet.docasne_prihlaseni)
        u = self.ucet(); self.assertEqual((u['username'], u['auth_version']), ('osvc', verze + 1)); self.assertIsNotNone(u['docasne'])
        self.assertEqual(jinde.get('/').headers['Location'], '/login', 'všechna zařízení odhlášena')
        # přes síť nikdy – ani se zapnutým síťovým přístupem
        r = self.prihlas(self.klient(CIZI), 'osvc', 'osvc')
        self.assertEqual(r.status_code, 403, r.get_data(as_text=True)[-1500:]); self.assertIn('jen přímo na počítači', r.get_data(as_text=True))
        # z tohoto počítače: jen stránka změny
        k = self.klient(); r = self.prihlas(k, 'osvc', 'osvc'); self.assertEqual(r.status_code, 302)
        for url in ('/', '/settings', '/payments/income', '/annual', '/ucet/zachranny-kod'):
            self.assertEqual(k.get(url).headers['Location'], '/ucet/zmena-hesla', url)
        self.assertEqual(k.post('/settings/account', data={'csrf_token': token(k, '/ucet/zmena-hesla')}).status_code, 409)
        html = k.get('/ucet/zmena-hesla').get_data(as_text=True); self.assertIn('Jste přihlášeni dočasně', html); self.assertIn('/logout', html)
        # stejná session ze sítě (třeba ukradená cookie) = odhlášení
        cookie = k.get_cookie('session').value
        zcizi = self.klient(CIZI); zcizi.set_cookie('session', cookie)
        self.assertEqual(zcizi.get('/ucet/zmena-hesla').headers['Location'], '/login')
        t = token(k, '/ucet/zmena-hesla')
        r = k.post('/ucet/zmena-hesla', data={'csrf_token': t, 'username': 'OSVC', 'password': 'noveheslo1', 'password2': 'noveheslo1'})
        self.assertEqual(r.status_code, 400); self.assertIn('jiné uživatelské jméno', r.get_data(as_text=True))
        r = k.post('/ucet/zmena-hesla', data={'csrf_token': t, 'username': 'majitel', 'password': 'kratke', 'password2': 'kratke'})
        self.assertEqual(r.status_code, 400); self.assertIsNotNone(self.ucet()['docasne'], 'chybný pokus nic nezměnil')
        r = k.post('/ucet/zmena-hesla', data={'csrf_token': t, 'username': 'majitel', 'password': 'noveheslo1', 'password2': 'noveheslo1'})
        self.assertEqual(r.headers['Location'], '/ucet/zachranny-kod')
        kod = re.search(r'data-zachranny-kod>([A-Z0-9-]+)<', k.get('/ucet/zachranny-kod').get_data(as_text=True)).group(1)
        u = self.ucet(); self.assertIsNone(u['docasne']); self.assertEqual((u['username'], u['auth_version']), ('majitel', verze + 2)); self.assertTrue(self.over(kod))
        self.assertEqual(k.get('/').status_code, 200); self.assertEqual(k.get('/ucet/zmena-hesla').headers['Location'], '/')
        self.assertEqual(self.prihlas(self.klient(), 'osvc', 'osvc').status_code, 200, 'dočasné přihlášení už neplatí')
        self.assertEqual(self.prihlas(self.klient(CIZI), 'majitel', 'noveheslo1').status_code, 302, 'nové heslo funguje i přes síť')
        self.assertEqual(self.otisk_dat(), data_pred, 'data se nezměnila')

    def test_je_mistni(self):
        for adresa in ('127.0.0.1', '127.0.1.1', '::1', '::ffff:127.0.0.1'): self.assertTrue(obnova.je_mistni(adresa), adresa)
        for adresa in ('192.0.2.10', '203.0.113.5', '2001:db8::1', '', 'nesmysl', '0.0.0.0x'): self.assertFalse(obnova.je_mistni(adresa), adresa)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s: s.connect(('192.0.2.1', 9)); vlastni = s.getsockname()[0]
        except OSError: vlastni = None
        if vlastni and not vlastni.startswith('127.'): self.assertTrue(obnova.je_mistni(vlastni), 'vlastní adresa počítače (síťová karta)')

    def test_stare_hodnoty_z_doby_dockeru_se_nepouziji(self):
        """Dřívější obnova hesla e-mailem mohla ve sloupcích nechat hodnoty – bez značky 1.0.3 nic nespustí."""
        self.v(db.execute, "UPDATE app_accounts SET password_reset_token_hash=%s, password_reset_requested_at='2025-01-01 10:00:00', password_reset_expires_at='2025-01-02 10:00:00', "
               "email_verification_token_hash=%s WHERE id=1", (generate_password_hash('ABCDABCDABCD'), 'a' * 64))
        u = self.ucet(); self.assertIsNone(u['kod_otisk']); self.assertIsNone(u['docasne']); self.assertIsNone(u['kod_vytvoren'])
        self.assertFalse(self.over('ABCD-ABCD-ABCD'))
        k = self.klient(CIZI); self.assertEqual(self.prihlas(k, 'osvc', 'osvc').status_code, 302, 'běžné přihlášení i přes síť')
        self.assertEqual(k.get('/').status_code, 200); self.assertIn('Zatím nemáte záchranný kód', k.get('/settings').get_data(as_text=True))

    def test_bez_uctu(self):
        self.v(db.execute, 'UPDATE app_accounts SET auth_version=1'); self.app.config['APP_USER'] = None
        with self.assertRaisesRegex(ValueError, 'průvodce'): self.v(ucet.docasne_prihlaseni)


class FormulareSHeslem(Zaklad):
    """Atributy pro prohlížeče a správce hesel, oddělené formuláře se „Současným heslem“, ikonka oka."""
    def pole(self, html, form_id=None):
        if form_id: html = re.search(r'<form[^>]*id="%s".*?</form>' % form_id, html, re.S).group(0)
        return [dict(re.findall(r'([\w-]+)="([^"]*)"', i)) for i in re.findall(r'<input([^>]*)>', html)]

    def test_atributy(self):
        k = self.klient()
        login = {p.get('name'): p for p in self.pole(k.get('/login').get_data(as_text=True))}
        self.assertEqual((login['username']['autocomplete'], login['password']['autocomplete'], login['password']['type']), ('username', 'current-password', 'password'))
        self.prihlas(k, 'osvc', 'osvc'); html = k.get('/settings').get_data(as_text=True)
        zmena = {p.get('name'): p for p in self.pole(html, 'ucet-zmena-hesla')}
        self.assertEqual({n: zmena[n]['autocomplete'] for n in ('username', 'current_password', 'new_password', 'new_password2')},
                         {'username': 'username', 'current_password': 'current-password', 'new_password': 'new-password', 'new_password2': 'new-password'})
        self.assertEqual((zmena['new_password']['id'], zmena['new_password2']['id']), ('ucet-nove-heslo', 'ucet-nove-heslo-znovu'))
        kod = {p.get('name'): p for p in self.pole(html, 'ucet-zachranny-kod')}
        self.assertEqual(kod['rescue_current_password']['autocomplete'], 'current-password'); self.assertEqual(kod['rescue_username']['autocomplete'], 'username')
        self.assertNotIn('current_password', kod, 'každý formulář má své jednoznačné pole současného hesla')
        self.assertNotIn('rescue_current_password', zmena)
        ids = re.findall(r'\bid="([^"]+)"', html); self.assertEqual(len(ids), len(set(ids)), 'id na stránce jen jednou')
        self.assertNotIn('autocomplete="off"', re.search(r'<form[^>]*id="ucet-zmena-hesla"[^>]*>', html).group(0))
        # vynucená změna a nové heslo po kódu: jméno + 2× new-password
        self.v(ucet.docasne_prihlaseni); d = self.klient(); self.prihlas(d, 'osvc', 'osvc')
        obnova_pole = {p.get('name'): p for p in self.pole(d.get('/ucet/zmena-hesla').get_data(as_text=True), 'obnova-nove-prihlaseni')}
        self.assertEqual([obnova_pole[n]['autocomplete'] for n in ('username', 'password', 'password2')], ['username', 'new-password', 'new-password'])
        pruvodce = (KOREN / 'osvc_app/templates/pruvodce.html').read_text(encoding='utf-8')
        for text in ('id="pruvodce-jmeno" name="username"', 'autocomplete="username"', 'id="pruvodce-nove-heslo" name="password"', 'id="pruvodce-nove-heslo-znovu" name="password2"'):
            self.assertIn(text, pruvodce)
        self.assertEqual(pruvodce.count('autocomplete="new-password"'), 2)

    def test_ikonka_oka(self):
        js = (KOREN / 'osvc_app/static/ui.js').read_text(encoding='utf-8')
        for text in ("input[type=password]", "'Zobrazit heslo'", "'Skrýt heslo'", 'aria-pressed', 'aria-controls', "b.type = 'button'", "addEventListener('submit'"):
            self.assertIn(text, js, text)


class Nastroj(unittest.TestCase):
    """spoustec obnovit-heslo --config (Windows zástupce, Linux sudo osvc-evidence obnovit-heslo)."""
    def spust(self, *argumenty, vstup=None):
        env = {k: v for k, v in os.environ.items() if k not in ('APP_USER', 'APP_PASSWORD_HASH', 'DB_PATH', 'DB_ENGINE')}
        return subprocess.run([sys.executable, '-X', 'utf8', '-m', 'osvc_app.spoustec', 'obnovit-heslo', '--config', str(self.konf), *argumenty],
                              input=vstup, capture_output=True, text=True, env=env, timeout=120, cwd=KOREN)

    def test_nastroj(self):
        self.konf = Path(TMP.name) / 'n' / 'osvc.conf'; data = Path(TMP.name) / 'n' / 'data'
        r = subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'init', '--config', str(self.konf), '--data', str(data), '--port', '8799'], capture_output=True, text=True, cwd=KOREN)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.spust('--ano'); self.assertEqual(r.returncode, 2, r.stdout + r.stderr); self.assertIn('průvodce prvním spuštěním', r.stderr)
        c = spojeni(data / 'osvc.sqlite3')
        c.execute("INSERT INTO app_accounts (id, username, password_hash, auth_version) VALUES (1, 'jana', ?, 2)", (generate_password_hash('heslo-jany-1'),)); c.commit()
        pocty = {t: c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('vehicles', 'travel_rates', 'counterparties')}
        r = self.spust(vstup='n\n'); self.assertEqual(r.returncode, 1, 'bez potvrzení (ne terminál) nic'); self.assertIn('Zrušeno', r.stdout)
        self.assertEqual(c.execute('SELECT username FROM app_accounts').fetchone()[0], 'jana')
        r = self.spust('--ano'); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Heslo bylo obnoveno, přihlaste se jako osvc / osvc na tomto počítači', r.stdout); self.assertIn('http://localhost:8799/', r.stdout)
        jmeno, verze, docasne = c.execute('SELECT username, auth_version, email_verification_token_hash FROM app_accounts').fetchone()
        self.assertEqual((jmeno, verze), ('osvc', 3)); self.assertTrue(docasne.startswith('osvc-docasne:'))
        self.assertEqual({t: c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in pocty}, pocty, 'data beze změny')
        self.assertIn('nástroj Obnovit heslo nastavil dočasné přihlášení', (data / 'logy' / 'osvc.log').read_text(encoding='utf-8'))
        c.close()


class Balicky(unittest.TestCase):
    def test_windows_a_linux(self):
        iss = (KOREN / 'scripts/windows/osvc.iss').read_text(encoding='utf-8-sig')
        self.assertIn('Source: "Obnovit heslo.cmd"; DestDir: "{app}"', iss)
        self.assertIn('Name: "{autoprograms}\\{#Nazev} – obnovit heslo"', iss); self.assertIn('osvc_app.spoustec obnovit-heslo --config ""{#Konf}""', iss)
        sys.path.insert(0, str(KOREN / 'scripts/windows'))
        import sestav
        self.assertIn('osvc_app.spoustec obnovit-heslo --config "%LOCALAPPDATA%\\OSVC evidence\\osvc.conf"', sestav.OBNOVIT_CMD); sestav.OBNOVIT_CMD.encode('ascii')
        deb = (KOREN / 'scripts/linux/debian/osvc-evidence').read_text(encoding='utf-8')
        self.assertIn('runuser -u osvc-evidence -- /opt/osvc-evidence/venv/bin/python -X utf8 -m osvc_app.spoustec obnovit-heslo --config /etc/osvc-evidence/osvc.conf', deb)
        readme = (KOREN / 'README.md').read_text(encoding='utf-8')
        self.assertIn('## Zapomenuté heslo', readme); self.assertIn('sudo osvc-evidence obnovit-heslo', readme)


if __name__ == '__main__':
    unittest.main()
