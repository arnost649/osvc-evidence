#!/usr/bin/env python3
"""Popis vydání z CHANGELOG.md (oddíl „## vX.Y.Z“) pro GitHub Releases (V5). Bez oddílu pro danou verzi = chyba (nic se nevydá).

    python scripts/ci/popis_vydani.py v0.1.0 > popis.md
"""
import re
import sys
from pathlib import Path


def popis(tag, text):
    zaklad = re.sub(r'-.*$', '', tag)   # v0.1.0-test → popis v0.1.0
    m = re.search(rf'^## {re.escape(zaklad)}\b.*?$(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not m or not m.group(1).strip(): raise SystemExit(f'CHYBA: CHANGELOG.md nemá popis pro {zaklad}')
    return m.group(1).strip() + '\n\n---\nKontrolní součty souborů: `SHA256SUMS.txt`. Windows: `osvc-evidence-windows.exe` (bez práv správce). Linux: `sudo apt install ./osvc-evidence-linux.deb`.\n' + zasady()


def zasady():
    """Odkaz na zásady podepisování na stránce vydání (podmínka SignPath Foundation)."""
    import os
    repo = os.environ.get('GITHUB_REPOSITORY')
    return f'\n[Code signing policy](https://github.com/{repo}#code-signing-policy)\n' if repo else ''


if __name__ == '__main__':
    print(popis(sys.argv[1], (Path(__file__).resolve().parents[2] / 'CHANGELOG.md').read_text(encoding='utf-8')))
