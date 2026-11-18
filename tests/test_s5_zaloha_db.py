"""S5b – noční záloha SQLite (flask zaloha-db): konzistentní snímek za běhu, kontrola integrity, gzip, práva 600, obnovitelný.
Pracuje s kopií vzoru od tests/spust.sh (DB_PATH) a dočasnou složkou. Běží jen přes tests/spust.sh (výchozí SQLite)."""
import gzip
import os
import stat
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from osvc_app import create_app, db, prevod, zaloha_db

TMP = tempfile.TemporaryDirectory()


def setUpModule():
    if os.environ.get('DB_ENGINE') != 'sqlite': raise unittest.SkipTest('jen pro SQLite')


class ZalohaDb(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'DB_ENGINE': 'sqlite', 'DB_PATH': os.environ['DB_PATH'], 'MODULY_SETTINGS_FILE': TMP.name + '/m.json'})

    def rozbal(self, cesta):
        cil = Path(TMP.name) / (cesta.name[:-3]); cil.write_bytes(gzip.decompress(cesta.read_bytes())); return cil

    def test_snimek_je_uplny_a_obnovitelny(self):
        slozka = Path(TMP.name) / 'zalohy'
        with self.app.app_context():
            pred = prevod.souhrn(db.query)
            cesta = zaloha_db.vytvor(slozka, datetime(2026, 11, 17, 3, 22, 0))
        self.assertEqual(cesta.name, 'osvc_2026-11-17_03-22-00.sqlite3.gz')
        self.assertEqual(stat.S_IMODE(cesta.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in slozka.iterdir()], [cesta.name], 'žádné zbytky')
        obnoveny = self.rozbal(cesta)
        self.assertFalse(Path(str(obnoveny) + '-wal').exists())
        jiny = create_app({'TESTING': True, 'DB_ENGINE': 'sqlite', 'DB_PATH': str(obnoveny), 'MODULY_SETTINGS_FILE': TMP.name + '/m.json'})
        with jiny.app_context():
            self.assertTrue(prevod.porovnej(pred, prevod.souhrn(db.query))[1], 'snímek se liší od databáze')
        with self.app.app_context(), self.assertRaises(FileExistsError): zaloha_db.vytvor(slozka, datetime(2026, 11, 17, 3, 22, 0))

    def test_za_behu_se_zapisem(self):
        """Během zálohy zapisuje jiné vlákno (synchronizace) – záloha projde a snímek je konzistentní."""
        stop = threading.Event(); chyby = []
        def zapisuj():
            with self.app.app_context():
                i = 0
                while not stop.is_set():
                    try: db.execute("INSERT INTO business_events (event_date,name) VALUES ('2026-11-17',%s)", (f'souběh zálohy {i}',)); i += 1
                    except Exception as e: chyby.append(e); break
                    time.sleep(0.01)
        v = threading.Thread(target=zapisuj); v.start()
        try:
            with self.app.app_context(): cesta = zaloha_db.vytvor(Path(TMP.name) / 'soubeh')
        finally: stop.set(); v.join(10)
        self.assertEqual(chyby, [])
        from osvc_app import sqlite_db
        kontrola = sqlite_db.otevri(self.rozbal(cesta))   # s porovnáním OSVC_CI
        self.assertEqual(kontrola.execute('PRAGMA quick_check').fetchone()[0], 'ok')
        with self.app.app_context(): db.execute("DELETE FROM business_events WHERE name LIKE 'souběh zálohy%%'")

    def test_prikaz_a_mysql_odmitne(self):
        r = self.app.test_cli_runner().invoke(args=['zaloha-db', str(Path(TMP.name) / 'cli')])
        self.assertEqual(r.exit_code, 0, r.output); self.assertTrue(r.output.strip().endswith('.sqlite3.gz'))
        m = create_app({'TESTING': True, 'DB_ENGINE': 'mysql'})
        with m.app_context(), self.assertRaises(RuntimeError): zaloha_db.vytvor(Path(TMP.name) / 'x')


if __name__ == '__main__':
    unittest.main()
