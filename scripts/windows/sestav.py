#!/usr/bin/env python3
"""Sestavení OSVČ evidence pro Windows (krok I4). Běží na Linuxu i ve Windows (GitHub Actions), potřebuje jen Python a pip.

    python scripts/windows/sestav.py --verze 0.1.0 [--vystup sestaveni] [--cache sestaveni/cache]

Výsledek ve VYSTUP/windows-VERZE/:
    python/      oficiální vložitelný Python pro Windows (python.org, ověřený SHA-256) + knihovny v Lib/site-packages
    app/         kód aplikace (osvc_app, sql/sqlite)
    osvc.ico, osvc.iss (skript instalátoru Inno Setup), Spustit OSVC evidence.cmd (přenosné spuštění bez instalace)
a VYSTUP/osvc-evidence-VERZE-windows-prenosna.zip (totéž zabalené). Instalátor .exe: ISCC /DVerze=VERZE osvc.iss (Inno Setup 6, Windows).
"""
import argparse
import os
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PYTHON = '3.14.10'
PYTHON_ZIP = f'python-{PYTHON}-embed-amd64.zip'
PYTHON_URL = f'https://www.python.org/ftp/python/{PYTHON}/{PYTHON_ZIP}'
PYTHON_SHA256 = '90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159'
PTH = f'python{"".join(PYTHON.split(".")[:2])}._pth'
KOREN = Path(__file__).resolve().parents[2]
TADY = Path(__file__).resolve().parent
KOD = ['osvc_app', 'sql/sqlite']          # co aplikace za běhu potřebuje (schéma SQLite je v sql/sqlite)
NEBRAT = ('__pycache__', '*.pyc', '*.pyo')
SPUSTIT_CMD = ('@echo off\r\n'
               'rem OSVC evidence - prenosne spusteni bez instalace (data jsou ve stejne slozce jako u instalace)\r\n'
               'start "" "%~dp0python\\pythonw.exe" -X utf8 -m osvc_app.spoustec spust --config "%LOCALAPPDATA%\\OSVC evidence\\osvc.conf" '
               '--data "%LOCALAPPDATA%\\OSVC evidence\\data" --otevrit\r\n')


def sha256(cesta):
    h = hashlib.sha256()
    with open(cesta, 'rb') as f:
        for kus in iter(lambda: f.read(1 << 20), b''): h.update(kus)
    return h.hexdigest()


def stahni_python(cache):
    cache.mkdir(parents=True, exist_ok=True); cil = cache / PYTHON_ZIP
    if not cil.exists():
        print(f'stahuji {PYTHON_URL}')
        with urllib.request.urlopen(PYTHON_URL, timeout=120) as r, open(cil.with_suffix('.part'), 'wb') as f: shutil.copyfileobj(r, f)
        cil.with_suffix('.part').rename(cil)
    if sha256(cil) != PYTHON_SHA256:
        cil.unlink(); raise SystemExit(f'CHYBA: {PYTHON_ZIP} nemá očekávaný SHA-256 (smazán, spusťte znovu)')
    return cil


def python_pro_windows(zip_cesta, cil):
    with zipfile.ZipFile(zip_cesta) as z: z.extractall(cil)
    pth = cil / PTH
    if not pth.exists(): raise SystemExit(f'CHYBA: ve vložitelném Pythonu chybí {PTH}')
    # cesty pro import: standardní knihovna, knihovny aplikace, kód aplikace (..\app); „import site“ zapne site-packages
    zaklad = [r for r in pth.read_text().splitlines() if r.strip() and not r.lstrip().startswith(('#', 'import site'))]
    pth.write_text('\r\n'.join(zaklad + [r'Lib\site-packages', r'..\app', 'import site']) + '\r\n')


def knihovny(cil):
    cil.mkdir(parents=True, exist_ok=True)
    verze = '.'.join(PYTHON.split('.')[:2])
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--no-compile',
                    '--target', str(cil), '--platform', 'win_amd64', '--python-version', verze, '--implementation', 'cp',
                    '--only-binary=:all:', '--no-deps', '-r', str(TADY / 'requirements-windows.txt')], check=True, cwd=TADY)
    shutil.rmtree(cil / 'bin', ignore_errors=True)   # spouštěcí skripty knihoven (flask, …) aplikace nepotřebuje
    for p in list(cil.rglob('__pycache__')): shutil.rmtree(p, ignore_errors=True)


def kod_aplikace(cil):
    for cast in KOD:
        shutil.copytree(KOREN / cast, cil / cast, ignore=shutil.ignore_patterns(*NEBRAT))


def ikona(cil):
    """Ikona aplikace (modrý čtverec s bílým „O“ a fajfkou) – vygenerovaná, bez cizích obrázků."""
    from PIL import Image, ImageDraw
    velikost = 256; img = Image.new('RGBA', (velikost, velikost), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, 248, 248), radius=48, fill=(37, 99, 235, 255))
    d.ellipse((52, 52, 204, 204), outline=(255, 255, 255, 255), width=26)
    d.line((98, 130, 122, 156, 162, 104), fill=(255, 255, 255, 255), width=22, joint='curve')
    img.save(cil, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def zabal(slozka, cil):
    with zipfile.ZipFile(cil, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(slozka.rglob('*')):
            if p.is_file(): z.write(p, Path(slozka.name) / p.relative_to(slozka))


def verze_py(verze, repo=None):
    """verze.py v balíčku: číslo verze z tagu a repozitář pro upozornění na novou verzi (V2; v Actions GITHUB_REPOSITORY)."""
    return f'"""Verze aplikace (doplnilo sestavení balíčku)."""\nVERZE = {verze!r}\nREPO = {repo!r}\n'


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument('--verze', required=True); a.add_argument('--vystup', default=str(KOREN / 'sestaveni')); a.add_argument('--cache')
    a.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'), help='vlastník/repozitář pro upozornění na novou verzi')
    a = a.parse_args(argv)
    vystup = Path(a.vystup).resolve(); cil = vystup / f'windows-{a.verze}'
    if cil.exists(): shutil.rmtree(cil)
    cil.mkdir(parents=True)
    python_pro_windows(stahni_python(Path(a.cache) if a.cache else vystup / 'cache'), cil / 'python')
    knihovny(cil / 'python' / 'Lib' / 'site-packages')
    kod_aplikace(cil / 'app')
    (cil / 'app' / 'osvc_app' / 'verze.py').write_text(verze_py(a.verze, a.repo), encoding='utf-8')
    ikona(cil / 'osvc.ico')
    iss = (TADY / 'osvc.iss').read_text(encoding='utf-8-sig').replace('#define Verze "0.0.0"', f'#define Verze "{a.verze}"')
    (cil / 'osvc.iss').write_text(iss, encoding='utf-8-sig')   # Inno Setup potřebuje UTF-8 s BOM kvůli diakritice
    (cil / 'Spustit OSVC evidence.cmd').write_bytes(SPUSTIT_CMD.encode('ascii'))
    balik = vystup / f'osvc-evidence-{a.verze}-windows-prenosna.zip'
    zabal(cil, balik)
    print(f'hotovo: {cil}\n        {balik} ({balik.stat().st_size // 1_000_000} MB, SHA-256 {sha256(balik)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
