"""V4 – balíček .deb: skripty (syntaxe; remove nechá data, purge nejdřív záloha do /var/backups/osvc-evidence, pak smazání),
služba (uživatel bez práv, zápis jen do dat, jen localhost), žádné pravidlo firewallu ani plánovač mimo službu.
Skutečnou instalaci, aktualizaci a odinstalaci ověřuje GitHub Actions (V5). Běží jen přes tests/spust.sh."""
import subprocess
import unittest
from pathlib import Path

D = Path.cwd() / 'scripts' / 'linux' / 'debian'


def cti(jmeno): return (D / jmeno).read_text(encoding='utf-8')


class Skripty(unittest.TestCase):
    def test_syntaxe(self):
        for s in ('postinst', 'prerm', 'postrm', 'osvc-evidence'):
            self.assertEqual(subprocess.run(['sh', '-n', str(D / s)]).returncode, 0, s)
            self.assertTrue(cti(s).startswith('#!/bin/sh'), s)

    def test_remove_nechá_data_purge_zalohuje(self):
        postrm = cti('postrm')
        remove = postrm.split('if [ "$1" = purge ]')[0]
        self.assertNotIn('rm -rf "$DATA"', remove); self.assertNotIn('$KONF', remove.split('case')[1])
        purge = postrm.split('if [ "$1" = purge ]')[1]
        self.assertLess(purge.index('tar -czf'), purge.index('rm -rf "$DATA" "$KONF"'), 'nejdřív záloha')
        self.assertLess(purge.index('tar -tzf'), purge.index('rm -rf "$DATA" "$KONF"'), 'záloha musí jít přečíst')
        self.assertIn('/var/backups/osvc-evidence', postrm); self.assertIn('set -e', postrm)
        self.assertIn('systemctl disable', postrm); self.assertIn('rm -rf "$APP"', postrm)

    def test_postinst_nesmaze_data_ani_nastaveni(self):
        postinst = cti('postinst')
        self.assertNotIn('rm -rf "$DATA', postinst); self.assertNotIn('rm -rf "$KONF', postinst)
        self.assertIn('if [ ! -e "$KONF/osvc.conf" ]', postinst, 'nastavení jen poprvé')
        self.assertIn('--no-index', postinst, 'knihovny jen z balíčku, bez internetu')
        self.assertIn('systemctl stop', cti('prerm'))

    def test_sluzba_a_firewall(self):
        sluzba = cti('osvc-evidence.service')
        for radek in ('Environment=OSVC_SLUZBA=systemd', 'User=osvc-evidence', 'NoNewPrivileges=yes', 'ProtectSystem=strict', 'ReadWritePaths=/var/lib/osvc-evidence', '-X utf8'):
            self.assertIn(radek, sluzba)
        for s in ('postinst', 'prerm', 'postrm', 'osvc-evidence.service'):
            for zakazane in ('ufw', 'iptables', 'nft ', 'firewall-cmd', 'crontab', '.timer'):
                self.assertNotIn(zakazane, cti(s), (s, zakazane))
        from osvc_app import instalace
        self.assertEqual(instalace.VYCHOZI_HOST, '127.0.0.1')

    def test_verze_deb(self):
        zdroj = (Path.cwd() / 'scripts' / 'linux' / 'sestav_deb.py').read_text(encoding='utf-8')
        self.assertIn(".replace('-', '~')", zdroj, 'předběžná verze (0.1.0-test) je v dpkg nižší než vydaná')


if __name__ == '__main__':
    unittest.main()
