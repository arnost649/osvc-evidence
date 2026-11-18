"""SQLite úložiště OSVČ (přechod na SQLite, krok S2). Rozhraní jako PyMySQL s DictCursor, aby zbytek aplikace zůstal beze změny.

- Souběh webu a plánovače synchronizace: WAL, busy_timeout 10 s, transakce connection() začíná BEGIN IMMEDIATE (místo FOR UPDATE).
- Desetinná čísla jako celá: sloupec s deklarovaným typem DECs ukládá hodnotu × 10^s (DEC2 = haléře). Při čtení vrací Decimal,
  při zápisu (INSERT … VALUES, SET sloupec=%s, sloupec=%s ve WHERE) převede parametr podle sloupce. Decimal, u kterého sloupec
  poznat nejde, skončí chybou (žádné tiché uložení ve špatném měřítku).
- Text porovnává OSVC_CI: bez ohledu na velikost písmen a diakritiku (jako MySQL utf8mb4_0900_ai_ci); stejně LIKE a LOWER().
- Datum a čas jako text ISO 8601 (UTC), čtení vrací date/datetime jako PyMySQL.
"""
import re
import sqlite3
import threading
import unicodedata
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / 'sql' / 'sqlite' / 'schema.sql'
OperationalError = sqlite3.OperationalError
IntegrityError = sqlite3.IntegrityError


# --- porovnávání textu jako MySQL utf8mb4_0900_ai_ci --------------------------------------------------------------------
def klic_textu(value):
    """Klíč pro porovnání: bez diakritiky, bez ohledu na velikost písmen (MySQL ai_ci ignoruje i mezery na konci u PAD SPACE – 0900 ne)."""
    s = unicodedata.normalize('NFKD', value)
    return ''.join(ch for ch in s if not unicodedata.combining(ch)).casefold()


def _collation(a, b):
    ka, kb = klic_textu(a), klic_textu(b)
    return (ka > kb) - (ka < kb)


def _like_vzor(vzor, escape='\\'):
    out, i = [], 0
    while i < len(vzor):
        ch = vzor[i]
        if ch == escape and i + 1 < len(vzor): out.append(re.escape(klic_textu(vzor[i + 1]))); i += 2; continue
        out.append('.*' if ch == '%' else '.' if ch == '_' else re.escape(klic_textu(ch))); i += 1
    return re.compile(''.join(out), re.S)


_like_cache = {}


def _like(vzor, hodnota, escape='\\'):
    if vzor is None or hodnota is None: return None
    key = (vzor, escape)
    rx = _like_cache.get(key) or _like_cache.setdefault(key, _like_vzor(str(vzor), escape))
    return 1 if rx.fullmatch(klic_textu(str(hodnota))) else 0


# --- převody hodnot ------------------------------------------------------------------------------------------------------
def _dec_converter(scale):
    q = Decimal(1).scaleb(-scale)
    return lambda b: (Decimal(int(b)).scaleb(-scale)).quantize(q)


def _date(b):
    return date.fromisoformat(b.decode()[:10])


def _datetime(b):
    s = b.decode().replace('T', ' ')
    return datetime.fromisoformat(s).replace(tzinfo=None, microsecond=0) if len(s) > 10 else datetime.fromisoformat(s + ' 00:00:00')


for _s in range(0, 7): sqlite3.register_converter(f'DEC{_s}', _dec_converter(_s))
sqlite3.register_converter('DATE', _date)
sqlite3.register_converter('DATETIME', _datetime)
sqlite3.register_converter('TIMESTAMP', _datetime)
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(datetime, lambda d: d.replace(tzinfo=None, microsecond=0).isoformat(' '))


def _decimal_bez_sloupce(value):
    raise TypeError(f'Desetinné číslo {value} bez známého desetinného sloupce – v SQLite by se uložilo ve špatném měřítku.')


sqlite3.register_adapter(Decimal, _decimal_bez_sloupce)


def na_cele(value, scale):
    """Hodnota desetinného sloupce → celé číslo × 10^scale (zaokrouhlení jako MySQL DECIMAL: od nuly)."""
    if value is None or isinstance(value, bool): return value
    if isinstance(value, str):
        value = value.strip()
        if value == '': return value
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.scaleb(scale).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --- překlad SQL z PyMySQL zápisu ----------------------------------------------------------------------------------------
_RETEZCE = re.compile(r"'(?:[^']|'')*'")
_FOR_UPDATE = re.compile(r'\s+FOR\s+UPDATE\b', re.I)
_ZAPIS = re.compile(r'^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b', re.I)
_INSERT = re.compile(r'^\s*INSERT\s+INTO\s+[`"]?(\w+)[`"]?\s*\(([^)]*)\)\s*VALUES\s*', re.I | re.S)
_SLOUPEC_PRED = re.compile(r'(?:[`"]?\w+[`"]?\.)?[`"]?(\w+)[`"]?\s*(?:=|<>|!=|<=|>=|<|>)\s*$')
_IN_PRED = re.compile(r'(?:[`"]?\w+[`"]?\.)?[`"]?(\w+)[`"]?\s+(?:NOT\s+)?IN\s*\((?:\s*\?\s*,)*\s*$', re.I)


def _hodnoty_insertu(text, start):
    """Seznam výrazů v (… , …) za VALUES od pozice start; vrátí [(výraz, počet ?)] pro všechny řádky VALUES."""
    radky, i, n = [], start, len(text)
    while i < n:
        while i < n and text[i] in ' \n\t,': i += 1
        if i >= n or text[i] != '(': break
        hloubka, j, casti, zac = 0, i, [], i + 1
        while j < n:
            ch = text[j]
            if ch == '(': hloubka += 1
            elif ch == ')':
                hloubka -= 1
                if hloubka == 0: casti.append(text[zac:j]); break
            elif ch == ',' and hloubka == 1: casti.append(text[zac:j]); zac = j + 1
            j += 1
        radky.append(casti); i = j + 1
    return radky


def _mimo_retezce(sql, fn):
    kusy, posl = [], 0
    for m in _RETEZCE.finditer(sql): kusy.append(fn(sql[posl:m.start()])); kusy.append(m.group(0)); posl = m.end()
    kusy.append(fn(sql[posl:])); return ''.join(kusy)


def preloz(sql, params, meritka):
    """PyMySQL SQL + parametry → SQLite SQL + parametry (zástupné znaky, FOR UPDATE, desetinná čísla podle sloupců)."""
    params = tuple(params or ())
    if not params:
        sql2 = sql.replace('%%', '%') if '%%' in sql else sql
        return _FOR_UPDATE.sub('', _mimo_retezce(sql2, lambda s: s.replace('<=>', ' IS '))), params
    # zástupné znaky mimo řetězce: %s → ?, %% → %
    kusy, posl = [], 0
    for m in _RETEZCE.finditer(sql):
        kusy.append(sql[posl:m.start()].replace('%s', '?').replace('%%', '%').replace('<=>', ' IS ')); kusy.append(m.group(0)); posl = m.end()
    kusy.append(sql[posl:].replace('%s', '?').replace('%%', '%').replace('<=>', ' IS '))   # <=> (MySQL: rovnost i pro NULL) = IS
    text = _FOR_UPDATE.sub('', ''.join(kusy))
    if not meritka: return text, params
    sloupce = [None] * len(params)
    bez_retezcu = _RETEZCE.sub(lambda m: ' ' * len(m.group(0)), text)
    pozice = [m.start() for m in re.finditer(r'\?', bez_retezcu)]
    if len(pozice) != len(params):
        raise ValueError(f'SQL má {len(pozice)} zástupných znaků, parametrů je {len(params)}')
    ins = _INSERT.match(bez_retezcu)
    if ins:
        jmena = [c.strip().strip('`"') for c in ins.group(2).split(',')]
        k = 0
        for radek in _hodnoty_insertu(bez_retezcu, ins.end()):
            for jmeno, vyraz in zip(jmena, radek):
                for _ in range(vyraz.count('?')):
                    if k < len(sloupce): sloupce[k] = jmeno; k += 1
    for k, p in enumerate(pozice):
        if sloupce[k] is not None: continue
        pred = bez_retezcu[max(0, p - 200):p]
        m = _SLOUPEC_PRED.search(pred) or _IN_PRED.search(pred)
        if m: sloupce[k] = m.group(1)
    nove = list(params)
    for k, jmeno in enumerate(sloupce):
        if jmeno in meritka: nove[k] = na_cele(nove[k], meritka[jmeno])
    return text, tuple(nove)


# --- spojení ----------------------------------------------------------------------------------------------------------------
_meritka_cache, _zamek = {}, threading.Lock()


def _registruj(conn):
    conn.create_collation('OSVC_CI', _collation)
    conn.create_function('LOWER', 1, lambda s: s.lower() if isinstance(s, str) else s, deterministic=True)
    conn.create_function('UPPER', 1, lambda s: s.upper() if isinstance(s, str) else s, deterministic=True)
    conn.create_function('like', 2, _like, deterministic=True)
    conn.create_function('like', 3, _like, deterministic=True)


def _meritka(conn, path):
    with _zamek:
        if path in _meritka_cache: return _meritka_cache[path]
    m = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        for col in conn.execute(f'PRAGMA table_info("{t}")').fetchall():
            typ = (col[2] or '').upper()
            if re.fullmatch(r'DEC\d', typ):
                s = int(typ[3:])
                if m.setdefault(col[1], s) != s: raise RuntimeError(f'sloupec {col[1]} má v různých tabulkách jiné měřítko')
    with _zamek: _meritka_cache[path] = m
    return m


def otevri(path):
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    _registruj(conn)
    conn.execute('PRAGMA busy_timeout=10000'); conn.execute('PRAGMA foreign_keys=ON'); conn.execute('PRAGMA synchronous=NORMAL')
    return conn


ZAKLADNI_DATA = SCHEMA.parent / 'zakladni-data.sql'


def zaloz(path, zakladni_data=False):
    """Prázdná databáze ze schématu (jen když soubor neexistuje); režim WAL je uložený v souboru.
    zakladni_data=True: nová samostatná instalace – i výchozí názvy typů a vyhláškové sazby (sql/sqlite/zakladni-data.sql).
    Převod z MySQL (prevod.py) a testy zakládají bez nich (data přijdou z MySQL)."""
    path = Path(path)
    if path.exists(): raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = otevri(path)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript(SCHEMA.read_text(encoding='utf-8'))
        if zakladni_data: conn.executescript('BEGIN;' + ZAKLADNI_DATA.read_text(encoding='utf-8') + 'COMMIT;')
        from .struktura import proved, ZAKLAD
        proved(conn, ZAKLAD)   # nová databáze rovnou v aktuální verzi struktury (bez snímku – nic v ní není)
    finally: conn.close()
    with _zamek: _meritka_cache.pop(str(path), None)
    return path


class Cursor:
    def __init__(self, spojeni):
        self._s = spojeni; self._cur = spojeni._conn.cursor(); self.lastrowid = None; self.rowcount = -1

    def __enter__(self): return self
    def __exit__(self, *a): self.close()
    def close(self): self._cur.close()

    def execute(self, sql, params=()):
        if isinstance(params, dict): raise TypeError('pojmenované parametry nejsou podporované')
        # zámek pro zápis až u prvního zápisu nebo SELECT … FOR UPDATE; čtení předtím nikoho neblokuje (WAL)
        if _ZAPIS.match(sql) or _FOR_UPDATE.search(sql): self._s._zacni_transakci()
        text, p = preloz(sql, params, self._s.meritka)
        self._cur.execute(text, p)
        self.lastrowid = self._cur.lastrowid; self.rowcount = self._cur.rowcount
        return self.rowcount

    def executemany(self, sql, seq):
        n = 0
        for params in seq: self.execute(sql, params); n += max(self.rowcount, 0)
        self.rowcount = n; return n

    def _radek(self, r):
        if r is None: return None
        out = {}
        for (jmeno, *_), v in zip(self._cur.description, r):
            out.setdefault(jmeno, v)   # stejně jako PyMySQL DictCursor: první sloupec daného jména
        return out

    def fetchone(self): return self._radek(self._cur.fetchone())
    def fetchall(self): return [self._radek(r) for r in self._cur.fetchall()]


class Connection:
    """Spojení s rozhraním PyMySQL: autocommit=True = každý dotaz zvlášť; jinak transakce BEGIN IMMEDIATE (od prvního zápisu
    nebo FOR UPDATE) do commit()/rollback()."""

    def __init__(self, path, autocommit=False):
        self.path = str(path); self.autocommit = autocommit
        self._conn = otevri(self.path); self.meritka = _meritka(self._conn, self.path); self.open = True

    def _zacni_transakci(self):
        if not self.autocommit and not self._conn.in_transaction: self._conn.execute('BEGIN IMMEDIATE')

    def begin(self):
        if not self._conn.in_transaction: self._conn.execute('BEGIN IMMEDIATE')

    def begin_read(self):
        """Čtecí transakce: všechna následující čtení vidí jeden stav databáze (WAL snímek), zápisy ostatních neblokuje."""
        if not self._conn.in_transaction: self._conn.execute('BEGIN')

    def cursor(self): return Cursor(self)

    def commit(self):
        if self._conn.in_transaction: self._conn.execute('COMMIT')

    def rollback(self):
        if self._conn.in_transaction: self._conn.execute('ROLLBACK')

    def close(self):
        if not self.open: return
        try: self.rollback()
        finally: self._conn.close(); self.open = False

    def __enter__(self): return self
    def __exit__(self, *a): self.close()
