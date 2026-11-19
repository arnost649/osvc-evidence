"""V3 – odinstalace Windows: ZIP záloha příkazem spouštěče (i při běžící aplikaci, obnovitelná), skript instalátoru:
ponechat data (výchozí) / smazat i data se zálohou a potvrzením, tichý režim pro testy, žádná služba ani pravidlo firewallu.
Instalátor sám (Inno Setup) se ověří v GitHub Actions (V5). Běží jen přes tests/spust.sh."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from osvc_app import instalace, sqlite_db

TMP = tempfile.TemporaryDirectory()
KOREN = Path.cwd()


def spoustec(*args, **kw):
    return subprocess.run([sys.executable, '-X', 'utf8', '-m', 'osvc_app.spoustec', *args], capture_output=True, text=True, timeout=120, cwd=KOREN, **kw)


class ZalohaZip(unittest.TestCase):
    def test_zip_na_plochu(self):
        konf = Path(TMP.name) / 'a' / 'osvc.conf'; instalace.zapis_nastaveni(konf, konf.parent / 'data')
        s = instalace.priprav(instalace.nacti(konf))
        c = sqlite_db.otevri(s['db']); c.execute("INSERT INTO vehicles (name, active) VALUES ('Škoda Octavia', 1)"); c.close()
        (s['uploads'] / 'doklad.pdf').write_bytes(b'%PDF-1.4 zkusebni')
        plocha = Path(TMP.name) / 'Plocha s mezerou'
        r = spoustec('zaloha-zip', '--config', str(konf), '--cil', str(plocha))
        self.assertEqual(r.returncode, 0, r.stderr)
        zipy = list(plocha.glob('OSVC-evidence-zaloha-*.zip')); self.assertEqual(len(zipy), 1); self.assertEqual(Path(r.stdout.strip()), zipy[0])
        self.assertFalse(list(plocha.glob('*.part')))
        with zipfile.ZipFile(zipy[0]) as z:
            m = json.loads(z.read('manifest.json')); data = json.loads(z.read('database/data.json'))
            self.assertEqual(z.read('files/uploads/doklad.pdf'), b'%PDF-1.4 zkusebni', 'doklady jsou v záloze')
            self.assertIn('files/uploads/doklad.pdf', [f['path'] for f in m['files']])
        self.assertIn('Škoda Octavia', json.dumps(data['tables']['vehicles'], ensure_ascii=False))
        self.assertNotIn('app_accounts', data['tables'])

    def test_chyba_zalohy_kod_5(self):
        r = spoustec('zaloha-zip', '--config', str(Path(TMP.name) / 'neni.conf'), '--cil', str(Path(TMP.name) / 'x'))
        self.assertEqual(r.returncode, 5); self.assertIn('ZIP zálohu nejde vytvořit', r.stderr)


class SkriptInstalatoru(unittest.TestCase):
    iss = (KOREN / 'scripts' / 'windows' / 'osvc.iss').read_text(encoding='utf-8')

    def test_volby_odinstalace(self):
        for text in ("'Ponechat data (doporučeno)', 'Smazat i data'", 'Uložit zálohu na Plochu', 'MB_DEFBUTTON2', "{param:SMAZATDATA|0}",
                     "zaloha-zip --config", 'DelTree(ExpandConstant(\'{localappdata}\\OSVC evidence\')', 'ZastavAplikaci();      // dokud je Python'):
            self.assertIn(text, self.iss)
        self.assertLess(self.iss.index('ZalohaZip(ExpandConstant(\'{param:ZALOHA'), self.iss.index("DelTree("), 'tichý režim maže jen po záloze')

    def test_metadata_a_soukromi(self):
        """Podmínky SignPath: název produktu a verze v metadatech, zásady soukromí ukázané při instalaci."""
        for radek in ('VersionInfoProductName={#Nazev}', 'VersionInfoVersion={#VerzeCislo}', 'VersionInfoProductVersion={#VerzeCislo}',
                      'VersionInfoTextVersion={#Verze}', 'VersionInfoProductTextVersion={#Verze}', 'InfoBeforeFile=soukromi.txt', '#define VerzeCislo "0.0.0"'):
            self.assertIn(radek, self.iss)
        sestav = (KOREN / 'scripts' / 'windows' / 'sestav.py').read_text(encoding='utf-8')
        self.assertIn("replace('#define VerzeCislo \"0.0.0\"'", sestav, 'sestavení musí číselnou verzi opravdu doplnit')
        soukromi = (KOREN / 'scripts' / 'windows' / 'soukromi.txt').read_text(encoding='utf-8-sig')
        for text in ('ARES', 'GitHub', 'Nastavení → Účet / Přihlášení → Aktualizace'): self.assertIn(text, soukromi)
        readme = (KOREN / 'README.md').read_text(encoding='utf-8')
        for text in ('## Code signing policy', 'Free code signing provided by [SignPath.io]', 'certificate by [SignPath Foundation]', 'Committers and reviewers',
                     'Approvers', 'will not transfer any information to other networked systems', '[Code signing policy](#code-signing-policy)'):
            self.assertIn(text, readme)

    def test_zadna_sluzba_planovac_ani_firewall(self):
        for zakazane in ('add rule', 'schtasks', 'sc.exe', 'New-NetFirewallRule', '{app}\\data', 'PrivilegesRequired=admin'):
            self.assertNotIn(zakazane, self.iss)
        self.assertIn('firewall delete rule name="OSVC evidence"', self.iss, 'pravidlo ze síťového přístupu odinstalace odebere')
        self.assertLess(self.iss.index('OdeberPravidloFirewallu();'), self.iss.index('RozhodniOData();\n  end;'))
        self.assertEqual(instalace.VYCHOZI_HOST, '127.0.0.1', 'jen tento počítač – pravidlo ve firewallu není potřeba')


if __name__ == '__main__':
    unittest.main()
