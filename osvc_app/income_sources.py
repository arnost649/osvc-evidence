"""Provider registry and non-secret source settings. Accounting stays in existing tables."""
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from . import cas
from decimal import Decimal
from pathlib import Path
from contextlib import contextmanager
from . import zamky
from flask import current_app
from .db import query, execute

@dataclass(frozen=True)
class IncomeDocument:
    external_document_id: str
    document_type: str = 'invoice'
    mime_type: str = 'application/pdf'
    source_reference: str | None = None
    # Local identity and checksum live in existing documents / attachments tables.

@dataclass(frozen=True)
class ExternalIncome:
    source_id: int
    source_name: str
    external_id: str
    date: str | None
    customer_name: str
    description: str
    amount: Decimal
    document: IncomeDocument | None = None
    source_metadata: dict = field(default_factory=dict)
    invoice_amount_czk: Decimal | None = None
    payment_received_czk: Decimal | None = None
    payment_currency: str | None = None
    fx_settlement_diff_czk: Decimal | None = None
    payment_needs_review: bool = False

class SourceError(ValueError):
    pass

def sync_warnings(source):
    summary=source.get('last_summary')
    try:summary=json.loads(summary) if isinstance(summary,str) else summary or {}
    except ValueError:summary={}
    return [str(w) for w in summary.get('warnings') or []]

def sync_error(source):
    """Real failure of the last synchronization. Before 2026-11-13 warnings were also stored in last_error (joined by '; ');
    such a value is recognised and not treated as an error."""
    error=source.get('last_error')
    if not error:return None
    warnings=sync_warnings(source)
    return None if warnings and error=='; '.join(warnings)[:300] else error

class IncomeSourceProvider:
    """Connectors own transport/mapping; core pages only call this interface."""
    def __init__(self, source): self.source = source
    def validate_config(self): raise NotImplementedError
    def discover_capabilities(self): raise NotImplementedError
    def fetch_income(self, **kwargs): raise NotImplementedError
    def fetch_document(self, record): raise NotImplementedError
    def get_status(self): raise NotImplementedError
    def test_connection(self): raise NotImplementedError
    def sync(self, automatic=False): raise NotImplementedError

from .connectors import WooCommerceProvider, MANIFESTS
PROVIDERS = {'woocommerce': WooCommerceProvider}
PROVIDER_LABELS = {k:v['name'] for k,v in MANIFESTS.items()}

def sources():
    return query('SELECT * FROM income_sources ORDER BY id')

def get_source(ident):
    row=query('SELECT * FROM income_sources WHERE id=%s',(ident,),one=True)
    if not row: raise SourceError('Zdroj nebyl nalezen.')
    return row

def provider(source):
    cls=PROVIDERS.get(source['provider'])
    if cls is None: raise SourceError('Tento typ konektoru není implementovaný.')
    return cls(source)

def default_source():
    # Primary shortcut for existing dashboard/header; all sources have their own settings actions.
    return query("SELECT * FROM income_sources ORDER BY active DESC,id LIMIT 1",one=True)

def legacy_source():
    # dřív JSON_EXTRACT v SQL; teď v Pythonu (MySQL i SQLite)
    for s in query("SELECT * FROM income_sources ORDER BY id"):
        c = s.get('configuration')
        try: c = json.loads(c) if isinstance(c, (str, bytes)) else (c or {})
        except ValueError: c = {}
        if isinstance(c, dict) and c.get('legacy_records') is True: return s
    return None

def source_ready():
    s=default_source()
    return bool(s and s['active'] and provider(s).get_status()['configured'])

def sync_block_reason(source):
    """Why the source cannot be synchronized right now (Czech, for the page), or None when the Synchronize button can be used."""
    if not source:return 'Žádný zdroj příjmů není nastavený.'
    if not source['active']:return 'Zdroj je vypnutý – zapnete ho v Nastavení → Zdroje příjmů.'
    status=provider(source).get_status()
    if not status['configured']:
        return 'Zdroj není připravený ('+', '.join(c['label'] for c in status['checks'] if not c['ok'])+') – podrobnosti v Nastavení → Zdroje příjmů.'
    return None

def last_sync():
    s=default_source()
    return {'at':s['last_sync_at']} if s and s['last_sync_at'] else None

@contextmanager
def source_lock(ident):
    from .backup import state_dir
    with (state_dir()/f'.income-source-{int(ident)}.lock').open('ab') as handle:
        try: zamky.zamkni(handle,vyhradni=True,necekat=True)
        except BlockingIOError: raise SourceError('Synchronizace tohoto zdroje už probíhá.')
        yield

def planovana_synchronizace(vypis):
    """Jeden běh plánovače: všechny aktivní zdroje s automatickou synchronizací. vypis(text, chyba=False) = výstup běhu.
    Vrátí {'chyb', 'hotovo', 'modul_vypnuty'}; stav běhu se zapíše pro Nastavení → Zdroje příjmů."""
    from .connectors import record_scheduler_run
    from .backup import data_lock
    from . import moduly
    failed=0; done=0; results={}
    modul_vypnuty=not moduly.zapnuto('externi_web')
    try:
        with data_lock():
            for source in sources():
                label=f"zdroj {source['id']} ({source.get('name') or '?'})"
                if modul_vypnuty:
                    # Vypnutý modul Externí web: plánovač nesynchronizuje nic; stažené příjmy zůstávají v Příjmech.
                    results[source['id']]={'state':'skipped','message':'modul Externí web je vypnutý'}
                    vypis(f'{label}: modul Externí web je vypnutý (Nastavení → Moduly) – přeskočeno'); continue
                if not source['active']:
                    results[source['id']]={'state':'skipped','message':'zdroj je vypnutý'}
                    vypis(f'{label}: vypnutý – přeskočeno'); continue
                if not source['automatic_sync']:
                    results[source['id']]={'state':'skipped','message':'automatická synchronizace je vypnutá'}
                    vypis(f'{label}: automatická synchronizace vypnutá v Nastavení – přeskočeno'); continue
                try:
                    summary=synchronize(source['id'],automatic=True); done+=1
                    counts={k:v for k,v in (summary or {}).items() if isinstance(v,int) and not isinstance(v,bool)}
                    results[source['id']]={'state':'ok','message':'','counts':counts}
                    vypis(f'{label}: OK {counts}')
                except SourceError as exc:
                    # Safe Czech message only (no URLs or credentials); also persisted for settings UI.
                    results[source['id']]={'state':'error','message':str(exc)[:300]}
                    failed+=1; vypis(f'{label}: CHYBA {exc}', True)
    except Exception as exc:
        results['beh']={'state':'error','message':'běh skončil neočekávanou chybou ('+type(exc).__name__+')'}
        raise
    finally:
        # skutečný stav plánovače pro Nastavení → Zdroje příjmů; zápis nesmí shodit běh.
        try: record_scheduler_run(results)
        except Exception as exc: vypis(f'Stav plánovače nejde zapsat: {type(exc).__name__}: {exc}', True)
    if not failed:
        if modul_vypnuty: vypis('Modul Externí web je vypnutý – synchronizace přeskočena.')
        elif not done: vypis('Žádný zdroj nemá zapnutou automatickou synchronizaci.')
    return {'chyb':failed,'hotovo':done,'modul_vypnuty':modul_vypnuty}

def synchronize(ident, automatic=False):
    with source_lock(ident):
        s=get_source(ident)
        if not s['active'] or (automatic and not s['automatic_sync']):
            raise SourceError('Zdroj je vypnutý.' if not s['active'] else 'Automatická synchronizace je vypnutá.')
        p=provider(s)
        if not p.get_status()['configured']: raise SourceError('Doplňte adresu, datum importu a serverové přístupové údaje.')
        try:
            summary=p.sync(automatic=automatic)
        except Exception as exc:
            # Do not expose transport URLs, authentication or external response bodies.
            message='Zdroj není dostupný nebo import selhal. Zkontrolujte připojení.'
            execute('UPDATE income_sources SET last_error=%s WHERE id=%s',(message,ident))
            current_app.logger.warning('Income source id=%s failure=%s',ident,type(exc).__name__)
            raise SourceError(message) from exc
        # Warnings (partial refund, foreign currency, missing PDF) stay in last_summary; last_error is only for a failed synchronization.
        execute('UPDATE income_sources SET last_sync_at=%s,last_summary=%s,last_error=NULL WHERE id=%s',
                (cas.utc_now_naive(),json.dumps(summary,ensure_ascii=False),ident))
        return summary

def link_document(source_id, external_id, document_id, metadata=None):
    existing=query('SELECT id,document_id FROM income_source_records WHERE source_id=%s AND external_id=%s',(source_id,str(external_id)),one=True)
    encoded=json.dumps(metadata or {},ensure_ascii=False)
    if existing:
        if existing['document_id'] != document_id: raise SourceError('Externí příjem už odkazuje na jiný doklad.')
        execute('UPDATE income_source_records SET source_metadata=%s WHERE id=%s',(encoded,existing['id']))
    else:
        execute('INSERT INTO income_source_records (source_id,external_id,document_id,source_metadata) VALUES (%s,%s,%s,%s)',
                (source_id,str(external_id),document_id,encoded))
