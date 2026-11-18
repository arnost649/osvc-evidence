"""Český čas.

Server běží v UTC a aplikace i databáze ukládají časy v UTC: `datetime.now(timezone.utc)` v JSON (ověření, plánovač, zálohy),
MySQL NOW()/CURRENT_TIMESTAMP (deleted_at, verified_at, created_at…) a `last_sync_at`. Naivní datum a čas bez časového
pásma je proto vždy UTC. Uložená data se nemění – převádí se jen při zobrazení a pro „dnešní datum“ uživatele.
Čisté datum (DATE, např. datum platby nebo jízdy) se nepřevádí nikdy."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

PRAHA = ZoneInfo('Europe/Prague')


def datum(d, s_casem=False):
    """Datum česky „5. 1. 2026“ (s_casem: „5. 1. 2026 14:03“). Bez formátu „den bez nuly“ ve strftime, který Windows nezná."""
    text = f'{d.day}. {d.month}. {d.year}'
    return text + d.strftime(' %H:%M') if s_casem else text


def parse_utc(value):
    """datetime/řetězec → datetime v UTC s časovým pásmem; None, když to není datum a čas (prázdné, čisté datum, nesmysl)."""
    if not value or (isinstance(value, date) and not isinstance(value, datetime)): return None
    if isinstance(value, datetime): parsed = value
    else:
        text = str(value).strip().replace('Z', '+00:00')
        if len(text) <= 10: return None          # jen datum
        try: parsed = datetime.fromisoformat(text)
        except ValueError: return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def local(value):
    """Čas v Praze (letní/zimní čas podle data) nebo None."""
    parsed = parse_utc(value)
    return parsed.astimezone(PRAHA) if parsed else None


def today():
    """Dnešní datum v Česku (server v UTC by mezi půlnocí a 1:00 / v létě 2:00 vrátil ještě včerejšek)."""
    return datetime.now(PRAHA).date()


def utc_now_naive():
    """Aktuální čas UTC bez pásma – pro sloupce DATETIME, které ukládají UTC (např. last_sync_at)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
