#!/usr/bin/env python3
"""Sestavení balíčku .deb OSVČ evidence (krok V4). Potřebuje Python, pip a dpkg-deb (Linux; GitHub Actions ubuntu runner).

    python scripts/linux/sestav_deb.py --verze 0.1.0 [--vystup sestaveni] [--repo vlastnik/repozitar]

Balíček osvc-evidence_VERZE_amd64.deb:
    /opt/osvc-evidence/app        kód aplikace (osvc_app, sql/sqlite), verze.py z tagu
    /opt/osvc-evidence/wheels     knihovny pro Python 3.12–3.14 (postinst z nich bez internetu vytvoří /opt/osvc-evidence/venv)
    /usr/lib/systemd/system/osvc-evidence.service, /usr/bin/osvc-evidence, zástupce a ikona
Data /var/lib/osvc-evidence a nastavení /etc/osvc-evidence vytváří postinst (nejsou součástí balíčku → aktualizace je nepřepíše).
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
TADY = Path(__file__).resolve().parent
PYTHONY = ('3.12', '3.13', '3.14')   # Ubuntu 24.04, Debian 13, Ubuntu 26.04
PLATFORMY = ('manylinux_2_17_x86_64', 'manylinux2014_x86_64', 'manylinux_2_28_x86_64', 'manylinux_2_34_x86_64')
KOD = ['osvc_app', 'sql/sqlite']
NEBRAT = ('__pycache__', '*.pyc', '*.pyo')
CONTROL = """Package: osvc-evidence
Version: {verze}
Section: misc
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.12), python3-venv, adduser, systemd, xdg-utils
Maintainer: OSVC evidence <osvc-evidence@localhost>
Installed-Size: {velikost}
{homepage}Description: Evidence prijmu, vydaju a podkladu pro dane OSVC
 Webova aplikace pro OSVC (nepatce DPH): prijmy, vydaje, jizdy a PHM, doklady,
 Rocni prehled pro Financni urad, CSSZ a zdravotni pojistovnu. Bezi jako sluzba
 na tomto pocitaci (http://localhost), data jsou v /var/lib/osvc-evidence.
"""


def knihovny(cil):
    """Kola (wheels) všech závislostí pro podporované verze Pythonu – postinst instaluje bez internetu."""
    cil.mkdir(parents=True, exist_ok=True)
    for verze in PYTHONY:
        prikaz = [sys.executable, '-m', 'pip', 'download', '--quiet', '--disable-pip-version-check', '--dest', str(cil), '--only-binary=:all:',
                  '--python-version', verze, '--implementation', 'cp', '--no-deps', '-r', str(KOREN / 'requirements.lock.txt')]
        for p in PLATFORMY: prikaz += ['--platform', p]
        subprocess.run(prikaz, check=True, cwd=KOREN)


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument('--verze', required=True); a.add_argument('--vystup', default=str(KOREN / 'sestaveni'))
    a.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'))
    a = a.parse_args(argv)
    verze_deb = a.verze.lstrip('v').replace('-', '~')   # 0.1.0-test → 0.1.0~test (předběžná verze je v dpkg nižší)
    vystup = Path(a.vystup).resolve(); koren = vystup / f'deb-{a.verze}'
    if koren.exists(): shutil.rmtree(koren)
    app = koren / 'opt' / 'osvc-evidence'
    for cast in KOD: shutil.copytree(KOREN / cast, app / 'app' / cast, ignore=shutil.ignore_patterns(*NEBRAT))
    sys.path.insert(0, str(KOREN / 'scripts' / 'windows'))
    from sestav import verze_py, ikona
    (app / 'app' / 'osvc_app' / 'verze.py').write_text(verze_py(a.verze, a.repo), encoding='utf-8')
    shutil.copy(KOREN / 'requirements.lock.txt', app / 'requirements.txt')
    knihovny(app / 'wheels')
    for zdroj, cil, prava in (('osvc-evidence.service', 'usr/lib/systemd/system/osvc-evidence.service', 0o644),
                              ('osvc-evidence', 'usr/bin/osvc-evidence', 0o755),
                              ('osvc-evidence.desktop', 'usr/share/applications/osvc-evidence.desktop', 0o644)):
        c = koren / cil; c.parent.mkdir(parents=True, exist_ok=True); shutil.copy(TADY / 'debian' / zdroj, c); c.chmod(prava)
    ico = koren / 'usr/share/icons/hicolor/256x256/apps'; ico.mkdir(parents=True)
    ikona(ico / 'osvc-evidence.ico')
    from PIL import Image
    Image.open(ico / 'osvc-evidence.ico').save(ico / 'osvc-evidence.png'); (ico / 'osvc-evidence.ico').unlink()
    doc = koren / 'usr/share/doc/osvc-evidence'; doc.mkdir(parents=True)
    (doc / 'README.Debian').write_text('OSVČ evidence: http://localhost:<PORT>/ (PORT v /etc/osvc-evidence/osvc.conf), data /var/lib/osvc-evidence.\n'
                                       'apt remove = program a služba pryč, data zůstanou; apt purge = záloha do /var/backups/osvc-evidence, pak smazání dat.\n', encoding='utf-8')
    debian = koren / 'DEBIAN'; debian.mkdir()
    velikost = sum(p.stat().st_size for p in koren.rglob('*') if p.is_file()) // 1024
    (debian / 'control').write_text(CONTROL.format(verze=verze_deb, velikost=velikost, homepage=f'Homepage: https://github.com/{a.repo}\n' if a.repo else ''), encoding='utf-8')
    for skript in ('postinst', 'prerm', 'postrm'):
        shutil.copy(TADY / 'debian' / skript, debian / skript); (debian / skript).chmod(0o755)
    koren.chmod(0o755)
    for p in koren.rglob('*'):
        if p.is_dir(): p.chmod(0o755)
        elif not os.access(p, os.X_OK) or p.parent.name == 'wheels': p.chmod(0o644)
    balik = vystup / f'osvc-evidence_{a.verze.lstrip("v")}_amd64.deb'   # název souboru bez „~“ (GitHub ho v Release mění); verze uvnitř balíčku s „~“
    subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(koren), str(balik)], check=True, stdout=subprocess.DEVNULL)
    print(f'hotovo: {balik} ({balik.stat().st_size // 1_000_000} MB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
