"""V1 – bezpečnost dat: verze struktury (PRAGMA user_version), úpravy sql/sqlite/migrace při startu se snímkem předem,
návrat ze snímku při chybě, databáze novější než aplikace se nemění, data nesmí být ve složce programu.
Vše v dočasné složce. Běží jen přes tests/spust.sh."""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from osvc_app import create_app, instalace, sqlite_db, struktura

TMP = tempfile.TemporaryDirectory()
KOREN = Path.cwd()
DOBRA_002 = "-- nový sloupec\nALTER TABLE vehicles ADD COLUMN pruvodni_text TEXT;\nUPDATE vehicles SET pruvodni_text = 'ok';\n"
DOBRA_003 = "CREATE TABLE zkusebni (id INTEGER PRIMARY KEY, castka DEC2);\nINSERT INTO zkusebni (castka) VALUES (12345);\n"
SPATNA_003 = "CREATE TABLE zkusebni (id INTEGER PRIMARY KEY);\nINSERT INTO neexistuje VALUES (1);\n"
n = 0


def slozka(**soubory):
    global n; n += 1
    s = Path(TMP.name) / f'mig{n}'; s.mkdir()
    for jmeno, obsah in soubory.items(): (s / jmeno.replace('_', '-', 1)).write_text(obsah, encoding='utf-8')
    return s


def databaze():
    global n; n += 1
    cesta = Path(TMP.name) / f'db{n}' / 'osvc.sqlite3'; sqlite_db.zaloz(cesta, zakladni_data=True)
    c = sqlite_db.otevri(cesta); c.execute("INSERT INTO vehicles (name, active) VALUES ('Škoda', 1)"); c.close()
    return cesta


def sloupce(cesta, tabulka):
    c = sqlite_db.otevri(cesta)
    try: return {r[1] for r in c.execute(f'PRAGMA table_info({tabulka})')}
    finally: c.close()


def otisk(cesta): return hashlib.sha256(Path(cesta).read_bytes()).hexdigest()


class Uprava(unittest.TestCase):
    def test_souvisla_rada(self):
        self.assertEqual(struktura.cilova(slozka()), 1)
        self.assertEqual(struktura.cilova(slozka(**{'002_a.sql': DOBRA_002, '003_b.sql': DOBRA_003})), 3)
        self.assertRaises(struktura.UpravaSelhala, struktura.migrace, slozka(**{'002_a.sql': DOBRA_002, '004_b.sql': DOBRA_003}))
        self.assertEqual(struktura.cilova(), struktura.verze_db(databaze()), 'nová databáze je v aktuální verzi')

    def test_uspech_se_snimkem(self):
        db = databaze(); mig = slozka(**{'002_a.sql': DOBRA_002, '003_b.sql': DOBRA_003})
        od, do, snimek = struktura.uprav(db, mig)
        self.assertEqual((od, do, struktura.verze_db(db)), (1, 3, 3))
        self.assertIn('pruvodni_text', sloupce(db, 'vehicles')); self.assertIn('castka', sloupce(db, 'zkusebni'))
        c = sqlite_db.otevri(db)
        self.assertEqual(c.execute("SELECT name, pruvodni_text FROM vehicles WHERE name='Škoda'").fetchone(), ('Škoda', 'ok'))
        self.assertEqual(str(c.execute('SELECT castka FROM zkusebni').fetchone()[0]), '123.45', 'nový sloupec DEC2 = haléře')
        c.close()
        self.assertEqual(snimek.parent, db.parent / 'pred-upravou'); self.assertEqual(struktura.verze_db(snimek), 1)
        self.assertNotIn('pruvodni_text', sloupce(snimek, 'vehicles'))
        self.assertEqual(struktura.uprav(db, mig), (3, 3, None), 'podruhé nic')

    def test_chyba_v_uprave_nic_nezmeni(self):
        db = databaze(); pred = sloupce(db, 'vehicles')
        with self.assertRaises(struktura.UpravaSelhala) as e: struktura.uprav(db, slozka(**{'002_a.sql': DOBRA_002, '003_b.sql': SPATNA_003}))
        self.assertIn('vrácená', str(e.exception))
        self.assertEqual((struktura.verze_db(db), sloupce(db, 'vehicles')), (1, pred), 'ani úprava 002 nezůstala')
        c = sqlite_db.otevri(db); self.assertEqual(c.execute("SELECT COUNT(*) FROM vehicles WHERE name='Škoda'").fetchone()[0], 1); c.close()
        self.assertEqual(len(list((db.parent / 'pred-upravou').glob('*.sqlite3'))), 1)

    def test_chyba_po_uprave_navrat_ze_snimku(self):
        db = databaze()
        with self.assertRaises(struktura.UpravaSelhala):
            struktura.uprav(db, slozka(**{'002_a.sql': DOBRA_002}), selhani=lambda: (_ for _ in ()).throw(RuntimeError('simulace')))
        self.assertEqual(struktura.verze_db(db), 1); self.assertNotIn('pruvodni_text', sloupce(db, 'vehicles'))
        c = sqlite_db.otevri(db); self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok'); c.close()

    def test_novejsi_databaze_se_nemeni(self):
        db = databaze(); c = sqlite_db.otevri(db); c.execute('PRAGMA user_version = 9'); c.close(); pred = otisk(db)
        with self.assertRaises(struktura.NovejsiDatabaze) as e: struktura.uprav(db, slozka(**{'002_a.sql': DOBRA_002}))
        self.assertIn('novější verzi aplikace', str(e.exception))
        self.assertEqual(otisk(db), pred); self.assertFalse((db.parent / 'pred-upravou').exists())

    def test_uklid_snimku(self):
        db = databaze(); s = db.parent / 'pred-upravou'; s.mkdir()
        for i in range(12): (s / f'osvc_pred-upravou_v1-na-v2_2026-01-{i + 1:02d}_00-00-00.sqlite3').write_bytes(b'x')
        struktura.uprav(db, slozka(**{'002_a.sql': DOBRA_002}))
        self.assertEqual(len(list(s.glob('*.sqlite3'))), struktura.PONECHAT_SNIMKU)


class PriStartu(unittest.TestCase):
    """Start aplikace (create_app mimo testovací režim) nad samostatnou instalací."""
    def instalace(self):
        global n; n += 1
        konf = Path(TMP.name) / f'inst{n}' / 'osvc.conf'; instalace.zapis_nastaveni(konf, konf.parent / 'data')
        s = instalace.priprav(instalace.nacti(konf)); return konf, s

    def app(self, konf, **conf):
        os.environ['OSVC_CONFIG'] = str(konf)
        try: return create_app(conf)
        finally: os.environ.pop('OSVC_CONFIG')

    def test_nova_verze_upravi_strukturu(self):
        konf, s = self.instalace()
        app = self.app(konf, OSVC_MIGRACE_DIR=str(slozka(**{'002_a.sql': DOBRA_002})))
        self.assertEqual(struktura.verze_db(s['db']), 2); self.assertTrue(list((s['data'] / 'pred-upravou').glob('*v1-na-v2*')))
        with app.test_client() as k: self.assertEqual(k.get('/pruvodce').status_code, 200)

    def test_chyba_upravy_aplikaci_nespusti(self):
        konf, s = self.instalace(); pred = otisk(s['db'])
        with self.assertRaises(struktura.UpravaSelhala): self.app(konf, OSVC_MIGRACE_DIR=str(slozka(**{'002_a.sql': SPATNA_003})))
        self.assertEqual(struktura.verze_db(s['db']), 1)

    def test_spoustec_se_starsi_aplikaci(self):
        konf, s = self.instalace(); c = sqlite_db.otevri(s['db']); c.execute('PRAGMA user_version = 50'); c.close()
        instalace.zapis_nastaveni  # port 8080 ze zapis_nastaveni – server se ale ani nespustí
        r = subprocess.run([sys.executable, '-m', 'osvc_app.spoustec', 'spust', '--config', str(konf)], capture_output=True, text=True, timeout=60, cwd=KOREN)
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr); self.assertIn('novější verzi aplikace', r.stderr)
        self.assertIn('NovejsiDatabaze', (s['data'] / 'logy' / 'osvc.log').read_text(encoding='utf-8'))

    def test_data_ve_slozce_programu(self):
        konf = Path(TMP.name) / 'uvnitr.conf'; instalace.zapis_nastaveni(konf, KOREN / 'data-zkouska')
        with self.assertRaises(ValueError) as e: instalace.priprav(instalace.nacti(konf))
        self.assertIn('nesmí být ve složce programu', str(e.exception)); self.assertFalse((KOREN / 'data-zkouska').exists())


if __name__ == '__main__':
    unittest.main()
