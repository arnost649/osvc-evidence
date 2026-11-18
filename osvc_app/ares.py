import json
import re
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ARES_BASE = 'https://ares.gov.cz/ekonomicke-subjekty-v-be/rest'
ICO_RE = re.compile(r'(?i)\bIČO\s*[:\-]?\s*((?:\d[\s\u00a0]*){8})\b')
DIC_RE = re.compile(r'(?i)\bDIČ\s*[:\-]?\s*CZ\s*((?:\d[\s\u00a0]*){8})\b')


class AresUnavailable(RuntimeError):
    pass


def _request(path, payload=None, timeout=5):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = Request(
        ARES_BASE + path,
        data=data,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'OSVC-evidence/1.0'},
        method='POST' if data is not None else 'GET',
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise AresUnavailable('ARES není dostupný.') from exc


def _subject(data):
    address = data.get('sidlo') or {}
    return {
        'name': data.get('obchodniJmeno') or '',
        'ico': data.get('ico') or '',
        'dic': data.get('dic') or '',
        'address': address.get('textovaAdresa') or '',
        'city': address.get('nazevObce') or '',
        'street': address.get('nazevUlice') or '',
        'number': str(address.get('cisloDomovni') or '') + (('/' + str(address['cisloOrientacni']) + str(address.get('cisloOrientacniPismeno') or '')) if address.get('cisloOrientacni') else ''),
        'zip': str(address.get('psc') or ''),
        'country': address.get('nazevStatu') or '',
        'vznik': str(data.get('datumVzniku') or '')[:10],   # datum vzniku subjektu (IČO), RRRR-MM-DD
    }


def lookup_by_ico(ico, timeout=5):
    digits = re.sub(r'\D', '', str(ico or ''))
    if len(digits) != 8:
        return None
    try:
        return _subject(_request('/ekonomicke-subjekty/' + digits, timeout=timeout))
    except AresUnavailable as exc:
        if isinstance(exc.__cause__, HTTPError) and exc.__cause__.code == 404:
            return None
        raise


def lookup_by_name(name, timeout=5, limit=10):
    text = ' '.join(str(name or '').split())
    if not text:
        return []
    data = _request('/ekonomicke-subjekty/vyhledat', {'obchodniJmeno': text, 'start': 0, 'pocet': limit}, timeout)
    return [_subject(item) for item in data.get('ekonomickeSubjekty', []) if item.get('ico')]


def identifiers_from_text(text):
    for pattern in (ICO_RE, DIC_RE):
        match = pattern.search(text or '')
        if match:
            digits = re.sub(r'\D', '', match.group(1))
            if len(digits) == 8:
                return {'ico': digits, 'source': 'document+ares'}
    return None


def text_from_attachment(attachment, upload_folder):
    if not attachment or attachment.get('mime_type') != 'application/pdf':
        return ''
    folder = Path(upload_folder).resolve()
    filename = attachment.get('stored_filename') or ''
    path = (folder / filename).resolve()
    if path.parent != folder or not path.is_file():
        return ''
    try:
        result = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5, check=True)
        return result.stdout[:200000]
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return ''


def verify_supplier(supplier, attachment=None, upload_folder=None, timeout=5):
    document_id = None
    if attachment and upload_folder:
        document_id = identifiers_from_text(text_from_attachment(attachment, upload_folder))
    if document_id:
        result = lookup_by_ico(document_id['ico'], timeout)
        return ([result] if result else []), document_id['source']
    if supplier.get('ico'):
        result = lookup_by_ico(supplier['ico'], timeout)
        return ([result] if result else []), 'ares'
    return lookup_by_name(supplier.get('name'), timeout), 'ares'
